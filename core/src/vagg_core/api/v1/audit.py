"""Audit log read-only endpoints (SPEC §8).

Phase 2 surfaces existing rows. Phase 9 fills in hash-chain creation, Vector
shipping and PDF report generation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vagg_core.api.deps import CurrentAdmin, get_db, require_admin
from vagg_core.db.models import AuditEvent

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


class AuditEventOut(BaseModel):
    id: str
    event_type: str
    actor_consultant_id: int | None
    payload: dict[str, object] | None
    occurred_at: datetime


@router.get("", response_model=list[AuditEventOut])
async def list_audit(
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    event_type: Annotated[str | None, Query()] = None,
    actor_consultant_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditEventOut]:
    stmt = select(AuditEvent).order_by(AuditEvent.occurred_at.desc()).limit(limit).offset(offset)
    if event_type is not None:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if actor_consultant_id is not None:
        stmt = stmt.where(AuditEvent.actor_consultant_id == actor_consultant_id)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        AuditEventOut(
            id=r.id,
            event_type=r.event_type,
            actor_consultant_id=r.actor_consultant_id,
            payload=r.payload,
            occurred_at=r.occurred_at,
        )
        for r in rows
    ]
