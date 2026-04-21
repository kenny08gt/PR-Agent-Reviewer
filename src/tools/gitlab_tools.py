from typing import List, Dict, Any, Optional
import gitlab
from langchain.tools import BaseTool
from pydantic import Field
import logging

logger = logging.getLogger(__name__)


class GitLabTools:
    def __init__(self, token: str, url: str = "https://gitlab.com"):
        self.gitlab = gitlab.Gitlab(url, private_token=token)

    def get_mr_details(self, project_id: str, mr_iid: int) -> Dict[str, Any]:
        """Get comprehensive MR details including files and diffs."""
        try:
            project = self.gitlab.projects.get(project_id)
            mr = project.mergerequests.get(mr_iid)

            # Get changed files
            changes = mr.changes()
            files = []

            for change in changes.get('changes', []):
                if change.get('diff'):  # Only include files with actual changes
                    files.append({
                        'filename': change['new_path'] or change['old_path'],
                        'status': 'modified' if change['new_path'] and change['old_path'] else
                                 'added' if change['new_path'] else 'deleted',
                                 'old_path': change.get('old_path'),
                                 'new_path': change.get('new_path'),
                                 # Limit diff size
                                 'diff': change['diff'][:2000],
                                 })

            return {
                'title': mr.title,
                'description': mr.description or '',
                'state': mr.state,
                'author': mr.author['username'],
                'source_branch': mr.source_branch,
                'target_branch': mr.target_branch,
                'files': files,
                'changes_count': len(files),
                'web_url': mr.web_url,
                'sha': mr.sha
            }

        except Exception as e:
            logger.error(f"Error fetching MR details: {e}")
            raise

    def post_mr_note(self, project_id: str, mr_iid: int, note: str) -> bool:
        """Post a note (comment) on the MR."""
        try:
            project = self.gitlab.projects.get(project_id)
            mr = project.mergerequests.get(mr_iid)

            mr.notes.create({'body': note})
            return True

        except Exception as e:
            logger.error(f"Error posting MR note: {e}")
            return False


class GetMRDetailsTool(BaseTool):
    name = "get_mr_details"
    description = "Get details about a GitLab Merge Request including changed files and diffs"
    gitlab_tools: GitLabTools = Field(exclude=True)

    def _run(self, project_id: str, mr_iid: int) -> str:
        """Get MR details and return as formatted string."""
        details = self.gitlab_tools.get_mr_details(project_id, mr_iid)

        formatted_output = f"""
MR Details:
Title: {details['title']}
Author: {details['author']}
Source Branch: {details['source_branch']} → Target Branch: {details['target_branch']}
State: {details['state']}

Description:
{details['description']}

Files Changed ({details['changes_count']}):

Changed Files:
"""

        for file in details['files'][:10]:  # Limit to first 10 files
            formatted_output += f"\n📁 {file['filename']} ({file['status']})\n"
            if file['diff']:
                formatted_output += f"   Diff preview:\n{file['diff'][:500]}...\n"

        return formatted_output


class PostMRNoteTool(BaseTool):
    name = "post_mr_note"
    description = "Post a note (comment) on a GitLab Merge Request"
    gitlab_tools: GitLabTools = Field(exclude=True)

    def _run(self, project_id: str, mr_iid: int, note: str) -> str:
        """Post MR note and return success status."""
        success = self.gitlab_tools.post_mr_note(project_id, mr_iid, note)
        return "MR note posted successfully!" if success else "Failed to post MR note."
