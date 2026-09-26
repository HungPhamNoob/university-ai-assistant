# ============================================
# services/conversation/main.py
# ============================================
"""
Entrypoint of the Conversation service (persistence + episode memory).

Run with:
    uvicorn services.conversation.main:app --reload --port 8004
"""

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env BEFORE building settings so Postgres credentials are picked up.
load_dotenv()

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .cache import RedisCacheService
from .db import build_engine, build_session_factory
from .episodic.retriever import EpisodicRetriever
from .episodic.service import EpisodicService
from .repository import ConversationRepository
from .routes.internal import router as internal_router
from .routes.public import router as conversation_router
from .service import ConversationService
from .settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan: build engine, wire repository/service,
    and initialize the optional Redis cache.

    Schema do Alembic quản lý (services/conversation/migrations/) — container
    start chạy `alembic upgrade head` trước khi serve, KHÔNG create_all ở đây.
    """
    engine = build_engine()
    session_factory = build_session_factory(engine)
    repository = ConversationRepository(session_factory)
    cache = RedisCacheService()
    # Episodic memory: SQL-only, independent per thread (no vector store).
    retriever = EpisodicRetriever(repository)
    episodic = EpisodicService(repository, retriever)
    app.state.conversation_service = ConversationService(repository, cache, episodic)
    app.state.episodic_service = episodic
    app.state.redis_cache = cache
    logger.info("Conversation service ready (db=%s)", settings.POSTGRES_DB)
    yield
    await engine.dispose()


app = FastAPI(
    title="Conversation Service",
    version="1.0.0",
    description="Conversation persistence and episode memory.",
    lifespan=lifespan,
)

# Mirrors the agent service so the frontend can call this service directly in
# local dev (direct mode) without being CORS-blocked by the browser.
# allow_credentials=False: frontend dùng Bearer token (localStorage), không cookie.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(conversation_router, prefix="/conversations", tags=["conversation"])
app.include_router(internal_router, prefix="/internal/conversations", tags=["internal"])


@app.get("/health")
async def health() -> dict:
    """
    Liveness probe for infrastructure checks.

    Returns:
        Simple status payload.
    """
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(
        "services.conversation.main:app", host="0.0.0.0", port=8004, reload=True
    )
