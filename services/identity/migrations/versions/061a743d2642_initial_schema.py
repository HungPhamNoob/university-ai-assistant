"""initial schema

Revision ID: 061a743d2642
Revises:
Create Date: 2026-09-11 23:52:36.576593

Idempotent guard: DB cũ từng chạy bằng create_all có thể đã tồn tại bảng `users`
mà chưa được stamp — guard dưới đây giúp `alembic upgrade head` không vỡ
(DuplicateTable) trên DB legacy; bảng chỉ được tạo khi chưa tồn tại.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "061a743d2642"
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
    if _table_exists("users"):
        return
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)


def downgrade() -> None:
    if not _table_exists("users"):
        return
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
