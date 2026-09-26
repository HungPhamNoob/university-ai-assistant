"""Alembic environment configuration — conversation service.

Pattern theo reference/D/app/backend/db/migrations/env.py:
- load_dotenv từ .env ở repo root TRƯỚC khi import settings;
- import toàn bộ models để đăng ký Base.metadata;
- ghi đè sqlalchemy.url từ settings (không hardcode);
- compare_type + compare_server_default;
- version_table riêng vì 3 service dùng chung 1 database (uet_ai_db).

Env override: MIGRATION_DATABASE_URL (dùng khi autogenerate trên scratch DB).
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Repo root: migrations/ -> conversation/ -> services/ -> root
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")

# Import Base + toàn bộ models để đăng ký metadata (kể cả episodic memory).
from services.conversation.models import (  # noqa: F401
    Base,
    Conversation,
    EpisodeSummary,
    Message,
)
from services.conversation.settings import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# URL sync cho alembic: psycopg (v3) — asyncpg không dùng được với alembic sync run.
_database_url = os.environ.get("MIGRATION_DATABASE_URL")
if not _database_url:
    _database_url = settings.postgres_uri.replace("+asyncpg", "+psycopg")
config.set_main_option("sqlalchemy.url", _database_url)


def run_migrations_offline() -> None:
    """Chạy migration ở chế độ offline (chỉ cần URL, không cần DBAPI)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        version_table="alembic_version_conversation",
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Chạy migration ở chế độ online (engine thật)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            version_table="alembic_version_conversation",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
