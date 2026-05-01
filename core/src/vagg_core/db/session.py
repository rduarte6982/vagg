"""Async SQLAlchemy engine for SQLite + WAL.

SPEC §2.1 mandates SQLite WAL. We enable WAL on every new connection via the
``connect`` event because SQLite stores ``journal_mode`` per database file, and
losing the pragma on a fresh DB silently regresses to rollback-journal.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    """Apply SQLite pragmas the project relies on.

    ``foreign_keys=ON`` is required by our ``ondelete=CASCADE`` constraints (SQLite
    silently ignores them otherwise). ``journal_mode=WAL`` matches SPEC §2.1.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
    finally:
        cursor.close()


def make_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Build an async engine. ``database_url`` must use ``sqlite+aiosqlite`` scheme."""
    engine = create_async_engine(
        database_url,
        echo=echo,
        future=True,
        pool_pre_ping=True,
    )
    # The event hook needs the sync Engine; AsyncEngine exposes it as ``sync_engine``.
    event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    return engine


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


# Re-exported so test fixtures can listen for the same hook explicitly if needed.
__all__ = [
    "Engine",
    "make_engine",
    "make_session_factory",
]
