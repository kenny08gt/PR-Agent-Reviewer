"""Unit tests for `src/utils/diff_parser.py`.

Covers the `position`-semantics contract we rely on when posting inline
review comments: position starts at 1 under the first hunk header,
keeps incrementing across hunks (does NOT reset), and skips file-header
lines and `\\ No newline` markers.
"""
import pytest

from src.utils.diff_parser import DiffLine, find_position_for_line, parse_patch


# ---------------------------------------------------------------------------
# parse_patch — base cases
# ---------------------------------------------------------------------------

def test_parse_patch_empty_returns_empty_list():
    assert parse_patch("") == []


def test_parse_patch_none_raises_type_error():
    # Matches the redactor's convention — callers must not pass None.
    with pytest.raises(TypeError):
        parse_patch(None)  # type: ignore[arg-type]


def test_parse_patch_single_hunk_context_plus_added():
    """A 1-hunk patch with one context line and one added line."""
    patch = "@@ -1,1 +1,2 @@\n old\n+new\n"
    dls = parse_patch(patch)

    assert len(dls) == 2

    # First line after the hunk header = position 1 (context line).
    assert dls[0] == DiffLine(
        kind="context",
        new_line=1,
        old_line=1,
        position=1,
        content="old",
    )
    # Added line — new_line advances; old_line stays None.
    assert dls[1] == DiffLine(
        kind="added",
        new_line=2,
        old_line=None,
        position=2,
        content="new",
    )


def test_parse_patch_added_lines_have_new_line_only():
    patch = "@@ -10,0 +10,3 @@\n+a\n+b\n+c\n"
    dls = parse_patch(patch)
    assert [dl.kind for dl in dls] == ["added", "added", "added"]
    assert [dl.new_line for dl in dls] == [10, 11, 12]
    assert all(dl.old_line is None for dl in dls)
    assert [dl.position for dl in dls] == [1, 2, 3]


def test_parse_patch_removed_only_has_new_line_none():
    patch = "@@ -5,3 +5,0 @@\n-a\n-b\n-c\n"
    dls = parse_patch(patch)
    assert [dl.kind for dl in dls] == ["removed", "removed", "removed"]
    assert [dl.old_line for dl in dls] == [5, 6, 7]
    assert all(dl.new_line is None for dl in dls)
    assert [dl.position for dl in dls] == [1, 2, 3]


# ---------------------------------------------------------------------------
# parse_patch — multi-hunk position continuity
# ---------------------------------------------------------------------------

def test_parse_patch_multi_hunk_position_continues_line_numbers_reset():
    """Position MUST keep counting across hunks; line numbers jump per hunk.

    Regression guard: the trivial bug is to reset position to 0 on every
    hunk header.
    """
    patch = (
        "@@ -1,2 +1,2 @@\n"
        " first\n"
        "+added-1\n"
        "@@ -100,1 +101,2 @@\n"
        " hundredth\n"
        "+added-2\n"
    )
    dls = parse_patch(patch)
    # Expect 4 DiffLines (2 per hunk). Hunk headers don't emit a DiffLine.
    assert len(dls) == 4

    positions = [dl.position for dl in dls]
    # 1, 2 (first hunk) then 3, 4 (second hunk) — NO reset.
    assert positions == [1, 2, 3, 4]

    # Line numbers jumped per the second hunk header.
    assert dls[2].new_line == 101
    assert dls[2].old_line == 100
    assert dls[3].new_line == 102  # added line
    assert dls[3].old_line is None


# ---------------------------------------------------------------------------
# parse_patch — header / footer edge cases
# ---------------------------------------------------------------------------

def test_parse_patch_ignores_file_headers():
    """`diff --git`, `index ...`, `+++ b/foo`, `--- a/foo` don't count."""
    patch = (
        "diff --git a/foo.py b/foo.py\n"
        "index 1234abc..5678def 100644\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,1 +1,2 @@\n"
        " a\n"
        "+b\n"
    )
    dls = parse_patch(patch)
    assert len(dls) == 2
    assert dls[0].position == 1  # first line under hunk header
    assert dls[1].position == 2


