"""Secret-pattern redaction for patches before they reach the LLM.

Pure module: no globals, no I/O. `redact(text)` replaces known secret
shapes with `[REDACTED:<type>]` placeholders so we never ship a raw API
key, bearer token, or private key to OpenAI / Moonshot.

Design choices:
- Patterns are applied **longest-match-first**: specific token shapes
  (GitHub, AWS, JWT, PEM) run before the generic
  `password|secret|api_key=...` pattern, otherwise the generic pattern
  would clobber a GitHub token that happens to sit after
  `github_token=`. Ordering matters; do not reorder casually.
- The generic credential regex additionally refuses to match when the
  value is already a `[REDACTED:...]` placeholder. Without this, a
  previously-scrubbed `password = "[REDACTED:github-token]"` would get
  re-wrapped to `[REDACTED:credential]`, erasing the original shape.
- `redact(None)` raises `TypeError` on purpose — callers must not
  silently swallow None; they should decide whether to skip or stringify.
- Counts: `redact_with_count(text)` returns the number of substitutions
  so callers can log "redactor: redacted N potential secrets" WITHOUT
  ever logging the matches themselves.

The replacement format is stable: `[REDACTED:<kind>]`. Tests assert on
it, and it needs to be recognizable in LLM output too (so the model
knows the value was scrubbed rather than hallucinate a plausible one).
"""
from __future__ import annotations

import re
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Pattern registry — ordered from most-specific to most-generic. Each entry
# is (name, compiled regex, replacement-factory).
#
# The replacement-factory takes the match and returns the final string. For
# simple "replace the whole match" patterns this is a constant; for capture-
# group patterns (AWS secret, generic credential) it preserves the prefix
# and only scrubs the secret value itself so the logs / LLM can still see
# that it was an `aws_secret_access_key=` assignment.
# ---------------------------------------------------------------------------

_PEM_BLOCK = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"
)

_GITHUB_TOKEN = re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")
_OPENAI_KEY = re.compile(r"sk-[A-Za-z0-9]{20,}")
_SLACK_TOKEN = re.compile(r"xox[abprs]-[A-Za-z0-9-]+")
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_AWS_ACCESS_KEY = re.compile(r"AKIA[0-9A-Z]{16}")

# AWS secret: scrub only the value, keep the `aws_secret_access_key =` prefix.
_AWS_SECRET = re.compile(
    r"(aws_secret_access_key\s*[:=]\s*[\"']?)([A-Za-z0-9/+=]{40})([\"']?)",
    re.IGNORECASE,
)

# `Authorization: Bearer <token>` — preserve the "Bearer " literal so humans
# and the LLM can see the auth shape, scrub only the token value. Runs AFTER
# JWT so a `Bearer eyJ...` gets tagged as a JWT (more specific); the negative
# lookahead keeps us from re-wrapping an already-redacted value.
_BEARER_TOKEN = re.compile(
    r"(?i)(bearer\s+)(?!\[REDACTED:)([A-Za-z0-9._\-]{20,})"
)

# Generic credential assignments with quoted values. Case-insensitive key
# names. Must run after the specific patterns so that an explicit
# GitHub/AWS/Slack token inside a `password=...` assignment has already
# been replaced with `[REDACTED:github-token]` (etc.). The negative
# lookahead `(?!\[REDACTED:)` keeps us from re-wrapping an already-
# scrubbed value — without it, the output would regress to
# `[REDACTED:credential]` after the first pass.
_GENERIC_CREDENTIAL = re.compile(
    r"(?i)(password|secret|api_key|auth_token)"
    r"(\s*[:=]\s*[\"'])"
    r"(?!\[REDACTED:)"
    r"([^\"'\s]{8,})"
    r"([\"'])"
)

# Same as above but for unquoted values (e.g. `.env`-style `API_KEY=abc123`).
# Value terminates at whitespace, end of string, or a closing bracket. The
# `(?![\"'\[])` guard prevents double-matching with the quoted pattern or
# re-wrapping an already-redacted placeholder that opens with `[`.
_GENERIC_CREDENTIAL_UNQUOTED = re.compile(
    r"(?i)(password|secret|api_key|auth_token)"
    r"(\s*[:=]\s*)"
    r"(?![\"'\[])"
    r"([^\s\"']{8,})"
)


def _sub_whole(kind: str):
    """Factory: replace the whole match with a single placeholder."""
    return lambda _m: f"[REDACTED:{kind}]"


def _sub_aws_secret(match: "re.Match[str]") -> str:
    prefix, _value, suffix = match.group(1), match.group(2), match.group(3)
    return f"{prefix}[REDACTED:aws-secret]{suffix}"


def _sub_generic_credential(match: "re.Match[str]") -> str:
    key, sep, _value, quote = match.groups()
    return f"{key}{sep}[REDACTED:credential]{quote}"


def _sub_generic_credential_unquoted(match: "re.Match[str]") -> str:
    key, sep, _value = match.groups()
    return f"{key}{sep}[REDACTED:credential]"


def _sub_bearer(match: "re.Match[str]") -> str:
    prefix, _value = match.group(1), match.group(2)
    return f"{prefix}[REDACTED:bearer-token]"


# The order below is load-bearing. See module docstring.
_PATTERNS: List[Tuple[str, "re.Pattern[str]", object]] = [
    ("private-key", _PEM_BLOCK, _sub_whole("private-key")),
    ("jwt", _JWT, _sub_whole("jwt")),
    ("github-token", _GITHUB_TOKEN, _sub_whole("github-token")),
    ("openai-key", _OPENAI_KEY, _sub_whole("openai-key")),
    ("slack-token", _SLACK_TOKEN, _sub_whole("slack-token")),
    ("aws-access-key", _AWS_ACCESS_KEY, _sub_whole("aws-access-key")),
    ("aws-secret", _AWS_SECRET, _sub_aws_secret),
    ("bearer-token", _BEARER_TOKEN, _sub_bearer),
    ("credential", _GENERIC_CREDENTIAL, _sub_generic_credential),
    ("credential-unquoted", _GENERIC_CREDENTIAL_UNQUOTED,
     _sub_generic_credential_unquoted),
]


def redact(text: str) -> str:
    """Return `text` with known secret patterns replaced by placeholders.

    Raises:
        TypeError: if `text` is not a string (including None). Callers
            must handle the absence of text before calling; silently
            accepting None would hide bugs where a patch is missing.
    """
    if not isinstance(text, str):
        raise TypeError(
            f"redact() requires a str, got {type(text).__name__}")
    if not text:
        return text

    for _kind, pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def redact_with_count(text: str) -> Tuple[str, int]:
    """Like `redact()` but also returns how many substitutions happened.

    The count is the sum of substitutions across all patterns. Use it for
    structured logging — never log the matches themselves.
    """
    if not isinstance(text, str):
        raise TypeError(
            f"redact_with_count() requires a str, got {type(text).__name__}")
    if not text:
        return text, 0

    total = 0
    for _kind, pattern, repl in _PATTERNS:
        text, n = pattern.subn(repl, text)
        total += n
    return text, total
