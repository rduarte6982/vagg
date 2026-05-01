"""High-level facade: rebuild + apply the host network state from DB.

Contains the asyncio.Lock that serializes rebuilds, so concurrent connect /
disconnect operations don't trample each other's `iptables-restore`.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vagg_core.core.logging import get_logger
from vagg_core.db.models import Client, TunnelState, TunnelStatus
from vagg_core.services.network_applier import NetworkApplier
from vagg_core.services.network_plan import (
    ClientNet,
    NatMappingSpec,
    NetworkPlan,
    build_plan,
    iface_name,
)

log = get_logger(__name__)


class NetworkManagerProtocol(Protocol):
    """Public interface — orchestrators and tests depend on this."""

    async def rebuild(self) -> NetworkPlan: ...

    def iface_name(self, client_id: str) -> str: ...


class NetworkManager:
    """Reads the live DB, builds a plan, applies it under a lock."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        applier: NetworkApplier,
        virtual_range: str,
    ) -> None:
        self._sessions = session_factory
        self._applier = applier
        self._virtual_range = virtual_range
        self._lock = asyncio.Lock()

    def iface_name(self, client_id: str) -> str:
        return iface_name(client_id)

    async def rebuild(self) -> NetworkPlan:
        async with self._lock:
            clients = await self._collect_active_clients()
            plan = build_plan(virtual_range=self._virtual_range, clients=clients)
            log.info(
                "network.rebuild.start",
                clients=len(clients),
                fwmarks=list(plan.fwmark_by_client.values()),
            )
            await self._applier.apply(plan)
            log.info("network.rebuild.done")
            return plan

    async def _collect_active_clients(self) -> list[ClientNet]:
        async with self._sessions() as session:
            stmt = (
                select(Client)
                .join(Client.tunnel_status)
                .where(
                    TunnelStatus.state.in_((TunnelState.STARTING, TunnelState.UP, TunnelState.DOWN))
                )
                .order_by(Client.id)
            )
            result = await session.execute(stmt)
            rows: list[ClientNet] = []
            for client in result.scalars().all():
                # Avoid lazy-loading nat_mappings under async by fetching them in the
                # same statement via the relationship's lazy="selectin" (set in models).
                rows.append(_to_client_net(client))
            return rows


def _to_client_net(client: Any) -> ClientNet:
    """Convert an ORM Client into the planner's ``ClientNet`` snapshot."""
    mappings: list[NatMappingSpec] = []
    if client.nat_mappings:
        for m in client.nat_mappings:
            mappings.append(NatMappingSpec(virtual_cidr=m.virtual_cidr, real_cidr=m.real_cidr))
    else:
        # Fall back to the client-level virtual/real CIDRs as a single mapping.
        mappings.append(
            NatMappingSpec(virtual_cidr=client.virtual_cidr, real_cidr=client.real_cidr)
        )
    return ClientNet(
        id=client.id,
        virtual_cidr=client.virtual_cidr,
        real_cidr=client.real_cidr,
        nat_mappings=tuple(mappings),
    )
