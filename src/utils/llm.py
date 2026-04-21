import logging
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel

from .config import Settings

logger = logging.getLogger(__name__)

_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "kimi": "kimi-k2-0905-preview",
}
_KIMI_BASE_URL = "https://api.moonshot.ai/v1"

# Stable `user` identifier passed on every request. OpenAI uses it as part of
# the automatic prompt-prefix cache key so cache lookups are scoped per app,
# not per end-user. Moonshot (OpenAI-compatible) accepts + ignores it.
# NOTE: Phase 1.7 intentionally stops here — per-repo `prompt_cache_key` /
# Moonshot context-cache plumbing is deferred to a later wave because
# LangChain 0.3's per-invocation pass-through for AgentExecutor is brittle.
_PROMPT_CACHE_USER = "pr-reviewer-agent"


def get_chat_model(settings: Settings) -> BaseChatModel:
    """Return a ChatOpenAI configured for the selected provider."""
    provider = settings.llm_provider
    model = settings.llm_model or _DEFAULT_MODELS[provider]

    if provider == "openai":
        api_key = settings.openai_api_key
        base_url = settings.llm_base_url  # None means OpenAI default
    elif provider == "kimi":
        api_key = settings.moonshot_api_key
        base_url = settings.llm_base_url or _KIMI_BASE_URL
    else:
        raise ValueError(f"Unknown llm_provider: {provider}")

    logger.info("LLM configured: provider=%s model=%s base_url=%s",
                provider, model, base_url or "<default>")

    kwargs = {
        "model": model,
        "api_key": api_key,
        "temperature": 0.1,
        # Routed via model_kwargs (not a first-class ChatOpenAI field) so the
        # OpenAI SDK sees `user` in the request body. Avoids the pydantic
        # "transferred to model_kwargs" UserWarning at construction time.
        "model_kwargs": {"user": _PROMPT_CACHE_USER},
    }
    if base_url is not None:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)
