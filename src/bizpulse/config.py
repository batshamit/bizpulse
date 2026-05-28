"""Settings, loaded from environment + .env via pydantic-settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    env: str = Field(default="dev", alias="BIZPULSE_ENV")
    log_level: str = Field(default="INFO", alias="BIZPULSE_LOG_LEVEL")
    default_tenant: str = Field(default="demo", alias="BIZPULSE_DEFAULT_TENANT")

    postgres_host: str = Field(default="127.0.0.1", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="bizpulse", alias="POSTGRES_DB")
    postgres_user: str = Field(default="bizpulse", alias="POSTGRES_USER")
    postgres_password: str = Field(default="", alias="POSTGRES_PASSWORD")

    qdrant_url: str = Field(default="http://127.0.0.1:6333", alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")

    llm_base_url: str = Field(default="http://127.0.0.1:8800/v1", alias="LLM_BASE_URL")
    llm_model: str = Field(default="Qwen/Qwen2.5-14B-Instruct", alias="LLM_MODEL")
    llm_api_key: str = Field(default="EMPTY", alias="LLM_API_KEY")

    embed_base_url: str = Field(default="http://127.0.0.1:8081", alias="EMBED_BASE_URL")
    embed_model: str = Field(default="BAAI/bge-large-en-v1.5", alias="EMBED_MODEL")
    embed_dim: int = Field(default=1024, alias="EMBED_DIM")

    rerank_base_url: str = Field(default="http://127.0.0.1:8082", alias="RERANK_BASE_URL")
    rerank_model: str = Field(default="BAAI/bge-reranker-v2-m3", alias="RERANK_MODEL")

    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    brave_search_api_key: str | None = Field(default=None, alias="BRAVE_SEARCH_API_KEY")
    google_api_key: str | None = Field(default=None, alias="GOOGLE_API_KEY")
    google_cse_id: str | None = Field(default=None, alias="GOOGLE_CSE_ID")

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
