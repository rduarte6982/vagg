"""Alembic env using the project's async SQLAlchemy engine + SQLite-compatible batch mode."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from vagg_core.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _normalize_db_url(url: str) -> str:
    """Same logic as vagg_core.config — keep them in sync."""
    if url.startswith("sqlite+aiosqlite://"):
        return url
    if url.startswith("sqlite://"):
        return "sqlite+aiosqlite://" + url.removeprefix("sqlite://")
    return url


def _resolve_url() -> str:
    """Migration only needs the DB URL — read it directly from env to avoid
    pulling in the full Settings (which requires admin_password_hash and
    jwt_secret that are unrelated to migrations)."""
    url = os.environ.get("VAGG_CORE_DATABASE_URL", "").strip()
    if url:
        return _normalize_db_url(url)
    # Fall back to alembic.ini's `sqlalchemy.url` if someone runs migrations
    # outside the container. Last-resort default makes `alembic --help` work.
    fallback = config.get_main_option("sqlalchemy.url")
    if fallback:
        return _normalize_db_url(fallback)
    raise RuntimeError(
        "VAGG_CORE_DATABASE_URL is required for migrations (set in env or in alembic.ini)"
    )


def run_migrations_offline() -> None:
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=True,  # SQLite ALTER TABLE compatibility
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _resolve_url()
    connectable = async_engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
