"""FastAPI dependencies: DB session, JWT-protected admin/user identity."""

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
from vagg_core.services.tunnel_orchestrator import TunnelOrchestratorProtocol

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


@dataclass(frozen=True)
class CurrentUser:
    """Identidade do principal autenticado — admin do .env OU consultor da tabela.

    `consultant_id` é None quando é o admin do .env. `is_admin` é True para o
    admin do .env e para consultores com role=admin.
    """

    subject: str
    role: str
    consultant_id: int | None
    name: str | None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def get_tunnel_orchestrator(request: Request) -> TunnelOrchestratorProtocol:
    orchestrator: TunnelOrchestratorProtocol = request.app.state.tunnel_orchestrator
    return orchestrator


async def require_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    signer: Annotated[JWTSigner, Depends(get_jwt_signer)],
) -> CurrentUser:
    """Aceita admin do .env OU consultor — usado pelo VAGG Client."""
    if not token:
        raise AuthRequiredError("token de acesso ausente")
    try:
        claims = signer.decode(token, expected_type=TokenType.ACCESS)
    except pyjwt.PyJWTError as exc:
        raise AuthRequiredError("token inválido ou expirado") from exc

    subject = str(claims["sub"])
    role = str(claims.get("role") or "admin")  # tokens antigos não têm role → admin
    consultant_id_raw = claims.get("consultant_id")
    consultant_id = int(consultant_id_raw) if consultant_id_raw is not None else None
    name = claims.get("name")
    return CurrentUser(
        subject=subject,
        role=role,
        consultant_id=consultant_id,
        name=str(name) if name else None,
    )


async def require_admin(
    user: Annotated[CurrentUser, Depends(require_user)],
) -> CurrentAdmin:
    """Mantido pra compat: rotas administrativas que recusam consultor não-admin.

    Aceita o admin do .env (sem consultant_id) OU consultor com role=admin.
    """
    if not user.is_admin:
        raise AuthRequiredError("ação requer privilégio de administrador")
    return CurrentAdmin(email=user.subject)
