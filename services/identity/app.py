# ============================================
# services/identity/app.py
# ============================================
"""
FastAPI application factory of the Identity service (JWT + users).

Run with:
    uvicorn services.identity.app:app --reload --port 8001
"""

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env BEFORE building settings so Postgres/JWT credentials are picked up.
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import build_engine, build_session_factory
from .settings import settings
from .users.repository import UserRepository
from .users.routes import router as auth_router
from .users.service import AuthService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan: build the database engine and wire the
    repository + service into app.state.

    Schema do Alembic quản lý (services/identity/migrations/) — container
    start chạy `alembic upgrade head` trước khi serve, KHÔNG create_all ở đây.
    """
    engine = build_engine()
    session_factory = build_session_factory(engine)
    repository = UserRepository(session_factory)
    app.state.auth_service = AuthService(repository)
    logger.info("Identity service ready (db=%s)", settings.POSTGRES_DB)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    """
    Build the FastAPI application with routers and lifespan wired in.

    Returns:
        A fully configured FastAPI instance.
    """
    application = FastAPI(
        title="Identity Service",
        version="1.0.0",
        description="User registration, login and JWT issuing.",
        lifespan=lifespan,
    )
    # CORS mirror agent service (frontend direct-mode gọi thẳng :8001 từ browser).
    # allow_credentials=False: frontend dùng Bearer token (localStorage), không
    # dùng cookie — wildcard origin + credentials là combo mâu thuẫn/không cần.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(auth_router, prefix="/auth", tags=["identity"])

    @application.get("/health")
    async def health() -> dict:
        """
        Liveness probe for infrastructure checks.

        Returns:
            Simple status payload.
        """
        return {"status": "ok"}

    return application


# Module-level instance so `uvicorn services.identity.app:app` works directly.
app = create_app()
