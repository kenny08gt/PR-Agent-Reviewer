"""Unit tests for `PostReviewTool._run`.

Covers both the pre-Wave-4 summary-only path (backward compat) and the
new inline-comments path introduced in Wave 4. PyGithub is never
touched here — we mock `GitHubTools` wholesale so these tests run
offline and deterministically.
"""
from unittest.mock import MagicMock

import pytest

from src.tools.github_tools import GitHubTools, PostReviewTool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def gh_tools():
    """A mock `GitHubTools` with sensible defaults.

    `get_pr_details` returns two small patches so `find_position_for_line`
    has real data to work with. `post_review_comment` and
    `post_inline_review` both return True.

    `spec=GitHubTools` satisfies Pydantic's isinstance check inside
    `PostReviewTool`'s `github_tools: GitHubTools` field.
    """
    m = MagicMock(spec=GitHubTools)
    m.post_review_comment.return_value = True
    m.post_inline_review.return_value = True
    m.get_pr_details.return_value = {
        "files": [
            # foo.py — line 2 is added (position 2), line 1 context (position 1).
            {
                "filename": "foo.py",
                "patch": "@@ -1,1 +1,2 @@\n old\n+new\n",
            },
            # bar.py — line 2 is added (position 2), line 1 context (position 1).
            {
                "filename": "bar.py",
                "patch": "@@ -1,1 +1,2 @@\n x\n+y\n",
            },
        ]
    }
    return m


@pytest.fixture
def tool(gh_tools):
    return PostReviewTool(github_tools=gh_tools)


@pytest.fixture(autouse=True)
def clear_dry_run(monkeypatch):
    """Default: dry-run OFF for every test. Individual tests can set it."""
    monkeypatch.delenv("INPUT_DRY_RUN", raising=False)
    yield


# ---------------------------------------------------------------------------
# Summary-only path (backward compat with Wave 3 call shape)
# ---------------------------------------------------------------------------

def test_summary_only_path_calls_post_review_comment_once(tool, gh_tools):
    result = tool._run(
        repo_name="octo/demo",
        pr_number=7,
        comment="overall looks good",
        commit_sha="abc123",
    )
    gh_tools.post_review_comment.assert_called_once_with(
        "octo/demo", 7, "overall looks good", "abc123")
    gh_tools.post_inline_review.assert_not_called()
    gh_tools.get_pr_details.assert_not_called()
    assert "successfully" in result.lower()


def test_summary_only_explicit_none_comments(tool, gh_tools):
    """Passing `comments=None` is equivalent to omitting it."""
    tool._run(
        repo_name="octo/demo",
        pr_number=7,
        comment="s",
        commit_sha="abc",
        comments=None,
    )
    gh_tools.post_review_comment.assert_called_once()
    gh_tools.post_inline_review.assert_not_called()


def test_summary_only_empty_list_falls_back_to_summary(tool, gh_tools):
    """An empty `comments=[]` should NOT go through the inline path."""
    tool._run(
        repo_name="octo/demo",
        pr_number=7,
        comment="s",
        commit_sha="abc",
        comments=[],
    )
    gh_tools.post_review_comment.assert_called_once()
    gh_tools.post_inline_review.assert_not_called()


def test_summary_only_failure_returns_error_string(tool, gh_tools):
    gh_tools.post_review_comment.return_value = False
    result = tool._run(
        repo_name="octo/demo", pr_number=1,
        comment="x", commit_sha="sha",
    )
    assert "failed" in result.lower()


# ---------------------------------------------------------------------------
# Inline path — all lines map cleanly
# ---------------------------------------------------------------------------

