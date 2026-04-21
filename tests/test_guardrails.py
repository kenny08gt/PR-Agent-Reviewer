"""Tests for `review_pr` short-circuit paths (kill switch, draft, size).

Wave 3 (2026-04-21): dropped the history-dedup and GitLab tests. The
remaining short-circuits are GitHub-only and stateless — each Action
run is a fresh container, so the old durable-dedup scenario simply
can't exist at this layer.
"""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def clean_env(monkeypatch):
    """Baseline env: required keys present, guardrails at defaults."""
    for var in (
        "LLM_PROVIDER", "LLM_MODEL", "OPENAI_MODEL", "LLM_BASE_URL",
        "OPENAI_API_KEY", "MOONSHOT_API_KEY", "REVIEW_ENABLED",
        "MAX_FILES_TO_REVIEW", "MAX_DIFF_LINES", "GITHUB_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-test")
    yield monkeypatch


def _build_agent(monkeypatch):
    """Construct a PRReviewerAgent with the LLM + platform tools stubbed."""
    import src.agents.pr_reviewer as mod

    monkeypatch.setattr(
        mod, "get_chat_model",
        lambda _settings: MagicMock(name="chat_model"),
    )

    # Rebuild settings so REVIEW_ENABLED et al. pick up the patched env.
    from src.utils.config import Settings
    fresh = Settings(_env_file=None)
    monkeypatch.setattr(mod, "settings", fresh)

    monkeypatch.setattr(
        mod, "GitHubTools",
        lambda token: MagicMock(name="GitHubTools"),
    )
    monkeypatch.setattr(
        mod, "GetPRDetailsTool",
        lambda **kw: MagicMock(name="GetPRDetailsTool"),
    )
    monkeypatch.setattr(
        mod, "PostReviewTool",
        lambda **kw: MagicMock(name="PostReviewTool"),
    )

    # Short-circuit _create_agent so we never build a real AgentExecutor.
    monkeypatch.setattr(
        mod.PRReviewerAgent, "_create_agent",
        lambda self: MagicMock(name="AgentExecutor"),
    )

    agent = mod.PRReviewerAgent()
    agent.agent = MagicMock(name="agent_executor")
    agent.gh_tools = MagicMock(name="gh_tools")
    return agent, mod


# ---------------------------------------------------------------------------
# (1) Kill switch — REVIEW_ENABLED=false
# ---------------------------------------------------------------------------
def test_review_disabled_short_circuits(clean_env):
    clean_env.setenv("REVIEW_ENABLED", "false")
    pr_agent, _mod = _build_agent(clean_env)

    result = pr_agent.review_pr("octo/demo", 1, commit_sha="abc")

    assert result == {
        "success": True,
        "skipped": "disabled",
        "message": "Review skipped: REVIEW_ENABLED=false",
        "details": None,
    }
    pr_agent.agent.invoke.assert_not_called()
    pr_agent.gh_tools.get_pr_details.assert_not_called()
    pr_agent.gh_tools.post_review_comment.assert_not_called()


# ---------------------------------------------------------------------------
# (2) Draft / WIP
# ---------------------------------------------------------------------------
def test_draft_pr_is_skipped(clean_env):
    pr_agent, _mod = _build_agent(clean_env)

    pr_agent.gh_tools.get_pr_details.return_value = {
        "title": "Draft: wip",
        "draft": True,
        "files": [{"filename": "src/a.py", "patch": "+x\n"}],
    }

    result = pr_agent.review_pr("octo/demo", 7, commit_sha="sha1")

    assert result == {
        "success": True,
        "skipped": "draft",
        "message": "Draft/WIP — review deferred",
        "details": None,
    }
    pr_agent.agent.invoke.assert_not_called()
    pr_agent.gh_tools.post_review_comment.assert_not_called()


# ---------------------------------------------------------------------------
# (3) Size limits
# ---------------------------------------------------------------------------
def test_too_many_files_posts_skip_notice_and_no_llm(clean_env):
    clean_env.setenv("MAX_FILES_TO_REVIEW", "2")
    clean_env.setenv("MAX_DIFF_LINES", "10000")
    pr_agent, _mod = _build_agent(clean_env)

    # 5 files > limit of 2
    files = [{"filename": f"src/f{i}.py", "patch": "+x\n"} for i in range(5)]
    pr_agent.gh_tools.get_pr_details.return_value = {
        "title": "big change",
        "draft": False,
        "files": files,
    }
    pr_agent.gh_tools.post_review_comment.return_value = True

    result = pr_agent.review_pr("octo/demo", 99, commit_sha="sha99")

    assert result["success"] is True
    assert result["skipped"] == "too_large"
    assert pr_agent.gh_tools.post_review_comment.call_count == 1
    pr_agent.agent.invoke.assert_not_called()

    # signature: (repo_name, pr_number, comment, commit_sha)
    args, _ = pr_agent.gh_tools.post_review_comment.call_args
    assert args[0] == "octo/demo"
    assert args[1] == 99
    assert "safety limits" in args[2]
    assert args[3] == "sha99"


def test_too_many_diff_lines_posts_skip_notice(clean_env):
    clean_env.setenv("MAX_FILES_TO_REVIEW", "1000")
    clean_env.setenv("MAX_DIFF_LINES", "5")
    pr_agent, _mod = _build_agent(clean_env)

    # 10 added lines > limit 5
    big_patch = "\n".join(f"+added {i}" for i in range(10)) + "\n"
    pr_agent.gh_tools.get_pr_details.return_value = {
        "title": "big",
        "draft": False,
        "files": [{"filename": "src/a.py", "patch": big_patch}],
    }
    pr_agent.gh_tools.post_review_comment.return_value = True

    result = pr_agent.review_pr("octo/demo", 5, commit_sha="sha5")
    assert result["skipped"] == "too_large"
    pr_agent.agent.invoke.assert_not_called()
    assert pr_agent.gh_tools.post_review_comment.call_count == 1


# ---------------------------------------------------------------------------
# (4) Happy path — small, non-draft, enabled
# ---------------------------------------------------------------------------
def test_happy_path_invokes_agent_once(clean_env):
    pr_agent, _mod = _build_agent(clean_env)

    pr_agent.gh_tools.get_pr_details.return_value = {
        "title": "tiny",
        "draft": False,
        "files": [{"filename": "src/a.py", "patch": "+one line\n"}],
    }
    pr_agent.agent.invoke.return_value = {"output": "looks good"}

    result = pr_agent.review_pr("octo/demo", 1, commit_sha="cafebabe")

    assert result["success"] is True
    assert "skipped" not in result
    pr_agent.agent.invoke.assert_called_once()
    # No skip-notice post on the happy path.
    pr_agent.gh_tools.post_review_comment.assert_not_called()
