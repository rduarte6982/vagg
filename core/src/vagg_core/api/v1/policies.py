"""CRUD over Policy (SPEC §5.1, §7)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vagg_core.api.deps import CurrentAdmin, get_db, require_admin
from vagg_core.core.errors import ConflictError, NotFoundError
from vagg_core.db.models import Client, Consultant, Policy, PolicyScopeKind

router = APIRouter(prefix="/api/v1/policies", tags=["policies"])


class PolicyCreate(BaseModel):
    consultant_id: int
    client_id: str = Field(min_length=1, max_length=64)
    scope_kind: PolicyScopeKind = PolicyScopeKind.FULL
    scope_value: str | None = Field(default=None, max_length=64)
    expires_at: datetime | None = None


class PolicyOut(BaseModel):
    id: int
    consultant_id: int
    client_id: str
    scope_kind: PolicyScopeKind
    scope_value: str | None
    expires_at: datetime | None
    created_at: datetime


def _to_out(p: Policy) -> PolicyOut:
    return PolicyOut(
        id=p.id,
        consultant_id=p.consultant_id,
        client_id=p.client_id,
        scope_kind=p.scope_kind,
        scope_value=p.scope_value,
        expires_at=p.expires_at,
        created_at=p.created_at,
    )


@router.get("", response_model=list[PolicyOut])
async def list_policies(
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    consultant_id: Annotated[int | None, Query()] = None,
    client_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PolicyOut]:
    stmt = select(Policy).order_by(Policy.id).limit(limit).offset(offset)
    if consultant_id is not None:
        stmt = stmt.where(Policy.consultant_id == consultant_id)
    if client_id is not None:
        stmt = stmt.where(Policy.client_id == client_id)
    result = await session.execute(stmt)
    return [_to_out(p) for p in result.scalars().all()]


@router.post("", response_model=PolicyOut, status_code=status.HTTP_201_CREATED)
async def create_policy(
    body: PolicyCreate,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PolicyOut:
    # Confirm referenced consultant + client exist (FK alone would 500 in some drivers).
    if not await session.get(Consultant, body.consultant_id):
        raise NotFoundError("consultor não encontrado", context={"id": body.consultant_id})
    if not await session.get(Client, body.client_id):
        raise NotFoundError("cliente não encontrado", context={"id": body.client_id})

    # SQL UNIQUE treats NULL as distinct, so two ``full`` policies (scope_value=NULL)
    # would both insert. Enforce uniqueness in app logic.
    duplicate_q = select(Policy).where(
        Policy.consultant_id == body.consultant_id,
        Policy.client_id == body.client_id,
        Policy.scope_kind == body.scope_kind,
        Policy.scope_value.is_(body.scope_value)
        if body.scope_value is None
        else Policy.scope_value == body.scope_value,
    )
    if (await session.execute(duplicate_q)).scalar_one_or_none() is not None:
        raise ConflictError(
            "policy duplicada (mesma combinação consultant/client/scope)",
            context={"consultant_id": body.consultant_id, "client_id": body.client_id},
        )

    policy = Policy(
        consultant_id=body.consultant_id,
        client_id=body.client_id,
        scope_kind=body.scope_kind,
        scope_value=body.scope_value,
        expires_at=body.expires_at,
    )
    session.add(policy)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "policy duplicada (mesma combinação consultant/client/scope)",
            context={"consultant_id": body.consultant_id, "client_id": body.client_id},
        ) from exc
    return _to_out(policy)


@router.get("/{policy_id}", response_model=PolicyOut)
async def get_policy(
    policy_id: int,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PolicyOut:
    obj = await session.get(Policy, policy_id)
    if obj is None:
        raise NotFoundError("policy não encontrada", context={"id": policy_id})
    return _to_out(obj)


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
    policy_id: int,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    obj = await session.get(Policy, policy_id)
    if obj is None:
        raise NotFoundError("policy não encontrada", context={"id": policy_id})
    await session.delete(obj)
