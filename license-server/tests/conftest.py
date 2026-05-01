"""Shared pytest fixtures.

Integration tests need Postgres. We resolve the DB URL in this order:
  1. ``VAGG_LICENSE_TEST_DATABASE_URL`` env var (set by CI / dev with `make test`).
  2. testcontainers-postgres on demand (local dev with Docker).
If neither works, integration tests are skipped (unit tests still run anywhere).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from vagg_license.config import Settings
from vagg_license.db.models import Base, Plan
from vagg_license.main import create_app
from vagg_license.services.jwt_signer import JWTSigner
from vagg_license.services.stripe_client import StripeClient


# ----- Ed25519 keypair (ephemeral per test session) -----


@pytest.fixture(scope="session")
def ed25519_keypair_pem() -> tuple[str, str]:
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


@pytest.fixture
def jwt_signer(ed25519_keypair_pem: tuple[str, str]) -> JWTSigner:
    private_pem, public_pem = ed25519_keypair_pem
    return JWTSigner(
        private_key_pem=private_pem,
        public_key_pem=public_pem,
        issuer="vagg-license-server-test",
        ttl_seconds=600,
    )


# ----- Settings -----


@pytest.fixture
def settings(ed25519_keypair_pem: tuple[str, str], database_url: str) -> Settings:
    private_pem, public_pem = ed25519_keypair_pem
    return Settings(  # type: ignore[call-arg]
        environment="test",
        log_level="WARNING",
        database_url=database_url,  # type: ignore[arg-type]
        jwt_private_key_pem=private_pem,  # type: ignore[arg-type]
        jwt_public_key_pem=public_pem,
        jwt_issuer="vagg-license-server-test",
        jwt_ttl_seconds=600,
        stripe_api_key="sk_test_dummy",  # type: ignore[arg-type]
        stripe_webhook_secret="whsec_test_dummy",  # type: ignore[arg-type]
        stripe_price_id_starter="price_starter_test",
        stripe_price_id_professional="price_professional_test",
        stripe_price_id_enterprise="price_enterprise_test",
    )


# ----- Database (testcontainers OR env var) -----


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    env_url = os.environ.get("VAGG_LICENSE_TEST_DATABASE_URL")
    if env_url:
        yield _ensure_asyncpg_scheme(env_url)
        return

    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip(
            "Postgres não disponível: defina VAGG_LICENSE_TEST_DATABASE_URL ou instale Docker"
        )

    try:
        with PostgresContainer("postgres:16-alpine") as pg:
            yield _ensure_asyncpg_scheme(pg.get_connection_url())
    except Exception as exc:  # noqa: BLE001 — surface the whole reason in skip message
        pytest.skip(f"Não consegui subir Postgres via testcontainers: {exc}")


def _ensure_asyncpg_scheme(url: str) -> str:
    """Normalize ``postgresql://`` and ``postgresql+psycopg2://`` to ``postgresql+asyncpg://``."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql+psycopg2://")
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    return url


@pytest_asyncio.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[Any]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


# ----- App + HTTP client -----


@pytest_asyncio.fixture
async def app_and_client(
    settings: Settings,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[Any],
    jwt_signer: JWTSigner,
) -> AsyncIterator[tuple[Any, AsyncClient]]:
    """Build the FastAPI app with state pre-wired (no real lifespan)."""
    app = create_app(settings)

    # Manually populate state — we skip the engine lifespan to reuse the test fixture engine.
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.jwt_signer = jwt_signer
    app.state.stripe_client = StripeClient(
        api_key="sk_test_dummy",
        webhook_secret=settings.stripe_webhook_secret.get_secret_value(),
        webhook_tolerance_seconds=settings.stripe_webhook_tolerance_seconds,
        plan_by_price_id={
            settings.stripe_price_id_starter: Plan.STARTER,
            settings.stripe_price_id_professional: Plan.PROFESSIONAL,
            settings.stripe_price_id_enterprise: Plan.ENTERPRISE,
        },
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield app, client
