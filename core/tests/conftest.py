"""Shared pytest fixtures for vagg-core.

Tests use a tempfile SQLite per session so we exercise the same dialect as prod
(SQLite + WAL pragmas) without needing Docker.

Tunnel orchestrator is replaced by an in-memory fake (FakeTunnelOrchestrator)
so endpoints can be exercised without a Docker daemon.
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
from vagg_core.db.models import Base, TunnelState, VpnType
from vagg_core.db.session import make_engine, make_session_factory
from vagg_core.main import create_app
from vagg_core.services.dns_manager import _NoopDnsManager
from vagg_core.services.tunnel_orchestrator import (
    DiscoveryReport,
    TunnelStatusReport,
)

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
        tunnels_health_enabled=False,  # disable background loop in tests
    )


# ----- Fake tunnel orchestrator -----


class FakeTunnelOrchestrator:
    """In-memory ``TunnelOrchestratorProtocol``. Tests inspect ``calls`` directly."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._connected: dict[str, str] = {}  # client_id → container_id
        self._next_container_id = 0
        self.status_overrides: dict[str, TunnelStatusReport] = {}
        self.fail_otp_for: set[str] = set()
        self.logs: dict[str, list[str]] = {}
        self.discovery_overrides: dict[str, DiscoveryReport] = {}
        self.saml_seen_overrides: dict[str, list[dict]] = {}

    async def connect(
        self,
        *,
        client_id: str,
        protocol: VpnType,
        config_text: str,
        username: str | None = None,
        password: str | None = None,
        requires_otp: bool = False,
        saml_cookie: str | None = None,
    ) -> str:
        self._next_container_id += 1
        container_id = f"fake-container-{self._next_container_id}"
        self._connected[client_id] = container_id
        self.calls.append(
            (
                "connect",
                {
                    "client_id": client_id,
                    "protocol": protocol.value,
                    "config_text_len": len(config_text),
                    "username": username,
                    "has_password": password is not None,
                },
            )
        )
        return container_id

    async def disconnect(self, client_id: str) -> None:
        self._connected.pop(client_id, None)
        self.calls.append(("disconnect", {"client_id": client_id}))

    async def status(self, client_id: str) -> TunnelStatusReport:
        self.calls.append(("status", {"client_id": client_id}))
        if client_id in self.status_overrides:
            return self.status_overrides[client_id]
        if client_id in self._connected:
            return TunnelStatusReport(
                state=TunnelState.STARTING,
                container_id=self._connected[client_id],
            )
        return TunnelStatusReport(state=TunnelState.STOPPED)

    async def send_otp(self, client_id: str, code: str) -> None:
        self.calls.append(("send_otp", {"client_id": client_id, "code_len": len(code)}))
        if client_id in self.fail_otp_for:
            from vagg_core.services.tunnel_orchestrator import TunnelOrchestrationError

            raise TunnelOrchestrationError(f"OTP rejected for {client_id}")

    async def tail_logs(self, client_id: str, *, lines: int = 100) -> list[str]:
        self.calls.append(("tail_logs", {"client_id": client_id, "lines": lines}))
        return self.logs.get(client_id, [])

    async def start_saml_portal(
        self, *, client_id: str, gateway_url: str, kind: str = "gp"
    ):
        from vagg_core.services.tunnel_orchestrator import SamlPortalSession
        from datetime import UTC, datetime, timedelta

        self.calls.append(
            (
                "start_saml_portal",
                {"client_id": client_id, "gateway_url": gateway_url, "kind": kind},
            )
        )
        return SamlPortalSession(
            client_id=client_id,
            container_id=f"fake-saml-{client_id}",
            portal_url=f"http://test.local:14500/{client_id}",
            expires_at=datetime.now(UTC) + timedelta(minutes=20),
        )

    async def poll_saml_cookie(self, client_id: str):
        from vagg_core.services.tunnel_orchestrator import SamlPollResult

        self.calls.append(("poll_saml_cookie", {"client_id": client_id}))
        return SamlPollResult(captured=False)

    async def stop_saml_portal(self, client_id: str) -> None:
        self.calls.append(("stop_saml_portal", {"client_id": client_id}))

    async def discover(self, client_id: str) -> DiscoveryReport:
        self.calls.append(("discover", {"client_id": client_id}))
        return self.discovery_overrides.get(
            client_id,
            DiscoveryReport(routes=(), dns_servers=(), search_domains=()),
        )

    async def saml_seen_cookies(self, client_id: str, *, limit: int = 200):
        self.calls.append(("saml_seen_cookies", {"client_id": client_id, "limit": limit}))
        return self.saml_seen_overrides.get(client_id, [])


@pytest.fixture
def fake_orchestrator() -> FakeTunnelOrchestrator:
    return FakeTunnelOrchestrator()


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
    fake_orchestrator: FakeTunnelOrchestrator,
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
    app.state.tunnel_orchestrator = fake_orchestrator
    app.state.dns_manager = _NoopDnsManager()
    # Portal signing key — generate a throwaway in-memory key so endpoints
    # that read app.state.portal_signing_key don't 500.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    app.state.portal_signing_key = Ed25519PrivateKey.generate()

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
