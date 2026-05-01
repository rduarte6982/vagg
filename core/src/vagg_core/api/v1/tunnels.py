"""Sub-routes under /api/v1/clients/{id}/* — tunnel actions.

Phase 2 stubs the orchestration. Phase 3 fills in:
- connect/disconnect: docker SDK calls
- otp: unix-socket message to the tunnel container
- logs: tail container stdout
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from vagg_core.api.deps import CurrentAdmin, get_db, require_admin
from vagg_core.core.errors import NotFoundError, NotImplementedYetError
from vagg_core.db.models import Client, TunnelState, TunnelStatus

router = APIRouter(prefix="/api/v1/clients/{client_id}", tags=["tunnels"])


class TunnelStatusOut(BaseModel):
    client_id: str
    state: TunnelState
    container_id: str | None
    last_check_at: datetime | None
    last_error: str | None


class StubResponse(BaseModel):
    status: Literal["accepted_stub"] = "accepted_stub"
    message: str
    phase: Literal[3] = Field(default=3, description="implemented in Phase 3")


class OtpRequest(BaseModel):
    code: str = Field(min_length=4, max_length=16)


async def _load_status(session: AsyncSession, client_id: str) -> TunnelStatus:
    client = await session.get(Client, client_id)
    if client is None:
        raise NotFoundError("cliente não encontrado", context={"id": client_id})
    if client.tunnel_status is None:
        client.tunnel_status = TunnelStatus(client_id=client_id, state=TunnelState.STOPPED)
        await session.flush()
    return client.tunnel_status


@router.post("/connect", response_model=StubResponse, status_code=status.HTTP_202_ACCEPTED)
async def connect_tunnel(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> StubResponse:
    """Phase 3 will start the docker container and apply NAT rules."""
    status_obj = await _load_status(session, client_id)
    status_obj.state = TunnelState.STARTING
    status_obj.last_check_at = datetime.now(UTC)
    return StubResponse(message=f"connect orquestrado para {client_id} (stub)")


@router.post("/disconnect", response_model=StubResponse, status_code=status.HTTP_202_ACCEPTED)
async def disconnect_tunnel(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> StubResponse:
    status_obj = await _load_status(session, client_id)
    status_obj.state = TunnelState.STOPPED
    status_obj.last_check_at = datetime.now(UTC)
    return StubResponse(message=f"disconnect orquestrado para {client_id} (stub)")


@router.post("/otp", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def submit_otp(
    client_id: str,
    body: OtpRequest,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """OTP relay to tunnel container is implemented in Phase 3."""
    # Confirm the client exists so we surface 404 vs 501 appropriately.
    if await session.get(Client, client_id) is None:
        raise NotFoundError("cliente não encontrado", context={"id": client_id})
    raise NotImplementedYetError(
        "envio de OTP para o container do túnel será implementado na Fase 3",
        context={"client_id": client_id, "code_length": len(body.code)},
    )


@router.get("/status", response_model=TunnelStatusOut)
async def get_tunnel_status(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TunnelStatusOut:
    status_obj = await _load_status(session, client_id)
    return TunnelStatusOut(
        client_id=client_id,
        state=status_obj.state,
        container_id=status_obj.container_id,
        last_check_at=status_obj.last_check_at,
        last_error=status_obj.last_error,
    )


@router.get("/logs")
async def tail_tunnel_logs(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    if await session.get(Client, client_id) is None:
        raise NotFoundError("cliente não encontrado", context={"id": client_id})
    return {
        "client_id": client_id,
        "lines": [],
        "note": "logs do container serão expostos na Fase 3",
    }
