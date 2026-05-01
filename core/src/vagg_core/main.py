"""FastAPI entrypoint for vagg-core.

Use the factory pattern with uvicorn so importing this module never triggers
``Settings()`` at load time:

    uvicorn --factory vagg_core.main:create_app
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from vagg_core import __version__
from vagg_core.api.v1 import audit, auth, clients, consultants, policies, system, tunnels
from vagg_core.config import Settings, get_settings
from vagg_core.core.errors import CoreError
from vagg_core.core.logging import configure_logging, get_logger
from vagg_core.core.security import JWTSigner
from vagg_core.db.session import make_engine, make_session_factory

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    engine = make_engine(settings.database_url.get_secret_value())
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    app.state.jwt_signer = JWTSigner(
        secret=settings.jwt_secret.get_secret_value(),
        issuer=settings.jwt_issuer,
        access_ttl_seconds=settings.jwt_access_ttl_seconds,
        refresh_ttl_seconds=settings.jwt_refresh_ttl_seconds,
    )

    log.info("vagg_core.started", version=__version__, environment=settings.environment)
    try:
        yield
    finally:
        await engine.dispose()
        log.info("vagg_core.stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="VPN Aggregator Core",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(clients.router)
    app.include_router(consultants.router)
    app.include_router(policies.router)
    app.include_router(tunnels.router)
    app.include_router(audit.router)

    @app.exception_handler(CoreError)
    async def _domain_error_handler(_: Request, exc: CoreError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    return app
