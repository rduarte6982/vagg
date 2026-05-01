"""FastAPI entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from vagg_license import __version__
from vagg_license.api import activate, refresh, system, webhook_stripe
from vagg_license.config import Settings, get_settings
from vagg_license.core.errors import LicenseServerError
from vagg_license.core.logging import configure_logging, get_logger
from vagg_license.db.models import Plan
from vagg_license.db.session import make_engine, make_session_factory
from vagg_license.services.jwt_signer import JWTSigner
from vagg_license.services.stripe_client import StripeClient

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    engine = make_engine(settings.database_url.get_secret_value())
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    app.state.jwt_signer = JWTSigner(
        private_key_pem=settings.jwt_private_key_pem.get_secret_value(),
        public_key_pem=settings.jwt_public_key_pem,
        issuer=settings.jwt_issuer,
        ttl_seconds=settings.jwt_ttl_seconds,
    )

    app.state.stripe_client = StripeClient(
        api_key=settings.stripe_api_key.get_secret_value(),
        webhook_secret=settings.stripe_webhook_secret.get_secret_value(),
        webhook_tolerance_seconds=settings.stripe_webhook_tolerance_seconds,
        plan_by_price_id={
            settings.stripe_price_id_starter: Plan.STARTER,
            settings.stripe_price_id_professional: Plan.PROFESSIONAL,
            settings.stripe_price_id_enterprise: Plan.ENTERPRISE,
        },
    )

    log.info("license_server.started", version=__version__, environment=settings.environment)
    try:
        yield
    finally:
        await engine.dispose()
        log.info("license_server.stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="VPN Aggregator License Server",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    app.include_router(system.router)
    app.include_router(activate.router)
    app.include_router(refresh.router)
    app.include_router(webhook_stripe.router)

    @app.exception_handler(LicenseServerError)
    async def _domain_error_handler(_: Request, exc: LicenseServerError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    return app


# Uvicorn entrypoint uses the factory pattern: `uvicorn vagg_license.main:create_app --factory`.
# This avoids evaluating Settings() (which requires env vars) at module import time, so tests
# can `from vagg_license.main import create_app` without triggering missing-env errors.
