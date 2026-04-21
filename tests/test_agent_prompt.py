"""Sanity check: the agent's ChatPromptTemplate must only reference
the expected input variables.

This regression test exists because a stray literal `{path, line, body}`
in the system prompt (Wave 4) was interpreted by LangChain as a template
variable, causing every real PR review to fail with
`Input to ChatPromptTemplate is missing variables {'path, line, body'}`.

Any curly-brace content meant as illustrative JSON/dict syntax must be
double-braced (`{{...}}`) in the prompt string.
"""
from __future__ import annotations

import pytest

from src.agents.pr_reviewer import PRReviewerAgent


@pytest.fixture
def agent(monkeypatch):
    """Construct the real agent; we don't call it, just inspect the prompt."""
    # Avoid touching the network; the LLM client is instantiated but never
    # invoked by these tests.
    return PRReviewerAgent()


def _collect_prompt(agent_executor):
    """Walk the AgentExecutor to find the ChatPromptTemplate."""
    # create_openai_tools_agent wraps the prompt into a RunnableSequence.
    # The prompt is the first runnable whose type carries template vars.
    runnable = agent_executor.agent.runnable
    for step in getattr(runnable, "steps", []) + [runnable]:
        if hasattr(step, "input_variables"):
            return step
    raise AssertionError("no ChatPromptTemplate found in agent runnable")


def test_prompt_input_variables_are_expected(agent):
    prompt = _collect_prompt(agent.agent)
    # The agent prompt must expect ONLY the documented user-supplied var:
    # `input`. (`agent_scratchpad` is declared as a placeholder, not a
    # regular variable, so it does not appear in `input_variables`.)
    # Any additional entry (e.g. the string `"path, line, body"`) means
    # an unescaped `{...}` literal leaked into the system prompt and
    # LangChain is treating it as a template variable.
    assert set(prompt.input_variables) == {"input"}, (
        f"Unexpected prompt variables: {prompt.input_variables}. "
        "Likely a literal `{...}` in the system prompt needs to be `{{...}}`."
    )


def test_prompt_formats_without_missing_variables(agent):
    """Belt-and-suspenders: actually format the prompt and confirm no KeyError."""
    prompt = _collect_prompt(agent.agent)
    # Supply only the documented variables; should succeed.
    formatted = prompt.format_messages(input="hello", agent_scratchpad=[])
    assert formatted  # non-empty list of messages
