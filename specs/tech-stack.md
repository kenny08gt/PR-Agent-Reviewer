# Tech Stack

## Language & Runtime

- **Python 3.13**: Primary language for the agent implementation
- **Type hints**: Enforced via Pydantic models for all data structures

## Core Frameworks & Libraries

### AI/LLM Layer
- **LangChain 0.3.27**: Framework for building LLM applications with chain composition
- **LangChain-OpenAI 0.3.28**: OpenAI-compatible chat model wrapper used for both OpenAI and Moonshot/Kimi
- **OpenAI 1.98.0**: Underlying SDK
- **Supported LLM providers**:
  - **OpenAI**: GPT-4o-class models via `langchain-openai`'s `ChatOpenAI` (default `gpt-4o-mini`)
  - **Moonshot / Kimi**: Kimi K2 family (`kimi-k2-0905-preview`, `kimi-k2-turbo-preview`, `kimi-k2-thinking*`). The Kimi API is OpenAI-SDK-compatible (`base_url=https://api.moonshot.ai/v1`), so we reuse `ChatOpenAI` with a different base URL and API key — no new LangChain dependency. Provider selection is a runtime input via `llm-provider`.

### Configuration
- **Pydantic 2.11.7**: Data validation
- **Pydantic-Settings 2.6.1**: Environment-variable-driven configuration
- **python-dotenv 1.2.2**: Local `.env` loading for smoke-tests; no-op inside the Action container

### Platform Integrations
- **PyGithub 2.7.0**: GitHub API client

### Test tooling
- **pytest 8.3.3**
- **pytest-asyncio 0.24.0**

## Infrastructure & Deployment

- **Docker-container GitHub Action** (only delivery model):
  - `action.yml` at repo root declares the input schema (github-token, llm-provider, openai-api-key, moonshot-api-key, llm-model, llm-base-url, max-files-to-review, max-diff-lines, review-enabled, dry-run).
  - `Dockerfile` at repo root builds a `python:3.13-slim` image that installs `src/requirements.txt` and runs `python -m src.action` on entry.
  - `src/action.py` is the container entry point. It maps `INPUT_<NAME>` env vars onto `Settings`-compatible names, reads the `GITHUB_EVENT_PATH` JSON, and invokes `PRReviewerAgent.review_pr(...)` for pull-request events with actions `opened` / `synchronize` / `reopened`.
  - Distribution: consumers add `uses: alanhurtarte/pr-reviewer-agent@v1` to a workflow; GitHub builds and caches the image.
- **Self-hosted webhook server**: removed 2026-04-21 (Wave 3). See Constraint #1.
- **GitLab**: dropped 2026-04-21. See Constraint #4.

## Data Storage (Future: RAG Integration)

- **Vector Store**: TBD (Pinecone, Weaviate, or pgvector)
- **Embeddings**: OpenAI text-embedding-3-small or similar
- **Document Store**: Repository code indexed by file path and commit history

## Development Tools

- **venv**: Virtual environment management for local test runs
- **Git**: Version control with conventional commits

## Constraints & Decisions

1. **GitHub Action First** _(revised 2026-04-21; was "Webhook First")_: The MVP ships as a Docker-container GitHub Action. `src/main.py` (FastAPI webhook server) was deleted along with its `/webhook/github`, `/webhook/gitlab`, `/review/...`, `/analyze/...`, and `/health` endpoints. Target users (OSS maintainers, 5-50 dev teams) want zero-hosting install, and the Action gives us `uses: ... @v1` in a workflow as the entire install story. Auth flows via `${{ secrets.GITHUB_TOKEN }}`, so no webhook secret has to be provisioned.

2. **Python Over TypeScript**: Python's superior ML/AI ecosystem (LangChain, OpenAI SDKs) makes it the right choice for an LLM-heavy application.

3. **LangChain for Orchestration**: Raw OpenAI calls would be simpler for basic cases, but LangChain provides essential abstractions for context management, prompt templating, and future RAG integration.

4. **GitHub Only (GitLab Dropped)** _(revised 2026-04-21)_: The original plan had parallel GitHub and GitLab tool sets. Wave 3 dropped GitLab entirely (`src/tools/gitlab_tools.py` deleted, `tests/test_guardrails.py` GitLab cases removed, `specs/roadmap.md` Phase 4 rewritten). If a concrete GitLab user emerges we'll re-introduce the platform abstraction with a shared interface — but we won't speculatively carry it.

