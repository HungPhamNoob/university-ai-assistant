# ============================================
# services/booking/models.py
# ============================================
"""
SQLAlchemy ORM models for the Booking service.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base shared by all models of this service."""


def _new_booking_id() -> str:
    """Generate a short, human-friendly booking id (e.g. bk-1a2b3c4d)."""
    return f"bk-{uuid.uuid4().hex[:8]}"


def utc_now() -> datetime:
    """Return the current UTC time as a naive datetime (Postgres TIMESTAMP)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Booking(Base):
    """A single meeting room booking persisted in Postgres."""

    __tablename__ = "bookings"

    booking_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_booking_id
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    room: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(512), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="confirmed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
