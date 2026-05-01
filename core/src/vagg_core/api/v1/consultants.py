"""CRUD over Consultant (SPEC §5.1, §7)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vagg_core.api.deps import CurrentAdmin, get_db, require_admin
from vagg_core.core.errors import ConflictError, NotFoundError
from vagg_core.db.models import Consultant

router = APIRouter(prefix="/api/v1/consultants", tags=["consultants"])

ConsultantRole = Literal["viewer", "operator", "admin"]


class ConsultantCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=128)
    openvpn_username: str | None = Field(default=None, min_length=1, max_length=128)
    static_pool_ip: str | None = Field(default=None, min_length=4, max_length=45)
    role: ConsultantRole = "viewer"
    active: bool = True


class ConsultantUpdate(BaseModel):
    email: EmailStr | None = None
    name: str | None = Field(default=None, min_length=1, max_length=128)
    openvpn_username: str | None = Field(default=None, max_length=128)
    static_pool_ip: str | None = Field(default=None, max_length=45)
    role: ConsultantRole | None = None
    active: bool | None = None


class ConsultantOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    openvpn_username: str | None
    static_pool_ip: str | None
    role: ConsultantRole
    active: bool
    created_at: datetime
    updated_at: datetime


def _to_out(c: Consultant) -> ConsultantOut:
    return ConsultantOut(
        id=c.id,
        email=c.email,
        name=c.name,
        openvpn_username=c.openvpn_username,
        static_pool_ip=c.static_pool_ip,
        role=c.role,
        active=c.active,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


async def _load(session: AsyncSession, consultant_id: int) -> Consultant:
    obj = await session.get(Consultant, consultant_id)
    if obj is None:
        raise NotFoundError("consultor não encontrado", context={"id": consultant_id})
    return obj


@router.get("", response_model=list[ConsultantOut])
async def list_consultants(
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    active: Annotated[bool | None, Query()] = None,
) -> list[ConsultantOut]:
    stmt = select(Consultant).order_by(Consultant.id).limit(limit).offset(offset)
    if active is not None:
        stmt = stmt.where(Consultant.active == active)
    result = await session.execute(stmt)
    return [_to_out(c) for c in result.scalars().all()]


@router.post("", response_model=ConsultantOut, status_code=status.HTTP_201_CREATED)
async def create_consultant(
    body: ConsultantCreate,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ConsultantOut:
    consultant = Consultant(
        email=body.email,
        name=body.name,
        openvpn_username=body.openvpn_username,
        static_pool_ip=body.static_pool_ip,
        role=body.role,
        active=body.active,
    )
    session.add(consultant)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "email, openvpn_username ou static_pool_ip duplicado",
            context={"email": body.email},
        ) from exc
    return _to_out(consultant)


@router.get("/{consultant_id}", response_model=ConsultantOut)
async def get_consultant(
    consultant_id: int,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ConsultantOut:
    return _to_out(await _load(session, consultant_id))


@router.patch("/{consultant_id}", response_model=ConsultantOut)
async def update_consultant(
    consultant_id: int,
    body: ConsultantUpdate,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ConsultantOut:
    consultant = await _load(session, consultant_id)
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(consultant, field, value)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("violação de restrição na atualização") from exc
    # Refresh so server-side ``updated_at`` is loaded before serializing.
    await session.refresh(consultant)
    return _to_out(consultant)


@router.delete("/{consultant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_consultant(
    consultant_id: int,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    consultant = await _load(session, consultant_id)
    await session.delete(consultant)
