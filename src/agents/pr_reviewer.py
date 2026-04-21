"""GitHub-only PR review agent.

Wave 3 (2026-04-21): GitLab, the history KV, and the FastAPI webhook
all went away when we pivoted to a Docker-container GitHub Action.
The agent is now GitHub-only and ephemeral — each run is a fresh
container, so dedup is handled upstream by GitHub Actions' own event
semantics (the workflow only triggers on `opened`/`synchronize`/
`reopened`), not by a durable KV.

Wave 4 (2026-04-21): the agent now produces per-line inline comments in
addition to the overall summary. The `post_review` tool accepts an
optional `comments` array of `{path, line, body}`; translation of
file-line -> GitHub diff-position happens inside the tool via
`src/utils/diff_parser.py`. See the tool docstring for the full
behavior matrix (dry-run, fallback when no lines map, etc.).

Short-circuit order in `review_pr` (each returns before the LLM fires):

    1. Kill switch (`REVIEW_ENABLED=false`)
    2. Fetch details
    3. Draft / WIP
    4. Size limits (posts a polite "too large" notice, then bails)
    5. Happy path — invoke the agent

After a successful run we log an INFO line with the aggregated token
usage pulled from `UsageCallbackHandler`. We no longer persist it; the
Action's own run logs are the record.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain.prompts import ChatPromptTemplate

from ..tools.github_tools import GetPRDetailsTool, GitHubTools, PostReviewTool
from ..utils.config import settings
from ..utils.diff_filter import count_diff_lines
from ..utils.llm import get_chat_model
from ..utils.usage_callback import UsageCallbackHandler

logger = logging.getLogger(__name__)

# Skip-notice comment body, used only for the "too large" short-circuit.
_TOO_LARGE_COMMENT = (
    "Hi! I'm the automated code reviewer.\n\n"
    "I'm skipping this pull request because it's larger than my safety limits:\n"
    "- Files changed (after filtering): **{files}** (limit {max_files})\n"
    "- Diff lines (added + removed, after filtering): **{diff_lines}** (limit {max_diff_lines})\n\n"
    "Consider splitting it into smaller, focused changes — that'll make it easier "
    "for humans to review too. If you want a review anyway, re-trigger manually "
    "after trimming the diff."
)


class PRReviewerAgent:
    """Review a GitHub pull request and post the result back.

    Constructed once per Action run (see `src/action.py`). Not safe to
    reuse across unrelated PRs within the same process because the
    underlying LangChain `AgentExecutor` keeps per-invocation state in
    the scratchpad — we rebuild on each `review_pr` call instead of
    sharing.
    """

    def __init__(self) -> None:
        self.llm = get_chat_model(settings)
        self.gh_tools = GitHubTools(settings.github_token)
        self.tools = [
            GetPRDetailsTool(github_tools=self.gh_tools),
            PostReviewTool(github_tools=self.gh_tools),
        ]
        self.agent = self._create_agent()

    def _create_agent(self) -> AgentExecutor:
        """Build the tool-calling agent with a repo-agnostic system prompt.

        The system prompt intentionally contains NO repo- or PR-specific
        strings — that keeps the prefix bit-identical across calls so
        OpenAI's automatic prefix cache can hit. Per-PR content goes in
        the human turn in `review_pr`.
        """
        system_prompt = """You are an expert code reviewer and senior software engineer.
        Your job is to review GitHub Pull Requests and provide constructive, actionable feedback.

        ## Your Review Process:
        1. **Analyze the Pull Request**: Use the appropriate tool to understand what changed
        2. **Review Code Quality**: Check for bugs, performance issues, security concerns
        3. **Suggest Improvements**: Provide specific, actionable recommendations
        4. **Post Review**: Use the posting tool to share your feedback

        ## Posting Output Contract (post_review):
        - `comment` (required): the overall summary body for the PR review. Use
          this for high-level themes, praise, and anything that spans multiple
          files.
        - `comments` (optional): an array of `{{path, line, body}}` objects for
          line-specific feedback. `line` is the 1-based line number in the NEW
          version of the file and MUST correspond to an added or modified line
          that appears in the diff. Do NOT choose lines that were only removed
          — inline comments on deleted lines cannot be attached by this tool.
          Keep each inline `body` concise (at most 3 sentences).
        - Strongly prefer inline comments for specific, line-tied feedback and
          reserve the summary `comment` for overall themes. If a line you want
          to comment on is not in the diff window, include that observation in
          the summary instead.

        ## Review Focus Areas:
        - **Code Quality**: Clean, readable, maintainable code
        - **Security**: Potential vulnerabilities or security issues
        - **Performance**: Inefficient algorithms or resource usage
        - **Best Practices**: Following language/framework conventions
        - **Testing**: Adequate test coverage for changes
        - **Documentation**: Clear comments and documentation

        ## Review Style:
        - Be constructive and encouraging
        - Provide specific examples and suggestions
        - Explain the "why" behind your recommendations
        - Recognize good code practices when you see them
        - Use markdown formatting for clarity

        ## When to Skip:
        - Don't review auto-generated files
        - Skip files with minimal changes (whitespace, formatting)
        - Focus on the most impactful files first

        Remember: Your goal is to help developers improve while maintaining team velocity."""

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ])

        agent = create_openai_tools_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=prompt,
        )
        return AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=True,
            max_iterations=5,
        )

    # ------------------------------------------------------------------
    # Short-circuit helpers
    # ------------------------------------------------------------------
    def _post_notice(
        self,
        repo_name: str,
        pr_number: int,
        body: str,
        commit_sha: Optional[str],
    ) -> bool:
        """Post a plain notice comment (used by the 'too large' short-circuit).

        GitHub's `create_review` requires a commit SHA. If the caller
        didn't supply one (rare — Actions always have `GITHUB_SHA`), we
        pass an empty string and let `post_review_comment` fail loudly
        rather than invent a value.
        """
        try:
            return self.gh_tools.post_review_comment(
                repo_name, pr_number, body, commit_sha or "")
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(
                "Failed to post skip notice for %s#%s: %s",
                repo_name, pr_number, exc,
            )
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def review_pr(
        self,
        repo_name: str,
        pr_number: int,
        commit_sha: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Review a GitHub PR and (unless short-circuited) post the result.

        The return shape is stable across short-circuits — callers
        inspect `result["skipped"]` to differentiate. On LLM success the
        `details` key carries the raw `AgentExecutor` output.
        """
        try:
            logger.info(
                "Starting review for PR #%s in %s", pr_number, repo_name)

            # (1) Kill switch
            if not settings.review_enabled:
                logger.info(
                    "REVIEW_ENABLED is false — skipping PR #%s", pr_number)
                return {
                    "success": True,
                    "skipped": "disabled",
                    "message": "Review skipped: REVIEW_ENABLED=false",
                    "details": None,
                }

            # (2) Fetch details
            details = self.gh_tools.get_pr_details(repo_name, pr_number)

            # (3) Draft / WIP
            if details.get("draft"):
                logger.info("Skipping draft/WIP PR #%s", pr_number)
                return {
                    "success": True,
                    "skipped": "draft",
                    "message": "Draft/WIP — review deferred",
                    "details": None,
                }

            # (4) Size limits — files are already post-filter (lockfiles /
            #     vendored / generated / minified dropped in get_pr_details).
            files = details.get("files") or []
            total_diff_lines = sum(
                count_diff_lines(f.get("patch") or "") for f in files
            )
            file_count = len(files)

            if (file_count > settings.max_files_to_review
                    or total_diff_lines > settings.max_diff_lines):
                logger.info(
                    "PR #%s too large (files=%d/%d, diff_lines=%d/%d) — skipping",
                    pr_number, file_count, settings.max_files_to_review,
                    total_diff_lines, settings.max_diff_lines,
                )
                body = _TOO_LARGE_COMMENT.format(
                    files=file_count,
                    max_files=settings.max_files_to_review,
                    diff_lines=total_diff_lines,
                    max_diff_lines=settings.max_diff_lines,
                )
                posted = self._post_notice(
                    repo_name, pr_number, body, commit_sha)
                return {
                    "success": True,
                    "skipped": "too_large",
                    "message": ("PR too large; skip notice posted"
                                if posted else "PR too large; notice post failed"),
                    "details": {
                        "files": file_count,
                        "diff_lines": total_diff_lines,
                        "max_files": settings.max_files_to_review,
                        "max_diff_lines": settings.max_diff_lines,
                    },
                }

            # (5) Happy path — invoke the agent.
            review_request = (
                f"\n                Please review Pull Request #{pr_number} "
                f"in repository {repo_name}.\n\n"
                "                Steps:\n"
                "                1. Get the PR details and analyze the changes\n"
                "                2. Review the code for quality, security, and best practices\n"
                "                3. Post a comprehensive review with your findings\n\n"
                "                Focus on the most important issues and provide actionable feedback.\n"
                f"                The commit SHA for posting the review is: {commit_sha}\n"
                "                "
            )

            usage = UsageCallbackHandler()
            result = self.agent.invoke(
                {"input": review_request},
                config={"callbacks": [usage]},
            )

            totals = usage.totals()
            logger.info(
                "usage: prompt=%s completion=%s cached=%s calls=%s "
                "provider=%s model=%s",
                totals.get("prompt_tokens", 0),
                totals.get("completion_tokens", 0),
                totals.get("cached_tokens", 0),
                totals.get("calls", 0),
                settings.llm_provider,
                settings.llm_model or "",
            )

            logger.info("Review completed for PR #%s", pr_number)
            return {
                "success": True,
                "message": "PR review completed successfully",
                "details": result,
            }

        except Exception as exc:
            logger.error("Error reviewing PR #%s: %s", pr_number, exc)
            return {
                "success": False,
                "message": f"Review failed: {exc}",
                "details": None,
            }
