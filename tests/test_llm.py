import pytest


@pytest.fixture
def clean_llm_env(monkeypatch):
    for var in ("LLM_PROVIDER", "LLM_MODEL", "OPENAI_MODEL",
                "LLM_BASE_URL", "OPENAI_API_KEY", "MOONSHOT_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield monkeypatch


def _settings():
    from src.utils.config import Settings
    return Settings(_env_file=None)


def _build():
    from src.utils.llm import get_chat_model
    return get_chat_model(_settings())


def test_openai_default_model_and_no_base_url(clean_llm_env):
    clean_llm_env.setenv("OPENAI_API_KEY", "sk-test")
    model = _build()
    assert model.model_name == "gpt-4o-mini"
    assert model.openai_api_base is None


def test_kimi_uses_moonshot_base_url(clean_llm_env):
    clean_llm_env.setenv("LLM_PROVIDER", "kimi")
    clean_llm_env.setenv("MOONSHOT_API_KEY", "ms-test")
    model = _build()
    assert model.model_name == "kimi-k2-0905-preview"
    assert model.openai_api_base == "https://api.moonshot.ai/v1"


def test_llm_base_url_override_openai(clean_llm_env):
    clean_llm_env.setenv("OPENAI_API_KEY", "sk-test")
    clean_llm_env.setenv("LLM_BASE_URL", "https://proxy.example.com/v1")
    model = _build()
    assert model.openai_api_base == "https://proxy.example.com/v1"


def test_llm_base_url_override_kimi(clean_llm_env):
    clean_llm_env.setenv("LLM_PROVIDER", "kimi")
    clean_llm_env.setenv("MOONSHOT_API_KEY", "ms-test")
    clean_llm_env.setenv("LLM_BASE_URL", "https://proxy.example.com/v1")
    model = _build()
    assert model.openai_api_base == "https://proxy.example.com/v1"


def test_explicit_llm_model_beats_default(clean_llm_env):
    clean_llm_env.setenv("OPENAI_API_KEY", "sk-test")
    clean_llm_env.setenv("LLM_MODEL", "gpt-4o")
    model = _build()
    assert model.model_name == "gpt-4o"
