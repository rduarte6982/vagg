"""Background worker that refreshes ``tunnel_status`` rows every 30s.

Lives only inside the running FastAPI app (started in lifespan, cancelled on
shutdown). Tests don't run it — they instantiate the orchestrator directly.

SPEC §11 Phase 3: "Health check de túnel (a cada 30s)".

Hook adicional (Fase 5+): quando o estado transiciona pra UP pela primeira
vez (ou o cliente nunca foi descoberto), dispara ``orchestrator.discover``
e replica em nat_mappings + dns_server pra evitar config manual.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vagg_core.core.errors import CoreError
from vagg_core.core.logging import get_logger
from vagg_core.db.models import Client, NatMapping, TunnelState, TunnelStatus
from vagg_core.services.dns_manager import DnsManagerProtocol
from vagg_core.services.network_manager import NetworkManagerProtocol
from vagg_core.services.tunnel_orchestrator import (
    DiscoveryReport,
    TunnelOrchestratorProtocol,
    TunnelStatusReport,
)

log = get_logger(__name__)


# DNS servers que NUNCA devem ser usados como dns_server do cliente —
# sempre vêm do host do container (systemd-resolved, link-local, etc),
# nunca do gateway VPN. O auto-discovery filtra antes de persistir.
_INVALID_DNS_PREFIXES = (
    "127.",         # loopback IPv4
    "::1",          # loopback IPv6
    "0.",           # 0.0.0.0/8
    "169.254.",     # link-local IPv4
    "fe80:",        # link-local IPv6
)


def _is_valid_dns(server: str) -> bool:
    return not any(server.startswith(p) for p in _INVALID_DNS_PREFIXES)


def _sanitize_report(report: DiscoveryReport) -> DiscoveryReport:
    """Remove DNS servers loopback/link-local antes de persistir."""
    return DiscoveryReport(
        routes=report.routes,
        dns_servers=tuple(s for s in report.dns_servers if _is_valid_dns(s)),
        search_domains=report.search_domains,
    )


class TunnelHealthWorker:
    """Periodic poll loop. Cancellable on shutdown."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[Any],
        orchestrator: TunnelOrchestratorProtocol,
        interval_s: float = 30.0,
        network_manager: NetworkManagerProtocol | None = None,
        dns_manager: DnsManagerProtocol | None = None,
    ) -> None:
        self._sessions = session_factory
        self._orchestrator = orchestrator
        self._interval = interval_s
        self._network_manager = network_manager
        self._dns_manager = dns_manager
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="vagg.tunnel_health")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        log.info("tunnel_health.started", interval_s=self._interval)
        try:
            while True:
                try:
                    await self.tick()
                except Exception as exc:  # noqa: BLE001 — never let the loop die
                    log.exception("tunnel_health.tick_failed", error=str(exc))
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            log.info("tunnel_health.stopped")
            raise

    async def tick(self) -> None:
        """Inspect every client and update the persisted ``TunnelStatus`` row."""
        async with self._sessions() as session:
            result = await session.execute(select(Client))
            clients = result.scalars().all()
            transitioned_to_up: list[Client] = []
            for client in clients:
                report = await self._safe_status(client.id)
                if self._just_came_up(client, report):
                    transitioned_to_up.append(client)
                await self._persist_status(session, client, report)
            await session.commit()

            # Auto-discovery roda DEPOIS do commit pra que cada cliente seja
            # tratado individualmente (uma falha não derruba a tick inteira).
            for client in transitioned_to_up:
                if client.auto_discovery_enabled:
                    await self._auto_discover(client.id)

    async def _safe_status(self, client_id: str) -> TunnelStatusReport:
        try:
            return await self._orchestrator.status(client_id)
        except Exception as exc:  # noqa: BLE001 — surface as ERRORED
            log.warning("tunnel_health.status_failed", client_id=client_id, error=str(exc))
            return TunnelStatusReport(state=TunnelState.ERRORED, error=str(exc))

    @staticmethod
    def _just_came_up(client: Client, report: TunnelStatusReport) -> bool:
        """Detecta transição STARTING/DOWN/ERRORED/STOPPED → UP.

        Também cobre o caso "primeira vez UP de sempre" (auto_discovered_at
        é None) — útil pra clientes que já estavam UP antes desse worker
        existir, ou quando o admin reseta auto_discovered_at via API.
        """
        if report.state != TunnelState.UP:
            return False
        if client.auto_discovered_at is None:
            return True
        prev_state = (
            client.tunnel_status.state if client.tunnel_status is not None else None
        )
        return prev_state != TunnelState.UP

    async def _auto_discover(self, client_id: str) -> None:
        """Pede discovery ao container, escreve nat_mappings + dns_server,
        rebuilda o plano de rede / DNS.

        Cada falha é logada como warning — auto-discovery é best-effort. Se o
        gateway não pushou rotas, deixa o cliente sem mappings (admin pode
        criar manualmente; auto_discovered_at vira NULL pra retentativa).

        Guard rails contra falsos-UPs (descoberto na hard way em 2026-05-06):
          - Se report.routes está vazio, ABORTA. Sem rotas via tun*/ppp*, o
            tunnel não está realmente up — o discover pegou o resolv.conf
            do HOST do container (systemd-resolved local).
          - DNS loopback / metadata (127.x, ::1, 0.0.0.0, 169.254.x) é
            filtrado antes de aplicar — esses são DNS do host, não do gateway.
        """
        try:
            report = await self._orchestrator.discover(client_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("tunnel_health.discover_failed", client_id=client_id, error=str(exc))
            return
        if not report.routes:
            log.info(
                "tunnel_health.discover_skipped_no_routes",
                client_id=client_id,
                dns_servers=len(report.dns_servers),
            )
            return

        sanitized = _sanitize_report(report)
        if sanitized.is_empty():
            log.info("tunnel_health.discover_empty_after_sanitize", client_id=client_id)
            return

        applied = await self._apply_discovery(client_id, sanitized)
        if not applied:
            return

        if self._network_manager is not None:
            try:
                await self._network_manager.rebuild()
            except CoreError as exc:
                log.warning(
                    "tunnel_health.discover_network_rebuild_failed",
                    client_id=client_id,
                    error=str(exc.detail),
                )
        if self._dns_manager is not None:
            try:
                await self._dns_manager.regenerate_and_reload()
            except CoreError as exc:
                log.warning(
                    "tunnel_health.discover_dns_reload_failed",
                    client_id=client_id,
                    error=str(exc.detail),
                )

    async def _apply_discovery(self, client_id: str, report: DiscoveryReport) -> bool:
        """Persiste o resultado da discovery. Retorna True se mudou algo.

        Estratégia: substitui TODOS os nat_mappings do cliente pelos
        descobertos (1:1, virtual=real). Mappings manuais ficam preservados
        só se ``auto_discovery_enabled`` estiver False — nesse caso o
        worker nem chega a chamar este método.
        """
        async with self._sessions() as session:
            client = await session.get(Client, client_id)
            if client is None:
                return False

            # Drop tudo que existir; o orchestrator de fato fonte-da-verdade
            # pra rotas é o gateway durante a sessão.
            for old in list(client.nat_mappings):
                await session.delete(old)

            seen: set[str] = set()
            for r in report.routes:
                if r.cidr in seen:
                    continue
                seen.add(r.cidr)
                session.add(
                    NatMapping(
                        client_id=client.id,
                        virtual_cidr=r.cidr,
                        real_cidr=r.cidr,
                        description=f"auto-discovered via {r.dev}",
                    )
                )

            if report.dns_servers:
                client.dns_server = report.dns_servers[0]
            client.auto_discovered_at = datetime.now(UTC)
            await session.commit()
            log.info(
                "tunnel_health.discover_applied",
                client_id=client_id,
                routes=len(seen),
                dns_servers=len(report.dns_servers),
                first_dns=report.dns_servers[0] if report.dns_servers else None,
            )
            return True

    @staticmethod
    async def _persist_status(session: Any, client: Client, report: TunnelStatusReport) -> None:
        if client.tunnel_status is None:
            client.tunnel_status = TunnelStatus(
                client_id=client.id,
                state=report.state,
                container_id=report.container_id,
                last_check_at=datetime.now(UTC),
                last_error=report.error,
            )
            session.add(client.tunnel_status)
        else:
            client.tunnel_status.state = report.state
            client.tunnel_status.container_id = report.container_id
            client.tunnel_status.last_check_at = datetime.now(UTC)
            client.tunnel_status.last_error = report.error
