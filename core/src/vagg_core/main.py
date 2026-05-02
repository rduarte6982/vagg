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
from vagg_core.portal import router as portal_router
from vagg_core.portal.admin import router as portal_admin_router
from vagg_core.portal.report import load_or_create_signing_key
from vagg_core.services.dns_manager import DnsManagerProtocol, maybe_dns_manager
from vagg_core.services.network_applier import NetworkApplier, shell_runner
from vagg_core.services.network_manager import NetworkManager
from vagg_core.services.tunnel_orchestrator import (
    TunnelOrchestrator,
    default_image_map,
    docker_from_env,
)
from vagg_core.workers.tunnel_health import TunnelHealthWorker

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

    # Network manager (SPEC §4.2 / §4.3). Disabled by default; production
    # installer sets ``network_apply_enabled=true`` to push iptables to the host.
    network_manager: NetworkManager | None = None
    if settings.network_apply_enabled:
        applier = NetworkApplier(
            runner=shell_runner,
            rt_tables_path=settings.rt_tables_path,
        )
        network_manager = NetworkManager(
            session_factory=app.state.session_factory,
            applier=applier,
            virtual_range=settings.virtual_range,
        )
    app.state.network_manager = network_manager

    # Tunnel orchestrator (SPEC §5.2 / Fase 3). The Docker client is created here so
    # connection failures surface in startup logs, not on the first request.
    docker_client = docker_from_env()
    app.state.docker = docker_client

    # DNS manager (SPEC §4.4 / §5.3). Disabled by default; installer turns it
    # on and points dns_config_path at the volume the vagg-dns container reads.
    dns_manager: DnsManagerProtocol = maybe_dns_manager(
        enabled=settings.dns_enabled,
        session_factory=app.state.session_factory,
        config_path=settings.dns_config_path,
        domain=settings.domain,
        docker=docker_client,
        container_name=settings.dns_container_name,
    )
    app.state.dns_manager = dns_manager

    # Seed an initial Corefile so vagg-dns finds *something* on first start
    # (otherwise coredns crashes and restart-loops until a tunnel triggers
    # regenerate). Best-effort — if it fails, the worker retries later.
    if settings.dns_enabled:
        try:
            await dns_manager.regenerate()
        except Exception as exc:  # noqa: BLE001
            log.warning("vagg_core.dns_regenerate_init_failed", error=str(exc))

    app.state.tunnel_orchestrator = TunnelOrchestrator(
        docker=docker_client,
        config_dir=settings.tunnels_config_dir,
        sockets_dir=settings.tunnels_sockets_dir,
        image_by_protocol=default_image_map(settings.tunnels_image_tag),
        network_name=settings.tunnels_network_name,
        restart_policy=settings.tunnels_restart_policy,
        controller_timeout_s=settings.tunnels_controller_timeout_s,
        network_manager=network_manager,
        dns_manager=dns_manager,
    )

    # Portal signing key (Fase 11). Loaded once at startup so the lifespan
    # surfaces a fresh key file if the volume was reset; subsequent requests
    # re-use the cached key.
    if settings.portal_enabled:
        app.state.portal_signing_key = load_or_create_signing_key(settings.portal_signing_key_path)

    health_worker = TunnelHealthWorker(
        session_factory=app.state.session_factory,
        orchestrator=app.state.tunnel_orchestrator,
        interval_s=settings.tunnels_health_interval_s,
    )
    app.state.tunnel_health_worker = health_worker
    if settings.tunnels_health_enabled:
        health_worker.start()

    log.info("vagg_core.started", version=__version__, environment=settings.environment)
    try:
        yield
    finally:
        await health_worker.stop()
        try:
            await docker_client.close()
        except Exception as exc:  # noqa: BLE001 — log but don't crash shutdown
            log.warning("vagg_core.docker_close_failed", error=str(exc))
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
    app.include_router(portal_admin_router)
    app.include_router(portal_router)

    @app.exception_handler(CoreError)
    async def _domain_error_handler(_: Request, exc: CoreError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    return app
