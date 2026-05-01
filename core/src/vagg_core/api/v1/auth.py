"""POST /api/v1/auth/login and /refresh — admin OAuth2 password flow + JWT (SPEC §5.1)."""

from __future__ import annotations

from typing import Annotated

import jwt as pyjwt
from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from vagg_core.api.deps import get_jwt_signer
from vagg_core.config import Settings
from vagg_core.core.errors import AuthRequiredError, InvalidCredentialsError
from vagg_core.core.security import JWTSigner, TokenType, verify_password

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
) -> TokenPair:
    settings = _settings(request)
    expected_email = settings.admin_email
    expected_hash = settings.admin_password_hash.get_secret_value()

    if form.username != expected_email or not verify_password(form.password, expected_hash):
        raise InvalidCredentialsError("usuário ou senha inválidos")

    access = signer.issue(subject=form.username, token_type=TokenType.ACCESS)
    refresh = signer.issue(subject=form.username, token_type=TokenType.REFRESH)
    return TokenPair(
        access_token=access.token,
        refresh_token=refresh.token,
        access_expires_at=access.expires_at.isoformat(),
        refresh_expires_at=refresh.expires_at.isoformat(),
    )


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
    access = signer.issue(subject=subject, token_type=TokenType.ACCESS)
    refresh_token = signer.issue(subject=subject, token_type=TokenType.REFRESH)
    return TokenPair(
        access_token=access.token,
        refresh_token=refresh_token.token,
        access_expires_at=access.expires_at.isoformat(),
        refresh_expires_at=refresh_token.expires_at.isoformat(),
    )
