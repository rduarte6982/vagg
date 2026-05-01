"""Integration tests for NetworkManager (DB → plan → applier)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from vagg_core.db.models import Client, NatMapping, TunnelState, TunnelStatus, VpnType
from vagg_core.services.network_applier import CommandResult, NetworkApplier
from vagg_core.services.network_manager import NetworkManager
from vagg_core.services.network_plan import NetworkPlan

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str | None]] = []

    async def __call__(self, argv: list[str], *, stdin_data: str | None = None) -> CommandResult:
        self.calls.append((argv, stdin_data))
        # Empty rule/route lists so apply takes the "add missing" path.
        return CommandResult(0, "", "")


async def _insert_active_client(
    session_factory: async_sessionmaker[Any],
    *,
    slug: str,
    virtual: str,
    real: str,
    state: TunnelState = TunnelState.UP,
) -> None:
    async with session_factory() as session:
        client = Client(
            id=slug,
            name=slug,
            vpn_type=VpnType.OPENVPN,
            virtual_cidr=virtual,
            real_cidr=real,
        )
        client.nat_mappings = [NatMapping(virtual_cidr=virtual, real_cidr=real)]
        client.tunnel_status = TunnelStatus(state=state)
        session.add(client)
        await session.commit()


class TestRebuild:
    async def test_picks_up_only_active_clients(
        self,
        session_factory: async_sessionmaker[Any],
        engine: Any,  # ensures fresh DB
        tmp_path: Path,
    ) -> None:
        await _insert_active_client(
            session_factory,
            slug="petroleo",
            virtual="10.200.1.0/24",
            real="192.168.1.0/24",
        )
        await _insert_active_client(
            session_factory,
            slug="dormente",
            virtual="10.200.99.0/24",
            real="192.168.99.0/24",
            state=TunnelState.STOPPED,
        )

        runner = FakeRunner()
        applier = NetworkApplier(runner=runner, rt_tables_path=tmp_path / "rt_tables")
        manager = NetworkManager(
            session_factory=session_factory,
            applier=applier,
            virtual_range="10.200.0.0/16",
        )

        plan = await manager.rebuild()
        assert "petroleo" in plan.iface_by_client
        assert "dormente" not in plan.iface_by_client

    async def test_lock_serializes_concurrent_rebuilds(
        self,
        session_factory: async_sessionmaker[Any],
        engine: Any,
        tmp_path: Path,
    ) -> None:
        await _insert_active_client(
            session_factory,
            slug="petroleo",
            virtual="10.200.1.0/24",
            real="192.168.1.0/24",
        )
        runner = FakeRunner()
        applier = NetworkApplier(runner=runner, rt_tables_path=tmp_path / "rt_tables")
        manager = NetworkManager(
            session_factory=session_factory,
            applier=applier,
            virtual_range="10.200.0.0/16",
        )

        # Fire two concurrent rebuilds.
        import asyncio as _asyncio

        plans = await _asyncio.gather(manager.rebuild(), manager.rebuild())
        # Both rebuilds produce the same deterministic plan.
        assert isinstance(plans[0], NetworkPlan)
        assert plans[0].iptables_restore_content == plans[1].iptables_restore_content

    async def test_iface_name_helper_matches_plan(
        self,
        session_factory: async_sessionmaker[Any],
        engine: Any,
        tmp_path: Path,
    ) -> None:
        await _insert_active_client(
            session_factory,
            slug="petroleo",
            virtual="10.200.1.0/24",
            real="192.168.1.0/24",
        )
        manager = NetworkManager(
            session_factory=session_factory,
            applier=NetworkApplier(runner=FakeRunner(), rt_tables_path=tmp_path / "rt_tables"),
            virtual_range="10.200.0.0/16",
        )
        plan = await manager.rebuild()
        assert plan.iface_by_client["petroleo"] == manager.iface_name("petroleo")
