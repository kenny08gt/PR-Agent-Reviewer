"""Tests for `src.action.main()` — the Action entry point.

We drive main() by writing a fixture PR event JSON to `tmp_path`,
pointing `GITHUB_EVENT_PATH` at it, and asserting the agent was
(or was not) called with the right args. The `PRReviewerAgent` class
is stubbed via monkeypatch so no LLM / GitHub calls occur.

Note on env plumbing: `src.agents.pr_reviewer` instantiates `Settings`
at import time (via `from ..utils.config import settings`). Before any
test patches `src.agents.pr_reviewer.PRReviewerAgent`, the helper
below first promotes `INPUT_*` env vars onto the Settings-compatible
names — exactly what `action.main()` does at runtime — so the module
import succeeds even when the test fixture has wiped `OPENAI_API_KEY`.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

import pytest


# Duplicated from src.action — tiny table, and duplicating avoids importing
# src.action before env is prepared, which would eagerly load Settings.
_INPUT_MAP = (
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


def _pre_map_inputs(monkeypatch):
    """Mirror of `src.action._map_inputs_to_settings_env` — run before
    any import that touches `src.utils.config`.
    """
    for input_key, settings_key in _INPUT_MAP:
        value = os.environ.get(input_key, "")
        if value and not os.environ.get(settings_key):
            monkeypatch.setenv(settings_key, value)


@pytest.fixture
def clean_action_env(monkeypatch):
    """Wipe the env vars main() cares about between tests."""
    for var in (
        "INPUT_GITHUB_TOKEN", "INPUT_OPENAI_API_KEY", "INPUT_MOONSHOT_API_KEY",
        "INPUT_LLM_PROVIDER", "INPUT_LLM_MODEL", "INPUT_LLM_BASE_URL",
        "INPUT_MAX_FILES_TO_REVIEW", "INPUT_MAX_DIFF_LINES",
        "INPUT_REVIEW_ENABLED", "INPUT_DRY_RUN",
        "GITHUB_TOKEN", "OPENAI_API_KEY", "MOONSHOT_API_KEY",
        "LLM_PROVIDER", "LLM_MODEL", "LLM_BASE_URL",
        "MAX_FILES_TO_REVIEW", "MAX_DIFF_LINES", "REVIEW_ENABLED",
        "GITHUB_EVENT_PATH", "GITHUB_EVENT_NAME", "GITHUB_REPOSITORY",
        "GITHUB_SHA", "CLI_REPO", "CLI_PR", "CLI_SHA",
    ):
        monkeypatch.delenv(var, raising=False)
    yield monkeypatch


def _write_event(tmp_path, action: str, number: int = 42,
                 repo: str = "octocat/hello-world",
                 sha: str = "abc123def4567890abc123def4567890abc123de"):
    payload = {
        "action": action,
        "pull_request": {
            "number": number,
            "title": "Test PR",
            "head": {"sha": sha, "ref": "feature"},
            "base": {"ref": "main"},
        },
        "repository": {"full_name": repo},
    }
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload))
    return str(path), repo, number, sha


def _install_stub_agent(monkeypatch, review_result=None):
    """Replace `PRReviewerAgent` with a MagicMock; return the stub class.

    The monkeypatch target string triggers an import of
    `src.agents.pr_reviewer`, which in turn imports `Settings` at module
    top. We therefore call `_pre_map_inputs` first so the Settings
    validator has the keys it needs.
    """
    _pre_map_inputs(monkeypatch)

    stub_instance = MagicMock(name="agent_instance")
    stub_instance.review_pr.return_value = review_result or {
        "success": True,
        "message": "PR review completed successfully",
        "details": {"output": "LGTM"},
    }

    stub_cls = MagicMock(name="PRReviewerAgent", return_value=stub_instance)
    monkeypatch.setattr(
        "src.agents.pr_reviewer.PRReviewerAgent",
        stub_cls,
    )
    return stub_cls, stub_instance


# ---------------------------------------------------------------------------
# Pull-request actions that DO trigger a review
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("action", ["opened", "synchronize", "reopened"])
def test_pull_request_triggers_review(clean_action_env, tmp_path, action):
    event_path, repo, number, sha = _write_event(tmp_path, action)
    clean_action_env.setenv("GITHUB_EVENT_PATH", event_path)
    clean_action_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_action_env.setenv("INPUT_GITHUB_TOKEN", "gh-test")
    clean_action_env.setenv("INPUT_OPENAI_API_KEY", "sk-test")

    _stub_cls, stub_instance = _install_stub_agent(clean_action_env)

    from src.action import main
    exit_code = main()

    assert exit_code == 0
    stub_instance.review_pr.assert_called_once_with(
        repo, number, commit_sha=sha,
    )


def test_inputs_mapped_onto_settings_env(clean_action_env, tmp_path):
    """INPUT_* vars must reach the Settings layer as the bare env names."""
    event_path, *_ = _write_event(tmp_path, "opened")
    clean_action_env.setenv("GITHUB_EVENT_PATH", event_path)
    clean_action_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_action_env.setenv("INPUT_GITHUB_TOKEN", "gh-inputval")
    clean_action_env.setenv("INPUT_OPENAI_API_KEY", "sk-inputval")
    clean_action_env.setenv("INPUT_LLM_MODEL", "gpt-4o")

    _install_stub_agent(clean_action_env)

    from src.action import main
    assert main() == 0

    assert os.environ["GITHUB_TOKEN"] == "gh-inputval"
    assert os.environ["OPENAI_API_KEY"] == "sk-inputval"
    assert os.environ["LLM_MODEL"] == "gpt-4o"


# ---------------------------------------------------------------------------
# Unrelated events exit 0 without invoking the agent
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("action", ["closed", "labeled", "edited", "assigned"])
def test_unrelated_pull_request_actions_exit_zero(clean_action_env, tmp_path,
                                                  action):
    event_path, *_ = _write_event(tmp_path, action)
    clean_action_env.setenv("GITHUB_EVENT_PATH", event_path)
    clean_action_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_action_env.setenv("INPUT_GITHUB_TOKEN", "gh-test")
    clean_action_env.setenv("INPUT_OPENAI_API_KEY", "sk-test")

    _stub_cls, stub_instance = _install_stub_agent(clean_action_env)

    from src.action import main
    assert main() == 0
    stub_instance.review_pr.assert_not_called()


def test_non_pull_request_event_exits_zero(clean_action_env, tmp_path):
    """e.g. `push` event should not invoke the agent."""
    event_path, *_ = _write_event(tmp_path, "opened")  # payload still PR-shaped
    clean_action_env.setenv("GITHUB_EVENT_PATH", event_path)
    clean_action_env.setenv("GITHUB_EVENT_NAME", "push")  # but the NAME differs
    clean_action_env.setenv("INPUT_GITHUB_TOKEN", "gh-test")
    clean_action_env.setenv("INPUT_OPENAI_API_KEY", "sk-test")

    _stub_cls, stub_instance = _install_stub_agent(clean_action_env)

    from src.action import main
    assert main() == 0
    stub_instance.review_pr.assert_not_called()


# ---------------------------------------------------------------------------
# Missing / misconfigured secrets -> exit 1
# ---------------------------------------------------------------------------
def test_missing_github_token_exits_one(clean_action_env, tmp_path):
    event_path, *_ = _write_event(tmp_path, "opened")
    clean_action_env.setenv("GITHUB_EVENT_PATH", event_path)
    clean_action_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    # Deliberately no INPUT_GITHUB_TOKEN and no GITHUB_TOKEN.
    clean_action_env.setenv("INPUT_OPENAI_API_KEY", "sk-test")

    from src.action import main
    assert main() == 1


def test_missing_openai_key_when_provider_openai_exits_one(clean_action_env,
                                                           tmp_path):
    event_path, *_ = _write_event(tmp_path, "opened")
    clean_action_env.setenv("GITHUB_EVENT_PATH", event_path)
    clean_action_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_action_env.setenv("INPUT_GITHUB_TOKEN", "gh-test")
    clean_action_env.setenv("INPUT_LLM_PROVIDER", "openai")
    # No INPUT_OPENAI_API_KEY.

    from src.action import main
    assert main() == 1


def test_missing_moonshot_key_when_provider_kimi_exits_one(clean_action_env,
                                                           tmp_path):
    event_path, *_ = _write_event(tmp_path, "opened")
    clean_action_env.setenv("GITHUB_EVENT_PATH", event_path)
    clean_action_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_action_env.setenv("INPUT_GITHUB_TOKEN", "gh-test")
    clean_action_env.setenv("INPUT_LLM_PROVIDER", "kimi")
    # No INPUT_MOONSHOT_API_KEY.

    from src.action import main
    assert main() == 1


# ---------------------------------------------------------------------------
# Local smoke-test fallback (no GITHUB_EVENT_PATH)
# ---------------------------------------------------------------------------
def test_cli_fallback_invokes_review_when_event_missing(clean_action_env):
    clean_action_env.setenv("INPUT_GITHUB_TOKEN", "gh-test")
    clean_action_env.setenv("INPUT_OPENAI_API_KEY", "sk-test")
    clean_action_env.setenv("CLI_REPO", "octocat/hello-world")
    clean_action_env.setenv("CLI_PR", "7")
    clean_action_env.setenv("CLI_SHA", "deadbeef")

    _stub_cls, stub_instance = _install_stub_agent(clean_action_env)

    from src.action import main
    assert main() == 0
    stub_instance.review_pr.assert_called_once_with(
        "octocat/hello-world", 7, commit_sha="deadbeef",
    )


def test_no_event_and_no_cli_fallback_exits_one(clean_action_env):
    clean_action_env.setenv("INPUT_GITHUB_TOKEN", "gh-test")
    clean_action_env.setenv("INPUT_OPENAI_API_KEY", "sk-test")
    # No GITHUB_EVENT_PATH, no CLI_*.

    from src.action import main
    assert main() == 1


# ---------------------------------------------------------------------------
# Agent failure propagates as exit 1
# ---------------------------------------------------------------------------
def test_agent_review_failure_returns_exit_one(clean_action_env, tmp_path):
    event_path, *_ = _write_event(tmp_path, "opened")
    clean_action_env.setenv("GITHUB_EVENT_PATH", event_path)
    clean_action_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_action_env.setenv("INPUT_GITHUB_TOKEN", "gh-test")
    clean_action_env.setenv("INPUT_OPENAI_API_KEY", "sk-test")

    _install_stub_agent(clean_action_env, review_result={
        "success": False,
        "message": "boom",
        "details": None,
    })

    from src.action import main
    assert main() == 1


def test_skipped_review_still_returns_exit_zero(clean_action_env, tmp_path):
    """A successful short-circuit (e.g. draft PR) must not fail the workflow."""
    event_path, *_ = _write_event(tmp_path, "opened")
    clean_action_env.setenv("GITHUB_EVENT_PATH", event_path)
    clean_action_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_action_env.setenv("INPUT_GITHUB_TOKEN", "gh-test")
    clean_action_env.setenv("INPUT_OPENAI_API_KEY", "sk-test")

    _install_stub_agent(clean_action_env, review_result={
        "success": True,
        "skipped": "draft",
        "message": "Draft/WIP — review deferred",
        "details": None,
    })

    from src.action import main
    assert main() == 0


def test_hyphenated_input_env_vars_are_normalized(clean_action_env):
    """GitHub Docker runtime passes inputs as INPUT_FOO-BAR; mirror to _."""
    clean_action_env.setenv("INPUT_GITHUB-TOKEN", "gh-hyphen")
    clean_action_env.setenv("INPUT_OPENAI-API-KEY", "sk-hyphen")
    clean_action_env.setenv("INPUT_DRY-RUN", "true")

    from src.action import _normalize_input_env_keys
    _normalize_input_env_keys()

    assert os.environ["INPUT_GITHUB_TOKEN"] == "gh-hyphen"
    assert os.environ["INPUT_OPENAI_API_KEY"] == "sk-hyphen"
    assert os.environ["INPUT_DRY_RUN"] == "true"
    # Original hyphenated keys preserved (we only mirror, never delete).
    assert os.environ["INPUT_GITHUB-TOKEN"] == "gh-hyphen"


def test_hyphen_normalization_does_not_clobber_existing_underscored_values(
    clean_action_env,
):
    """If both forms exist, the underscored value wins (user's explicit env)."""
    clean_action_env.setenv("INPUT_GITHUB-TOKEN", "from-hyphen")
    clean_action_env.setenv("INPUT_GITHUB_TOKEN", "from-underscore")

    from src.action import _normalize_input_env_keys
    _normalize_input_env_keys()

    assert os.environ["INPUT_GITHUB_TOKEN"] == "from-underscore"
