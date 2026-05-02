"""GET /health, /version, /license, /metrics — operational endpoints (SPEC §5.1)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from vagg_core import __version__
from vagg_core.api.deps import CurrentAdmin
from vagg_core.services.dns_manager import DnsManagerProtocol

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/version")
async def version() -> dict[str, str]:
    return {"version": __version__}


@router.get("/license")
async def license_status() -> dict[str, object]:
    """Phase 2 stub. The license refresh worker (Fase 1 client integration)
    will populate real status here."""
    return {
        "status": "unknown",
        "note": "validacao real da licenca contra o license-server e tarefa da Fase 9",
    }


@router.get("/metrics")
async def metrics() -> dict[str, str]:
    """Stub. Real Prometheus exposition is part of operational hardening (SPEC §10.5)."""
    return {"note": "Prometheus exposition implementada em uma fase posterior"}


@router.post("/dns/regenerate")
async def dns_regenerate(request: Request, _: CurrentAdmin) -> dict[str, object]:
    """Force a Corefile regenerate + SIGUSR1 reload (SPEC §4.4 / §5.3 / Fase 6).

    Normally this happens automatically on tunnel connect/disconnect; the
    endpoint is for ops who tweak ``dns_server`` on a Client and want to push
    the change without bouncing tunnels.
    """
    dns_manager: DnsManagerProtocol = request.app.state.dns_manager
    corefile = await dns_manager.regenerate_and_reload()
    return {"reloaded": True, "corefile_bytes": len(corefile.encode("utf-8"))}
