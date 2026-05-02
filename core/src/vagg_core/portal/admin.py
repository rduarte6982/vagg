"""Admin endpoints to manage external viewers (SPEC §5.6 / Fase 11).

Lives under ``/api/v1/external-viewers`` so it stays clearly separated from
the public ``/portal`` surface. Admin-only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vagg_core.api.deps import CurrentAdmin, get_db, require_admin
from vagg_core.core.errors import ConflictError, NotFoundError
from vagg_core.db.models import Client, ExternalViewer
from vagg_core.portal.auth import generate_totp_secret, totp_provisioning_uri
from vagg_core.services.audit import record_event

router = APIRouter(prefix="/api/v1/external-viewers", tags=["external-viewers"])


class ExternalViewerCreate(BaseModel):
    client_id: str = Field(min_length=1, max_length=64)
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=128)
    role: str = Field(default="auditor")
    enable_totp: bool = False


class ExternalViewerOut(BaseModel):
    id: int
    client_id: str
    email: str
    display_name: str
    role: str
    totp_enabled: bool
    invited_at: datetime
    last_login_at: datetime | None
    active: bool
    totp_uri: str | None = None  # populated only on creation


@router.post("", response_model=ExternalViewerOut, status_code=status.HTTP_201_CREATED)
async def create_viewer(
    body: ExternalViewerCreate,
    actor: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ExternalViewerOut:
    if not await session.get(Client, body.client_id):
        raise NotFoundError("client not found", context={"id": body.client_id})

    existing = (
        await session.execute(
            select(ExternalViewer).where(
                ExternalViewer.client_id == body.client_id,
                ExternalViewer.email == body.email,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(
            "auditor já cadastrado para este cliente",
            context={"client_id": body.client_id, "email": body.email},
        )

    secret = generate_totp_secret() if body.enable_totp else None
    viewer = ExternalViewer(
        client_id=body.client_id,
        email=body.email,
        display_name=body.display_name,
        role=body.role,
        totp_enabled=body.enable_totp,
        totp_secret=secret,
        invited_by_id=getattr(actor, "id", None),
    )
    session.add(viewer)
    await session.flush()

    await record_event(
        session,
        event_type="external_viewer.invited",
        actor_consultant_id=getattr(actor, "id", None),
        payload={
            "viewer_id": viewer.id,
            "client_id": viewer.client_id,
            "email": viewer.email,
        },
    )

    return ExternalViewerOut(
        id=viewer.id,
        client_id=viewer.client_id,
        email=viewer.email,
        display_name=viewer.display_name,
        role=viewer.role,
        totp_enabled=viewer.totp_enabled,
        invited_at=viewer.invited_at,
        last_login_at=viewer.last_login_at,
        active=viewer.active,
        totp_uri=(
            totp_provisioning_uri(secret, account=viewer.email, issuer="vagg-portal")
            if secret
            else None
        ),
    )


@router.get("", response_model=list[ExternalViewerOut])
async def list_viewers(
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    client_id: str | None = None,
) -> list[ExternalViewerOut]:
    stmt = select(ExternalViewer).order_by(ExternalViewer.invited_at.desc())
    if client_id is not None:
        stmt = stmt.where(ExternalViewer.client_id == client_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        ExternalViewerOut(
            id=v.id,
            client_id=v.client_id,
            email=v.email,
            display_name=v.display_name,
            role=v.role,
            totp_enabled=v.totp_enabled,
            invited_at=v.invited_at,
            last_login_at=v.last_login_at,
            active=v.active,
        )
        for v in rows
    ]


@router.delete("/{viewer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_viewer(
    viewer_id: int,
    actor: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    obj = await session.get(ExternalViewer, viewer_id)
    if obj is None:
        raise NotFoundError("viewer not found", context={"id": viewer_id})
    payload = {"viewer_id": obj.id, "client_id": obj.client_id, "email": obj.email}
    await session.delete(obj)
    await session.flush()
    await record_event(
        session,
        event_type="external_viewer.removed",
        actor_consultant_id=getattr(actor, "id", None),
        payload=payload,
    )
