"""Runtime configuration for the PR reviewer.

Wave 3 (2026-04-21) reshaped this module: we shipped as a Docker-container
GitHub Action and dropped GitLab support, the FastAPI webhook server, and
the SQLite history KV. The remaining knobs are the ones that matter when
an Action container boots per-event:

- LLM provider + credentials
- GitHub token (the Action receives it via `${{ secrets.GITHUB_TOKEN }}`)
- Size guardrails + the kill switch

Everything else (platform selection, webhook secrets, api host/port,
history paths) is gone.
"""
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    # LLM provider selection
    llm_provider: Literal["openai", "kimi"] = Field(
        default="openai",
        validation_alias=AliasChoices("LLM_PROVIDER"),
    )
    llm_model: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL"),
    )
    llm_base_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("LLM_BASE_URL"),
    )

    # Provider credentials
    openai_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY"),
    )
    moonshot_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("MOONSHOT_API_KEY"),
    )

    # GitHub auth. The Action maps `${{ secrets.GITHUB_TOKEN }}` onto this.
    github_token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("GITHUB_TOKEN"),
    )

    # Agent knobs
    agent_name: str = Field(
        default="PR-Reviewer-Bot",
        validation_alias=AliasChoices("AGENT_NAME"),
    )
    max_files_to_review: int = Field(
        default=10,
        validation_alias=AliasChoices("MAX_FILES_TO_REVIEW"),
    )
    max_diff_lines: int = Field(
        default=500,
        validation_alias=AliasChoices("MAX_DIFF_LINES"),
    )

    # Kill switch — set REVIEW_ENABLED=false to acknowledge the event
    # without calling the LLM (useful during incidents or cost spikes).
    review_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("REVIEW_ENABLED"),
    )

    @model_validator(mode="after")
    def _require_provider_key(self):
        """Fail fast when the selected provider's key is missing.

        Wave 3: no more `platform` branching — just the per-provider key
        check. The GitHub token check lives in `src/action.py` because
        constructing Settings without it must still succeed for local
        smoke-tests that never touch the PR API.
        """
        if self.llm_provider == "openai" and not self.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        if self.llm_provider == "kimi" and not self.moonshot_api_key:
            raise ValueError(
                "MOONSHOT_API_KEY is required when LLM_PROVIDER=kimi")
        return self

    class Config:
        env_file = ".env"


settings = Settings()
