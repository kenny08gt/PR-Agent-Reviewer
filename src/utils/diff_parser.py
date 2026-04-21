"""Unified-diff parser used to translate file-line numbers into the
`position` integer that GitHub's review-comments API expects.

Pure module: no PyGithub, no Settings, no I/O. Callers feed it the same
`patch` string that `GitHubTools.get_pr_details` already redacted, and
it returns a flat list of `DiffLine`s that know both:
  * the `new_line` / `old_line` number in the respective file, and
  * the 1-based `position` within the diff — which is the value the
    GitHub REST v3 review-comments API wants as `position=`. This value
    is the count of lines under the hunk headers only; hunk headers
    themselves don't count and the file-header lines (`diff --git`,
    `index ...`, `+++ ...`, `---`) don't count either. The counter does
    NOT reset between hunks.

GitHub's newer `line` + `side` API is deliberately not used here — the
`position` form works across more Enterprise Server installs and PyGithub
versions, and the agent's tests mock the call anyway.

Why `parse_patch(None)` raises instead of returning `[]`: matches the
redactor's convention. A None patch almost always means "we fetched a
file without changes", which should be filtered upstream. Failing loudly
here stops that bug from becoming a silent miss.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

# `@@ -a[,b] +c[,d] @@` — the counts are optional (`@@ -5 +5 @@` is valid
# and means a single-line hunk on each side).
_HUNK_RE = re.compile(
    r"^@@\s*-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?\s+"
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s*@@"
)


@dataclass(frozen=True)
class DiffLine:
    """One line within a unified diff, with both file-line and position info.

    Attributes:
        kind: "added" | "removed" | "context".
        new_line: 1-based line number in the NEW file. None for removed lines.
        old_line: 1-based line number in the OLD file. None for added lines.
        position: 1-based position within the diff, counting only lines under
            hunk headers. This is the GitHub-API `position` value.
        content: The line content without the leading `+` / `-` / ` ` marker.
    """

    kind: str
    new_line: Optional[int]
    old_line: Optional[int]
    position: int
    content: str


def parse_patch(patch: str) -> List[DiffLine]:
    """Parse a unified-diff `patch` string into `DiffLine` entries.

    Rules encoded here:
      * File-header lines (`diff --git ...`, `index ...`, `+++ ...`, `---`)
        do NOT increment `position`.
      * `@@ ... @@` hunk-header lines do NOT increment `position`; they
        reset the per-file line counters to the values they declare.
      * Every other line (added `+...`, removed `-...`, context ` ...`)
        increments `position` by 1.
      * `\\ No newline at end of file` markers are ignored — they don't
        emit a `DiffLine` and don't count toward `position`.
      * Multi-hunk patches: position keeps counting across hunks; file
        line numbers jump per the new hunk header.

    Raises:
        TypeError: if `patch` is not a string (matches the redactor's
            convention — callers must not pass None silently).
    """
    if not isinstance(patch, str):
        raise TypeError(
            f"parse_patch() requires a str, got {type(patch).__name__}"
        )
    if not patch:
        return []

    lines: List[DiffLine] = []
    position = 0
    new_line_cursor: Optional[int] = None
    old_line_cursor: Optional[int] = None
    in_hunk = False

    for raw in patch.splitlines():
        # File-level headers — ignored, no position increment, no DiffLine.
        if raw.startswith("diff --git") or raw.startswith("index "):
            continue
        if raw.startswith("+++") or raw.startswith("---"):
            # `+++ b/foo` and `--- a/foo` — also `--- /dev/null`. None of
            # these count; they precede the first hunk header.
            continue

        # Hunk header — resets the per-file line cursors. Does NOT count
        # toward position.
        m = _HUNK_RE.match(raw)
        if m:
            old_line_cursor = int(m.group("old_start"))
            new_line_cursor = int(m.group("new_start"))
            in_hunk = True
            continue

        # "\ No newline at end of file" — ignore entirely.
        if raw.startswith("\\"):
            continue

        # Everything else only counts once we've seen a hunk header. A
        # malformed patch that has content before the first `@@` is
        # skipped defensively (don't count garbage).
        if not in_hunk:
            continue

        position += 1

        if raw.startswith("+"):
            content = raw[1:]
            assert new_line_cursor is not None
            lines.append(DiffLine(
                kind="added",
                new_line=new_line_cursor,
                old_line=None,
                position=position,
                content=content,
            ))
            new_line_cursor += 1
        elif raw.startswith("-"):
            content = raw[1:]
            assert old_line_cursor is not None
            lines.append(DiffLine(
                kind="removed",
                new_line=None,
                old_line=old_line_cursor,
                position=position,
                content=content,
            ))
            old_line_cursor += 1
        else:
            # Context line. Git emits them prefixed with a single space,
            # but some tools/edge-cases produce a bare empty line inside
            # a hunk — treat that as an empty context line too.
            content = raw[1:] if raw.startswith(" ") else raw
            assert new_line_cursor is not None and old_line_cursor is not None
            lines.append(DiffLine(
                kind="context",
                new_line=new_line_cursor,
                old_line=old_line_cursor,
                position=position,
                content=content,
            ))
            new_line_cursor += 1
            old_line_cursor += 1

    return lines


def find_position_for_line(
    patch: str,
    file_line: int,
    *,
    side: str = "new",
) -> Optional[int]:
    """Return the GitHub `position` corresponding to `file_line`, or None.

    Args:
        patch: unified-diff patch string.
        file_line: 1-based line number in the target file.
        side: "new" (default) or "old". With "new" we only consider
            added or context lines — their `new_line` is what we match
            against `file_line`. With "old" we consider removed or
            context lines and match `old_line`.

    Returns:
        The `position` integer for that line, or None if the line isn't
        present in the diff (very common — we can't comment on unchanged
        lines outside the hunk windows). Callers should treat None as
        "skip this inline comment" rather than posting a default.
    """
    if side not in ("new", "old"):
        raise ValueError(f"side must be 'new' or 'old', got {side!r}")

    for dl in parse_patch(patch):
        if side == "new":
            # Added and context lines both have a valid `new_line`.
            if dl.kind in ("added", "context") and dl.new_line == file_line:
                return dl.position
        else:
            if dl.kind in ("removed", "context") and dl.old_line == file_line:
                return dl.position
    return None
