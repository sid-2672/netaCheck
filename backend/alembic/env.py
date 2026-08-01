"""
Alembic environment configuration.

Key design decisions:
- Uses async engine (asyncpg) consistent with the application runtime.
- Loads `DATABASE_URL` from application settings — no secrets in alembic.ini.
- `include_schemas=True` for future multi-schema support.
- `compare_type=True` ensures column type changes are detected by autogenerate.
- All models must be imported here (via `netacheck.models`) so that
  Base.metadata is fully populated for autogenerate.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import TYPE_CHECKING

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Phase 2: All models imported so autogenerate discovers all tables
import netacheck.models  # noqa: F401
from alembic import context

# ---------------------------------------------------------------------------
# Import application settings + all models
# IMPORTANT: Every model module must be imported here.
# Alembic autogenerate discovers tables via Base.metadata only if the model
# classes have been imported (which registers them with the mapper).
# ---------------------------------------------------------------------------
from netacheck.core.config import settings
from netacheck.core.database import Base

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

# ---------------------------------------------------------------------------
# Alembic Config object — access to values within the .ini file
# ---------------------------------------------------------------------------
config = context.config

# Inject database URL from settings (overrides the blank value in alembic.ini)
config.set_main_option("sqlalchemy.url", str(settings.database_url))

# Setup Python logging from the config file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    Generates SQL without a live database connection.
    Useful for previewing migration SQL or generating scripts for DBA review.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations against a live database using asyncpg."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with an active database connection."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
