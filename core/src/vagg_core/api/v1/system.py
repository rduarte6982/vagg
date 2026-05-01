"""GET /health, /version, /license, /metrics — operational endpoints (SPEC §5.1)."""

from __future__ import annotations

from fastapi import APIRouter

from vagg_core import __version__

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
