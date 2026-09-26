"""initial schema — conversations + conversation_messages

Bảng đã tồn tại trên uet_ai_db từ trước (create_all) nên DB thật được
`alembic stamp 0001_initial`; revision này là nguồn sự thật cho DB mới
(scratch/prod/RDS): `alembic upgrade head` tạo đủ schema.

Idempotent guard: DB legacy chưa stamp vẫn chạy `upgrade head` an toàn —
bảng chỉ được tạo khi chưa tồn tại (to_regclass).

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
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
    if not _table_exists("conversations"):
        op.create_table(
            "conversations",
            sa.Column("conversation_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=128), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("conversation_id"),
        )
        op.create_index(
            op.f("ix_conversations_user_id"), "conversations", ["user_id"], unique=False
        )
    if not _table_exists("conversation_messages"):
        op.create_table(
            "conversation_messages",
            sa.Column("message_id", sa.String(length=64), nullable=False),
            sa.Column("conversation_id", sa.String(length=64), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["conversation_id"],
                ["conversations.conversation_id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("message_id"),
        )
        op.create_index(
            op.f("ix_conversation_messages_conversation_id"),
            "conversation_messages",
            ["conversation_id"],
            unique=False,
        )


def downgrade() -> None:
    if _table_exists("conversation_messages"):
        op.drop_index(
            op.f("ix_conversation_messages_conversation_id"),
            table_name="conversation_messages",
        )
        op.drop_table("conversation_messages")
    if _table_exists("conversations"):
        op.drop_index(op.f("ix_conversations_user_id"), table_name="conversations")
        op.drop_table("conversations")
