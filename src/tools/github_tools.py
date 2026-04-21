from typing import List, Dict, Any, Optional
from github import Github
from github.PullRequest import PullRequest
from github.Repository import Repository
from langchain.tools import BaseTool
from pydantic import Field
import logging

logger = logging.getLogger(__name__)


class GitHubTools:
    def __init__(self, token: str):
        self.github = Github(token)

    def get_pr_details(self, repo_name: str, pr_number: int) -> Dict[str, Any]:
        """Get comprehensive PR details including files and diffs."""
        try:
            repo = self.github.get_repo(repo_name)
            pr = repo.get_pull(pr_number)

            # Get changed files
            files = []
            for file in pr.get_files():
                if file.patch:  # Only include files with actual changes
                    files.append({
                        'filename': file.filename,
                        'status': file.status,
                        'additions': file.additions,
                        'deletions': file.deletions,
                        'patch': file.patch[:2000],  # Limit patch size
                        'blob_url': file.blob_url
                    })

            return {
                'title': pr.title,
                'body': pr.body or '',
                'state': pr.state,
                'author': pr.user.login,
                'base_branch': pr.base.ref,
                'head_branch': pr.head.ref,
                'files': files,
                'commits_count': pr.commits,
                'additions': pr.additions,
                'deletions': pr.deletions,
                'changed_files': pr.changed_files,
                'sha': pr.head.sha
            }

        except Exception as e:
            logger.error(f"Error fetching PR details: {e}")
            raise

    def post_review_comment(self, repo_name: str, pr_number: int,
                            comment: str, commit_sha: str) -> bool:
        """Post a review comment on the PR."""
        try:
            repo = self.github.get_repo(repo_name)
            pr = repo.get_pull(pr_number)

            pr.create_review(
                commit=repo.get_commit(commit_sha),
                body=comment,
                event="COMMENT"
            )
            return True

        except Exception as e:
            logger.error(f"Error posting review comment: {e}")
            return False


class GetPRDetailsTool(BaseTool):
    name = "get_pr_details"
    description = "Get details about a GitHub Pull Request including changed files and diffs"
    github_tools: GitHubTools = Field(exclude=True)

    def _run(self, repo_name: str, pr_number: int) -> str:
        """Get PR details and return as formatted string."""
        details = self.github_tools.get_pr_details(repo_name, pr_number)

        formatted_output = f"""
PR Details:
Title: {details['title']}
Author: {details['author']}
Base Branch: {details['base_branch']} → Head Branch: {details['head_branch']}
State: {details['state']}

Description:
{details['body']}

Files Changed ({details['changed_files']}):
+{details['additions']} -{details['deletions']} lines

Changed Files:
"""

        for file in details['files'][:10]:  # Limit to first 10 files
            formatted_output += f"\n📁 {file['filename']} ({file['status']})\n"
            formatted_output += f"   +{file['additions']} -{file['deletions']} lines\n"
            if file['patch']:
                formatted_output += f"   Diff preview:\n{file['patch'][:500]}...\n"

        return formatted_output


class PostReviewTool(BaseTool):
    name = "post_review"
    description = "Post a review comment on a GitHub Pull Request"
    github_tools: GitHubTools = Field(exclude=True)

    def _run(self, repo_name: str, pr_number: int, comment: str, commit_sha: str) -> str:
        """Post review comment and return success status."""
        success = self.github_tools.post_review_comment(
            repo_name, pr_number, comment, commit_sha)
        return "Review comment posted successfully!" if success else "Failed to post review comment."
