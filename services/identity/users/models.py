# ============================================
# services/identity/users/models.py
# ============================================
"""
SQLAlchemy ORM models of the users feature.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base shared by all models of this service."""


def _new_user_id() -> str:
    """Generate a unique user id (uuid4 hex)."""
    return uuid.uuid4().hex


def utc_now() -> datetime:
    """Return the current UTC time as a naive datetime (Postgres TIMESTAMP)."""
    return datetime.now(UTC).replace(tzinfo=None)


class User(Base):
    """A registered platform user persisted in Postgres."""

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_new_user_id
    )
    email: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
