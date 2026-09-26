# ============================================
# services/conversation/db.py
# ============================================
"""
Async SQLAlchemy engine and session factory for the Conversation service.
The driver is asyncpg (see settings.postgres_uri).
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .settings import settings


def build_engine() -> AsyncEngine:
    """
    Create the async engine used by the whole service.

    Returns:
        A configured AsyncEngine pointing at Postgres.
    """
    return create_async_engine(settings.postgres_uri, echo=False, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """
    Create the async session factory bound to the given engine.

    Args:
        engine: Async engine that sessions will use.

    Returns:
        An async_sessionmaker producing AsyncSession instances.
    """
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
