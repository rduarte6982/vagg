"""Shared pytest fixtures for vagg-core.

Tests use a tempfile SQLite per session so we exercise the same dialect as prod
(SQLite + WAL pragmas) without needing Docker.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from vagg_core.config import Settings
from vagg_core.core.security import JWTSigner, hash_password
from vagg_core.db.models import Base
from vagg_core.db.session import make_engine, make_session_factory
from vagg_core.main import create_app

ADMIN_EMAIL = "admin@test.example"
ADMIN_PASSWORD = "test-password-1234"
JWT_SECRET = "test-jwt-secret-do-not-use-in-prod"


# ----- Settings -----


@pytest.fixture(scope="session")
def admin_password_hash() -> str:
    return hash_password(ADMIN_PASSWORD)


@pytest.fixture(scope="session")
def settings(admin_password_hash: str, database_path: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        environment="test",
        log_level="WARNING",
        database_url=f"sqlite+aiosqlite:///{database_path}",  # type: ignore[arg-type]
        admin_email=ADMIN_EMAIL,
        admin_password_hash=admin_password_hash,  # type: ignore[arg-type]
        jwt_secret=JWT_SECRET,  # type: ignore[arg-type]
        jwt_access_ttl_seconds=600,
        jwt_refresh_ttl_seconds=3600,
        jwt_issuer="vagg-core-test",
    )


# ----- Database (tempfile sqlite) -----


@pytest.fixture(scope="session")
def database_path() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="vagg-core-test-") as td:
        yield Path(td) / "core.db"


@pytest_asyncio.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = make_engine(settings.database_url.get_secret_value())
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[Any]:
    return make_session_factory(engine)


# ----- App + HTTP client -----


@pytest_asyncio.fixture
async def app_and_client(
    settings: Settings,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[Any],
) -> AsyncIterator[tuple[Any, AsyncClient]]:
    app = create_app(settings)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.jwt_signer = JWTSigner(
        secret=settings.jwt_secret.get_secret_value(),
        issuer=settings.jwt_issuer,
        access_ttl_seconds=settings.jwt_access_ttl_seconds,
        refresh_ttl_seconds=settings.jwt_refresh_ttl_seconds,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield app, client


@pytest_asyncio.fixture
async def auth_client(app_and_client: tuple[Any, AsyncClient]) -> AsyncClient:
    """An AsyncClient pre-authenticated with the bootstrap admin's access token."""
    _, client = app_and_client
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client
