"""Tests for the TunnelHealthWorker auto-discovery hook."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from vagg_core.db.models import Client, NatMapping, TunnelState, TunnelStatus, VpnType
from vagg_core.services.tunnel_orchestrator import (
    DiscoveredRoute,
    DiscoveryReport,
    TunnelStatusReport,
)
from vagg_core.workers.tunnel_health import (
    TunnelHealthWorker,
    _is_valid_dns,
    _sanitize_report,
)

from tests.conftest import FakeTunnelOrchestrator

pytestmark = pytest.mark.asyncio


async def _seed_client(
    session_factory: async_sessionmaker[Any],
    *,
    client_id: str = "longping",
    auto_enabled: bool = True,
    initial_state: TunnelState = TunnelState.STARTING,
) -> None:
    async with session_factory() as session:
        c = Client(
            id=client_id,
            name=client_id.title(),
            vpn_type=VpnType.OPENFORTIVPN,
            virtual_cidr="10.200.0.0/16",
            real_cidr="0.0.0.0/0",
            auto_discovery_enabled=auto_enabled,
        )
        c.tunnel_status = TunnelStatus(client_id=client_id, state=initial_state)
        session.add(c)
        await session.commit()


class TestDnsSanitization:
    @pytest.mark.parametrize(
        ("server", "valid"),
        [
            ("10.0.50.10", True),
            ("8.8.8.8", True),
            ("2001:4860:4860::8888", True),
            ("127.0.0.53", False),
            ("127.0.0.1", False),
            ("0.0.0.0", False),
            ("169.254.169.254", False),
            ("fe80::1", False),
            ("::1", False),
        ],
    )
    def test_is_valid_dns(self, server: str, valid: bool) -> None:
        assert _is_valid_dns(server) is valid

    def test_sanitize_report_filters_dns_keeps_routes(self) -> None:
        report = DiscoveryReport(
            routes=(DiscoveredRoute(cidr="10.0.0.0/8", dev="tun0"),),
            dns_servers=("127.0.0.53", "10.0.50.10"),
            search_domains=("corp.example.com",),
        )
        out = _sanitize_report(report)
        assert out.routes == report.routes
        assert out.dns_servers == ("10.0.50.10",)
        assert out.search_domains == report.search_domains


async def _read_client(session_factory: async_sessionmaker[Any], client_id: str) -> Client:
    async with session_factory() as session:
        client = await session.get(Client, client_id)
        assert client is not None
        # touch nat_mappings to trigger lazy load
        _ = list(client.nat_mappings)
        return client


class TestAutoDiscoveryHook:
    async def test_runs_discovery_on_starting_to_up_transition(
        self,
        session_factory: async_sessionmaker[Any],
        fake_orchestrator: FakeTunnelOrchestrator,
    ) -> None:
        await _seed_client(session_factory)
        fake_orchestrator.status_overrides["longping"] = TunnelStatusReport(
            state=TunnelState.UP, container_id="cid-1", controller_state="up"
        )
        fake_orchestrator.discovery_overrides["longping"] = DiscoveryReport(
            routes=(
                DiscoveredRoute(cidr="10.80.0.0/16", dev="ppp0"),
                DiscoveredRoute(cidr="10.123.55.0/24", dev="ppp0"),
            ),
            dns_servers=("10.0.50.10", "10.0.50.11"),
            search_domains=("lpht.com.br",),
        )

        worker = TunnelHealthWorker(
            session_factory=session_factory, orchestrator=fake_orchestrator
        )
        await worker.tick()

        # Discovery foi chamada
        discover_calls = [c for c in fake_orchestrator.calls if c[0] == "discover"]
        assert len(discover_calls) == 1
        assert discover_calls[0][1]["client_id"] == "longping"

        # Estado persistido + nat_mappings populados
        client = await _read_client(session_factory, "longping")
        cidrs = sorted(m.real_cidr for m in client.nat_mappings)
        assert cidrs == ["10.123.55.0/24", "10.80.0.0/16"]
        assert all(m.virtual_cidr == m.real_cidr for m in client.nat_mappings)
        assert client.dns_server == "10.0.50.10"
        assert client.auto_discovered_at is not None

    async def test_skips_when_auto_discovery_disabled(
        self,
        session_factory: async_sessionmaker[Any],
        fake_orchestrator: FakeTunnelOrchestrator,
    ) -> None:
        await _seed_client(session_factory, auto_enabled=False)
        fake_orchestrator.status_overrides["longping"] = TunnelStatusReport(
            state=TunnelState.UP, container_id="cid-1"
        )
        fake_orchestrator.discovery_overrides["longping"] = DiscoveryReport(
            routes=(DiscoveredRoute(cidr="10.80.0.0/16", dev="ppp0"),),
            dns_servers=("10.0.50.10",),
            search_domains=(),
        )

        worker = TunnelHealthWorker(
            session_factory=session_factory, orchestrator=fake_orchestrator
        )
        await worker.tick()

        assert not [c for c in fake_orchestrator.calls if c[0] == "discover"]
        client = await _read_client(session_factory, "longping")
        assert client.nat_mappings == []
        assert client.auto_discovered_at is None

    async def test_replaces_old_mappings(
        self,
        session_factory: async_sessionmaker[Any],
        fake_orchestrator: FakeTunnelOrchestrator,
    ) -> None:
        await _seed_client(session_factory)
        # Pré-popula com mappings velhos
        async with session_factory() as session:
            c = await session.get(Client, "longping")
            assert c is not None
            session.add(
                NatMapping(client_id="longping", virtual_cidr="9.9.9.0/24", real_cidr="9.9.9.0/24")
            )
            await session.commit()

        fake_orchestrator.status_overrides["longping"] = TunnelStatusReport(state=TunnelState.UP)
        fake_orchestrator.discovery_overrides["longping"] = DiscoveryReport(
            routes=(DiscoveredRoute(cidr="10.80.0.0/16", dev="ppp0"),),
            dns_servers=(),
            search_domains=(),
        )

        worker = TunnelHealthWorker(
            session_factory=session_factory, orchestrator=fake_orchestrator
        )
        await worker.tick()

        client = await _read_client(session_factory, "longping")
        cidrs = [m.real_cidr for m in client.nat_mappings]
        assert cidrs == ["10.80.0.0/16"]  # 9.9.9.0/24 sumiu

    async def test_empty_report_does_not_overwrite(
        self,
        session_factory: async_sessionmaker[Any],
        fake_orchestrator: FakeTunnelOrchestrator,
    ) -> None:
        await _seed_client(session_factory)
        async with session_factory() as session:
            session.add(
                NatMapping(client_id="longping", virtual_cidr="9.9.9.0/24", real_cidr="9.9.9.0/24")
            )
            await session.commit()

        fake_orchestrator.status_overrides["longping"] = TunnelStatusReport(state=TunnelState.UP)
        # Sem rotas, sem DNS — nada pra aplicar.
        fake_orchestrator.discovery_overrides["longping"] = DiscoveryReport(
            routes=(), dns_servers=(), search_domains=()
        )

        worker = TunnelHealthWorker(
            session_factory=session_factory, orchestrator=fake_orchestrator
        )
        await worker.tick()

        client = await _read_client(session_factory, "longping")
        cidrs = [m.real_cidr for m in client.nat_mappings]
        assert cidrs == ["9.9.9.0/24"]
        assert client.auto_discovered_at is None

    async def test_does_not_run_when_already_up(
        self,
        session_factory: async_sessionmaker[Any],
        fake_orchestrator: FakeTunnelOrchestrator,
    ) -> None:
        # Cliente já tinha sido descoberto antes.
        await _seed_client(session_factory, initial_state=TunnelState.UP)
        from datetime import UTC, datetime
        async with session_factory() as session:
            c = await session.get(Client, "longping")
            assert c is not None
            c.auto_discovered_at = datetime.now(UTC)
            await session.commit()

        fake_orchestrator.status_overrides["longping"] = TunnelStatusReport(state=TunnelState.UP)
        worker = TunnelHealthWorker(
            session_factory=session_factory, orchestrator=fake_orchestrator
        )
        await worker.tick()

        assert not [c for c in fake_orchestrator.calls if c[0] == "discover"]

    async def test_first_time_up_runs_even_if_state_was_up_before(
        self,
        session_factory: async_sessionmaker[Any],
        fake_orchestrator: FakeTunnelOrchestrator,
    ) -> None:
        # Cliente que já estava UP mas NUNCA foi descoberto (caso da
        # migração — auto_discovered_at é NULL).
        await _seed_client(session_factory, initial_state=TunnelState.UP)
        fake_orchestrator.status_overrides["longping"] = TunnelStatusReport(state=TunnelState.UP)
        fake_orchestrator.discovery_overrides["longping"] = DiscoveryReport(
            routes=(DiscoveredRoute(cidr="10.80.0.0/16", dev="ppp0"),),
            dns_servers=(),
            search_domains=(),
        )

        worker = TunnelHealthWorker(
            session_factory=session_factory, orchestrator=fake_orchestrator
        )
        await worker.tick()

        assert len([c for c in fake_orchestrator.calls if c[0] == "discover"]) == 1
        client = await _read_client(session_factory, "longping")
        assert [m.real_cidr for m in client.nat_mappings] == ["10.80.0.0/16"]

    async def test_skips_when_routes_empty_even_with_dns(
        self,
        session_factory: async_sessionmaker[Any],
        fake_orchestrator: FakeTunnelOrchestrator,
    ) -> None:
        """Regressão crítica: tunnel em auth-fail loop reporta UP (PID vivo)
        mas sem rotas reais. ``/etc/resolv.conf`` do container retorna o DNS
        do host (127.0.0.53 / systemd-resolved). Sem essa guarda, mappings
        manuais são destruídos e dns_server fica apontando pra localhost.
        """
        await _seed_client(session_factory)
        async with session_factory() as session:
            session.add(
                NatMapping(client_id="longping", virtual_cidr="9.9.9.0/24", real_cidr="9.9.9.0/24")
            )
            await session.commit()

        fake_orchestrator.status_overrides["longping"] = TunnelStatusReport(state=TunnelState.UP)
        fake_orchestrator.discovery_overrides["longping"] = DiscoveryReport(
            routes=(),
            dns_servers=("127.0.0.53",),  # DNS do host, não do gateway
            search_domains=(),
        )

        worker = TunnelHealthWorker(
            session_factory=session_factory, orchestrator=fake_orchestrator
        )
        await worker.tick()

        client = await _read_client(session_factory, "longping")
        # Mapping manual preservado, dns_server NÃO escrito, timestamp NULL.
        assert [m.real_cidr for m in client.nat_mappings] == ["9.9.9.0/24"]
        assert client.dns_server is None
        assert client.auto_discovered_at is None

    async def test_filters_loopback_dns_from_report(
        self,
        session_factory: async_sessionmaker[Any],
        fake_orchestrator: FakeTunnelOrchestrator,
    ) -> None:
        """Mesmo com routes legítimas, DNS 127.x / link-local é descartado
        antes de virar dns_server."""
        await _seed_client(session_factory)
        fake_orchestrator.status_overrides["longping"] = TunnelStatusReport(state=TunnelState.UP)
        fake_orchestrator.discovery_overrides["longping"] = DiscoveryReport(
            routes=(DiscoveredRoute(cidr="10.80.0.0/16", dev="ppp0"),),
            dns_servers=("127.0.0.53", "10.0.50.10", "169.254.169.254"),
            search_domains=(),
        )

        worker = TunnelHealthWorker(
            session_factory=session_factory, orchestrator=fake_orchestrator
        )
        await worker.tick()

        client = await _read_client(session_factory, "longping")
        # 10.0.50.10 é o primeiro válido — 127.x e 169.254.x foram filtrados.
        assert client.dns_server == "10.0.50.10"
