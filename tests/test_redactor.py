"""Unit tests for `src.utils.redactor`.

Each pattern is exercised in isolation, plus a handful of cross-pattern
interaction and edge-case tests (ordering, overlap, empty/None input).
The module's secret-detection value is only as good as its pattern
list, so regressions in pattern matching are first-class bugs.
"""
import pytest

from src.utils.redactor import redact, redact_with_count


# ---------------------------------------------------------------------------
# Per-pattern coverage
# ---------------------------------------------------------------------------
def test_github_token_classic():
    # classic PAT: ghp_ + 36+ base62 chars
    src = "token=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    out, n = redact_with_count(src)
    assert "[REDACTED:github-token]" in out
    assert "ghp_" not in out
    assert n == 1


@pytest.mark.parametrize("prefix", ["ghp_", "gho_", "ghu_", "ghs_", "ghr_"])
def test_github_token_all_prefixes(prefix):
    src = f"{prefix}" + "a" * 40
    out, n = redact_with_count(src)
    assert out == "[REDACTED:github-token]"
    assert n == 1


def test_openai_key():
    src = "OPENAI_API_KEY=sk-abcdefghij1234567890XYZ"
    out = redact(src)
    assert "[REDACTED:openai-key]" in out
    assert "sk-abc" not in out


def test_slack_token():
    src = "xoxb-12345-67890-abcdefghijABCDEFGHIJ"
    out = redact(src)
    assert out == "[REDACTED:slack-token]"


def test_jwt_detected_by_three_part_eyj_shape():
    # Minimal plausible JWT: header.payload.signature, both header and
    # payload start with `eyJ`.
    src = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc-_123"
    out = redact(src)
    assert "[REDACTED:jwt]" in out
    assert "eyJhbGci" not in out


def test_aws_access_key():
    src = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
    out = redact(src)
    assert "[REDACTED:aws-access-key]" in out
    assert "AKIA" not in out


def test_aws_secret_keeps_prefix_scrubs_value():
    # 40 chars, mixed charset per the AWS format.
    src = 'aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"'
    out = redact(src)
    assert "aws_secret_access_key" in out          # key name preserved
    assert "[REDACTED:aws-secret]" in out          # value scrubbed
    assert "wJalrXUtnFEMI" not in out


def test_aws_secret_case_insensitive_key_name():
    src = 'AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"'
    out = redact(src)
    assert "[REDACTED:aws-secret]" in out


def test_pem_private_key_block():
    src = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj\n"
        "MzEfYyjiWA4R4/M2bS1GB4t7NXp98C3SC6dVMvDuictGeurT8jNbvJZHtCSuYEvu\n"
        "-----END RSA PRIVATE KEY-----"
    )
    out = redact(src)
    assert out == "[REDACTED:private-key]"


def test_partial_pem_block_not_redacted():
    # Missing END marker — should NOT match.
    src = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEvQIBADAN... (file was truncated)\n"
    )
    out = redact(src)
    assert out == src  # unchanged


def test_generic_password_assignment_case_insensitive():
    src = 'PASSWORD = "hunter2supersecret"'
    out = redact(src)
    assert "[REDACTED:credential]" in out
    assert "hunter2" not in out


def test_generic_api_key_assignment():
    src = "api_key = 'mysupersecretkeyvalue'"
    out = redact(src)
    assert "[REDACTED:credential]" in out
    assert "mysupersecret" not in out


def test_generic_short_value_not_matched():
    # Values shorter than 8 chars don't look like real secrets.
    src = 'password = "short"'
    out = redact(src)
    assert out == src  # unchanged — below the length threshold


def test_generic_unquoted_env_style_assignment():
    # `.env`-style files and shell exports use unquoted values; those show
    # up in diffs all the time and must not leak through to the LLM.
    src = "API_KEY=abcdef1234567890supersecret"
    out = redact(src)
    assert "[REDACTED:credential]" in out
    assert "abcdef1234567890" not in out


def test_generic_unquoted_preserves_key_name():
    src = "DATABASE_PASSWORD=hunter2secretpass"
    out = redact(src)
    assert "PASSWORD" in out                # key preserved (caller can see the shape)
    assert "[REDACTED:credential]" in out
    assert "hunter2" not in out


def test_generic_unquoted_short_value_not_matched():
    # Below the 8-char threshold — same rule as the quoted variant.
    src = "api_key=short"
    out = redact(src)
    assert out == src


def test_generic_unquoted_does_not_double_wrap_already_redacted():
    # If an earlier pattern already replaced the value with a placeholder,
    # the unquoted generic pattern must not re-wrap it. The placeholder
    # opens with `[`, which the `(?![\"'\[])` guard forbids.
    src = "token=ghp_" + "a" * 40
    out = redact(src)
    assert out.count("[REDACTED:") == 1       # exactly one wrap
    assert "[REDACTED:github-token]" in out


def test_bearer_token_opaque():
    # `Authorization: Bearer <opaque>` is the single most common credential
    # shape in HTTP examples. The "Bearer " literal is preserved so humans
    # and the LLM still see the auth shape, but the token value is scrubbed.
    src = "Authorization: Bearer abc123def456ghi789jkl012"
    out = redact(src)
    assert "Bearer " in out                   # prefix kept
    assert "[REDACTED:bearer-token]" in out
    assert "abc123def456" not in out


def test_bearer_token_case_insensitive_prefix():
    src = "authorization: bearer abc123def456ghi789jkl"
    out = redact(src)
    assert "[REDACTED:bearer-token]" in out


def test_bearer_with_jwt_value_caught_as_jwt():
    # JWT runs before Bearer — a `Bearer eyJ...` should be tagged as a JWT
    # (the more specific pattern wins); Bearer must NOT re-wrap it.
    src = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc-_123"
    out = redact(src)
    assert "[REDACTED:jwt]" in out
    assert "[REDACTED:bearer-token]" not in out


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
def test_empty_string_round_trips():
    assert redact("") == ""
    out, n = redact_with_count("")
    assert (out, n) == ("", 0)


def test_none_raises_typeerror():
    with pytest.raises(TypeError):
        redact(None)  # type: ignore[arg-type]


def test_no_matches_returns_unchanged():
    src = "def hello():\n    return 'world'\n"
    out, n = redact_with_count(src)
    assert out == src
    assert n == 0


def test_multiple_distinct_secrets_in_one_string():
    src = (
        "github=ghp_" + "a" * 40 + "\n"
        "openai=sk-" + "b" * 30 + "\n"
        "aws=AKIAIOSFODNN7EXAMPLE\n"
    )
    out, n = redact_with_count(src)
    assert "[REDACTED:github-token]" in out
    assert "[REDACTED:openai-key]" in out
    assert "[REDACTED:aws-access-key]" in out
    # Exactly one of each.
    assert n == 3


def test_longest_match_first_github_token_inside_password_assignment():
    """An OpenAI-ish or GitHub-ish token that lives inside a
    password=... assignment should be caught by the specific pattern
    first, not clobbered to `[REDACTED:credential]`.
    """
    src = 'password = "ghp_' + "a" * 40 + '"'
    out = redact(src)
    # The github-token pattern should win.
    assert "[REDACTED:github-token]" in out
    # And the credential pattern should NOT re-wrap it (the value is
    # already the placeholder).
    assert "[REDACTED:credential]" not in out


def test_redact_with_count_returns_total_substitutions():
    src = f"a=sk-{'x' * 30}, b=AKIAIOSFODNN7EXAMPLE"
    out, n = redact_with_count(src)
    assert n == 2
    assert "[REDACTED:openai-key]" in out
    assert "[REDACTED:aws-access-key]" in out
