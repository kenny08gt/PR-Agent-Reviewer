# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AI-powered PR reviewer shipped as a Docker-container GitHub Action. Consumers add `uses: kenny08gt/PR-Agent-Reviewer@v1` to a workflow file; on each PR event the Action container runs, fetches the diff, asks an OpenAI model (or Moonshot/Kimi, configurable) to review it via a LangChain tool-using agent, and posts the review back. Python 3.13, LangChain 0.3, no server to host.

## Repository layout notes

- Git root is the repo root. `venv/` is there for local development only — the Action itself runs inside the Dockerfile-built image.
- `action.yml`, `Dockerfile`, and `src/action.py` are the three load-bearing files for the Action delivery model. Keep them in sync (inputs declared in `action.yml` -> env-var mapping in `src/action.py`).
- Top-level `README.md` has a minimal quickstart. Real project dependencies live in `src/requirements.txt`. `requirements.txt` at the repo root is an empty stub.
- The env template is `src/.env.example`. `.env` is loaded from CWD (python-dotenv behavior); the Action container never reads one, it receives env vars from the runner.
- `.cursor/rules/codacy.mdc` is gitignored — a local Cursor hint, not project policy.

## Commands

All commands run from the project root.

```bash
# --- Local development ---
source venv/bin/activate
pip install -r src/requirements.txt

# Run the test suite
pytest -q

# Smoke-test the Action entry point against a real PR (needs a real GITHUB_TOKEN
# + LLM key). The CLI_REPO / CLI_PR fallback kicks in when GITHUB_EVENT_PATH is
# unset, so this works outside GitHub's runner env.
CLI_REPO=owner/repo CLI_PR=123 \
INPUT_GITHUB_TOKEN=$GITHUB_TOKEN \
INPUT_OPENAI_API_KEY=$OPENAI_API_KEY \
python -m src.action

# --- Action image build ---
docker build -t prb:test .
docker run --rm \
  -e CLI_REPO=owner/repo -e CLI_PR=123 \
  -e INPUT_GITHUB_TOKEN=$GITHUB_TOKEN \
  -e INPUT_OPENAI_API_KEY=$OPENAI_API_KEY \
  prb:test
```

Always invoke the entry point as a package (`python -m src.action`) — `src/action.py` uses relative imports (`from .agents...`) and `python src/action.py` will break.

There is no linter or CI configured yet.

## Architecture

```
GitHub pull_request event
        │
        ▼
┌───────────────────────────────────────────────┐
│  Workflow: .github/workflows/*.yml            │
│  uses: kenny08gt/PR-Agent-Reviewer         │
└───────────────┬───────────────────────────────┘
                │ docker run per event
                ▼
        ┌─────────────────┐
        │ python -m       │
        │ src.action      │   maps INPUT_* → Settings env vars,
        └───────┬─────────┘   parses GITHUB_EVENT_PATH
                ▼
        ┌─────────────────┐
        │ PRReviewerAgent │   LangChain tool-using agent
        └───────┬─────────┘   (GitHub-only; GitLab dropped Wave 3)
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
┌─────────┐ ┌─────────┐ ┌──────────┐
│OpenAI / │ │ GitHub  │ │Redactor  │
│  Kimi   │ │   API   │ │(in-proc) │
└─────────┘ └─────────┘ └──────────┘
```

### Agent construction

`_create_agent` in `src/agents/pr_reviewer.py` builds a `ChatPromptTemplate` -> `create_openai_tools_agent` -> `AgentExecutor` with `max_iterations=5`, `temperature=0.1`. The system prompt is intentionally repo-agnostic (no PR-specific strings) so OpenAI's automatic prompt-prefix cache stays hot. Per-PR content goes in the human turn. Model is resolved from `settings.llm_model` (default `gpt-4o-mini` for OpenAI, `kimi-k2-0905-preview` for Kimi).

### Short-circuit order in `review_pr`

1. Kill switch (`REVIEW_ENABLED=false`)
2. Fetch PR details
3. Draft / WIP -> skip
4. Size limits (post polite "too large" notice, bail)
5. Otherwise -> invoke the agent, log aggregated token usage at INFO

The Action is ephemeral (one PR per run), so there is no durable dedup layer — GitHub's event semantics handle that upstream.

### Safety limits already in place

- `GitHubTools.get_pr_details` (`src/tools/github_tools.py`) truncates each file patch to 2000 chars, applies `partition_files` (lockfiles / vendored / generated / minified dropped), and applies `redact_with_count` on each remaining patch before returning.
- `GetPRDetailsTool._run` only formats the first 10 files for the LLM.
- `config.py` exposes `MAX_FILES_TO_REVIEW` (default 10) and `MAX_DIFF_LINES` (default 500); both are read in `PRReviewerAgent.review_pr` step (4).
- `src/utils/redactor.py` scrubs GitHub / OpenAI / Slack / AWS / JWT / PEM / generic `password|secret|api_key=...` patterns. Counts are logged; matches never are.
- `PostReviewTool._run` short-circuits when `INPUT_DRY_RUN=true` and returns a stub instead of posting.
- `post_review` accepts an optional `comments` array of `{path, line, body}` for per-line inline feedback. `src/utils/diff_parser.py` translates each file line to the GitHub diff `position` the review-comments API expects; comments whose line falls outside the diff window are skipped (count logged, body never logged). If every line fails to map, the tool falls back to a summary-only review.

## Specs-driven workflow

`specs/` is the source of truth for direction:

- `specs/mission.md` — product vision, target users, success metrics. Wave 3 softened the "continuous learning" claim.
- `specs/tech-stack.md` — locked dependency versions and architectural constraints. Constraint #1 ("GitHub Action First") and #5 ("No Database, Anywhere") both came out of the Wave 3 pivot; honor them before adding a dep or server-side state.
- `specs/roadmap.md` — phased plan. Phase 1.7 (SQLite history KV + prompt caching) was **dropped** in Wave 3; do not re-open it without a concrete ask. Phase 4 is rescoped to "Distribution & Releases" (v1.0.0, Marketplace, GHCR image caching).

Before adding a dependency or changing architecture, check `tech-stack.md` — it explicitly rules out some directions (TypeScript, early DB usage, GitLab).

## Skills

`skills/` contains repo-local skills invokable via slash commands:

- **`skills/changelog/`** — `/changelog` regenerates or appends to a root `CHANGELOG.md` from `git log`. Runs `python3 skills/changelog/scripts/changelog.py` from the project root.
- **`skills/feature-spec/`** — `/feature-spec` finds the next incomplete phase in `specs/roadmap.md`, creates a `phase-N-<name>` branch, interviews the user (3 questions via `AskUserQuestion`), then writes `specs/YYYY-MM-DD-<feature>/{plan,requirements,validation}.md`.
