# ============================================
# services/identity/users/repository.py
# ============================================
"""
Data access layer for users. Every method performs real SQL against Postgres.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import User


class UserRepository:
    """Repository encapsulating all user persistence operations."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        """
        Args:
            session_factory: Factory producing async database sessions.
        """
        self._session_factory = session_factory

    async def create(self, user: User) -> User:
        """
        Insert a new user row.

        Args:
            user: User entity to persist.

        Returns:
            The persisted user entity.
        """
        async with self._session_factory() as session:
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def get_by_id(self, user_id: str) -> User | None:
        """
        Fetch one user by id.

        Args:
            user_id: Unique user identifier.

        Returns:
            The user entity, or None when not found.
        """
        async with self._session_factory() as session:
            return await session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """
        Fetch one user by email (case-insensitive).

        Args:
            email: Email address to look up.

        Returns:
            The user entity, or None when not found.
        """
        async with self._session_factory() as session:
            statement = select(User).where(User.email == email.lower()).limit(1)
            result = await session.execute(statement)
            return result.scalars().first()
