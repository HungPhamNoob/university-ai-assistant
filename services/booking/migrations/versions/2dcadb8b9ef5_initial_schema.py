"""initial schema

Revision ID: 2dcadb8b9ef5
Revises:
Create Date: 2026-09-12 00:01:32.025305

Idempotent guard: DB cũ từng chạy bằng create_all có thể đã có sẵn bảng
`bookings` mà chưa được stamp — guard giúp `alembic upgrade head` không vỡ
(DuplicateTable) trên DB legacy; bảng chỉ được tạo khi chưa tồn tại.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2dcadb8b9ef5"
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
    if _table_exists("bookings"):
        return
    op.create_table(
        "bookings",
        sa.Column("booking_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("room", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=512), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("booking_id"),
    )
    op.create_index(op.f("ix_bookings_user_id"), "bookings", ["user_id"], unique=False)


def downgrade() -> None:
    if not _table_exists("bookings"):
        return
    op.drop_index(op.f("ix_bookings_user_id"), table_name="bookings")
    op.drop_table("bookings")
