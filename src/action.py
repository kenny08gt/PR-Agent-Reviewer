"""GitHub Action entry point.

Invoked as `python -m src.action` from inside the Docker container
defined by the repo's `Dockerfile` (see `action.yml`). The runner
supplies inputs as `INPUT_<NAME>` env vars and a small set of
first-party vars (`GITHUB_EVENT_PATH`, `GITHUB_REPOSITORY`,
`GITHUB_EVENT_NAME`, `GITHUB_SHA`).

Flow:

  1. Map each `INPUT_<NAME>` onto the `Settings`-compatible env var name
     so the existing Pydantic settings loader keeps working unchanged.
  2. Load + parse the webhook event payload from `GITHUB_EVENT_PATH`.
     Only `pull_request` events with actions `opened`, `synchronize`,
     or `reopened` proceed; everything else exits 0 cleanly.
  3. Construct `PRReviewerAgent` and call `review_pr(repo, num, sha)`.
  4. Honor `INPUT_DRY_RUN=true` — `PostReviewTool` checks the same env
     var and returns a stub instead of actually posting.

Local smoke-test escape hatch: when `GITHUB_EVENT_PATH` is missing and
the env vars `CLI_REPO` (e.g. `octocat/hello-world`) and `CLI_PR`
(integer) are set, we fall back to those so you can run
`python -m src.action` against any real PR without fabricating an
event JSON.

Exit codes: 0 on success OR on "ignored event" (the Action must NOT
fail the workflow for unrelated events); 1 on unrecoverable error
(missing token, unreadable event JSON, agent exception).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Dict, Optional, Tuple

logger = logging.getLogger("pr-reviewer-agent")

# ---------------------------------------------------------------------------
# Input-var mapping
# ---------------------------------------------------------------------------
# Each entry: (INPUT_<NAME> -> Settings-env-var). We set the Settings var
# only if the INPUT_ var is non-empty — this preserves any value the user
# may have set via `env:` in their workflow step (unlikely, but cheap to
# respect).
_INPUT_MAP: Tuple[Tuple[str, str], ...] = (
    ("INPUT_GITHUB_TOKEN", "GITHUB_TOKEN"),
    ("INPUT_OPENAI_API_KEY", "OPENAI_API_KEY"),
    ("INPUT_MOONSHOT_API_KEY", "MOONSHOT_API_KEY"),
    ("INPUT_LLM_PROVIDER", "LLM_PROVIDER"),
    ("INPUT_LLM_MODEL", "LLM_MODEL"),
    ("INPUT_LLM_BASE_URL", "LLM_BASE_URL"),
    ("INPUT_MAX_FILES_TO_REVIEW", "MAX_FILES_TO_REVIEW"),
    ("INPUT_MAX_DIFF_LINES", "MAX_DIFF_LINES"),
    ("INPUT_REVIEW_ENABLED", "REVIEW_ENABLED"),
)

# Pull-request actions we act on. Anything else is a no-op.
_TRIGGER_ACTIONS = frozenset({"opened", "synchronize", "reopened"})


def _normalize_input_env_keys() -> None:
    """Mirror hyphenated `INPUT_*` vars onto their underscored form.

    GitHub's Docker-action runtime serializes input names by only
    uppercasing — hyphens stay as hyphens. So `github-token` arrives as
    `INPUT_GITHUB-TOKEN`, not `INPUT_GITHUB_TOKEN`. Python can read
    either via `os.environ[...]`, but our `_INPUT_MAP` keys and all
    downstream `os.environ.get("INPUT_...")` calls assume underscores.
    Copy each hyphenated INPUT_* to its underscored alias so both lookups
    work transparently.
    """
    for key in list(os.environ.keys()):
        if key.startswith("INPUT_") and "-" in key:
            alias = key.replace("-", "_")
            if alias not in os.environ:
                os.environ[alias] = os.environ[key]


def _map_inputs_to_settings_env() -> None:
    """Promote `INPUT_<NAME>` env vars onto the `Settings`-compatible names.

    Must run BEFORE importing `src.utils.config` so the settings module
    picks up `OPENAI_API_KEY` etc. on first construction.
    """
    for input_key, settings_key in _INPUT_MAP:
        value = os.environ.get(input_key, "")
        if value and not os.environ.get(settings_key):
            os.environ[settings_key] = value


def _validate_required_secrets() -> Optional[str]:
    """Return an error message if a required secret is missing, else None.

    We check here (rather than leaving it to `Settings`) because we want
    a single friendly error line pointing the user at their workflow
    file, not a pydantic ValidationError dump.
    """
    if not os.environ.get("GITHUB_TOKEN"):
        return (
            "github-token is required. "
            "Pass `github-token: ${{ secrets.GITHUB_TOKEN }}` in your "
            "workflow step."
        )

    provider = os.environ.get("LLM_PROVIDER", "openai").lower()
    if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        return (
            "openai-api-key is required when llm-provider=openai. "
            "Store it as a repo secret and pass it via `openai-api-key`."
        )
    if provider == "kimi" and not os.environ.get("MOONSHOT_API_KEY"):
        return (
            "moonshot-api-key is required when llm-provider=kimi. "
            "Store it as a repo secret and pass it via `moonshot-api-key`."
        )
    return None


def _load_event() -> Optional[Dict]:
    """Read + parse `GITHUB_EVENT_PATH`, or None if unavailable."""
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to read GITHUB_EVENT_PATH=%s: %s", path, exc)
        return None


def _extract_pr_args(event: Dict) -> Optional[Tuple[str, int, str]]:
    """Return `(repo, pr_number, head_sha)` or None if event is not actionable.

    Acts only on pull_request events whose `action` is in the trigger
    set. GITHUB_EVENT_NAME takes precedence over guessing from payload
    shape — the runner sets it unambiguously.
    """
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if event_name and event_name != "pull_request":
        logger.info(
            "Ignoring event_name=%s (only pull_request is handled)", event_name)
        return None

    action = event.get("action", "")
    if action not in _TRIGGER_ACTIONS:
        logger.info(
            "Ignoring pull_request action=%s (handled: %s)",
            action, sorted(_TRIGGER_ACTIONS),
        )
        return None

    pr = event.get("pull_request") or {}
    number = pr.get("number")
    head = pr.get("head") or {}
    sha = head.get("sha") or os.environ.get("GITHUB_SHA", "")

    repo = (event.get("repository") or {}).get("full_name") \
        or os.environ.get("GITHUB_REPOSITORY", "")

    if not repo or not isinstance(number, int) or not sha:
        logger.error(
            "pull_request event missing required fields: "
            "repo=%r number=%r sha=%r", repo, number, sha,
        )
        return None

    return repo, number, sha


def _cli_fallback() -> Optional[Tuple[str, int, str]]:
    """Local-dev escape hatch: use `CLI_REPO` + `CLI_PR` env vars.

    Lets developers smoke-test without concocting a full GitHub event
    payload. The commit SHA is optional — we pass an empty string when
    not provided; review_pr will fetch PR details either way and only
    the `post` step cares about the SHA.
    """
    repo = os.environ.get("CLI_REPO", "").strip()
    pr_str = os.environ.get("CLI_PR", "").strip()
    if not repo or not pr_str:
        return None
    try:
        number = int(pr_str)
    except ValueError:
        logger.error("CLI_PR=%r is not an integer", pr_str)
        return None
    sha = os.environ.get("CLI_SHA", "").strip()
    return repo, number, sha


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )

    # Step 1 — normalize GitHub's hyphenated INPUT_* keys, then promote
    # them onto Settings-compatible names before anything imports
    # src.utils.config (which constructs Settings on import).
    _normalize_input_env_keys()
    _map_inputs_to_settings_env()

    # Step 2 — friendly early-fail on missing secrets.
    err = _validate_required_secrets()
    if err:
        logger.error(err)
        return 1

    # Step 3 — figure out which PR to review.
    event = _load_event()
    if event is not None:
        args = _extract_pr_args(event)
        if args is None:
            # Unrelated event — the Action must exit cleanly so the
            # workflow doesn't show a red X on every push / label / close.
            return 0
        repo, pr_number, commit_sha = args
    else:
        fallback = _cli_fallback()
        if fallback is None:
            logger.error(
                "No GITHUB_EVENT_PATH and no CLI_REPO/CLI_PR env vars set. "
                "Nothing to review.",
            )
            return 1
        repo, pr_number, commit_sha = fallback
        logger.info(
            "Local smoke-test mode: CLI_REPO=%s CLI_PR=%s", repo, pr_number,
        )

    # Step 4 — construct the agent and run the review.
    # Import lazily so Settings only constructs AFTER env mapping above.
    try:
        from .agents.pr_reviewer import PRReviewerAgent
    except Exception as exc:  # noqa: BLE001 - blanket by design: startup
        logger.error("Failed to import agent: %s", exc)
        return 1

    dry_run = os.environ.get("INPUT_DRY_RUN", "").lower() == "true"
    if dry_run:
        logger.info("dry-run mode enabled — review will NOT be posted")

    try:
        agent = PRReviewerAgent()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to construct PRReviewerAgent: %s", exc)
        return 1

    result = agent.review_pr(repo, pr_number, commit_sha=commit_sha or None)

    if result.get("success"):
        skipped = result.get("skipped")
        if skipped:
            logger.info(
                "review skipped (%s): %s", skipped, result.get("message"),
            )
        else:
            logger.info("review completed: %s", result.get("message"))
        return 0

    logger.error("review failed: %s", result.get("message"))
    return 1


if __name__ == "__main__":  # pragma: no cover - entrypoint
    sys.exit(main())
