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
from vagg_core.db.models import Client, Consultant, Policy, TunnelState, TunnelStatus
from vagg_core.services.network_applier import NetworkApplier
from vagg_core.services.network_plan import (
    ClientNet,
    ConsultantAccess,
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
            clients = list(result.scalars().all())

            # SPEC §7 / Fase 8: pull policies + consultants together so the
            # RBAC chain has a row per (consultant, client) pair.
            access_by_client = await self._collect_accesses(session)

            rows: list[ClientNet] = []
            for client in clients:
                rows.append(_to_client_net(client, access_by_client.get(client.id, ())))
            return rows

    async def _collect_accesses(
        self, session: AsyncSession
    ) -> dict[str, tuple[ConsultantAccess, ...]]:
        """Index every (consultant, client) policy whose consultant is active and
        has a static_pool_ip mapped (Opção B — see SPEC §7.2).

        Policies whose consultant is inactive or lacks a static_pool_ip are
        skipped. The CIDR/host scope value is forwarded as-is; the planner
        validates shape at render time.
        """
        stmt = (
            select(Policy, Consultant)
            .join(Consultant, Policy.consultant_id == Consultant.id)
            .where(
                Consultant.active.is_(True),
                Consultant.static_pool_ip.is_not(None),
            )
        )
        result = await session.execute(stmt)
        out: dict[str, list[ConsultantAccess]] = {}
        for policy, consultant in result.all():
            ip = consultant.static_pool_ip
            if ip is None:
                continue
            out.setdefault(policy.client_id, []).append(
                ConsultantAccess(
                    src_ip=ip,
                    scope_kind=policy.scope_kind.value,
                    scope_value=policy.scope_value,
                )
            )
        # Freeze for hashability — the planner sorts already so we don't sort here.
        return {k: tuple(v) for k, v in out.items()}


def _to_client_net(client: Any, accesses: tuple[ConsultantAccess, ...]) -> ClientNet:
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
        accesses=accesses,
    )
