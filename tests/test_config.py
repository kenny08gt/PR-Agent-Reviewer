import pytest
from pydantic import ValidationError


@pytest.fixture
def clean_llm_env(monkeypatch):
    """Clear LLM-related env vars so each test starts from a known baseline."""
    for var in ("LLM_PROVIDER", "LLM_MODEL", "OPENAI_MODEL",
                "LLM_BASE_URL", "OPENAI_API_KEY", "MOONSHOT_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield monkeypatch


def _fresh_settings():
    from src.utils.config import Settings
    return Settings(_env_file=None)


def test_default_provider_is_openai(clean_llm_env):
    clean_llm_env.setenv("OPENAI_API_KEY", "sk-test")
    s = _fresh_settings()
    assert s.llm_provider == "openai"
    assert s.openai_api_key == "sk-test"


def test_kimi_provider_with_moonshot_key(clean_llm_env):
    clean_llm_env.setenv("LLM_PROVIDER", "kimi")
    clean_llm_env.setenv("MOONSHOT_API_KEY", "ms-test")
    s = _fresh_settings()
    assert s.llm_provider == "kimi"
    assert s.moonshot_api_key == "ms-test"


def test_kimi_without_moonshot_key_raises(clean_llm_env):
    clean_llm_env.setenv("LLM_PROVIDER", "kimi")
    with pytest.raises(ValidationError):
        _fresh_settings()


def test_openai_without_openai_key_raises(clean_llm_env):
    clean_llm_env.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(ValidationError):
        _fresh_settings()


def test_openai_model_alias_still_works(clean_llm_env):
    clean_llm_env.setenv("OPENAI_API_KEY", "sk-test")
    clean_llm_env.setenv("OPENAI_MODEL", "gpt-4o")
    s = _fresh_settings()
    assert s.llm_model == "gpt-4o"


def test_llm_model_takes_precedence_over_openai_model(clean_llm_env):
    clean_llm_env.setenv("OPENAI_API_KEY", "sk-test")
    clean_llm_env.setenv("OPENAI_MODEL", "gpt-4o")
    clean_llm_env.setenv("LLM_MODEL", "foo")
    s = _fresh_settings()
    assert s.llm_model == "foo"
