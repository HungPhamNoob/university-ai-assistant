"""episodic memory — episode_summaries

Bảng canonical của episodic memory (SQL-only, independent per thread — bản
Qdrant mirror cũ đã bị gỡ theo policy reference C/D; cột index_error giữ lại
để không cần migration mới).
Trên uet_ai_db (đã stamp 0001): `alembic upgrade head` áp revision này.

Idempotent guard: DB nào từng được create_all với model EpisodeSummary thì
bảng đã tồn tại — guard giúp `upgrade head` không vỡ (to_regclass).

Revision ID: 0002_episodic
Revises: 0001_initial
Create Date: 2026-09-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_episodic"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(name: str) -> bool:
    """True khi bảng đã tồn tại trong schema public (to_regclass)."""
    row = (
        op.get_bind()
        .execute(sa.text("SELECT to_regclass(:t)"), {"t": f"public.{name}"})
        .scalar()
    )
    return row is not None


def upgrade() -> None:
    if _table_exists("episode_summaries"):
        return
    op.create_table(
        "episode_summaries",
        sa.Column("episodic_memory_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("actions", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.JSON(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("user_corrections", sa.JSON(), nullable=False),
        sa.Column("lessons_learned", sa.JSON(), nullable=False),
        sa.Column("open_loops", sa.JSON(), nullable=False),
        sa.Column("agents_involved", sa.JSON(), nullable=False),
        sa.Column("total_message_count", sa.Integer(), nullable=False),
        sa.Column("last_summarized_position", sa.Integer(), nullable=False),
        sa.Column("last_summarized_message_count", sa.Integer(), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("summarization_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("summarized_at", sa.DateTime(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.Column("summarization_error", sa.Text(), nullable=False),
        sa.Column("index_error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("episodic_memory_id"),
        sa.UniqueConstraint(
            "user_id", "thread_id", name="uq_episode_summary_user_thread"
        ),
    )
    op.create_index(
        op.f("ix_episode_summaries_user_id"),
        "episode_summaries",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    if not _table_exists("episode_summaries"):
        return
    op.drop_index(op.f("ix_episode_summaries_user_id"), table_name="episode_summaries")
    op.drop_table("episode_summaries")
