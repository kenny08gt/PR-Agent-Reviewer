# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AI-powered PR/MR reviewer. Receives webhooks (or manual API calls) from GitHub or GitLab, fetches the diff, asks an OpenAI model (via LangChain tool-using agent) to review it, and posts the review back. Python 3.13, FastAPI, LangChain 0.3.

## Repository layout notes

- Git root and `venv/` are at the project root. Application code is under `src/`.
- Top-level `README.md` and `requirements.txt` are empty stubs — the real deps are in `src/requirements.txt`. The env template is `src/.env.example`, but `.env` is loaded from the project root (python-dotenv uses the CWD where the process starts).
- `.cursor/rules/codacy.mdc` is gitignored and exists only as a local Cursor hint; it is not project policy.

## Commands

All commands run from the project root.

```bash
# Activate venv
source venv/bin/activate

# Install / update dependencies
pip install -r src/requirements.txt

# Run the FastAPI webhook server (dev, with reload)
python -m src.main
# or equivalently
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

The module uses **relative imports** (`from .agents...`), so always invoke it as a package (`python -m src.main`) — never `python src/main.py`, which will break imports.

There are no tests, linters, or CI configured yet.

### Useful HTTP endpoints (once the server is running)

- `POST /webhook/github` — GitHub PR webhook (verifies `X-Hub-Signature-256` with `GITHUB_WEBHOOK_SECRET`)
- `POST /webhook/gitlab` — GitLab MR webhook (compares `X-Gitlab-Token` against `GITLAB_WEBHOOK_SECRET`)
- `POST /review/{owner}/{repo}/{pr_number}` — manually queue a review
- `GET  /analyze/{owner}/{repo}/{pr_number}` — quick LLM summary, no comment posted
- `GET  /health`

## Architecture

```
webhook / manual endpoint  ──▶  BackgroundTasks.process_review
                                         │
                                         ▼
                                 PRReviewerAgent.review_pr
                                         │
                          ┌──────────────┴──────────────┐
                          ▼                             ▼
              platform_tools (GitHub|GitLab)      ChatOpenAI (LangChain agent)
                          │                             │
                  PyGithub / python-gitlab      tool-calling loop:
                                                get_*_details → post_review/note
```

### Platform abstraction

`PLATFORM` env var (`"github"` or `"gitlab"`, default `"gitlab"` in `config.py`) selects the stack at startup in `PRReviewerAgent.__init__` (`src/agents/pr_reviewer.py`):

- GitHub → `GitHubTools` + `GetPRDetailsTool` + `PostReviewTool` (`src/tools/github_tools.py`)
- GitLab → `GitLabTools` + `GetMRDetailsTool` + `PostMRNoteTool` (`src/tools/gitlab_tools.py`)

There is no shared interface class — the tool classes are duck-typed and the agent stores both `self.platform_tools` and a parallel `self.github_tools` alias. When extending, keep method names parallel (`get_pr_details` ↔ `get_mr_details`, `post_review_comment` ↔ `post_mr_note`) and branch in `main.py` / `pr_reviewer.py` on `self.platform`.

### Agent construction

`_create_agent` builds a `ChatPromptTemplate` → `create_openai_tools_agent` → `AgentExecutor` with `max_iterations=5`, `temperature=0.1`, and a `ConversationBufferMemory`. The system prompt is templated on platform name ("GitHub Pull Request" vs "GitLab Merge Request"). Model comes from `settings.openai_model` (default `gpt-4-turbo-preview`).

### Safety limits already in place

- `GitHubTools.get_pr_details` truncates each file patch to 2000 chars.
- `GetPRDetailsTool._run` only formats the first 10 files.
- `config.py` exposes `MAX_FILES_TO_REVIEW` and `MAX_DIFF_LINES` but nothing reads them yet — wire them through if you add per-file limits.

### Webhook signature verification

`verify_webhook_signature` in `src/main.py` handles both platforms:
- GitHub: HMAC-SHA256 of the raw body with `GITHUB_WEBHOOK_SECRET`, compared to `sha256=<hex>`.
- GitLab: plain token compare against `X-Gitlab-Token` (GitLab doesn't sign the body).

Never log the raw payload or secret.

## Specs-driven workflow

`specs/` is the source of truth for direction:

- `specs/mission.md` — product vision, target users, success metrics
- `specs/tech-stack.md` — locked dependency versions and architectural constraints (e.g., "no database in MVP", "async throughout", "LangChain for orchestration")
- `specs/roadmap.md` — phased plan (Phase 0 foundation → Phase 6 team customization). The status table at the bottom is stale: code for GitHub/GitLab tools and the webhook server already exists even though those phases read "Not Started". Update the table when you finish work.

Before adding a dependency or changing architecture, check `tech-stack.md` — it explicitly rules out some directions (e.g., TypeScript, early DB usage).

## Skills

`skills/` contains repo-local skills invokable via slash commands:

- **`skills/changelog/`** — `/changelog` regenerates or appends to a root `CHANGELOG.md` from `git log`. Runs `python3 skills/changelog/scripts/changelog.py` from the project root.
- **`skills/feature-spec/`** — `/feature-spec` finds the next incomplete phase in `specs/roadmap.md`, creates a `phase-N-<name>` branch, interviews the user (3 questions via `AskUserQuestion`), then writes `specs/YYYY-MM-DD-<feature>/{plan,requirements,validation}.md`.