5. **No Database, Anywhere** _(revised 2026-04-21)_: Wave 2b added a SQLite history KV for durable dedup. Wave 3 dropped it because a Docker-container Action is ephemeral — each run is a fresh container with no writable durable state, so a KV adds zero value. Dedup is now handled upstream by GitHub's own event semantics (the workflow only triggers on `opened` / `synchronize` / `reopened`). If we later add RAG in Phase 3, a vector store lives OUTSIDE the Action container.

6. **Async Not Required**: The Action container is single-shot (one PR per run). We kept LangChain's async-friendly abstractions but don't rely on `asyncio.gather`-style concurrency anywhere in the code path. Async is a latent capability, not a requirement.

7. **Secret Redaction Mandatory**: As of Wave 3, `src/utils/redactor.py` scrubs obvious secrets (GitHub / OpenAI / Slack / AWS / JWT / PEM / generic password-assignments) from patches BEFORE they reach the LLM. Counts are logged; matches are never logged.

## Environment Configuration

Inputs are declared in `action.yml` (source of truth). For reference, the mapping from Action input to internal env var is:

| Action input           | Env var inside container   | Required | Default             |
|------------------------|----------------------------|----------|---------------------|
| `github-token`         | `INPUT_GITHUB_TOKEN` -> `GITHUB_TOKEN`         | yes      | — |
| `openai-api-key`       | `INPUT_OPENAI_API_KEY` -> `OPENAI_API_KEY`     | when `llm-provider=openai` | — |
| `moonshot-api-key`     | `INPUT_MOONSHOT_API_KEY` -> `MOONSHOT_API_KEY` | when `llm-provider=kimi`   | — |
| `llm-provider`         | `INPUT_LLM_PROVIDER` -> `LLM_PROVIDER`         | no       | `openai`            |
| `llm-model`            | `INPUT_LLM_MODEL` -> `LLM_MODEL`               | no       | per-provider default |
| `llm-base-url`         | `INPUT_LLM_BASE_URL` -> `LLM_BASE_URL`         | no       | provider default    |
| `max-files-to-review`  | `INPUT_MAX_FILES_TO_REVIEW` -> `MAX_FILES_TO_REVIEW` | no | `10` |
| `max-diff-lines`       | `INPUT_MAX_DIFF_LINES` -> `MAX_DIFF_LINES`     | no       | `500`               |
| `review-enabled`       | `INPUT_REVIEW_ENABLED` -> `REVIEW_ENABLED`     | no       | `true`              |
| `dry-run`              | `INPUT_DRY_RUN` (read directly)                | no       | `false`             |

First-party env vars supplied by the runner: `GITHUB_EVENT_PATH`, `GITHUB_REPOSITORY`, `GITHUB_EVENT_NAME`, `GITHUB_SHA`.

Local smoke-test escape hatch: when `GITHUB_EVENT_PATH` is unset and both `CLI_REPO` and `CLI_PR` are set, `src.action` uses them as the review target. See `src/.env.example`.

## Architecture Overview

```
                    GitHub pull_request event
                               │
                               ▼
           ┌────────────────────────────────────────┐
           │  Workflow: .github/workflows/*.yml     │
           │  uses: alanhurtarte/pr-reviewer-agent  │
           └──────────────────┬─────────────────────┘
                              │ (docker run per event)
                              ▼
                ┌────────────────────────────┐
                │  Container: python -m      │
                │  src.action                │
                └──────────────┬─────────────┘
                               │
                               ▼
                       ┌───────────────┐
                       │PRReviewerAgent│   (LangChain tool-using agent)
                       └──────┬────────┘
                              │
                 ┌────────────┼────────────┐
                 ▼            ▼            ▼
            ┌─────────┐  ┌─────────┐  ┌──────────┐
            │OpenAI / │  │ GitHub  │  │Redactor  │
            │  Kimi   │  │   API   │  │(in-proc) │
            └─────────┘  └─────────┘  └──────────┘
```

## Future Tech Considerations

- **Vector Database**: For RAG implementation (Phase 3+). Lives OUTSIDE the Action container — the Action queries it over HTTP.
- **GHCR image caching**: Pre-built images per tag so the Action cold-start drops from ~30s (pip install) to ~3s (docker pull). Phase 4.
- **tiktoken budget**: Pre-flight token estimation before calling the LLM.
- **Prometheus / Grafana**: For observability and metrics on a self-hosted dashboard consuming Action run logs.
