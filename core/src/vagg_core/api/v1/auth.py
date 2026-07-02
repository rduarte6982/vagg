"""POST /api/v1/auth/login — admin OAuth2 password flow + JWT (SPEC §5.1).

Aceita dois sujeitos:
  - admin: credenciais do .env (`VAGG_CORE_ADMIN_EMAIL`/`VAGG_CORE_ADMIN_PASSWORD_HASH`).
    O JWT recebe `sub=<email>` e `role=admin`.
  - consultor: tabela `consultants` com `password_hash`. Login pode ser pelo
    `email` ou pelo `name` (case-insensitive). JWT recebe `sub=consultant:<id>`
    e `role=<consultant.role>`.
"""

from __future__ import annotations

from typing import Annotated

import jwt as pyjwt
from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vagg_core.api.deps import get_db, get_jwt_signer
from vagg_core.config import Settings
from vagg_core.core.errors import AuthRequiredError, InvalidCredentialsError
from vagg_core.core.security import JWTSigner, TokenType, verify_password
from vagg_core.db.models import Consultant

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth2 spec literal, not a credential
    access_expires_at: str
    refresh_expires_at: str


class RefreshRequest(BaseModel):
    refresh_token: str


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


@router.post("/login", response_model=TokenPair, status_code=status.HTTP_200_OK)
async def login(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    signer: Annotated[JWTSigner, Depends(get_jwt_signer)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPair:
    settings = _settings(request)
    expected_email = settings.admin_email
    expected_hash = settings.admin_password_hash.get_secret_value()

    # 1) Tenta admin do .env primeiro (sem hit no banco).
    if form.username == expected_email and verify_password(form.password, expected_hash):
        access = signer.issue(
            subject=form.username,
            token_type=TokenType.ACCESS,
            extra_claims={"role": "admin"},
        )
        refresh_tok = signer.issue(
            subject=form.username,
            token_type=TokenType.REFRESH,
            extra_claims={"role": "admin"},
        )
        return TokenPair(
            access_token=access.token,
            refresh_token=refresh_tok.token,
            access_expires_at=access.expires_at.isoformat(),
            refresh_expires_at=refresh_tok.expires_at.isoformat(),
        )

    # 2) Tenta consultor — primeiro por email (único), depois por name.
    # Não dá pra usar OR + scalar_one_or_none porque podem existir vários
    # consultores com o mesmo nome (apenas email é UNIQUE).
    username_lower = form.username.lower()
    consultant = await session.scalar(
        select(Consultant).where(Consultant.email == username_lower).limit(1)
    )
    if consultant is None:
        # ilike é case-insensitive em ambos SQLite e Postgres.
        consultant = await session.scalar(
            select(Consultant).where(Consultant.name.ilike(form.username)).limit(1)
        )
    if (
        consultant is not None
        and consultant.active
        and consultant.password_hash
        and verify_password(form.password, consultant.password_hash)
    ):
        subject = f"consultant:{consultant.id}"
        extra = {"role": consultant.role, "consultant_id": consultant.id, "name": consultant.name}
        access = signer.issue(subject=subject, token_type=TokenType.ACCESS, extra_claims=extra)
        refresh_tok = signer.issue(subject=subject, token_type=TokenType.REFRESH, extra_claims=extra)
        return TokenPair(
            access_token=access.token,
            refresh_token=refresh_tok.token,
            access_expires_at=access.expires_at.isoformat(),
            refresh_expires_at=refresh_tok.expires_at.isoformat(),
        )

    raise InvalidCredentialsError("usuário ou senha inválidos")


@router.post("/refresh", response_model=TokenPair, status_code=status.HTTP_200_OK)
async def refresh(
    body: RefreshRequest,
    signer: Annotated[JWTSigner, Depends(get_jwt_signer)],
) -> TokenPair:
    try:
        claims = signer.decode(body.refresh_token, expected_type=TokenType.REFRESH)
    except pyjwt.PyJWTError as exc:
        raise AuthRequiredError("refresh_token inválido ou expirado") from exc

    subject = str(claims["sub"])
    extra = {k: v for k, v in claims.items() if k in {"role", "consultant_id", "name"}}
    access = signer.issue(subject=subject, token_type=TokenType.ACCESS, extra_claims=extra)
    refresh_token = signer.issue(subject=subject, token_type=TokenType.REFRESH, extra_claims=extra)
    return TokenPair(
        access_token=access.token,
        refresh_token=refresh_token.token,
        access_expires_at=access.expires_at.isoformat(),
        refresh_expires_at=refresh_token.expires_at.isoformat(),
    )
