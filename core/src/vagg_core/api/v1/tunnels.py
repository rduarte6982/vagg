"""Sub-routes under /api/v1/clients/{id}/* — tunnel lifecycle (SPEC §5.2)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from vagg_core.api.deps import (
    CurrentAdmin,
    get_db,
    get_tunnel_orchestrator,
    require_admin,
)
from vagg_core.core.crypto import CryptoConfigError, decrypt
from vagg_core.core.errors import ConflictError, NotFoundError
from vagg_core.core.logging import get_logger
from vagg_core.db.models import Client, TunnelState, TunnelStatus
from vagg_core.services.tunnel_orchestrator import (
    TotpSeedSpec,
    TunnelOrchestratorProtocol,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/clients/{client_id}", tags=["tunnels"])


class TunnelStatusOut(BaseModel):
    client_id: str
    state: TunnelState
    container_id: str | None
    controller_state: str | None = None
    uptime_s: int | None = None
    last_check_at: datetime | None
    last_error: str | None


class ConnectAck(BaseModel):
    client_id: str
    container_id: str
    state: TunnelState = TunnelState.STARTING


class DisconnectAck(BaseModel):
    client_id: str
    state: TunnelState = TunnelState.STOPPED


class OtpRequest(BaseModel):
    code: str = Field(min_length=4, max_length=16)


class OtpAck(BaseModel):
    client_id: str
    forwarded: bool = True


class LogsOut(BaseModel):
    client_id: str
    lines: list[str]


async def _load_client(session: AsyncSession, client_id: str) -> Client:
    client = await session.get(Client, client_id)
    if client is None:
        raise NotFoundError("cliente não encontrado", context={"id": client_id})
    return client


async def _ensure_status_row(session: AsyncSession, client: Client) -> TunnelStatus:
    if client.tunnel_status is None:
        client.tunnel_status = TunnelStatus(client_id=client.id, state=TunnelState.STOPPED)
        await session.flush()
    return client.tunnel_status


# ----- Endpoints -----


def _decrypt_totp_seed(client: Client) -> TotpSeedSpec | None:
    """Decifra o seed TOTP armazenado, retornando ``TotpSeedSpec`` pronto pro
    orchestrator. Retorna None quando não há seed; levanta ConflictError se
    crypto está mal-configurado (não dá pra cifrar/decifrar)."""
    if not client.totp_secret:
        return None
    try:
        plaintext = decrypt(client.totp_secret)
    except CryptoConfigError as exc:
        raise ConflictError(
            f"seed TOTP armazenado não pode ser decifrado: {exc}",
            context={"client_id": client.id},
        ) from exc
    try:
        payload = json.loads(plaintext)
        return TotpSeedSpec(
            secret=str(payload["secret"]),
            digits=int(payload.get("digits", 6)),
            period=int(payload.get("period", 30)),
            algorithm=str(payload.get("algorithm", "sha1")),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        # Compat: secret legacy gravado como base32 puro (pré-payload JSON).
        return TotpSeedSpec(secret=plaintext)


@router.post("/connect", response_model=ConnectAck, status_code=status.HTTP_202_ACCEPTED)
async def connect_tunnel(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> ConnectAck:
    client = await _load_client(session, client_id)
    if not client.config_text:
        raise ConflictError(
            "cliente não tem config_text definido — atualize via PATCH antes de conectar",
            context={"id": client_id},
        )
    totp_seed = _decrypt_totp_seed(client)
    if totp_seed is not None:
        log.info(
            "tunnel.connect.auto_otp_enabled",
            client_id=client_id,
            digits=totp_seed.digits,
            period=totp_seed.period,
        )
    container_id = await orchestrator.connect(
        client_id=client_id,
        protocol=client.vpn_type,
        config_text=client.config_text,
        username=client.vpn_username,
        password=client.vpn_password,
        requires_otp=bool(client.requires_otp),
        saml_cookie=client.saml_cookie,
        totp_seed=totp_seed,
    )
    status_row = await _ensure_status_row(session, client)
    status_row.state = TunnelState.STARTING
    status_row.container_id = container_id
    status_row.last_error = None
    return ConnectAck(client_id=client_id, container_id=container_id)


@router.post("/disconnect", response_model=DisconnectAck, status_code=status.HTTP_202_ACCEPTED)
async def disconnect_tunnel(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> DisconnectAck:
    client = await _load_client(session, client_id)
    await orchestrator.disconnect(client_id)
    status_row = await _ensure_status_row(session, client)
    status_row.state = TunnelState.STOPPED
    status_row.container_id = None
    status_row.last_error = None
    return DisconnectAck(client_id=client_id)


@router.post("/otp", response_model=OtpAck)
async def submit_otp(
    client_id: str,
    body: OtpRequest,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> OtpAck:
    await _load_client(session, client_id)
    await orchestrator.send_otp(client_id, body.code)
    return OtpAck(client_id=client_id)


@router.get("/status", response_model=TunnelStatusOut)
async def get_tunnel_status(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> TunnelStatusOut:
    client = await _load_client(session, client_id)
    report = await orchestrator.status(client_id)
    status_row = await _ensure_status_row(session, client)
    status_row.state = report.state
    status_row.container_id = report.container_id
    status_row.last_error = report.error
    return TunnelStatusOut(
        client_id=client_id,
        state=report.state,
        container_id=report.container_id,
        controller_state=report.controller_state,
        uptime_s=report.uptime_s,
        last_check_at=status_row.last_check_at,
        last_error=report.error,
    )


@router.get("/logs", response_model=LogsOut)
async def tail_tunnel_logs(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
    tail: int = 100,
) -> LogsOut:
    await _load_client(session, client_id)
    lines = await orchestrator.tail_logs(client_id, lines=tail)
    return LogsOut(client_id=client_id, lines=lines)


class DiscoveredRouteOut(BaseModel):
    cidr: str
    dev: str
    gateway: str | None = None


class DiscoveryOut(BaseModel):
    client_id: str
    routes: list[DiscoveredRouteOut]
    dns_servers: list[str]
    search_domains: list[str]


class SamlLoginStartOut(BaseModel):
    client_id: str
    vpn_type: str
    start_url: str
    # Forti-specific: port + container_id + expected_callback_prefix (browser
    # vai cair em http://127.0.0.1:PORT/?id=X). GP-specific: gateway_host
    # (extensão monitora cookies desse domínio).
    port: int = 0
    expected_callback_prefix: str = ""
    container_id: str | None = None
    portal_url: str | None = None
    gateway_host: str = ""


class SamlLoginRelayIn(BaseModel):
    saml_id: str = Field(min_length=4, max_length=200)


class SamlLoginRelayOut(BaseModel):
    client_id: str
    relayed: bool
    status_code: int


class SamlCookieEntry(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=8192)
    domain: str | None = None


class SamlLoginRelayCookieIn(BaseModel):
    gateway_host: str = Field(min_length=3, max_length=256)
    cookies: list[SamlCookieEntry] = Field(min_length=1, max_length=20)
    # openconnect precisa do --user com o saml-username retornado pelo IdP
    # via custom response header `saml-username:` no /SAML20/SP/ACS. Sem ele,
    # alguns gateways PA rejeitam o /ssl-vpn/login.esp follow-up.
    saml_username: str | None = Field(default=None, max_length=320)


class SamlLoginRelayCookieOut(BaseModel):
    client_id: str
    relayed: bool
    cookie_used: str
    state: TunnelState


@router.post(
    "/saml-login/start",
    response_model=SamlLoginStartOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_saml_login_tunnel(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> SamlLoginStartOut:
    """Inicia o flow SAML-login (openfortivpn --saml-login=PORT).

    Caminho NOVO pra FortiGate Vexia e similares com host-check ativo: sobe
    o container do tunnel direto em modo `--saml-login`. O frontend abre
    `start_url` num popup, o user completa o login Microsoft, o gateway
    redireciona pra `expected_callback_prefix<id>`, frontend posta `id`
    via `/saml-login/relay` → openfortivpn pega cookie internamente → tunnel
    sobe na MESMA TLS session (sem invalidação por TLS pinning).
    """
    client = await _load_client(session, client_id)
    if not client.config_text:
        raise ConflictError(
            "cliente não tem config_text definido",
            context={"id": client_id},
        )
    # Extrai gateway URL do config (host= e port= do openfortivpn.conf)
    host = port = None
    for line in client.config_text.splitlines():
        s = line.strip()
        if s.startswith("host"):
            host = s.split("=", 1)[1].strip().strip('"').strip("'") if "=" in s else None
        elif s.startswith("port"):
            try:
                port = int(s.split("=", 1)[1].strip().strip('"').strip("'"))
            except (ValueError, IndexError):
                pass
    if not host:
        raise ConflictError(
            "config_text do cliente não tem 'host=' — não dá pra montar a URL SAML",
            context={"id": client_id},
        )
    gateway_url = f"https://{host}:{port}" if port else f"https://{host}"

    # Branch por vpn_type:
    #   - openfortivpn: sobe tunnel container com --saml-login=PORT,
    #     extensão captura URL ?id= no popup
    #   - globalprotect: NÃO sobe tunnel ainda. Frontend abre popup pro
    #     /global-protect/login.esp. Extensão monitora cookies no
    #     gateway_host e posta via /saml-login/relay-cookie quando aparecem.
    #     Backend só sobe tunnel quando relay-cookie chega.
    if client.vpn_type.value == "globalprotect":
        # PaloAlto GlobalProtect: chama prelogin.esp com UA GP client,
        # extrai SAMLRequest decoded (URL Microsoft completa), retorna
        # pra frontend. Browser abre direto essa URL. Quando user volta
        # do SAML callback, gateway SETA cookies porque sabe que flow
        # foi iniciado por GP client legítimo (não browser comum).
        import base64
        import httpx
        try:
            # GATEWAY flow (working baseline). PORTAL flow seria ideal (config
            # completo via getconfig.esp) mas requer patch no openconnect source
            # pra não reinjetar VAGG_GP_COOKIE no follow-up /ssl-vpn/login.esp
            # (gateway rejeita cookie portal com HTTP 512). TODO: rebuild image
            # com inject condicional (só na primeira request).
            prelogin_url = f"{gateway_url}/ssl-vpn/prelogin.esp"
            params = {
                "tmp": "tmp",
                "kerberos-support": "yes",
                "ipv6-support": "yes",
                "clientVer": "4100",
            }
            headers = {
                "User-Agent": "PAN GlobalProtect/6.0.1-19 (Windows 10)",
            }
            async with httpx.AsyncClient(verify=False, timeout=15.0) as cl:
                resp = await cl.post(prelogin_url, params=params, headers=headers)
            if resp.status_code != 200:
                raise ConflictError(
                    f"prelogin.esp retornou HTTP {resp.status_code}",
                    context={"client_id": client_id},
                )
            import re as _re
            m = _re.search(r"<saml-request>([^<]+)</saml-request>", resp.text)
            if not m:
                raise ConflictError(
                    "prelogin.esp não retornou saml-request",
                    context={"client_id": client_id, "body_preview": resp.text[:200]},
                )
            saml_b64 = m.group(1).strip()
            ms_url = base64.b64decode(saml_b64).decode("utf-8", errors="replace")
            if not ms_url.startswith("http"):
                raise ConflictError(
                    "saml-request decoded não é URL HTTP",
                    context={"client_id": client_id, "preview": ms_url[:100]},
                )
        except httpx.HTTPError as exc:
            raise ConflictError(
                f"falha chamando prelogin.esp do gateway: {exc}",
                context={"client_id": client_id},
            ) from exc

        return SamlLoginStartOut(
            client_id=client_id,
            vpn_type="globalprotect",
            start_url=ms_url,
            gateway_host=host,
        )

    result = await orchestrator.start_saml_login(
        client_id=client_id,
        gateway_url=gateway_url,
        config_text=client.config_text,
    )
    status_row = await _ensure_status_row(session, client)
    status_row.state = TunnelState.STARTING
    status_row.container_id = result["container_id"]
    status_row.last_error = None
    return SamlLoginStartOut(
        client_id=client_id,
        vpn_type="openfortivpn",
        start_url=result["start_url"],
        port=result["port"],
        expected_callback_prefix=result["expected_callback_prefix"],
        container_id=result["container_id"],
        portal_url=result.get("portal_url"),
        gateway_host=host,
    )


@router.post("/saml-login/relay", response_model=SamlLoginRelayOut)
async def relay_saml_login(
    client_id: str,
    body: SamlLoginRelayIn,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> SamlLoginRelayOut:
    """Recebe o SAML session id capturado pelo browser do user (após o
    FortiGate redirecionar pra http://127.0.0.1:PORT/?id=X) e encaminha
    pro openfortivpn local."""
    await _load_client(session, client_id)
    result = await orchestrator.relay_saml_id(
        client_id=client_id,
        saml_id=body.saml_id,
    )
    return SamlLoginRelayOut(**result)


@router.post(
    "/saml-login/relay-cookie",
    response_model=SamlLoginRelayCookieOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def relay_saml_cookie(
    client_id: str,
    body: SamlLoginRelayCookieIn,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> SamlLoginRelayCookieOut:
    """Recebe cookies SAML capturados pela extensão Chrome (modo GlobalProtect).

    Diferente do `/saml-login/relay` (FortiGate, usa session id), GP devolve
    cookies de auth (`portal-userauthcookie`, `prelogin-cookie`) no domínio
    do gateway após o SAML callback. A extensão lê via chrome.cookies API
    e envia esses cookies aqui. Backend sobe tunnel openconnect com cookie.
    """
    client = await _load_client(session, client_id)
    # Seleciona o melhor cookie: portal-userauthcookie > prelogin-cookie > primeiro
    order = ["portal-userauthcookie", "portalusersso", "PortalUserAuth", "prelogin-cookie"]
    chosen = None
    for name in order:
        for c in body.cookies:
            if c.name == name:
                chosen = c
                break
        if chosen:
            break
    if not chosen:
        chosen = body.cookies[0]
    cookie_value = f"{chosen.name}={chosen.value}"
    # Salva no DB pra subsequent reconnects + dispara connect via orchestrator.connect()
    client.saml_cookie = cookie_value
    # saml_username é o identity assertado pelo IdP. openconnect usa como
    # --user no follow-up /ssl-vpn/login.esp request. Se a extensão não
    # mandou (PaloAlto antigo só retorna cookie), cai no vpn_username
    # cadastrado, e em último caso o entrypoint usa default "vagg-saml".
    effective_user = (body.saml_username or client.vpn_username or "").strip() or None
    if body.saml_username:
        client.vpn_username = body.saml_username
    await session.flush()
    container_id = await orchestrator.connect(
        client_id=client_id,
        protocol=client.vpn_type,
        config_text=client.config_text,
        username=effective_user,
        password=client.vpn_password,
        requires_otp=bool(client.requires_otp),
        saml_cookie=cookie_value,
    )
    status_row = await _ensure_status_row(session, client)
    status_row.state = TunnelState.STARTING
    status_row.container_id = container_id
    status_row.last_error = None
    return SamlLoginRelayCookieOut(
        client_id=client_id,
        relayed=True,
        cookie_used=chosen.name,
        state=TunnelState.STARTING,
    )


@router.get("/discover", response_model=DiscoveryOut)
async def get_tunnel_discovery(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> DiscoveryOut:
    """Lê (sem persistir) rotas e DNS empurrados pelo gateway.

    Útil pro admin auditar o que o auto-discovery vai (ou já) gravou. Read-only.
    """
    await _load_client(session, client_id)
    report = await orchestrator.discover(client_id)
    return DiscoveryOut(
        client_id=client_id,
        routes=[
            DiscoveredRouteOut(cidr=r.cidr, dev=r.dev, gateway=r.gateway)
            for r in report.routes
        ],
        dns_servers=list(report.dns_servers),
        search_domains=list(report.search_domains),
    )
