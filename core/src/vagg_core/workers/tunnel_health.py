"""Background worker that refreshes ``tunnel_status`` rows every 30s.

Lives only inside the running FastAPI app (started in lifespan, cancelled on
shutdown). Tests don't run it — they instantiate the orchestrator directly.

SPEC §11 Phase 3: "Health check de túnel (a cada 30s)".
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from vagg_core.core.logging import get_logger
from vagg_core.db.models import Client, TunnelState, TunnelStatus
from vagg_core.services.tunnel_orchestrator import (
    TunnelOrchestratorProtocol,
    TunnelStatusReport,
)

log = get_logger(__name__)


class TunnelHealthWorker:
    """Periodic poll loop. Cancellable on shutdown."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[Any],
        orchestrator: TunnelOrchestratorProtocol,
        interval_s: float = 30.0,
    ) -> None:
        self._sessions = session_factory
        self._orchestrator = orchestrator
        self._interval = interval_s
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
            for client in clients:
                report = await self._safe_status(client.id)
                await self._persist_status(session, client, report)
            await session.commit()

    async def _safe_status(self, client_id: str) -> TunnelStatusReport:
        try:
            return await self._orchestrator.status(client_id)
        except Exception as exc:  # noqa: BLE001 — surface as ERRORED
            log.warning("tunnel_health.status_failed", client_id=client_id, error=str(exc))
            return TunnelStatusReport(state=TunnelState.ERRORED, error=str(exc))

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
