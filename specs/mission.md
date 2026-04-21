# Mission

## Purpose

Build an intelligent PR review agent that goes beyond surface-level file analysis. Unlike conventional review tools that suggest changes in isolation, our agent understands the broader context of the codebase—architectural patterns, existing conventions, and cross-file dependencies—to provide meaningful, actionable feedback that improves code quality and team productivity.

## Vision

Every pull request receives a thoughtful, context-aware review within seconds. Developers spend less time on repetitive feedback loops and more time shipping value. The agent becomes a trusted team member that:

- Catches issues that humans miss due to time constraints or fatigue
- Enforces consistent patterns across the entire codebase
- Explains the "why" behind suggestions, not just the "what"
- Learns from the team's evolving standards and preferences

## Target Users

- **Development Teams**: Small to medium teams (5-50 developers) who want consistent code quality without blocking reviews
- **Tech Leads**: Leaders who want to enforce architectural standards across their organization
- **Open Source Maintainers**: Maintainers overwhelmed by community contributions who need automated first-pass reviews

## Core Values

1. **Context Over Rules**: We prioritize understanding over rigid rule-checking. A suggested change must consider the surrounding architecture.

2. **Explainability**: Every suggestion includes a clear rationale. Developers should learn from reviews, not blindly accept them.

3. **Pragmatism**: We balance ideal code with practical constraints. Not every imperfection needs a comment.

4. **Respect for Human Judgment**: The agent augments human reviewers, it doesn't replace them. Final decisions always rest with the team.

5. **Continuous Learning**: The agent improves over time by understanding the team's evolving patterns and feedback on its own suggestions.

## Problem Solved

Traditional PR review tools fall into two categories:

- **Linting/Static Analysis**: Catches syntax and basic style issues but misses architectural concerns, business logic errors, and cross-file impacts
- **Human Reviews**: Thorough but time-consuming, inconsistent, and prone to missing issues when reviewers are busy or fatigued

Our agent bridges this gap by combining the speed and consistency of automation with the contextual awareness of an experienced developer who knows the codebase intimately.

## Success Metrics

- Review time reduced from hours to minutes
- Consistent application of team conventions across all PRs
- Developers report learning from agent suggestions
- Reduced back-and-forth in PR comment threads
- Measurable reduction in bugs reaching production
