# ============================================
# services/agent/config.py
# ============================================
"""
Configuration for the Agent service.

All values are loaded from environment variables / the .env file.
The backup provider (API_KEY_2) is only used when the primary provider
keeps rejecting requests with HTTP 401, or its quota is exhausted with an
HTTP 403 quota error (see services/agent/llm.py).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings for the Agent service."""

    # Primary LLM provider (OpenAI-compatible gateway)
    LLM_MODEL: str = "deepseek-v4-flash-0731"
    API_KEY: str = ""
    BASE_URL: str = "https://api.openai.com/v1"

    # Backup LLM provider, used after persistent 401 errors or an exhausted
    # quota (403) on the primary
    API_KEY_2: str = ""
    API_KEY_2_BASE_URL: str = "https://api.openai.com/v1"
    API_KEY_2_MODEL: str = "gpt-5-nano"

    # Internal services
    RAG_SERVICE_URL: str = "http://localhost:8002"
    BOOKING_SERVICE_URL: str = "http://localhost:8003"
    CONVERSATION_SERVICE_URL: str = "http://localhost:8004"
    INTERNAL_API_TOKEN: str = "internal-secret-token"
    # RAG search có thể kích hoạt HyDE (gọi LLM, timeout 60s x max_retries 1)
    # nên worst-case hợp lệ ~120s+. Timeout 30s sẽ cắt oan các ca HyDE chậm.
    RAG_TIMEOUT_SECONDS: float = 150.0

    # API Gateway (production). When AGENT_REQUIRE_GATEWAY is true, every chat
    # request must carry X-Gateway-Token == GATEWAY_SHARED_SECRET plus the
    # X-User-Id / X-User-Email headers injected by Kong (see services/agent/auth.py).
    AGENT_REQUIRE_GATEWAY: bool = False
    GATEWAY_SHARED_SECRET: str = "gateway-shared-secret-change-in-prod"

    # Postgres (LangGraph checkpointer)
    POSTGRES_URI: str = (
        "postgresql+psycopg://admin:secret_password@localhost:5432/uet_ai_db"
    )

    # External tools
    TAVILY_API_KEY: str = ""
    # TavilySearchResults gọi aiohttp KHÔNG kèm timeout (mặc định aiohttp = 5
    # phút). Một cú search treo sẽ giữ SSE stream im lặng đủ lâu để ALB/Kong
    # (idle 60s) cắt kết nối. Bounded wait giúp tool fail-fast và trả message
    # để LLM lịch sự báo user thay vì giết cả stream.
    WEB_SEARCH_TIMEOUT_SECONDS: float = 20.0

    # Context engineering — per-component token budgets (hint.md "Ghi chú A").
    # history is compared after compaction; retrieved docs / tool outputs live
    # inside the ReAct history's ToolMessages and are capped separately.
    TOKEN_BUDGET_SYSTEM: int = 1500
    TOKEN_BUDGET_HISTORY: int = 3000
    TOKEN_BUDGET_DOCS: int = 20000
    TOKEN_BUDGET_TOOL_OUTPUTS: int = 5000
    TOKEN_BUDGET_RESERVE: int = 4096
    CONTEXT_LIMIT: int = 32768

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
