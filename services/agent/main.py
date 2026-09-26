# ============================================
# services/agent/main.py
# ============================================
"""
Main FastAPI application for the Agent service.

Initializes the chat LLM (with automatic backup-key fallback) and the
Postgres checkpointer for durable thread persistence. LangSmith tracing is
activated purely through environment variables loaded from .env.
"""

import logging

from dotenv import load_dotenv

# Load .env BEFORE any langchain/langsmith import so that LANGSMITH_* and
# provider variables are visible in os.environ for the tracing client.
load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from .api import router
from .config import settings
from .graph import build_primary_graph
from .llm import build_chat_llm

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared resources on startup and release them on shutdown."""
    logger.info("Initializing LLM (primary provider first, backup on 401)...")
    llm = build_chat_llm()

    logger.info("Connecting to Postgres for Checkpointer...")
    try:
        # langgraph-checkpoint-postgres 3.x builds the saver from an AsyncConnectionPool
        conninfo = settings.POSTGRES_URI.replace("+psycopg", "")
        pool = AsyncConnectionPool(
            conninfo=conninfo, kwargs={"autocommit": True}, open=False
        )
        await pool.open()
        checkpointer = AsyncPostgresSaver(conn=pool)
        await checkpointer.setup()  # Creates checkpoint tables if missing
        app.state.db_pool = pool
    except Exception as error:  # noqa: BLE001 - Postgres down falls back to in-memory checkpointer
        logger.warning(
            "Postgres unavailable (%s), falling back to MemorySaver for local dev.",
            error,
        )
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()

    app.state.graph = build_primary_graph(llm, checkpointer)
    logger.info("Agent service started.")
    yield
    if getattr(app.state, "db_pool", None) is not None:
        await app.state.db_pool.close()
    logger.info("Shutting down Agent service.")


app = FastAPI(title="Agent Service", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api/chat")


@app.get("/health")
async def health() -> dict:
    """
    Liveness probe for infrastructure checks.

    Returns:
        Simple status payload.
    """
    return {"status": "ok"}
