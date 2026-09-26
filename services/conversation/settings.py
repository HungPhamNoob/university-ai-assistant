# ============================================
# services/conversation/settings.py
# ============================================
"""
Configuration for the Conversation service.
All values come from environment variables / the .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Postgres connection (asyncpg driver)
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "admin"
    POSTGRES_PASSWORD: str = "secret_password"
    POSTGRES_DB: str = "uet_ai_db"

    # Security tokens
    INTERNAL_API_TOKEN: str = "internal-secret-token"
    GATEWAY_SHARED_SECRET: str = "gateway-shared-secret-change-in-prod"

    # Managed Redis Cloud cache. REDIS_URL carries the credentials and endpoint
    # so local, Compose, and ECS use the same connection contract.
    REDIS_ENABLED: bool = True
    REDIS_URL: str = ""
    REDIS_TTL_SECONDS: int = 300

    # LLM provider for the episodic summarizer (rolling per-thread summaries)
    LLM_MODEL: str = "deepseek-v4-flash-0731"
    API_KEY: str = ""
    BASE_URL: str = "https://api.openai.com/v1"

    # Episodic memory (rolling per-thread episode summaries, SQL-only).
    # Independent-thread policy (reference C/D): each conversation summarizes
    # its OWN old messages; no vector index, no cross-thread retrieval.
    EPISODIC_ENABLED: bool = True
    EPISODIC_MESSAGE_THRESHOLD: int = 20
    EPISODIC_SUMMARIZATION_VERSION: int = 1
    EPISODIC_LLM_TIMEOUT_SECONDS: float = 30
    EPISODIC_MAX_PROMPT_CHARS: int = 16000

    @property
    def postgres_uri(self) -> str:
        """Build the async SQLAlchemy connection string."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
