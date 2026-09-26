# ============================================
# services/identity/settings.py
# ============================================
"""
Configuration for the Identity service.
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

    # JWT configuration (HS256)
    JWT_SECRET_KEY: str = "your-super-secret-jwt-key-change-in-prod"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    JWT_ISSUER: str = "uet-identity"

    # API Gateway shared secret (production deployments only)
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