def test_parse_patch_ignores_no_newline_marker():
    """`\\ No newline at end of file` never emits a DiffLine or counts."""
    patch = (
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "\\ No newline at end of file\n"
        "+new\n"
        "\\ No newline at end of file\n"
    )
    dls = parse_patch(patch)
    assert [dl.kind for dl in dls] == ["removed", "added"]
    assert [dl.position for dl in dls] == [1, 2]


def test_parse_patch_omitted_hunk_counts():
    """`@@ -5 +5 @@` (counts omitted) is valid and defaults to 1."""
    patch = "@@ -5 +5 @@\n-old\n+new\n"
    dls = parse_patch(patch)
    assert len(dls) == 2
    assert dls[0] == DiffLine(
        kind="removed", new_line=None, old_line=5, position=1, content="old"
    )
    assert dls[1] == DiffLine(
        kind="added", new_line=5, old_line=None, position=2, content="new"
    )


def test_parse_patch_new_file_zero_start():
    """`@@ -0,0 +1,5 @@` — every DiffLine is added (no OLD side)."""
    patch = "@@ -0,0 +1,3 @@\n+alpha\n+beta\n+gamma\n"
    dls = parse_patch(patch)
    assert [dl.kind for dl in dls] == ["added", "added", "added"]
    assert [dl.new_line for dl in dls] == [1, 2, 3]
    assert all(dl.old_line is None for dl in dls)


def test_parse_patch_preserves_redacted_placeholders():
    """Redacted placeholders (`[REDACTED:github-token]`) ride through as content."""
    patch = (
        "@@ -1,1 +1,2 @@\n"
        " existing\n"
        "+token = \"[REDACTED:github-token]\"\n"
    )
    dls = parse_patch(patch)
    assert dls[1].kind == "added"
    assert "[REDACTED:github-token]" in dls[1].content


# ---------------------------------------------------------------------------
# find_position_for_line
# ---------------------------------------------------------------------------

def test_find_position_for_line_matches_added():
    patch = "@@ -1,1 +1,2 @@\n old\n+new\n"
    # Line 2 in the NEW file is the added one; it's at position 2.
    assert find_position_for_line(patch, 2, side="new") == 2


def test_find_position_for_line_matches_context():
    patch = "@@ -1,1 +1,2 @@\n old\n+new\n"
    assert find_position_for_line(patch, 1, side="new") == 1


def test_find_position_for_line_outside_hunk_returns_none():
    """File line outside the hunk window -> None (can't comment there)."""
    patch = "@@ -1,1 +1,2 @@\n old\n+new\n"
    assert find_position_for_line(patch, 999, side="new") is None


def test_find_position_for_line_removed_only_line_side_new_is_none():
    """A file_line that's only in the OLD side can't be mapped with side='new'."""
    patch = "@@ -5,1 +4,0 @@\n-removed\n"
    # Line 5 existed only in OLD; side='new' must return None.
    assert find_position_for_line(patch, 5, side="new") is None
    # But side='old' finds it at position 1.
    assert find_position_for_line(patch, 5, side="old") == 1


def test_find_position_for_line_invalid_side_raises():
    with pytest.raises(ValueError):
        find_position_for_line("", 1, side="sideways")


def test_find_position_for_line_multi_hunk():
    """Second hunk's file lines still map to a position that counts across."""
    patch = (
        "@@ -1,2 +1,2 @@\n"
        " first\n"
        "+added-1\n"
        "@@ -100,1 +101,2 @@\n"
        " hundredth\n"
        "+added-2\n"
    )
    # `added-2` is at new_line=102, position=4.
    assert find_position_for_line(patch, 102, side="new") == 4
    # `hundredth` context line -> position 3.
    assert find_position_for_line(patch, 101, side="new") == 3
