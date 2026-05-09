"""Sub-routes under /api/v1/clients/{id}/* — tunnel lifecycle (SPEC §5.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from vagg_core.api.deps import (
    CurrentAdmin,
    get_db,
    get_tunnel_orchestrator,
    require_admin,
)
from vagg_core.core.errors import ConflictError, NotFoundError
from vagg_core.db.models import Client, TunnelState, TunnelStatus
from vagg_core.services.tunnel_orchestrator import TunnelOrchestratorProtocol

router = APIRouter(prefix="/api/v1/clients/{client_id}", tags=["tunnels"])


class TunnelStatusOut(BaseModel):
    client_id: str
    state: TunnelState
    container_id: str | None
    controller_state: str | None = None
    uptime_s: int | None = None
    last_check_at: datetime | None
    last_error: str | None


class ConnectAck(BaseModel):
    client_id: str
    container_id: str
    state: TunnelState = TunnelState.STARTING


class DisconnectAck(BaseModel):
    client_id: str
    state: TunnelState = TunnelState.STOPPED


class OtpRequest(BaseModel):
    code: str = Field(min_length=4, max_length=16)


class OtpAck(BaseModel):
    client_id: str
    forwarded: bool = True


class LogsOut(BaseModel):
    client_id: str
    lines: list[str]


async def _load_client(session: AsyncSession, client_id: str) -> Client:
    client = await session.get(Client, client_id)
    if client is None:
        raise NotFoundError("cliente não encontrado", context={"id": client_id})
    return client


async def _ensure_status_row(session: AsyncSession, client: Client) -> TunnelStatus:
    if client.tunnel_status is None:
        client.tunnel_status = TunnelStatus(client_id=client.id, state=TunnelState.STOPPED)
        await session.flush()
    return client.tunnel_status


# ----- Endpoints -----


@router.post("/connect", response_model=ConnectAck, status_code=status.HTTP_202_ACCEPTED)
async def connect_tunnel(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> ConnectAck:
    client = await _load_client(session, client_id)
    if not client.config_text:
        raise ConflictError(
            "cliente não tem config_text definido — atualize via PATCH antes de conectar",
            context={"id": client_id},
        )
    container_id = await orchestrator.connect(
        client_id=client_id,
        protocol=client.vpn_type,
        config_text=client.config_text,
        username=client.vpn_username,
        password=client.vpn_password,
        requires_otp=bool(client.requires_otp),
        saml_cookie=client.saml_cookie,
    )
    status_row = await _ensure_status_row(session, client)
    status_row.state = TunnelState.STARTING
    status_row.container_id = container_id
    status_row.last_error = None
    return ConnectAck(client_id=client_id, container_id=container_id)


@router.post("/disconnect", response_model=DisconnectAck, status_code=status.HTTP_202_ACCEPTED)
async def disconnect_tunnel(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> DisconnectAck:
    client = await _load_client(session, client_id)
    await orchestrator.disconnect(client_id)
    status_row = await _ensure_status_row(session, client)
    status_row.state = TunnelState.STOPPED
    status_row.container_id = None
    status_row.last_error = None
    return DisconnectAck(client_id=client_id)


@router.post("/otp", response_model=OtpAck)
async def submit_otp(
    client_id: str,
    body: OtpRequest,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> OtpAck:
    await _load_client(session, client_id)
    await orchestrator.send_otp(client_id, body.code)
    return OtpAck(client_id=client_id)


@router.get("/status", response_model=TunnelStatusOut)
async def get_tunnel_status(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> TunnelStatusOut:
    client = await _load_client(session, client_id)
    report = await orchestrator.status(client_id)
    status_row = await _ensure_status_row(session, client)
    status_row.state = report.state
    status_row.container_id = report.container_id
    status_row.last_error = report.error
    return TunnelStatusOut(
        client_id=client_id,
        state=report.state,
        container_id=report.container_id,
        controller_state=report.controller_state,
        uptime_s=report.uptime_s,
        last_check_at=status_row.last_check_at,
        last_error=report.error,
    )


@router.get("/logs", response_model=LogsOut)
async def tail_tunnel_logs(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
    tail: int = 100,
) -> LogsOut:
    await _load_client(session, client_id)
    lines = await orchestrator.tail_logs(client_id, lines=tail)
    return LogsOut(client_id=client_id, lines=lines)


class DiscoveredRouteOut(BaseModel):
    cidr: str
    dev: str
    gateway: str | None = None


class DiscoveryOut(BaseModel):
    client_id: str
    routes: list[DiscoveredRouteOut]
    dns_servers: list[str]
    search_domains: list[str]


@router.get("/discover", response_model=DiscoveryOut)
async def get_tunnel_discovery(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> DiscoveryOut:
    """Lê (sem persistir) rotas e DNS empurrados pelo gateway.

    Útil pro admin auditar o que o auto-discovery vai (ou já) gravou. Read-only.
    """
    await _load_client(session, client_id)
    report = await orchestrator.discover(client_id)
    return DiscoveryOut(
        client_id=client_id,
        routes=[
            DiscoveredRouteOut(cidr=r.cidr, dev=r.dev, gateway=r.gateway)
            for r in report.routes
        ],
        dns_servers=list(report.dns_servers),
        search_domains=list(report.search_domains),
    )
