# ============================================
# services/booking/settings.py
# ============================================
"""
Configuration for the Booking domain service.
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

    # Shared secret for service-to-service calls (agent -> booking)
    INTERNAL_API_TOKEN: str = "internal-secret-token"

    # API Gateway shared secret (production: requests arrive via Kong)
    GATEWAY_SHARED_SECRET: str = "gateway-shared-secret-change-in-prod"

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
