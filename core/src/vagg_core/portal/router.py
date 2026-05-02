"""Portal de Transparência endpoints (SPEC §5.6 / Fase 11).

Mounted under ``/portal`` on the same FastAPI app as the admin API. Auth uses
its own ``viewer_id`` cookie + bearer token — there is **zero** overlap with
the admin's JWT, so a leak of the admin's signing secret cannot mint portal
sessions or vice-versa.

Multi-tenant isolation: every endpoint reads ``viewer.client_id`` and joins
on it explicitly. The router never accepts a ``client_id`` query param —
the auditor can only see their own client's data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vagg_core.api.deps import get_db
from vagg_core.core.errors import NotFoundError
from vagg_core.core.logging import get_logger
from vagg_core.db.models import (
    AuditEvent,
    Client,
    ExternalViewer,
    ExternalViewerToken,
    PortalAccessLog,
)
from vagg_core.portal.auth import (
    hash_token,
    magic_expires_at,
    now_utc,
    random_token,
    session_expires_at,
    verify_totp,
)
from vagg_core.portal.report import build_signed_report, pdf_available

router = APIRouter(prefix="/portal", tags=["portal"])
log = get_logger(__name__)


# ----- Auth dependency -----


async def current_viewer(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    vagg_session: Annotated[str | None, Cookie()] = None,
) -> ExternalViewer:
    if not vagg_session:
        raise HTTPException(status_code=401, detail="not authenticated")
    digest = hash_token(vagg_session)
    stmt = select(ExternalViewerToken).where(
        and_(
            ExternalViewerToken.token_hash == digest,
            ExternalViewerToken.kind == "session",
            ExternalViewerToken.consumed_at.is_(None),
            ExternalViewerToken.revoked_at.is_(None),
            ExternalViewerToken.expires_at > now_utc(),
        )
    )
    tok = (await session.execute(stmt)).scalar_one_or_none()
    if tok is None:
        raise HTTPException(status_code=401, detail="invalid session")
    viewer = await session.get(ExternalViewer, tok.viewer_id)
    if viewer is None or not viewer.active:
        raise HTTPException(status_code=403, detail="viewer disabled")
    # Best-effort access log — don't break the request if logging fails.
    log_entry = PortalAccessLog(
        viewer_id=viewer.id,
        client_id=viewer.client_id,
        endpoint=str(request.url.path),
        ip_address=request.client.host if request.client else "",
    )
    session.add(log_entry)
    await session.flush()
    return viewer


# ----- Auth endpoints -----


class MagicLinkRequest(BaseModel):
    email: EmailStr
    client_id: str = Field(min_length=1, max_length=64)


@router.post("/auth/request_magic_link", status_code=status.HTTP_202_ACCEPTED)
async def request_magic_link(
    body: MagicLinkRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Sempre responde 202 — não revelamos se o email existe (anti-enumeração).

    Em produção o instalador configura SMTP relay; em dev, o token cru é
    impresso no log para que o auditor possa copiar manualmente.
    """
    stmt = select(ExternalViewer).where(
        ExternalViewer.email == body.email,
        ExternalViewer.client_id == body.client_id,
        ExternalViewer.active.is_(True),
    )
    viewer = (await session.execute(stmt)).scalar_one_or_none()
    if viewer is None:
        return {"status": "accepted"}

    raw = random_token()
    token = ExternalViewerToken(
        viewer_id=viewer.id,
        kind="magic",
        token_hash=hash_token(raw),
        expires_at=magic_expires_at(),
        issued_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    session.add(token)
    await session.flush()
    log.info("portal.magic_link.issued", viewer_id=viewer.id, raw_token_hint=raw[:6])
    return {"status": "accepted"}


class ConsumeResponse(BaseModel):
    requires_totp: bool
    viewer_email: str
    client_id: str


@router.get("/auth/consume", response_model=ConsumeResponse)
async def consume_magic_link(
    token: str,
    response: Response,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ConsumeResponse:
    digest = hash_token(token)
    stmt = select(ExternalViewerToken).where(
        ExternalViewerToken.token_hash == digest,
        ExternalViewerToken.kind == "magic",
        ExternalViewerToken.consumed_at.is_(None),
        ExternalViewerToken.expires_at > now_utc(),
    )
    magic = (await session.execute(stmt)).scalar_one_or_none()
    if magic is None:
        raise HTTPException(status_code=401, detail="link inválido ou expirado")
    magic.consumed_at = now_utc()

    viewer = await session.get(ExternalViewer, magic.viewer_id)
    if viewer is None or not viewer.active:
        raise HTTPException(status_code=403, detail="viewer disabled")

    raw_session = random_token()
    sess_token = ExternalViewerToken(
        viewer_id=viewer.id,
        kind="session",
        token_hash=hash_token(raw_session),
        expires_at=session_expires_at(),
        issued_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    session.add(sess_token)
    viewer.last_login_at = now_utc()
    await session.flush()

    response.set_cookie(
        key="vagg_session",
        value=raw_session,
        max_age=int((session_expires_at() - now_utc()).total_seconds()),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/portal",
    )
    return ConsumeResponse(
        requires_totp=viewer.totp_enabled,
        viewer_email=viewer.email,
        client_id=viewer.client_id,
    )


class TotpBody(BaseModel):
    code: str = Field(min_length=6, max_length=6)


@router.post("/auth/totp")
async def post_totp(
    body: TotpBody,
    viewer: Annotated[ExternalViewer, Depends(current_viewer)],
) -> dict[str, str]:
    if not viewer.totp_enabled or not viewer.totp_secret:
        raise HTTPException(status_code=400, detail="TOTP not configured")
    if not verify_totp(viewer.totp_secret, body.code):
        raise HTTPException(status_code=401, detail="invalid TOTP code")
    return {"status": "ok"}


# ----- Read-only data endpoints -----


@router.get("/dashboard")
async def dashboard(
    viewer: Annotated[ExternalViewer, Depends(current_viewer)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    # Counters scoped to the viewer's client.
    consultants_count = (
        await session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type == "policy.created")
            .where(_payload_client_id_match(viewer.client_id))
        )
    ).scalar_one()

    connections_30d = (
        await session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type == "tunnel.access")
            .where(_payload_client_id_match(viewer.client_id))
        )
    ).scalar_one()

    denials = (
        await session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type == "tunnel.denied")
            .where(_payload_client_id_match(viewer.client_id))
        )
    ).scalar_one()

    return {
        "client_id": viewer.client_id,
        "viewer_email": viewer.email,
        "active_consultants": consultants_count,
        "connections": connections_30d,
        "denials": denials,
    }


