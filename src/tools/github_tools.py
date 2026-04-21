"""GitHub API tools used by the LangChain agent.

The two BaseTool subclasses at the bottom are what the LLM calls; the
underlying `GitHubTools` class is a plain wrapper around PyGithub so
both the tools and the `review_pr` short-circuit paths can share one
instance.

Wave 3 additions:
- Secret redaction is applied to each file's patch inside
  `get_pr_details` BEFORE the data is handed to the agent (see
  `src/utils/redactor.py`). We log only the redaction count — never
  the matches.
- `PostReviewTool._run` honors the `INPUT_DRY_RUN` env var. When the
  Action is invoked with `dry-run: true`, the agent's natural call to
  `post_review` returns a stub success message without actually
  touching the PR. This keeps the tool-calling loop well-formed without
  adding a branch in the agent prompt.

Wave 4 additions:
- `post_inline_review` creates a single COMMENT-type review that carries
  a list of per-line comments. Each comment is `{path, position, body}`
  — NOT `{path, line, body}`. PyGithub's `create_review(comments=...)`
  pipes the dicts straight to the v3 REST API, which expects `position`
  (unified-diff position, NOT the file line number). We use the
  `diff_parser` module to translate `(path, line)` inputs from the agent
  into the correct `position` value, and skip any comment we can't map.
- `PostReviewTool._run` accepts an optional `comments` arg. When
  present and non-empty, it routes through `post_inline_review`. When
  every comment fails to map (none of the agent's chosen lines are in
  the diff window) we fall back to the summary-only review so the tool
  always produces a user-visible output.
"""
import logging
import os
from typing import Any, Dict, List, Optional

from github import Github
from langchain.tools import BaseTool
from pydantic import Field

from ..utils.diff_filter import partition_files
from ..utils.diff_parser import find_position_for_line
from ..utils.redactor import redact_with_count

logger = logging.getLogger(__name__)


class GitHubTools:
    def __init__(self, token: str):
        self.github = Github(token)

    def get_pr_details(self, repo_name: str, pr_number: int) -> Dict[str, Any]:
        """Return PR metadata + filtered, redacted file patches.

        The returned dict's `files[*].patch` is already secret-redacted
        so anything downstream (the LLM, logs) only ever sees
        placeholders. The `redaction_count` field is informational — it
        lets `review_pr` log how many secrets got scrubbed without
        touching the raw values.
        """
        try:
            repo = self.github.get_repo(repo_name)
            pr = repo.get_pull(pr_number)

            raw_files = []
            for file in pr.get_files():
                if file.patch:  # only files with actual changes
                    raw_files.append({
                        'filename': file.filename,
                        'status': file.status,
                        'additions': file.additions,
                        'deletions': file.deletions,
                        'patch': file.patch[:2000],  # limit patch size
                        'blob_url': file.blob_url,
                    })

            # Apply skip filter (lockfiles, vendored dirs, generated, minified).
            files, skipped_files = partition_files(raw_files)
            if skipped_files:
                logger.info(
                    "Skipped %d low-value file(s) in %s#%s: %s",
                    len(skipped_files), repo_name, pr_number, skipped_files,
                )

            # Redact obvious secret patterns in the remaining patches. We
            # mutate the kept dicts in place so the rest of the pipeline
            # never sees the originals.
            total_redactions = 0
            for f in files:
                original = f.get('patch') or ''
                scrubbed, n = redact_with_count(original)
                f['patch'] = scrubbed
                total_redactions += n
            if total_redactions:
                # Count only — NEVER log the matches themselves.
                logger.info(
                    "redactor: redacted %d potential secrets in %s#%s",
                    total_redactions, repo_name, pr_number,
                )

            return {
                'title': pr.title,
                'body': pr.body or '',
                'state': pr.state,
                'draft': bool(getattr(pr, 'draft', False)),
                'author': pr.user.login,
                'base_branch': pr.base.ref,
                'head_branch': pr.head.ref,
                'files': files,
                'skipped_files': skipped_files,
                'redaction_count': total_redactions,
                'commits_count': pr.commits,
                'additions': pr.additions,
                'deletions': pr.deletions,
                'changed_files': pr.changed_files,
                'sha': pr.head.sha,
            }

        except Exception as e:
            logger.error(f"Error fetching PR details: {e}")
            raise

    def post_review_comment(self, repo_name: str, pr_number: int,
                            comment: str, commit_sha: str) -> bool:
        """Post a COMMENT-type review on the PR (summary body only)."""
        try:
            repo = self.github.get_repo(repo_name)
            pr = repo.get_pull(pr_number)

            pr.create_review(
                commit=repo.get_commit(commit_sha),
                body=comment,
                event="COMMENT",
            )
            return True

        except Exception as e:
            logger.error(f"Error posting review comment: {e}")
            return False

    def post_inline_review(
        self,
        repo_name: str,
        pr_number: int,
        summary: str,
        inline_comments: List[Dict[str, Any]],
        commit_sha: str,
    ) -> bool:
        """Post a single COMMENT-type review with per-line inline comments.

        Args:
            inline_comments: list of `{path, position, body}` dicts. These
                go straight to `pr.create_review(comments=...)`. The
                `position` is the GitHub unified-diff position (NOT the
                file line number); see `src/utils/diff_parser.py`.

        Returns True on success, False on any exception. The exception is
        logged — never re-raised — so the tool can fall back to a
        summary-only review if GitHub rejects the batch.
        """
        try:
            repo = self.github.get_repo(repo_name)
            pr = repo.get_pull(pr_number)

            pr.create_review(
                commit=repo.get_commit(commit_sha),
                body=summary,
                event="COMMENT",
                comments=inline_comments,
            )
            return True

        except Exception as e:
            logger.error(f"Error posting inline review: {e}")
            return False


