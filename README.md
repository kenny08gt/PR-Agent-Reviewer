# pr-reviewer-agent

AI-powered pull request reviewer shipped as a Docker-container GitHub Action. Uses OpenAI or Moonshot/Kimi via LangChain to post a review comment on every new PR. No server to host, no webhook to configure.

## Quick start

Create `.github/workflows/pr-review.yml` in your repo:

```yaml
name: PR Review
on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: Run PR Reviewer
        uses: alanhurtarte/pr-reviewer-agent@v1
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
          # Optional: swap providers
          # llm-provider: kimi
          # moonshot-api-key: ${{ secrets.MOONSHOT_API_KEY }}
```

Store your LLM API key as a repo secret (Settings -> Secrets and variables -> Actions). `GITHUB_TOKEN` is provided by the runner automatically.

## Inputs

| Name                 | Required                       | Default                 | Description                                                                 |
|----------------------|--------------------------------|-------------------------|-----------------------------------------------------------------------------|
| `github-token`       | yes                            | —                       | Usually `${{ secrets.GITHUB_TOKEN }}`; needs `pull-requests: write`.        |
| `openai-api-key`     | when `llm-provider=openai`     | —                       | OpenAI API key.                                                             |
| `moonshot-api-key`   | when `llm-provider=kimi`       | —                       | Moonshot / Kimi API key.                                                    |
| `llm-provider`       | no                             | `openai`                | `openai` or `kimi`.                                                         |
| `llm-model`          | no                             | per-provider default    | Model ID. Defaults: `gpt-4o-mini` (OpenAI), `kimi-k2-0905-preview` (Kimi).  |
| `llm-base-url`       | no                             | provider default        | Override the API base URL (proxy or self-hosted).                           |
| `max-files-to-review`| no                             | `10`                    | Skip PRs with more changed files than this.                                 |
| `max-diff-lines`     | no                             | `500`                   | Skip PRs with more total +/- lines than this.                               |
| `review-enabled`     | no                             | `true`                  | Set to `false` to acknowledge events without calling the LLM.               |
| `dry-run`            | no                             | `false`                 | Run the review but do not post the comment back to the PR.                  |

See [`action.yml`](./action.yml) for the canonical schema.

## Supported providers

- **OpenAI** — `gpt-4o-mini` by default. Any OpenAI chat-completions model works.
- **Moonshot / Kimi** — `kimi-k2-0905-preview` by default. OpenAI-SDK-compatible; set `llm-provider: kimi` and provide `moonshot-api-key`.

## What it does

On each `opened` / `synchronize` / `reopened` pull_request event:

1. Fetches the PR metadata and file patches from the GitHub API.
2. Drops lockfiles, `node_modules/`, generated files, and minified assets.
3. Redacts obvious secret patterns (GitHub / OpenAI / Slack / AWS keys, JWTs, PEM private-key blocks, generic `password = "..."` assignments) from the patch text **before** sending to the LLM.
4. Skips drafts, PRs larger than `max-files-to-review` / `max-diff-lines` (posts a polite notice for the size-skip), and everything when `review-enabled=false`.
5. Otherwise asks the LLM to review the diff and posts a COMMENT-type PR review, including per-line inline comments pinned to specific added or modified lines in the diff.

## Local development

```bash
source venv/bin/activate
pip install -r src/requirements.txt
pytest -q

# Run the entry point against a real PR without GitHub's runner env:
CLI_REPO=octocat/hello-world CLI_PR=1 \
INPUT_GITHUB_TOKEN=$GITHUB_TOKEN \
INPUT_OPENAI_API_KEY=$OPENAI_API_KEY \
python -m src.action

# Or build and run the Action image locally:
docker build -t prb:test .
```

## License

MIT (LICENSE file not yet added; see repository settings).
