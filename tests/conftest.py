"""Shared pytest setup.

Wave 3: the webhook server and the history KV are gone, so the env-var
preamble only needs `OPENAI_API_KEY` (for `Settings` to validate) and
`GITHUB_TOKEN` (for anywhere we instantiate `GitHubTools` even with
fully-mocked children). Nothing here opens files.
"""
import os

import pytest

# Set before any test module imports src.utils.config. Pytest evaluates
# conftest.py before collecting sibling modules, so this top-level block
# runs first.
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("GITHUB_TOKEN", "test-github-token")


@pytest.fixture(autouse=True, scope="session")
def _set_required_env():
    """Session-scoped guard: re-assert env in case a test deleted it."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    mp.setenv("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "test-key"))
    mp.setenv(
        "GITHUB_TOKEN",
        os.environ.get("GITHUB_TOKEN", "test-github-token"),
    )
    yield
    mp.undo()
