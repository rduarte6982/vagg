"""FastAPI dependencies: DB session, JWT-protected admin identity."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

import jwt as pyjwt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vagg_core.core.errors import AuthRequiredError
from vagg_core.core.security import JWTSigner, TokenType

# tokenUrl is what Swagger UI hits to exchange username/password for a token.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


async def get_db(
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_jwt_signer(request: Request) -> JWTSigner:
    signer: JWTSigner = request.app.state.jwt_signer
    return signer


@dataclass(frozen=True)
class CurrentAdmin:
    """Identity of the authenticated admin (single bootstrap admin in Phase 2)."""

    email: str


async def require_admin(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    signer: Annotated[JWTSigner, Depends(get_jwt_signer)],
) -> CurrentAdmin:
    if not token:
        raise AuthRequiredError("token de acesso ausente")
    try:
        claims = signer.decode(token, expected_type=TokenType.ACCESS)
    except pyjwt.PyJWTError as exc:
        raise AuthRequiredError("token inválido ou expirado") from exc
    return CurrentAdmin(email=str(claims["sub"]))