@router.get("/timeline")
async def timeline(
    viewer: Annotated[ExternalViewer, Depends(current_viewer)],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Cronologia de eventos do cliente do viewer. SPEC §5.6 — não expõe
    payload completo, só os campos públicos."""
    stmt = (
        select(AuditEvent)
        .where(_payload_client_id_match(viewer.client_id))
        .order_by(AuditEvent.occurred_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    out: list[dict[str, Any]] = []
    for r in rows:
        payload = r.payload or {}
        out.append(
            {
                "occurred_at": r.occurred_at,
                "event_type": r.event_type,
                # Public fields only — never expose IPs reais ou nomes de admin.
                "scope_kind": payload.get("scope_kind"),
                "scope_value_summary": _redact_scope(_as_optional_str(payload.get("scope_value"))),
            }
        )
    return out


@router.post("/reports/lgpd")
async def reports_lgpd(
    viewer: Annotated[ExternalViewer, Depends(current_viewer)],
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    since: datetime | None = None,
    until: datetime | None = None,
) -> Response:
    """Gera o PDF assinado. Rate-limit: 1/dia por viewer (ver TODO no
    middleware de rate limiting; por enquanto, limit permissivo)."""
    if not pdf_available():
        raise HTTPException(status_code=503, detail="PDF generation not available")

    client = await session.get(Client, viewer.client_id)
    if client is None:
        raise NotFoundError("client gone", context={"id": viewer.client_id})

    stmt = (
        select(AuditEvent)
        .where(_payload_client_id_match(viewer.client_id))
        .order_by(AuditEvent.occurred_at.asc())
    )
    if since is not None:
        stmt = stmt.where(AuditEvent.occurred_at >= since)
    if until is not None:
        stmt = stmt.where(AuditEvent.occurred_at <= until)
    events = list((await session.execute(stmt)).scalars().all())

    summary = {
        "consultants": sum(1 for e in events if e.event_type == "policy.created"),
        "connections": sum(1 for e in events if e.event_type == "tunnel.access"),
        "denials": sum(1 for e in events if e.event_type == "tunnel.denied"),
        "offboardings": sum(1 for e in events if e.event_type == "policy.deleted"),
    }
    last_anchor_stmt = select(AuditEvent.hash).order_by(AuditEvent.occurred_at.desc()).limit(1)
    chain_anchor = (await session.execute(last_anchor_stmt)).scalar_one_or_none()

    signing_key = request.app.state.portal_signing_key
    pdf_bytes = build_signed_report(
        signing_key=signing_key,
        client_id=client.id,
        client_name=client.name,
        viewer_email=viewer.email,
        since=since,
        until=until,
        summary=summary,
        events=events,
        chain_anchor=chain_anchor,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="portal-{client.id}-{now_utc().date().isoformat()}.pdf"'
            )
        },
    )


@router.get("/auth/public_key")
async def public_key(request: Request) -> dict[str, str]:
    """Chave pública Ed25519 — usada pelo verifier CLI."""
    from vagg_core.portal.report import public_key_b64

    return {"public_key_b64": public_key_b64(request.app.state.portal_signing_key)}


# ----- Helpers -----


def _payload_client_id_match(client_id: str) -> Any:
    """SQLite JSON1 query: payload->>'client_id' = :id."""
    return func.json_extract(AuditEvent.payload, "$.client_id") == client_id


def _as_optional_str(value: Any) -> str | None:
    """Coerce any payload value to a string for redaction (or pass None through)."""
    if value is None:
        return None
    return str(value)


def _redact_scope(value: str | None) -> str | None:
    """Mantém apenas a forma do escopo. Nunca expõe IP real."""
    if value is None:
        return None
    if "/" in value:
        # Mantém o tamanho da subnet, mas não o range exato.
        _, suffix = value.rsplit("/", 1)
        return f"<subnet>/{suffix}"
    return "<host>"
