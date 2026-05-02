"""High-level DNS orchestrator (SPEC §4.4 + §5.3 / Fase 6).

Reads connected clients from the DB, renders the Corefile via
``dns_render.render_corefile``, writes it atomically to the shared volume
mounted at ``settings.dns_config_dir``, and signals the ``vagg-dns``
container with SIGUSR1 to reload its config.

Disabled by default in dev/test; ``settings.dns_enabled=true`` enables it
in production.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any, Protocol

import aiodocker
from aiodocker.exceptions import DockerError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vagg_core.core.errors import CoreError
from vagg_core.core.logging import get_logger
from vagg_core.db.models import Client, TunnelState, TunnelStatus
from vagg_core.services.dns_render import DnsZoneSpec, render_corefile
from vagg_core.services.network_plan import iface_name

log = get_logger(__name__)


class DnsReloadError(CoreError):
    code = "DNS_RELOAD_ERROR"
    default_status = 502


class DnsManagerProtocol(Protocol):
    async def regenerate(self) -> str: ...

    async def reload(self) -> None: ...

    async def regenerate_and_reload(self) -> str: ...


class DnsManager:
    """Render Corefile from DB and signal CoreDNS to reload."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        config_path: Path,
        domain: str,
        docker: aiodocker.Docker | None = None,
        container_name: str = "vagg-dns",
        default_forwarders: tuple[str, ...] = ("8.8.8.8", "8.8.4.4"),
    ) -> None:
        self._sessions = session_factory
        self._config_path = config_path
        self._domain = domain
        self._docker = docker
        self._container_name = container_name
        self._default_forwarders = default_forwarders
        self._lock = asyncio.Lock()

    async def regenerate(self) -> str:
        """Render the Corefile from current DB state and write it atomically.

        Returns the rendered text — useful for tests and for the API that
        exposes the current config to the admin UI.
        """
        async with self._lock:
            zones = await self._collect_zones()
            corefile = render_corefile(
                domain=self._domain,
                zones=zones,
                default_forwarders=self._default_forwarders,
            )
            self._write_atomic(corefile)
            log.info("dns.regenerate", zones=len(zones), path=str(self._config_path))
            return corefile

    async def reload(self) -> None:
        """Send SIGUSR1 to the vagg-dns container so CoreDNS reloads its config."""
        if self._docker is None:
            log.debug("dns.reload.skipped", reason="no docker client")
            return
        try:
            container = await self._docker.containers.get(self._container_name)
            await container.kill(signal="SIGUSR1")
            log.info("dns.reload", container=self._container_name)
        except DockerError as exc:
            # Most operators run vagg-dns out of band of vagg-core (it's a
            # plain coredns image). Missing container should warn, not crash.
            log.warning(
                "dns.reload.failed",
                container=self._container_name,
                error=str(exc),
            )
            raise DnsReloadError(detail=str(exc)) from exc

    async def regenerate_and_reload(self) -> str:
        corefile = await self.regenerate()
        try:
            await self.reload()
        except DnsReloadError:
            # Regenerate already wrote the file; failing the reload should not
            # roll the file back, just propagate so the caller can decide.
            raise
        return corefile

    async def _collect_zones(self) -> list[DnsZoneSpec]:
        async with self._sessions() as session:
            stmt = (
                select(Client)
                .outerjoin(Client.tunnel_status)
                .where(
                    (TunnelStatus.state.in_((TunnelState.STARTING, TunnelState.UP)))
                    | (TunnelStatus.client_id.is_(None))
                )
                .order_by(Client.id)
            )
            result = await session.execute(stmt)
            zones: list[DnsZoneSpec] = []
            for client in result.scalars().all():
                state: TunnelState | None = None
                if client.tunnel_status is not None:
                    state = client.tunnel_status.state
                # ``iface`` is None until the tunnel is at least STARTING — the
                # ``bind`` directive points to a non-existent interface and
                # CoreDNS would refuse to start.
                iface = (
                    iface_name(client.id)
                    if state in (TunnelState.STARTING, TunnelState.UP)
                    else None
                )
                zones.append(
                    DnsZoneSpec(
                        client_id=client.id,
                        real_cidr=client.real_cidr,
                        virtual_cidr=client.virtual_cidr,
                        dns_server=client.dns_server,
                        iface=iface,
                    )
                )
            return zones

    def _write_atomic(self, content: str) -> None:
        """Write ``content`` to ``self._config_path`` atomically (temp + rename).

        rename(2) on POSIX is atomic on the same filesystem — the consumer
        (CoreDNS) never observes a half-written file. The parent dir is
        created on demand so first-boot doesn't crash on a missing volume.
        """
        target = self._config_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=".Corefile.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, target)


_NO_OP_LOG = get_logger(f"{__name__}.noop")


class _NoopDnsManager:
    """Used in tests / when DNS is disabled — methods are cheap no-ops."""

    async def regenerate(self) -> str:
        return ""

    async def reload(self) -> None:
        return None

    async def regenerate_and_reload(self) -> str:
        return ""


def maybe_dns_manager(
    *,
    enabled: bool,
    session_factory: async_sessionmaker[AsyncSession],
    config_path: Path,
    domain: str,
    docker: Any,
    container_name: str,
) -> DnsManagerProtocol:
    """Factory: return a real ``DnsManager`` when enabled, else a noop."""
    if not enabled:
        return _NoopDnsManager()
    return DnsManager(
        session_factory=session_factory,
        config_path=config_path,
        domain=domain,
        docker=docker,
        container_name=container_name,
    )
