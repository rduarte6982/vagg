"""FastAPI dependencies that pull singletons from app.state and yield request-scoped sessions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vagg_license.services.jwt_signer import JWTSigner
from vagg_license.services.license_store import LicenseStore
from vagg_license.services.stripe_client import StripeClient


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


async def get_db_session(
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    """Open a session for the request, commit on success, rollback on error."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_license_store(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LicenseStore:
    return LicenseStore(session)


def get_jwt_signer(request: Request) -> JWTSigner:
    signer: JWTSigner = request.app.state.jwt_signer
    return signer


def get_stripe_client(request: Request) -> StripeClient:
    client: StripeClient = request.app.state.stripe_client
    return client