def test_inline_all_lines_map_calls_post_inline_review(tool, gh_tools):
    comments = [
        {"path": "foo.py", "line": 2, "body": "consider renaming"},
        {"path": "bar.py", "line": 2, "body": "off-by-one risk"},
    ]
    result = tool._run(
        repo_name="octo/demo", pr_number=42,
        comment="Summary: LGTM with nits.",
        commit_sha="deadbeef",
        comments=comments,
    )

    gh_tools.post_inline_review.assert_called_once()
    gh_tools.post_review_comment.assert_not_called()

    # Verify the positions were translated correctly.
    args = gh_tools.post_inline_review.call_args.args
    # signature: (repo_name, pr_number, summary, inline_comments, commit_sha)
    assert args[0] == "octo/demo"
    assert args[1] == 42
    assert args[2] == "Summary: LGTM with nits."
    inline = args[3]
    assert args[4] == "deadbeef"

    assert len(inline) == 2
    # foo.py line 2 -> position 2; bar.py line 2 -> position 2.
    assert inline[0] == {"path": "foo.py", "position": 2, "body": "consider renaming"}
    assert inline[1] == {"path": "bar.py", "position": 2, "body": "off-by-one risk"}

    assert "2 inline" in result


# ---------------------------------------------------------------------------
# Inline path — partial mapping
# ---------------------------------------------------------------------------

def test_inline_some_lines_skipped_count_reported(tool, gh_tools, caplog):
    comments = [
        {"path": "foo.py", "line": 2, "body": "valid"},
        {"path": "foo.py", "line": 999, "body": "out of range"},  # no position
        {"path": "unknown.py", "line": 1, "body": "unknown file"},  # no patch
    ]
    with caplog.at_level("WARNING"):
        result = tool._run(
            repo_name="octo/demo", pr_number=9,
            comment="summary",
            commit_sha="sha9",
            comments=comments,
        )

    gh_tools.post_inline_review.assert_called_once()
    inline = gh_tools.post_inline_review.call_args.args[3]
    assert len(inline) == 1
    assert inline[0]["path"] == "foo.py"
    assert inline[0]["position"] == 2

    assert "1 inline" in result
    assert "2 skipped" in result

    # Count is logged; bodies are NOT.
    joined = "\n".join(rec.message for rec in caplog.records)
    assert "skipped 2 inline comment" in joined
    assert "out of range" not in joined
    assert "unknown file" not in joined


# ---------------------------------------------------------------------------
# Inline path — no lines map -> fallback to summary-only
# ---------------------------------------------------------------------------

def test_inline_no_lines_map_falls_back_to_summary(tool, gh_tools):
    comments = [
        {"path": "foo.py", "line": 999, "body": "miss"},
        {"path": "ghost.py", "line": 1, "body": "also miss"},
    ]
    result = tool._run(
        repo_name="octo/demo", pr_number=9,
        comment="overall summary",
        commit_sha="sha9",
        comments=comments,
    )

    # Must fall back — post_review_comment called, post_inline_review NOT.
    gh_tools.post_inline_review.assert_not_called()
    gh_tools.post_review_comment.assert_called_once_with(
        "octo/demo", 9, "overall summary", "sha9")

    assert "no inline comments could be mapped" in result.lower()
    assert "summary-only" in result.lower()


# ---------------------------------------------------------------------------
# Dry-run honored for both paths, stub reports inline count
# ---------------------------------------------------------------------------

def test_dry_run_summary_only(tool, gh_tools, monkeypatch):
    monkeypatch.setenv("INPUT_DRY_RUN", "true")
    result = tool._run(
        repo_name="octo/demo", pr_number=1,
        comment="hi", commit_sha="sha",
    )
    gh_tools.post_review_comment.assert_not_called()
    gh_tools.post_inline_review.assert_not_called()
    assert "[DRY RUN]" in result
    assert "NOT posted" in result


def test_dry_run_inline_reports_count(tool, gh_tools, monkeypatch):
    monkeypatch.setenv("INPUT_DRY_RUN", "true")
    comments = [
        {"path": "foo.py", "line": 2, "body": "c1"},
        {"path": "bar.py", "line": 2, "body": "c2"},
        {"path": "baz.py", "line": 2, "body": "c3"},
    ]
    result = tool._run(
        repo_name="octo/demo", pr_number=1,
        comment="hi", commit_sha="sha",
        comments=comments,
    )
    gh_tools.post_review_comment.assert_not_called()
    gh_tools.post_inline_review.assert_not_called()
    # We should NOT even fetch PR details in dry-run.
    gh_tools.get_pr_details.assert_not_called()
    assert "[DRY RUN]" in result
    assert "3 inline" in result
