from typing import List, Dict, Any
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.memory import ConversationBufferMemory
from langchain.schema import SystemMessage, HumanMessage
import logging

from ..tools.github_tools import GitHubTools, GetPRDetailsTool, PostReviewTool
from ..tools.gitlab_tools import GitLabTools, GetMRDetailsTool, PostMRNoteTool
from ..utils.config import settings

logger = logging.getLogger(__name__)


class PRReviewerAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0.1  # Lower temperature for consistent reviews
        )

        self.platform = settings.platform.lower()
        self.memory = ConversationBufferMemory(return_messages=True)

        # Initialize platform-specific tools
        if self.platform == "gitlab":
            self.platform_tools = GitLabTools(
                settings.gitlab_token, settings.gitlab_url)
            self.github_tools = self.platform_tools
            self.tools = [
                GetMRDetailsTool(gitlab_tools=self.platform_tools),
                PostMRNoteTool(gitlab_tools=self.platform_tools)
            ]
            self.review_type = "Merge Request"
        else:  # GitHub
            self.platform_tools = GitHubTools(settings.github_token)
            self.github_tools = self.platform_tools
            self.tools = [
                GetPRDetailsTool(github_tools=self.platform_tools),
                PostReviewTool(github_tools=self.platform_tools)
            ]
            self.review_type = "Pull Request"
        # Create the agent
        self.agent = self._create_agent()

    def _create_agent(self) -> AgentExecutor:
        """Create the PR/MR reviewer agent with specialized prompt."""

        platform_name = "GitLab" if self.platform == "gitlab" else "GitHub"
        action_name = "Merge Request" if self.platform == "gitlab" else "Pull Request"

        system_prompt = f"""You are an expert code reviewer and senior software engineer. 
        Your job is to review {platform_name} {action_name}s and provide constructive, actionable feedback.

        ## Your Review Process:
        1. **Analyze the {action_name}**: Use the appropriate tool to understand what changed
        2. **Review Code Quality**: Check for bugs, performance issues, security concerns
        3. **Suggest Improvements**: Provide specific, actionable recommendations
        4. **Post Review**: Use the posting tool to share your feedback

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
            ("placeholder", "{agent_scratchpad}")
        ])

        agent = create_openai_tools_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=prompt
        )

        return AgentExecutor(
            agent=agent,
            tools=self.tools,
            memory=self.memory,
            verbose=True,
            max_iterations=5
        )

    def review_pr(self, repo_or_project_id: str, pr_or_mr_number: int, commit_sha: str = None) -> Dict[str, Any]:
        """Review a Pull Request or Merge Request and post feedback."""
        try:
            action_type = "MR" if self.platform == "gitlab" else "PR"
            logger.info(
                f"Starting review for {action_type} #{pr_or_mr_number} in {repo_or_project_id}")

            # Prepare the review request
            if self.platform == "gitlab":
                review_request = f"""
                Please review Merge Request #{pr_or_mr_number} in project {repo_or_project_id}.
                
                Steps:
                1. Get the MR details and analyze the changes
                2. Review the code for quality, security, and best practices
                3. Post a comprehensive review with your findings
                
                Focus on the most important issues and provide actionable feedback.
                """
            else:
                review_request = f"""
                Please review Pull Request #{pr_or_mr_number} in repository {repo_or_project_id}.
                
                Steps:
                1. Get the PR details and analyze the changes
                2. Review the code for quality, security, and best practices
                3. Post a comprehensive review with your findings
                
                Focus on the most important issues and provide actionable feedback.
                The commit SHA for posting the review is: {commit_sha}
                """

            # Execute the review
            result = self.agent.invoke({"input": review_request})

            logger.info(
                f"Review completed for {action_type} #{pr_or_mr_number}")
            return {
                "success": True,
                "message": f"{action_type} review completed successfully",
                "details": result
            }

        except Exception as e:
            logger.error(
                f"Error reviewing {action_type} #{pr_or_mr_number}: {e}")
            return {
                "success": False,
                "message": f"Review failed: {str(e)}",
                "details": None
            }

    def analyze_pr_summary(self, repo_or_project_id: str, pr_or_mr_number: int) -> Dict[str, Any]:
        """Get a quick analysis summary without posting a review."""
        try:
            if self.platform == "gitlab":
                details = self.platform_tools.get_mr_details(
                    repo_or_project_id, pr_or_mr_number)
                files_changed = details.get('changes_count', 0)
                title = details.get('title', 'Unknown')
            else:
                details = self.platform_tools.get_pr_details(
                    repo_or_project_id, pr_or_mr_number)
                files_changed = details.get('changed_files', 0)
                title = details.get('title', 'Unknown')

            # Create a focused analysis prompt
            analysis_prompt = f"""
            Analyze this {self.review_type} briefly:

            Title: {title}
            Files Changed: {files_changed}

            Provide a concise summary:
            1. **Risk Level**: Low/Medium/High
            2. **Key Focus**: Main areas to review
            3. **Review Time**: Estimated minutes
            4. **Priority**: Any urgent concerns

            Keep response under 100 words.
            """

            response = self.llm.invoke([HumanMessage(content=analysis_prompt)],
                                       max_tokens=150)

            return {
                "success": True,
                "summary": response.content,
                "details": details
            }

        except Exception as e:
            action_type = "MR" if self.platform == "gitlab" else "PR"
            logger.error(
                f"Error analyzing {action_type} #{pr_or_mr_number}: {e}")
            return {
                "success": False,
                "message": f"Analysis failed: {str(e)}"
            }
