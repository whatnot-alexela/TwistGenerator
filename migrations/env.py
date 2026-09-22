"""Alembic environment.

The URL is read from DATABASE_URL rather than alembic.ini, so a migration can
only ever run against the database the bot itself is configured for.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.models import Base  # noqa: E402

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit("DATABASE_URL is not set; alembic has no database to migrate")
config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy."
    )
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
