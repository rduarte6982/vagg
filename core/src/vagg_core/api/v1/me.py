"""Endpoint `/me` — usado pelo VAGG Client (Windows) para descobrir as rotas
que o usuário autenticado tem permissão de acessar.

Lógica de filtragem:
  - Admin do .env (sem consultant_id): vê TODOS os clientes.
  - Consultor com role=admin: vê TODOS os clientes.
  - Consultor com role=operator/viewer: vê só os clientes para os quais existe
    pelo menos uma Policy ativa (não expirada) ligando o consultant ao client.

Os túneis estão sempre rodando no aggregator — o VAGG Client só adiciona
rotas no Windows do consultor, não levanta túneis. O `tunnel_state` exposto
aqui é o estado do túnel no aggregator, ou seja, se o consultor consegue
chegar no destino ou não.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vagg_core.api.deps import (
    CurrentUser,
    get_db,
    get_tunnel_orchestrator,
    require_user,
)
from vagg_core.api.v1.tunnels import ConnectAck, OtpAck, OtpRequest, perform_connect
from vagg_core.core.errors import ForbiddenError, NotFoundError
from vagg_core.db.models import Client, Policy, TunnelState
from vagg_core.services.tunnel_orchestrator import TunnelOrchestratorProtocol

router = APIRouter(prefix="/api/v1/me", tags=["me"])


class RouteEntry(BaseModel):
    cidr: str = Field(description="CIDR no formato a.b.c.d/n")
    client_id: str
    client_name: str
    label: str = Field(description="texto pra exibir no client")
    is_main: bool = Field(description="True se é o real_cidr principal; False se nat_mapping")


class RoutesResponse(BaseModel):
    """Lista plana de rotas que o usuário deve ter no Windows."""

    server_version: str = Field(description="versão do vagg-server, pra forçar refresh do client")
    routes: list[RouteEntry]


class ClientStatus(BaseModel):
    id: str
    name: str
    vpn_type: str
    tunnel_state: TunnelState
    routes: list[str]
    # Metadados de autenticação — o VAGG Client usa isto pra saber se, ao
    # reconectar, precisa pedir OTP ao usuário ou avisar que o SAML expirou.
    auth_method: str = Field(description="none | otp | saml")
    requires_otp: bool = Field(description="True se o túnel pede OTP ao conectar")
    has_saml_cookie: bool = Field(description="True se há cookie SAML armazenado")
    saml_cookie_valid: bool | None = Field(
        default=None,
        description="None se não há cookie; True se válido/sem expiração; False se expirado",
    )


class MyClientsResponse(BaseModel):
    """Visão consolidada pro VAGG Client mostrar na tela."""

    routes: list[RouteEntry]
    clients: list[ClientStatus]
    user: str = Field(description="display name do usuário autenticado")
    is_admin: bool


def _saml_cookie_valid(client: Client) -> bool | None:
    """None quando não há cookie; True se sem expiração ou ainda válido; False se expirado."""
    if not client.saml_cookie:
        return None
    if client.saml_cookie_expires_at is None:
        return True
    expires_at = client.saml_cookie_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > datetime.now(UTC)


async def _allowed_clients(session: AsyncSession, user: CurrentUser) -> list[Client]:
    """Retorna a lista de clients que o usuário pode ver.

    Admin → todos. Consultor não-admin → join via policies (não-expiradas)."""
    if user.is_admin or user.consultant_id is None:
        result = await session.execute(
            select(Client).options(
                selectinload(Client.nat_mappings), selectinload(Client.tunnel_status)
            )
        )
        return list(result.scalars().all())

    now = datetime.now(UTC)
    # join clients ↔ policies do consultor; expires_at NULL ou no futuro.
    stmt = (
        select(Client)
        .join(Policy, Policy.client_id == Client.id)
        .where(Policy.consultant_id == user.consultant_id)
        .where(or_(Policy.expires_at.is_(None), Policy.expires_at > now))
        .options(selectinload(Client.nat_mappings), selectinload(Client.tunnel_status))
        .distinct()
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/routes", response_model=RoutesResponse)
async def my_routes(
    user: Annotated[CurrentUser, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RoutesResponse:
    from vagg_core import __version__

    clients = await _allowed_clients(session, user)
    routes: list[RouteEntry] = []
    seen: set[str] = set()
    for c in clients:
        if c.real_cidr and c.real_cidr not in seen and c.real_cidr != "0.0.0.0/0":
            seen.add(c.real_cidr)
            routes.append(
                RouteEntry(
                    cidr=c.real_cidr,
                    client_id=c.id,
                    client_name=c.name,
                    label=f"{c.name} ({c.real_cidr})",
                    is_main=True,
                )
            )
        for nm in c.nat_mappings:
            if nm.real_cidr in seen:
                continue
            seen.add(nm.real_cidr)
            routes.append(
                RouteEntry(
                    cidr=nm.real_cidr,
                    client_id=c.id,
                    client_name=c.name,
                    label=f"{c.name} extra ({nm.real_cidr})",
                    is_main=False,
                )
            )

    return RoutesResponse(server_version=__version__, routes=routes)


@router.get("/clients", response_model=MyClientsResponse)
async def my_clients(
    user: Annotated[CurrentUser, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MyClientsResponse:
    """Combina rotas + estado dos clientes — tela principal do VAGG Client."""
    clients = await _allowed_clients(session, user)

    routes: list[RouteEntry] = []
    client_statuses: list[ClientStatus] = []
    seen: set[str] = set()

    for c in clients:
        client_routes: list[str] = []

        if c.real_cidr and c.real_cidr != "0.0.0.0/0":
            client_routes.append(c.real_cidr)
            if c.real_cidr not in seen:
                seen.add(c.real_cidr)
                routes.append(
                    RouteEntry(
                        cidr=c.real_cidr,
                        client_id=c.id,
                        client_name=c.name,
                        label=f"{c.name} ({c.real_cidr})",
                        is_main=True,
                    )
                )
        for nm in c.nat_mappings:
            client_routes.append(nm.real_cidr)
            if nm.real_cidr not in seen:
                seen.add(nm.real_cidr)
                routes.append(
                    RouteEntry(
                        cidr=nm.real_cidr,
                        client_id=c.id,
                        client_name=c.name,
                        label=f"{c.name} extra ({nm.real_cidr})",
                        is_main=False,
                    )
                )

        state = c.tunnel_status.state if c.tunnel_status else TunnelState.STOPPED
        client_statuses.append(
            ClientStatus(
                id=c.id,
                name=c.name,
                vpn_type=c.vpn_type.value,
                tunnel_state=state,
                routes=client_routes,
                auth_method=c.auth_method,
                requires_otp=bool(c.requires_otp),
                has_saml_cookie=bool(c.saml_cookie),
                saml_cookie_valid=_saml_cookie_valid(c),
            )
        )

    return MyClientsResponse(
        routes=routes,
        clients=client_statuses,
        user=user.name or user.subject,
        is_admin=user.is_admin,
    )


# ----- Ações self-service (modelo híbrido) -----
#
# O admin sobe o túnel inicialmente (via /api/v1/clients/{id}/connect), mas o
# consultor pode reconectar quando cai e reautenticar OTP, desde que:
#   - tenha uma Policy ativa ligando-o ao client (senão 404, como no resto do /me);
#   - tenha papel operator ou admin (viewer é read-only).


def _require_write_role(user: CurrentUser) -> None:
    if user.role not in ("operator", "admin"):
        raise ForbiddenError(
            "ação requer papel operator ou admin",
            context={"role": user.role},
        )


async def _authorized_client(
    session: AsyncSession, user: CurrentUser, client_id: str
) -> Client:
    """Carrega o client garantindo que o usuário tem acesso a ele.

    Admin (.env ou role=admin) → qualquer client. Consultor → só via Policy ativa.
    Retorna 404 (não 403) quando não autorizado, pra não vazar a existência de
    clients que o consultor não deveria enxergar.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise NotFoundError("cliente não encontrado", context={"id": client_id})
    if user.is_admin or user.consultant_id is None:
        return client
    now = datetime.now(UTC)
    stmt = (
        select(Policy.id)
        .where(Policy.client_id == client_id)
        .where(Policy.consultant_id == user.consultant_id)
        .where(or_(Policy.expires_at.is_(None), Policy.expires_at > now))
        .limit(1)
    )
    if (await session.execute(stmt)).first() is None:
        raise NotFoundError("cliente não encontrado", context={"id": client_id})
    return client


@router.post(
    "/clients/{client_id}/reconnect",
    response_model=ConnectAck,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reconnect_my_client(
    client_id: str,
    user: Annotated[CurrentUser, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> ConnectAck:
    """Reconecta o túnel de um client que o consultor tem permissão de acessar."""
    _require_write_role(user)
    client = await _authorized_client(session, user, client_id)
    container_id = await perform_connect(session, orchestrator, client)
    return ConnectAck(client_id=client_id, container_id=container_id)


@router.post("/clients/{client_id}/otp", response_model=OtpAck)
async def submit_my_otp(
    client_id: str,
    body: OtpRequest,
    user: Annotated[CurrentUser, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> OtpAck:
    """Encaminha um código OTP pro túnel de um client autorizado (reautenticação)."""
    _require_write_role(user)
    await _authorized_client(session, user, client_id)
    await orchestrator.send_otp(client_id, body.code)
    return OtpAck(client_id=client_id)
