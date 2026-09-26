# ============================================
# services/rag/config.py
# ============================================
"""
Configuration for the RAG service.
All environment variables are read here using pydantic-settings.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Qdrant Cloud Configuration
    QDRANT_URL: str
    QDRANT_API_KEY: str
    QDRANT_KB_COLLECTION: str = "uet_hr_docs"
    QDRANT_CACHE_COLLECTION: str = "uet_hr_cache"
    VECTOR_SIZE: int = 384  # Dimension for all-MiniLM-L6-v2
    QDRANT_TIMEOUT_SECONDS: float = 30.0
    QDRANT_STARTUP_RETRIES: int = 3

    # Model Configuration
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
    RERANKER_MODEL_NAME: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Processing Configuration
    CHUNK_SIMILARITY_THRESHOLD: float = 0.75

    # HyDE Configuration
    HYDE_ENABLED: bool = True
    HYDE_SCORE_THRESHOLD: float = (
        0.65  # Trigger HyDE if average top-k score is below this
    )
    # HyDE generates hypothetical docs with the primary chat model.
    HYDE_LLM_MODEL: str = "LLM_MODEL"

    # Primary LLM provider (explicit credentials so HyDE never relies on a
    # stale OPENAI_API_KEY from the shell environment)
    LLM_MODEL: str = "deepseek-v4-flash-0731"
    API_KEY: str = ""
    BASE_URL: str = "https://api.openai.com/v1"

    # Semantic Cache Configuration
    CACHE_TTL_SECONDS: int = 3600
    CACHE_SIMILARITY_THRESHOLD: float = 0.95

    # Uploaded document storage backend: 'local' or 's3'
    STORAGE_BACKEND: str = "local"
    STORAGE_DIR: str = "data/uploads"
    S3_BUCKET: str = ""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