class GetPRDetailsTool(BaseTool):
    name: str = "get_pr_details"
    description: str = "Get details about a GitHub Pull Request including changed files and diffs"
    github_tools: GitHubTools = Field(exclude=True)

    def _run(self, repo_name: str, pr_number: int) -> str:
        """Get PR details and return as a formatted string for the LLM."""
        details = self.github_tools.get_pr_details(repo_name, pr_number)

        formatted_output = f"""
PR Details:
Title: {details['title']}
Author: {details['author']}
Base Branch: {details['base_branch']} -> Head Branch: {details['head_branch']}
State: {details['state']}

Description:
{details['body']}

Files Changed ({details['changed_files']}):
+{details['additions']} -{details['deletions']} lines

Changed Files:
"""

        for file in details['files'][:10]:  # first 10 files only
            formatted_output += f"\n- {file['filename']} ({file['status']})\n"
            formatted_output += f"   +{file['additions']} -{file['deletions']} lines\n"
            if file['patch']:
                formatted_output += f"   Diff preview:\n{file['patch'][:500]}...\n"

        if details.get('skipped_files'):
            formatted_output += (
                f"\nSkipped (lockfiles / vendored / generated / minified): "
                f"{', '.join(details['skipped_files'])}\n"
            )

        return formatted_output


