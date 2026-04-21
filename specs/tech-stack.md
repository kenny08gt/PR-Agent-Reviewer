# Tech Stack

## Language & Runtime

- **Python 3.13**: Primary language for the agent implementation
- **Type hints**: Enforced via Pydantic models for all data structures

## Core Frameworks & Libraries

### AI/LLM Layer
- **LangChain 0.3.27**: Framework for building LLM applications with chain composition
- **LangChain-OpenAI 0.3.28**: OpenAI integration for GPT models
- **OpenAI 1.98.0**: Direct API access for advanced use cases

### API & Web Layer
- **FastAPI 0.116.1**: Modern, fast web framework for API endpoints
- **Uvicorn 0.35.0**: ASGI server for running the application
- **Pydantic 2.11.7**: Data validation and settings management
- **Pydantic-Settings 2.6.1**: Configuration management with environment variables

### Platform Integrations
- **PyGithub 2.7.0**: GitHub API client for PR interactions
- **python-gitlab 6.2.0**: GitLab API client for PR/MR interactions
- **requests 2.32.4**: HTTP library for webhook handling
- **aiohttp 3.12.15**: Async HTTP client for concurrent API calls

### Utilities
- **python-multipart 0.0.20**: Form data parsing for webhooks
- **python-dotenv**: Environment variable management

## Infrastructure & Deployment

- **GitHub Actions**: Primary execution environment for the agent
  - Triggered on PR events (open, update, synchronize)
  - Runs as a containerized job with access to repository code
  - Posts review comments directly to PRs

- **Webhook Support**: Optional self-hosted mode via FastAPI server
  - Receives platform webhooks (GitHub/GitLab)
  - Processes reviews asynchronously

## Data Storage (Future: RAG Integration)

- **Vector Store**: TBD (Pinecone, Weaviate, or pgvector)
- **Embeddings**: OpenAI text-embedding-3-small or similar
- **Document Store**: Repository code indexed by file path and commit history

## Development Tools

- **venv**: Virtual environment management
- **Git**: Version control with conventional commits

## Constraints & Decisions

1. **GitHub Actions First**: The MVP runs exclusively as a GitHub Action. Self-hosted webhook mode is a future phase.

2. **Python Over TypeScript**: While GitHub Actions supports TypeScript natively, Python's superior ML/AI ecosystem (LangChain, OpenAI SDKs) makes it the right choice for an LLM-heavy application.

3. **LangChain for Orchestration**: Raw OpenAI calls would be simpler for basic cases, but LangChain provides essential abstractions for context management, prompt templating, and future RAG integration.

4. **Dual Platform Support**: GitHub and GitLab APIs differ significantly. The architecture must abstract platform-specific logic while supporting both from day one.

5. **Async Throughout**: All external API calls (LLM, GitHub, GitLab) use async patterns to maximize throughput and minimize review latency.

6. **No Database in MVP**: The initial version is stateless. All context comes from the PR diff and shallow git history. RAG integration in future phases adds persistent knowledge.

## Environment Configuration

Required environment variables:

```bash
# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key_here

# Platform Selection (github or gitlab)
PLATFORM=github

# GitHub Configuration
GITHUB_TOKEN=your_github_personal_access_token
GITHUB_WEBHOOK_SECRET=your_webhook_secret_here

# GitLab Configuration (alternative)
GITLAB_TOKEN=your_gitlab_access_token
GITLAB_URL=https://gitlab.com
GITLAB_WEBHOOK_SECRET=your_webhook_secret_here

# Agent Behavior
AGENT_NAME=AH-Reviewer-Bot
MAX_FILES_TO_REVIEW=10
MAX_DIFF_LINES=500
```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Actions Runner                    │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   GitHub     │  │   GitLab     │  │   Webhook    │      │
│  │   Action     │  │   Action     │  │   Server     │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
└─────────┼────────────────┼─────────────────┼──────────────┘
          │                │                 │
          └────────────────┴─────────────────┘
                           │
                    ┌──────▼──────┐
                    │  PR Reviewer │
                    │    Agent     │
                    └──────┬───────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
      ┌────▼────┐    ┌────▼────┐    ┌────▼────┐
      │ OpenAI  │    │ GitHub  │    │ GitLab  │
      │  LLM    │    │   API   │    │   API   │
      └─────────┘    └─────────┘    └─────────┘
```

## Future Tech Considerations

- **Vector Database**: For RAG implementation (Phase 3+)
- **Redis**: For caching repository metadata and review state
- **PostgreSQL**: For persistent storage of review history and metrics
- **Prometheus/Grafana**: For observability and metrics
