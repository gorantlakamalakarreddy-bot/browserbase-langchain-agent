from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Browserbase
    browserbase_api_key: str
    browserbase_project_id: str

    # LLM keys
    openai_api_key: str
    anthropic_api_key: str = ""

    # Model overrides
    planner_model: str = "gpt-4o"
    stagehand_model: str = "openai/gpt-4o"
    stagehand_agent_model: str = "anthropic/claude-sonnet-4-6"

    # Observability (optional)
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
