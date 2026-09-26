# ============================================
# services/conversation/models.py
# ============================================
"""
SQLAlchemy ORM models for the Conversation service.

Conversation has a one-to-many relation to Message with cascade delete-orphan,
so removing a conversation also removes all of its messages.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base shared by all models of this service."""


def _new_id() -> str:
    """Generate a unique id (uuid4 hex)."""
    return uuid.uuid4().hex


def utc_now() -> datetime:
    """Return the current UTC time as a naive datetime (Postgres TIMESTAMP)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Conversation(Base):
    """One chat conversation owned by a user."""

    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_new_id
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(
        String(255), nullable=False, default="New conversation"
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    """One chat message inside a conversation."""

    __tablename__ = "conversation_messages"

    message_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_new_id
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class EpisodeSummary(Base):
    """Rolling episodic summary of one conversation thread (canonical SQL row).

    One row per (user_id, thread_id) — thread_id equals the conversation_id the
    agent syncs against. Memory is INDEPENDENT PER THREAD: a thread's episode
    is only injected back into its own thread (no vector mirror, no
    cross-thread retrieval). ``index_error`` is a legacy column kept for
    migration compatibility — nothing writes to it anymore.
    """

    __tablename__ = "episode_summaries"
    __table_args__ = (
        UniqueConstraint("user_id", "thread_id", name="uq_episode_summary_user_thread"),
    )

    episodic_memory_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_new_id
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)

    title: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    context: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    outcome: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    user_corrections: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    lessons_learned: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    open_loops: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    agents_involved: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    total_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_summarized_position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=-1
    )
    last_summarized_message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    summarization_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    summarized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    summarization_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    index_error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
