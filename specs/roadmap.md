# Roadmap

## Phase 0: Foundation (Current)
**Status**: In Progress

- [x] Project scaffold with directory structure
- [x] Virtual environment setup with dependencies
- [x] Environment configuration template
- [x] Skills framework for feature development
- [x] Constitution (mission, tech-stack, roadmap)

---

## Phase 1: GitHub Action MVP
**Goal**: A working GitHub Action that reviews PRs with OpenAI

- [ ] Implement GitHub API client wrapper (`src/tools/github_tools.py`)
  - Fetch PR metadata (title, description, author)
  - Fetch PR diff
  - Post review comments
  - Update check status

- [ ] Implement PR diff parsing (`src/utils/diff_parser.py`)
  - Parse unified diff format
  - Extract changed files, hunks, line numbers
  - Map diff positions to file/line for comments

- [ ] Build core review agent (`src/agents/pr_reviewer.py`)
  - Prompt template for code review
  - LLM chain with OpenAI GPT-4o-mini
  - Output parser for structured review comments
  - Per-file review generation

- [ ] Create GitHub Action workflow (`.github/workflows/pr-review.yml`)
  - Trigger on pull_request events (opened, synchronize)
  - Checkout repository code
  - Run review agent
  - Post results as PR review

- [ ] Add basic configuration system (`src/utils/config.py`)
  - Load settings from environment
  - Validate required variables
  - Platform-specific config (GitHub vs GitLab)

- [ ] Error handling and logging
  - Graceful handling of API failures
  - Structured logging for debugging
  - Skip large PRs (>500 lines) with notice

**Definition of Done**: Any PR to the repo triggers an automatic review with at least one meaningful comment from the agent.

---

## Phase 2: Enhanced Context
**Goal**: Reviews that understand more than just the diff

- [ ] Repository context gathering
  - Fetch repository structure (file tree)
  - Read relevant files referenced in PR
  - Identify import dependencies of changed files

- [ ] Code pattern detection
  - Detect existing naming conventions
  - Identify project-specific patterns (testing style, error handling)
  - Extract patterns from existing codebase

- [ ] Commit history context
  - Analyze recent commits for style patterns
  - Check for related recent changes
  - Identify authors of touched code for potential questions

- [ ] Improved prompt engineering
  - Dynamic prompt construction based on file type
  - Language-specific review guidelines
  - Severity classification (blocking vs suggestion vs nitpick)

- [ ] Review comment formatting
  - Categorize comments (security, performance, style, architecture)
  - Add emoji indicators for quick visual parsing
  - Include code snippets in suggestions

**Definition of Done**: Agent provides context-aware suggestions that reference other files or patterns in the repo, not just the changed lines.

---

## Phase 3: RAG Integration (Knowledge Layer)
**Goal**: Persistent, searchable knowledge of the codebase

- [ ] Vector database setup
  - Choose and integrate vector store (Pinecone/Weaviate/pgvector)
  - Set up embedding pipeline with OpenAI
  - Create document chunking strategy for code

- [ ] Code indexing system
  - Index entire repository by file and function
  - Store embeddings for semantic search
  - Incremental updates on code changes

- [ ] Semantic context retrieval
  - Retrieve similar code patterns when reviewing
  - Find relevant documentation or ADRs
  - Query past review decisions for consistency

- [ ] Architecture decision records (ADR) awareness
  - Parse ADR files from repo
  - Include relevant ADRs in review context
  - Flag potential ADR violations

- [ ] Knowledge graph of code relationships
  - Map module dependencies
  - Identify code owners and experts
  - Track API contracts between services

**Definition of Done**: Agent answers questions like "How do we usually handle errors in this service?" by querying the knowledge base.

---

## Phase 4: GitLab Support & Self-Hosting
**Goal**: Platform parity and deployment flexibility

- [ ] GitLab MR review support (`src/tools/gitlab_tools.py`)
  - MR diff fetching
  - Comment posting via GitLab API
  - Pipeline status integration
  - Thread-based discussions

- [ ] Abstract platform interface
  - Common interface for GitHub/GitLab operations
  - Platform-agnostic review data models
  - Unified configuration

- [ ] Self-hosted webhook mode (`src/main.py`)
  - FastAPI server for webhook reception
  - Async job queue for review processing
  - Health check and monitoring endpoints

- [ ] Container packaging
  - Dockerfile for the application
  - Docker Compose for local development
  - Helm chart for Kubernetes deployment

**Definition of Done**: Works identically on GitHub Actions, GitLab CI, and self-hosted Docker deployments.

---

## Phase 5: Advanced Review Capabilities
**Goal**: Reviews that rival senior engineer quality

- [ ] Security scanning integration
  - Detect common vulnerabilities (OWASP patterns)
  - Flag secrets or credentials in code
  - Suggest security best practices

- [ ] Performance analysis
  - Detect N+1 query patterns
  - Flag inefficient algorithms
  - Suggest async/concurrent patterns

- [ ] Test coverage awareness
  - Check if changed code has tests
  - Suggest test cases for uncovered logic
  - Identify risky changes lacking coverage

- [ ] Multi-turn conversation
  - Respond to developer replies on comments
  - Clarify suggestions when asked
  - Update reviews based on follow-up commits

- [ ] Review analytics dashboard
  - Track review acceptance rate
  - Measure time to review
  - Identify patterns in rejected suggestions

**Definition of Done**: Developers actively seek agent reviews for catching issues before human reviewers, and trust its security/performance insights.

---

## Phase 6: Team Customization & Learning
**Goal**: Agent that adapts to each team's unique culture

- [ ] Team configuration files
  - `.pr-review-rules.yml` in repo root
  - Custom severity thresholds per team
  - Ignore patterns and file exclusions

- [ ] Learning from feedback
  - Track which suggestions are accepted/rejected
  - Adjust future reviews based on team preferences
  - Identify team's unique conventions

- [ ] Review history insights
  - Summarize recurring issues by author (private)
  - Identify knowledge gaps in the team
  - Suggest documentation improvements

- [ ] Integration with team tools
  - Slack notifications for completed reviews
  - JIRA/Azure DevOps linking
  - IDE extensions for inline suggestions

**Definition of Done**: The agent feels like a custom-built team member that knows your codebase, your standards, and your preferences.

---

## Backlog (Future Ideas)

- Multi-language support beyond Python (JS/TS, Go, Rust, Java)
- CI/CD integration (flag if tests fail, suggest fixes)
- Auto-fix suggestions with patch generation
- Voice/video explanation of complex reviews
- Integration with static analysis tools (SonarQube, CodeClimate)
- Review assignment based on code ownership and expertise
- Historical review data for team retrospectives

---

## Progress Tracking

| Phase | Status | Started | Completed |
|-------|--------|---------|-----------|
| 0: Foundation | In Progress | 2026-04-21 | - |
| 1: GitHub Action MVP | Not Started | - | - |
| 2: Enhanced Context | Not Started | - | - |
| 3: RAG Integration | Not Started | - | - |
| 4: GitLab & Self-Hosting | Not Started | - | - |
| 5: Advanced Capabilities | Not Started | - | - |
| 6: Team Customization | Not Started | - | - |

**Last Updated**: 2026-04-21
