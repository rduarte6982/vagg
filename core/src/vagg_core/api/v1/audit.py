"""Audit log endpoints (SPEC §8 / Fase 9).

Read-only listing, JSON / NDJSON / CSV exports, hash-chain verification, and
single-tenant PDF report generation. The hash chain is built by
``services.audit.record_event`` (Fase 8).
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vagg_core.api.deps import CurrentAdmin, get_db, require_admin
from vagg_core.db.models import AuditEvent
from vagg_core.services.audit import verify_chain
from vagg_core.services.audit_report import (
    build_pdf_report,
    pdf_available,
)

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
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditEventOut]:
    stmt = select(AuditEvent).order_by(AuditEvent.occurred_at.desc()).limit(limit).offset(offset)
    if event_type is not None:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if actor_consultant_id is not None:
        stmt = stmt.where(AuditEvent.actor_consultant_id == actor_consultant_id)
    if since is not None:
        stmt = stmt.where(AuditEvent.occurred_at >= since)
    if until is not None:
        stmt = stmt.where(AuditEvent.occurred_at <= until)
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


async def _scan_filtered(
    session: AsyncSession,
    *,
    event_type: str | None,
    actor_consultant_id: int | None,
    since: datetime | None,
    until: datetime | None,
) -> AsyncIterator[AuditEvent]:
    """Yield rows in batches so we can stream millions of events without
    loading the whole table. SPEC critério Fase 9: 1M eventos performático.
    """
    batch = 5_000
    last_occurred: datetime | None = None
    last_id: str | None = None
    while True:
        stmt = (
            select(AuditEvent)
            .order_by(AuditEvent.occurred_at.asc(), AuditEvent.id.asc())
            .limit(batch)
        )
        if event_type is not None:
            stmt = stmt.where(AuditEvent.event_type == event_type)
        if actor_consultant_id is not None:
            stmt = stmt.where(AuditEvent.actor_consultant_id == actor_consultant_id)
        if since is not None:
            stmt = stmt.where(AuditEvent.occurred_at >= since)
        if until is not None:
            stmt = stmt.where(AuditEvent.occurred_at <= until)
        # Keyset cursor: tuple comparison on (occurred_at, id) keeps order
        # stable across batches even when many rows share a timestamp.
        if last_occurred is not None and last_id is not None:
            stmt = stmt.where(
                (AuditEvent.occurred_at > last_occurred)
                | ((AuditEvent.occurred_at == last_occurred) & (AuditEvent.id > last_id))
            )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        if not rows:
            return
        for r in rows:
            yield r
        last_occurred = rows[-1].occurred_at
        last_id = rows[-1].id
        if len(rows) < batch:
            return


@router.get("/export.ndjson")
async def export_ndjson(
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    event_type: Annotated[str | None, Query()] = None,
    actor_consultant_id: Annotated[int | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> StreamingResponse:
    """Streaming newline-delimited JSON. Each line is a self-contained event."""

    async def gen() -> AsyncIterator[str]:
        async for r in _scan_filtered(
            session,
            event_type=event_type,
            actor_consultant_id=actor_consultant_id,
            since=since,
            until=until,
        ):
            line = {
                "id": r.id,
                "event_type": r.event_type,
                "actor_consultant_id": r.actor_consultant_id,
                "payload": r.payload,
                "prev_hash": r.prev_hash,
                "hash": r.hash,
                "occurred_at": r.occurred_at.isoformat(),
            }
            yield json.dumps(line, separators=(",", ":"), default=str) + "\n"

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="audit.ndjson"'},
    )


@router.get("/export.csv")
async def export_csv(
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    event_type: Annotated[str | None, Query()] = None,
    actor_consultant_id: Annotated[int | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> StreamingResponse:
    """Streaming CSV — Excel/LibreOffice-compatible (UTF-8 with BOM)."""

    async def gen() -> AsyncIterator[str]:
        # BOM so Excel autodetects UTF-8.
        yield "﻿"
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "event_type",
                "actor_consultant_id",
                "occurred_at",
                "prev_hash",
                "hash",
                "payload",
            ]
        )
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        async for r in _scan_filtered(
            session,
            event_type=event_type,
            actor_consultant_id=actor_consultant_id,
            since=since,
            until=until,
        ):
            writer.writerow(
                [
                    r.id,
                    r.event_type,
                    r.actor_consultant_id if r.actor_consultant_id is not None else "",
                    r.occurred_at.isoformat(),
                    r.prev_hash or "",
                    r.hash,
                    json.dumps(r.payload or {}, separators=(",", ":"), default=str),
                ]
            )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(
        gen(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit.csv"'},
    )


@router.get("/verify")
async def verify(
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    """Recompute the entire hash chain and return ``{ok, count, first_bad_id}``.

    Used by the admin UI's System tab and by the standalone CLI verifier.
    """
    stmt = select(AuditEvent).order_by(AuditEvent.occurred_at.asc(), AuditEvent.id.asc())
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    ok, bad = verify_chain(rows)
    return {"ok": ok, "count": len(rows), "first_bad_id": bad}


@router.get("/report.pdf")
async def report_pdf(
    request: Request,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    client_id: Annotated[str | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> Response:
    """Render a PDF report (SPEC §8.4 / Fase 9).

    Requires WeasyPrint + jinja2 — installed only in production. Returns
    503 if the optional deps are missing so dev sandboxes don't choke.
    """
    if not pdf_available():
        return Response(
            status_code=503,
            content=json.dumps(
                {
                    "code": "PDF_NOT_AVAILABLE",
                    "detail": "weasyprint nao instalado neste deploy",
                }
            ),
            media_type="application/json",
        )

    rows = []
    async for r in _scan_filtered(
        session,
        event_type=None,
        actor_consultant_id=None,
        since=since,
        until=until,
    ):
        if client_id is not None and (r.payload or {}).get("client_id") != client_id:
            continue
        rows.append(r)

    settings = request.app.state.settings
    pdf_bytes = build_pdf_report(
        events=rows,
        client_id=client_id,
        since=since,
        until=until,
        domain=settings.domain,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": (f'attachment; filename="audit-{client_id or "all"}.pdf"')},
    )
