# Mission

## Purpose

Build an intelligent PR review agent that goes beyond surface-level file analysis. Unlike conventional review tools that suggest changes in isolation, our agent understands the broader context of the codebase — architectural patterns, existing conventions, and cross-file dependencies — to provide meaningful, actionable feedback that improves code quality and team productivity.

## Vision

Every pull request receives a thoughtful, context-aware review within seconds. Developers spend less time on repetitive feedback loops and more time shipping value. The agent becomes a trusted team member that:

- Catches issues that humans miss due to time constraints or fatigue
- Enforces consistent patterns across the entire codebase
- Explains the "why" behind suggestions, not just the "what"
- Reflects team conventions found in the repo itself — its code, its `.pr-review-rules.yml` (future Phase 6), and any indexed documentation (future Phase 3 RAG) — rather than inferring preferences from accepted/rejected suggestion labels

## Target Users

- **Open Source Maintainers**: Maintainers overwhelmed by community contributions who need automated first-pass reviews without hosting infrastructure
- **Development Teams**: Small to medium teams (5-50 developers) who want consistent code quality without blocking reviews
- **Tech Leads**: Leaders who want to enforce architectural standards across their organization

Both primary cohorts share one need: **zero-hosting install**. This is why Wave 3 (2026-04-21) pivoted from a self-hosted webhook server to a Docker-container GitHub Action — `uses: alanhurtarte/pr-reviewer-agent@v1` in a workflow file is the entire install.

## Core Values

1. **Context Over Rules**: We prioritize understanding over rigid rule-checking. A suggested change must consider the surrounding architecture.

2. **Explainability**: Every suggestion includes a clear rationale. Developers should learn from reviews, not blindly accept them.

3. **Pragmatism**: We balance ideal code with practical constraints. Not every imperfection needs a comment.

4. **Respect for Human Judgment**: The agent augments human reviewers, it doesn't replace them. Final decisions always rest with the team.

5. **Reflects Repository Conventions**: The agent's behavior is driven by what's in the repo — code, config, docs — not by an opaque "learned preferences" store it maintains across sessions. New team members should be able to read the same files the agent does and predict what it will say.

## Problem Solved

Traditional PR review tools fall into two categories:

- **Linting / Static Analysis**: Catches syntax and basic style issues but misses architectural concerns, business logic errors, and cross-file impacts
- **Human Reviews**: Thorough but time-consuming, inconsistent, and prone to missing issues when reviewers are busy or fatigued

Our agent bridges this gap by combining the speed and consistency of automation with the contextual awareness of an experienced developer who knows the codebase intimately — delivered via a GitHub Action so there is nothing to host.

## Success Metrics

- Review time reduced from hours to minutes (Action run + LLM call, typically under 60s for small-to-medium PRs)
- Consistent application of team conventions across all PRs
- Developers report learning from agent suggestions
- Reduced back-and-forth in PR comment threads
- Measurable reduction in bugs reaching production
- Install friction: a team can add the Action and get their first review in under 5 minutes
