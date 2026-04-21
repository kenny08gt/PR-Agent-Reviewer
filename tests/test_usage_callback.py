"""Tests for `UsageCallbackHandler` (Phase 1.7)."""
from types import SimpleNamespace

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from src.utils.usage_callback import UsageCallbackHandler


def _result_with_token_usage(prompt, completion, cached):
    """Build an LLMResult carrying classic `token_usage` in `llm_output`."""
    msg = AIMessage(content="ok")
    gen = ChatGeneration(message=msg, generation_info={})
    return LLMResult(
        generations=[[gen]],
        llm_output={
            "token_usage": {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "prompt_tokens_details": {"cached_tokens": cached},
            },
            "model_name": "gpt-4o-mini",
        },
    )


def _result_with_generation_info(prompt, completion, cached):
    """Some providers surface usage on the generation rather than llm_output."""
    msg = AIMessage(content="ok")
    gen = ChatGeneration(
        message=msg,
        generation_info={
            "token_usage": {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "prompt_tokens_details": {"cached_tokens": cached},
            }
        },
    )
    return LLMResult(generations=[[gen]], llm_output=None)


def _result_with_usage_metadata(input_tokens, output_tokens, cache_read):
    """Newer langchain-core shape: AIMessage.usage_metadata."""
    msg = AIMessage(
        content="ok",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "input_token_details": {"cache_read": cache_read},
        },
    )
    gen = ChatGeneration(message=msg, generation_info={})
    return LLMResult(generations=[[gen]], llm_output={})


# ---------------------------------------------------------------------------
# Accumulation across calls
# ---------------------------------------------------------------------------
def test_accumulates_across_multiple_on_llm_end_calls():
    handler = UsageCallbackHandler()
    handler.on_llm_end(_result_with_token_usage(100, 50, 10))
    handler.on_llm_end(_result_with_token_usage(200, 70, 30))

    totals = handler.totals()
    assert totals["prompt_tokens"] == 300
    assert totals["completion_tokens"] == 120
    assert totals["cached_tokens"] == 40
    assert totals["calls"] == 2


# ---------------------------------------------------------------------------
# Alternative shapes
# ---------------------------------------------------------------------------
def test_reads_from_generation_info_when_llm_output_empty():
    handler = UsageCallbackHandler()
    handler.on_llm_end(_result_with_generation_info(10, 5, 2))

    totals = handler.totals()
    assert totals["prompt_tokens"] == 10
    assert totals["completion_tokens"] == 5
    assert totals["cached_tokens"] == 2


def test_reads_from_usage_metadata_when_classic_missing():
    handler = UsageCallbackHandler()
    handler.on_llm_end(_result_with_usage_metadata(111, 22, 7))

    totals = handler.totals()
    assert totals["prompt_tokens"] == 111
    assert totals["completion_tokens"] == 22
    assert totals["cached_tokens"] == 7


# ---------------------------------------------------------------------------
# Missing / empty fields default to 0
# ---------------------------------------------------------------------------
def test_missing_fields_default_to_zero():
    """No token_usage anywhere => counts stay at 0 but call is counted."""
    msg = AIMessage(content="ok")
    gen = ChatGeneration(message=msg, generation_info={})
    result = LLMResult(generations=[[gen]], llm_output={})

    handler = UsageCallbackHandler()
    handler.on_llm_end(result)

    totals = handler.totals()
    assert totals["prompt_tokens"] == 0
    assert totals["completion_tokens"] == 0
    assert totals["cached_tokens"] == 0
    assert totals["calls"] == 1


def test_partial_token_usage_missing_cached_defaults_to_zero():
    """token_usage without prompt_tokens_details -> cached=0, others read."""
    msg = AIMessage(content="ok")
    gen = ChatGeneration(message=msg, generation_info={})
    result = LLMResult(
        generations=[[gen]],
        llm_output={"token_usage": {"prompt_tokens": 7, "completion_tokens": 3}},
    )

    handler = UsageCallbackHandler()
    handler.on_llm_end(result)

    totals = handler.totals()
    assert totals["prompt_tokens"] == 7
    assert totals["completion_tokens"] == 3
    assert totals["cached_tokens"] == 0


def test_non_integer_token_value_defaults_to_zero():
    """Defensive: string/None values in the usage dict -> 0, not a crash."""
    msg = AIMessage(content="ok")
    gen = ChatGeneration(message=msg, generation_info={})
    result = LLMResult(
        generations=[[gen]],
        llm_output={
            "token_usage": {
                "prompt_tokens": "not-a-number",
                "completion_tokens": None,
                "prompt_tokens_details": {"cached_tokens": "nope"},
            }
        },
    )

    handler = UsageCallbackHandler()
    handler.on_llm_end(result)

    totals = handler.totals()
    assert totals["prompt_tokens"] == 0
    assert totals["completion_tokens"] == 0
    assert totals["cached_tokens"] == 0


def test_handler_tolerates_non_llmresult_response():
    """If something odd is passed, we shouldn't crash; just count the call."""
    handler = UsageCallbackHandler()
    # Pass a random object (no generations, no llm_output).
    handler.on_llm_end(SimpleNamespace())
    totals = handler.totals()
    assert totals["calls"] == 1
    assert totals["prompt_tokens"] == 0
    assert totals["completion_tokens"] == 0
    assert totals["cached_tokens"] == 0
