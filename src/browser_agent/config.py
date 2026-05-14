from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Browserbase (required)
    browserbase_api_key: str
    browserbase_project_id: str

    # LLM keys (at least one required)
    openai_api_key: str
    anthropic_api_key: str = ""

    # Model overrides
    planner_model: str = "gpt-4o"
    stagehand_model: str = "openai/gpt-4o"
    stagehand_agent_model: str = "anthropic/claude-sonnet-4-6"

    # API / server
    cors_origins: list[str] = ["*"]
    max_message_length: int = 10_000
    max_body_bytes: int = 100_000

    # Observability (optional)
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("browserbase_api_key")
    @classmethod
    def key_not_placeholder(cls, v: str) -> str:
        if v.startswith("bb_live_...") or v == "":
            raise ValueError("BROWSERBASE_API_KEY is not set")
        return v


settings = Settings()
