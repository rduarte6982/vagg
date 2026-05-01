"""CRUD over Client + nested NAT mappings (SPEC §5.1, §4.2)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vagg_core.api.deps import CurrentAdmin, get_db, require_admin
from vagg_core.core.errors import ConflictError, NotFoundError
from vagg_core.db.models import Client, NatMapping, TunnelState, TunnelStatus, VpnType

router = APIRouter(prefix="/api/v1/clients", tags=["clients"])

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")


# ----- Schemas -----


class NatMappingPayload(BaseModel):
    virtual_cidr: str = Field(min_length=9, max_length=43)
    real_cidr: str = Field(min_length=9, max_length=43)
    description: str | None = Field(default=None, max_length=512)


class ClientCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64, description="kebab-case slug")
    name: str = Field(min_length=1, max_length=128)
    vpn_type: VpnType
    virtual_cidr: str = Field(min_length=9, max_length=43)
    real_cidr: str = Field(min_length=9, max_length=43)
    dns_server: str | None = Field(default=None, max_length=45)
    description: str | None = Field(default=None, max_length=512)
    nat_mappings: list[NatMappingPayload] = Field(default_factory=list)


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    vpn_type: VpnType | None = None
    virtual_cidr: str | None = Field(default=None, min_length=9, max_length=43)
    real_cidr: str | None = Field(default=None, min_length=9, max_length=43)
    dns_server: str | None = Field(default=None, max_length=45)
    description: str | None = Field(default=None, max_length=512)


class NatMappingOut(BaseModel):
    id: int
    virtual_cidr: str
    real_cidr: str
    description: str | None


class ClientOut(BaseModel):
    id: str
    name: str
    vpn_type: VpnType
    virtual_cidr: str
    real_cidr: str
    dns_server: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime
    tunnel_state: TunnelState
    nat_mappings: list[NatMappingOut]


# ----- Helpers -----


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise ConflictError(
            "id de cliente deve ser kebab-case (a-z, 0-9, hífens)",
            context={"id": slug},
        )


async def _load_client(session: AsyncSession, client_id: str) -> Client:
    result = await session.execute(select(Client).where(Client.id == client_id))
    obj = result.scalar_one_or_none()
    if obj is None:
        raise NotFoundError("cliente não encontrado", context={"id": client_id})
    return obj


def _to_out(client: Client) -> ClientOut:
    state = client.tunnel_status.state if client.tunnel_status else TunnelState.STOPPED
    return ClientOut(
        id=client.id,
        name=client.name,
        vpn_type=client.vpn_type,
        virtual_cidr=client.virtual_cidr,
        real_cidr=client.real_cidr,
        dns_server=client.dns_server,
        description=client.description,
        created_at=client.created_at,
        updated_at=client.updated_at,
        tunnel_state=state,
        nat_mappings=[
            NatMappingOut(
                id=m.id,
                virtual_cidr=m.virtual_cidr,
                real_cidr=m.real_cidr,
                description=m.description,
            )
            for m in client.nat_mappings
        ],
    )


# ----- Endpoints -----


@router.get("", response_model=list[ClientOut])
async def list_clients(
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ClientOut]:
    result = await session.execute(select(Client).order_by(Client.id).limit(limit).offset(offset))
    rows = result.scalars().all()
    # ``Client`` declares lazy="selectin" on nat_mappings/tunnel_status, so the
    # relationships were already fetched in the same SELECT pipeline.
    return [_to_out(c) for c in rows]


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
async def create_client(
    body: ClientCreate,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ClientOut:
    _validate_slug(body.id)
    client = Client(
        id=body.id,
        name=body.name,
        vpn_type=body.vpn_type,
        virtual_cidr=body.virtual_cidr,
        real_cidr=body.real_cidr,
        dns_server=body.dns_server,
        description=body.description,
    )
    for mapping in body.nat_mappings:
        client.nat_mappings.append(
            NatMapping(
                virtual_cidr=mapping.virtual_cidr,
                real_cidr=mapping.real_cidr,
                description=mapping.description,
            )
        )
    # Tunnel starts in 'stopped' until Phase 3 orchestrator brings it up.
    client.tunnel_status = TunnelStatus(state=TunnelState.STOPPED)
    session.add(client)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "cliente já existe ou viola restrição de unicidade",
            context={"id": body.id},
        ) from exc
    await session.refresh(client)
    return _to_out(client)


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ClientOut:
    client = await _load_client(session, client_id)
    await session.refresh(client)
    return _to_out(client)


@router.patch("/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: str,
    body: ClientUpdate,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ClientOut:
    client = await _load_client(session, client_id)
    updates = body.model_dump(exclude_unset=True, exclude_none=False)
    for field, value in updates.items():
        setattr(client, field, value)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("violação de restrição na atualização") from exc
    await session.refresh(client)
    return _to_out(client)


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    client = await _load_client(session, client_id)
    await session.delete(client)
