"""LangChain callback that accumulates OpenAI-style token usage across a run.

`AgentExecutor.invoke` does not return a direct token-usage breakdown. We
capture it via `on_llm_end`, which fires once per LLM call. An agent run
typically issues several LLM calls (plan -> tool -> plan -> ...), so we sum
the counts across them.

Shape notes (langchain-openai 0.3, OpenAI wire format):
- `LLMResult.llm_output` is a dict that may contain
  `{"token_usage": {"prompt_tokens": int, "completion_tokens": int,
                    "prompt_tokens_details": {"cached_tokens": int}}}`.
- Individual `ChatGeneration.generation_info` MAY also carry a similar blob;
  Moonshot (OpenAI-compatible) occasionally surfaces usage at this layer.
- Modern langchain-core attaches `usage_metadata` to the `AIMessage` itself
  with keys `input_tokens`, `output_tokens`, and nested
  `input_token_details.cache_read`.
Every field is treated as optional — missing shapes degrade to 0.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)


def _as_int(value: Any) -> int:
    """Coerce anything to a non-negative int; None/str/bad -> 0."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _extract_from_token_usage(tu: Any) -> Dict[str, int]:
    """Extract (prompt, completion, cached) from a classic `token_usage` dict."""
    if not isinstance(tu, dict):
        return {"prompt": 0, "completion": 0, "cached": 0}

    prompt = _as_int(tu.get("prompt_tokens"))
    completion = _as_int(tu.get("completion_tokens"))

    cached = 0
    details = tu.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached = _as_int(details.get("cached_tokens"))

    return {"prompt": prompt, "completion": completion, "cached": cached}


def _extract_from_usage_metadata(um: Any) -> Dict[str, int]:
    """Extract from the newer `usage_metadata` shape on AIMessage."""
    if not isinstance(um, dict):
        return {"prompt": 0, "completion": 0, "cached": 0}

    prompt = _as_int(um.get("input_tokens"))
    completion = _as_int(um.get("output_tokens"))

    cached = 0
    details = um.get("input_token_details")
    if isinstance(details, dict):
        # LangChain normalizes OpenAI's `cached_tokens` to `cache_read`.
        cached = _as_int(details.get("cache_read")) or _as_int(
            details.get("cached_tokens")
        )

    return {"prompt": prompt, "completion": completion, "cached": cached}


class UsageCallbackHandler(BaseCallbackHandler):
    """Accumulates token usage across all LLM calls in a single agent run.

    Not inherently tied to a specific run; instantiate fresh per
    `review_pr` call to avoid cross-request bleed. A lock protects the
    counters because LangChain may dispatch callbacks from a thread that
    differs from the one that created the handler (e.g. an async
    executor). The Action's single-shot container doesn't hit this in
    practice, but the lock costs nothing and keeps the handler reusable
    if we ever move to a long-running worker model.
    """

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.cached_tokens: int = 0
        self.call_count: int = 0

    # ------------------------------------------------------------------
    # Public read API — snapshot the totals at end of a run.
    # ------------------------------------------------------------------
    def totals(self) -> Dict[str, int]:
        with self._lock:
            return {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "cached_tokens": self.cached_tokens,
                "calls": self.call_count,
            }

    # ------------------------------------------------------------------
    # Callback hook
    # ------------------------------------------------------------------
    def on_llm_end(self, response: Any, **kwargs: Any) -> None:  # type: ignore[override]
        """Accumulate tokens from a single LLM call.

        We defensively try three locations in order:
          1. `response.llm_output["token_usage"]` (classic OpenAI shape)
          2. Per-generation `generation_info["token_usage"]`
          3. `AIMessage.usage_metadata` on the first generation's message
        Each extractor independently defaults missing fields to 0, and the
        three are OR'd — whichever surfaces the numbers wins, last-write
        wins per key. This keeps the handler robust across OpenAI, Moonshot,
        and LangChain version drift.
        """
        extracted: Optional[Dict[str, int]] = None

        # (1) llm_output.token_usage
        llm_output = getattr(response, "llm_output", None)
        if isinstance(llm_output, dict):
            tu = llm_output.get("token_usage")
            if tu:
                extracted = _extract_from_token_usage(tu)

        # (2) generation_info on each generation (fallback if llm_output empty)
        if not extracted:
            generations = getattr(response, "generations", None) or []
            for gen_list in generations:
                for gen in gen_list or []:
                    gen_info = getattr(gen, "generation_info", None)
                    if isinstance(gen_info, dict):
                        tu = gen_info.get("token_usage")
                        if tu:
                            extracted = _extract_from_token_usage(tu)
                            break
                if extracted:
                    break

        # (3) usage_metadata on the AIMessage (newer langchain-core shape)
        if not extracted:
            generations = getattr(response, "generations", None) or []
            for gen_list in generations:
                for gen in gen_list or []:
                    msg = getattr(gen, "message", None)
                    um = getattr(msg, "usage_metadata", None) if msg else None
                    if um:
                        extracted = _extract_from_usage_metadata(um)
                        break
                if extracted:
                    break

        if not extracted:
            # Nothing found; count the call but add zero.
            with self._lock:
                self.call_count += 1
            return

        with self._lock:
            self.prompt_tokens += extracted["prompt"]
            self.completion_tokens += extracted["completion"]
            self.cached_tokens += extracted["cached"]
            self.call_count += 1
