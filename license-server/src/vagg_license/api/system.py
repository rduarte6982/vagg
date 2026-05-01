"""GET /health and GET /version — operational endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from vagg_license import __version__

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/version")
async def version() -> dict[str, str]:
    return {"version": __version__}