class PostReviewTool(BaseTool):
    name: str = "post_review"
    description: str = (
        "Post a review on a GitHub Pull Request. Provide `comment` as the "
        "overall summary body. Optionally provide `comments`: a list of "
        "{path, line, body} dicts for per-line inline feedback. Use `line` "
        "as the 1-based NEW-file line number (added or modified lines only)."
    )
    github_tools: GitHubTools = Field(exclude=True)

    def _run(
        self,
        repo_name: str,
        pr_number: int,
        comment: str,
        commit_sha: str,
        comments: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Post a review — summary-only or with inline comments.

        Behavior matrix:
          * `INPUT_DRY_RUN=true` -> return a dry-run stub; do not touch
            GitHub. The stub includes the inline-comment count so the
            user can see what the agent *would* have posted.
          * `comments` is None or empty -> single summary-only review
            (backward-compatible with the Wave 3 call shape).
          * `comments` is non-empty -> map each `(path, line)` to a diff
            `position` using `diff_parser.find_position_for_line`. Skip
            comments whose line isn't present in the diff window. If
            ALL fail to map, fall back to the summary-only path.
        """
        inline_count = len(comments) if comments else 0

        if os.environ.get("INPUT_DRY_RUN", "").lower() == "true":
            logger.info(
                "dry-run: skipping actual post_review for %s#%s "
                "(comment length=%d chars, inline_comments=%d)",
                repo_name, pr_number, len(comment or ""), inline_count,
            )
            if inline_count:
                return (
                    f"[DRY RUN] Review NOT posted. Would have posted a "
                    f"summary plus {inline_count} inline comment(s). "
                    "See action logs for the generated content."
                )
            return (
                "[DRY RUN] Review comment NOT posted. "
                "The generated review has been captured in action logs."
            )

        # Summary-only path — identical to pre-Wave-4 behavior.
        if not comments:
            success = self.github_tools.post_review_comment(
                repo_name, pr_number, comment, commit_sha)
            return ("Review comment posted successfully!"
                    if success else "Failed to post review comment.")

        # Inline path — need the per-file patches to translate line -> position.
        # Re-fetching is cheap (one API call) and keeps this tool
        # self-contained. The patches come back already-redacted.
        try:
            details = self.github_tools.get_pr_details(repo_name, pr_number)
        except Exception as exc:
            logger.error(
                "post_review: failed to re-fetch PR details for inline "
                "mapping (%s#%s): %s — falling back to summary-only.",
                repo_name, pr_number, exc,
            )
            success = self.github_tools.post_review_comment(
                repo_name, pr_number, comment, commit_sha)
            return (
                "Inline comment mapping failed (could not fetch PR details); "
                + ("posted summary-only review." if success
                   else "summary-only post also failed.")
            )

        patches_by_path = {
            f.get("filename"): (f.get("patch") or "")
            for f in (details.get("files") or [])
        }

        mapped: List[Dict[str, Any]] = []
        skipped = 0
        for c in comments:
            path = c.get("path")
            line = c.get("line")
            body = c.get("body")
            if not path or line is None or not body:
                skipped += 1
                continue
            patch = patches_by_path.get(path)
            if patch is None:
                # Agent picked a path that's not in the reviewed file set
                # (either filtered out or hallucinated).
                skipped += 1
                continue
            try:
                position = find_position_for_line(patch, int(line), side="new")
            except (TypeError, ValueError):
                skipped += 1
                continue
            if position is None:
                skipped += 1
                continue
            mapped.append({
                "path": path,
                "position": position,
                "body": body,
            })

        if skipped:
            # Log COUNT ONLY — never log bodies, paths are fine (not secret).
            logger.warning(
                "post_review: skipped %d inline comment(s) that could not "
                "be mapped to a diff position for %s#%s",
                skipped, repo_name, pr_number,
            )

        if not mapped:
            # Nothing survived mapping — degrade gracefully.
            success = self.github_tools.post_review_comment(
                repo_name, pr_number, comment, commit_sha)
            base = (
                f"No inline comments could be mapped to diff lines "
                f"(all {skipped} skipped); "
            )
            return base + ("posted summary-only review." if success
                           else "summary-only post also failed.")

        success = self.github_tools.post_inline_review(
            repo_name, pr_number, comment, mapped, commit_sha)
        if not success:
            return (
                f"Failed to post inline review "
                f"({len(mapped)} mapped, {skipped} skipped)."
            )

        if skipped:
            return (
                f"Posted review with {len(mapped)} inline comment(s) "
                f"({skipped} skipped — line not in diff)."
            )
        return f"Posted review with {len(mapped)} inline comment(s)."
