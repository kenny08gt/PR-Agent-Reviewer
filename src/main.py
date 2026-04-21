from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import hmac
import hashlib
import json
import logging

from .agents.pr_reviewer import PRReviewerAgent
from .utils.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PR Reviewer Agent",
    description="AI-powered Pull Request reviewer using LangChain and OpenAI",
    version="1.0.0"
)

# Initialize the PR reviewer agent
pr_agent = PRReviewerAgent()


def verify_webhook_signature(payload: bytes, signature: str, platform: str) -> bool:
    """Unified webhook signature verification."""
    if not signature:
        return False

    if platform == "gitlab":
        return hmac.compare_digest(signature, settings.gitlab_webhook_secret)
    else:
        secret = settings.github_webhook_secret.encode()
        expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature)


async def process_review(identifier: str, number: int, commit_sha: str = None):
    """Unified background task to process PR/MR review."""
    try:
        action_type = "MR" if pr_agent.platform == "gitlab" else "PR"
        logger.info(
            f"Processing {action_type} review for {identifier}#{number}")

        result = pr_agent.review_pr(identifier, number, commit_sha)

        if result["success"]:
            logger.info(
                f"{action_type} review completed successfully for {identifier}#{number}")
        else:
            logger.error(
                f"{action_type} review failed for {identifier}#{number}: {result['message']}")

    except Exception as e:
        logger.error(f"Error in background {action_type} review: {e}")


@app.post("/webhook/gitlab")
async def gitlab_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle GitLab webhook events."""
    try:
        payload = await request.body()
        signature = request.headers.get("X-Gitlab-Token")

        if not verify_webhook_signature(payload, signature, "gitlab"):
            raise HTTPException(status_code=403, detail="Invalid signature")

        data = json.loads(payload)
        logger.info(f"Received GitLab webhook: {data.get('object_kind')}")

        if data.get("object_kind") == "merge_request":
            action = data["object_attributes"].get("action")

            if action in ["open", "update"]:
                mr_data = data["object_attributes"]
                project_id = data["project"]["id"]
                mr_iid = mr_data["iid"]
                commit_sha = mr_data["last_commit"]["id"]

                background_tasks.add_task(
                    process_review,
                    str(project_id),
                    mr_iid,
                    commit_sha
                )

                return JSONResponse({
                    "status": "success",
                    "message": f"MR review queued for project {project_id}!{mr_iid}"
                })

        return JSONResponse({"status": "ignored", "message": "Event not handled"})

    except Exception as e:
        logger.error(f"GitLab webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle GitHub webhook events."""
    try:
        # Get request data
        payload = await request.body()
        signature = request.headers.get("X-Hub-Signature-256")

        # Verify signature
        if not verify_webhook_signature(payload, signature, "github"):
            raise HTTPException(status_code=403, detail="Invalid signature")

        # Parse payload
        event_type = request.headers.get("X-GitHub-Event")
        data = json.loads(payload)

        logger.info(f"Received GitHub webhook: {event_type}")

        # Handle pull request events
        if event_type == "pull_request":
            action = data.get("action")

            # Trigger review on opened or updated PRs
            if action in ["opened", "synchronize"]:
                pr_data = data["pull_request"]
                repo_name = data["repository"]["full_name"]
                pr_number = pr_data["number"]
                commit_sha = pr_data["head"]["sha"]

                # Add review task to background queue
                background_tasks.add_task(
                    process_review,
                    repo_name,
                    pr_number,
                    commit_sha
                )

                return JSONResponse({
                    "status": "success",
                    "message": f"PR review queued for {repo_name}#{pr_number}"
                })

        return JSONResponse({"status": "ignored", "message": "Event not handled"})

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "agent": "PR Reviewer Agent"}


@app.post("/review/{owner}/{repo}/{pr_number}")
async def manual_review(owner: str, repo: str, pr_number: int, background_tasks: BackgroundTasks):
    """Manually trigger a PR review."""
    try:
        repo_name = f"{owner}/{repo}"

        # Get the latest commit SHA
        if pr_agent.platform == "gitlab":
            pr_details = pr_agent.platform_tools.get_mr_details(
                repo_name, pr_number)
            commit_sha = pr_details.get("sha", "main")  # GitLab field name
        else:
            pr_details = pr_agent.platform_tools.get_pr_details(
                repo_name, pr_number)
            commit_sha = pr_details.get("sha", "main")  # GitHub field name

        # Add review task to background queue
        background_tasks.add_task(
            process_review, repo_name, pr_number, commit_sha)

        return JSONResponse({
            "status": "success",
            "message": f"Manual review queued for {repo_name}#{pr_number}"
        })

    except Exception as e:
        logger.error(f"Manual review error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/analyze/{owner}/{repo}/{pr_number}")
async def analyze_pr(owner: str, repo: str, pr_number: int):
    """Get PR analysis without posting a review."""
    try:
        repo_name = f"{owner}/{repo}"
        result = pr_agent.analyze_pr_summary(repo_name, pr_number)

        return JSONResponse(result)

    except Exception as e:
        logger.error(f"PR analysis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True
    )
