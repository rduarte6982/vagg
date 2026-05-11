"""CRUD over Client + nested NAT mappings (SPEC §5.1, §4.2)."""

from __future__ import annotations

import contextlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vagg_core.api.deps import CurrentAdmin, get_db, get_tunnel_orchestrator, require_admin
from vagg_core.core.errors import ConflictError, NotFoundError
from vagg_core.db.models import Client, NatMapping, TunnelState, TunnelStatus, VpnType
from vagg_core.services.tunnel_orchestrator import TunnelOrchestratorProtocol

router = APIRouter(prefix="/api/v1/clients", tags=["clients"])

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")


# ----- Schemas -----


class NatMappingPayload(BaseModel):
    virtual_cidr: str = Field(min_length=9, max_length=43)
    real_cidr: str = Field(min_length=9, max_length=43)
    description: str | None = Field(default=None, max_length=512)


class ClientCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64, description="kebab-case slug")
    name: str = Field(min_length=1, max_length=128)
    vpn_type: VpnType
    virtual_cidr: str = Field(min_length=9, max_length=43)
    real_cidr: str = Field(min_length=9, max_length=43)
    dns_server: str | None = Field(default=None, max_length=45)
    description: str | None = Field(default=None, max_length=512)
    config_text: str | None = Field(default=None, description=".ovpn ou equivalente")
    vpn_username: str | None = Field(default=None, max_length=128)
    vpn_password: str | None = Field(default=None, max_length=256)
    requires_otp: bool = Field(
        default=False,
        description="[deprecated] use auth_method='otp'. Mantido pra compat.",
    )
    auth_method: Literal["none", "otp", "saml"] = Field(
        default="none",
        description="Método de autenticação MFA. 'none' = só user/senha, "
        "'otp' = token de app autenticador, 'saml' = SSO via browser.",
    )
    nat_mappings: list[NatMappingPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_required_credentials(self) -> "ClientCreate":
        # SAML/OTP precisam de vpn_username — pra OTP é o user da VPN; pra
        # SAML é o identity (UPN/email AD) que o gateway usa pra amarrar o
        # cookie capturado. Sem isso o openconnect manda 'vagg-saml' como
        # user e o gateway rejeita ("Invalid username or password").
        if self.auth_method in ("otp", "saml"):
            if not (self.vpn_username and self.vpn_username.strip()):
                raise ValueError(
                    f"vpn_username é obrigatório quando auth_method='{self.auth_method}'"
                )
        if self.auth_method == "otp":
            if not (self.vpn_password and self.vpn_password.strip()):
                raise ValueError("vpn_password é obrigatório quando auth_method='otp'")
        return self


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    vpn_type: VpnType | None = None
    virtual_cidr: str | None = Field(default=None, min_length=9, max_length=43)
    real_cidr: str | None = Field(default=None, min_length=9, max_length=43)
    dns_server: str | None = Field(default=None, max_length=45)
    description: str | None = Field(default=None, max_length=512)
    config_text: str | None = None
    vpn_username: str | None = Field(default=None, max_length=128)
    vpn_password: str | None = Field(default=None, max_length=256)
    requires_otp: bool | None = None
    auth_method: Literal["none", "otp", "saml"] | None = None
    # Cookie SAML manual — usado quando o user captura via gp-saml-gui
    # ou ferramenta similar e cola no VAGG. None = não altera; ""/null no
    # JSON apaga o cookie atual.
    saml_cookie: str | None = None
    saml_cookie_expires_at: datetime | None = None
    # Substitui completamente a lista de nat_mappings se fornecido. Usado
    # pelo auto-detect de rotas push da VPN — quando o tunel sobe, a UI
    # detecta as rotas e atualiza essa lista.
    nat_mappings: list[NatMappingPayload] | None = None


class NatMappingOut(BaseModel):
    id: int
    virtual_cidr: str
    real_cidr: str
    description: str | None


class ClientOut(BaseModel):
    id: str
    name: str
    vpn_type: VpnType
    virtual_cidr: str
    real_cidr: str
    dns_server: str | None
    description: str | None
    has_config: bool = Field(description="True if config_text is set; raw .ovpn is not exposed")
    has_credentials: bool = Field(description="True if vpn_username/password are set")
    requires_otp: bool = Field(default=False, description="True se exige token MFA no connect")
    auth_method: Literal["none", "otp", "saml"] = Field(
        default="none", description="Método de auth: none/otp/saml"
    )
    has_saml_cookie: bool = Field(
        default=False, description="True se há cookie SAML válido salvo (não expirado)"
    )
    saml_cookie_expires_at: datetime | None = Field(
        default=None, description="Validade do cookie SAML capturado"
    )
    created_at: datetime
    updated_at: datetime
    tunnel_state: TunnelState
    tunnel_last_error: str | None = Field(
        default=None,
        description="Último erro reportado pelo orchestrator quando state=errored",
    )
    tunnel_last_check_at: datetime | None = Field(
        default=None, description="Quando foi a última verificação do túnel"
    )
    nat_mappings: list[NatMappingOut]


# ----- Helpers -----


def _resolve_auth_fields(
    auth_method: str | None, requires_otp: bool | None
) -> dict[str, object]:
    """Sincroniza auth_method (source of truth) com requires_otp (legacy).

    Regra: se auth_method foi setado explicitamente, ele manda. Se não, e
    requires_otp=True, vira auth_method='otp'. Caso contrário, 'none'.
    """
    if auth_method and auth_method != "none":
        return {"auth_method": auth_method, "requires_otp": (auth_method == "otp")}
    if requires_otp:
        return {"auth_method": "otp", "requires_otp": True}
    return {"auth_method": "none", "requires_otp": False}


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise ConflictError(
            "id de cliente deve ser kebab-case (a-z, 0-9, hífens)",
            context={"id": slug},
        )


async def _load_client(session: AsyncSession, client_id: str) -> Client:
    result = await session.execute(select(Client).where(Client.id == client_id))
    obj = result.scalar_one_or_none()
    if obj is None:
        raise NotFoundError("cliente não encontrado", context={"id": client_id})
    return obj


# ----- SAML endpoints -----


class SamlStartResponse(BaseModel):
    portal_url: str = Field(description="URL HTTP do xpra-html5 — embute em iframe")
    expires_at: datetime
    container_id: str


class SamlPollResponse(BaseModel):
    captured: bool
    cookie_expires_at: datetime | None = None
    error: str | None = None


class SamlStartRequest(BaseModel):
    gateway_url: str | None = Field(
        default=None,
        description="URL do portal SAML (default: deriva do config_text). "
        "Ex: https://vpn.minerva.com.br/global-protect/login.esp",
    )


class SamlPreloginResponse(BaseModel):
    """Resposta do prelogin GP — URL Microsoft pronta pro user autenticar
    no próprio browser dele."""

    idp_url: str = Field(description="URL do IdP (Microsoft) já com SAMLRequest")
    method: str = Field(description="REDIRECT ou POST")
    gateway_host: str = Field(description="Host do GP — pra capturar cookie depois")
    cookie_capture_hint: str = Field(
        description="Como o user encontra o cookie depois de autenticar"
    )


def _to_out(client: Client) -> ClientOut:
    state = client.tunnel_status.state if client.tunnel_status else TunnelState.STOPPED
    last_error = client.tunnel_status.last_error if client.tunnel_status else None
    last_check = client.tunnel_status.last_check_at if client.tunnel_status else None
    return ClientOut(
        id=client.id,
        name=client.name,
        vpn_type=client.vpn_type,
        virtual_cidr=client.virtual_cidr,
        real_cidr=client.real_cidr,
        dns_server=client.dns_server,
        description=client.description,
        has_config=bool(client.config_text),
        has_credentials=bool(client.vpn_username or client.vpn_password),
        requires_otp=bool(client.requires_otp),
        auth_method=client.auth_method or "none",  # type: ignore[arg-type]
        has_saml_cookie=bool(client.saml_cookie),
        saml_cookie_expires_at=client.saml_cookie_expires_at,
        created_at=client.created_at,
        updated_at=client.updated_at,
        tunnel_state=state,
        tunnel_last_error=last_error,
        tunnel_last_check_at=last_check,
        nat_mappings=[
            NatMappingOut(
                id=m.id,
                virtual_cidr=m.virtual_cidr,
                real_cidr=m.real_cidr,
                description=m.description,
            )
            for m in client.nat_mappings
        ],
    )


# ----- Endpoints -----


@router.get("", response_model=list[ClientOut])
async def list_clients(
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ClientOut]:
    result = await session.execute(select(Client).order_by(Client.id).limit(limit).offset(offset))
    rows = result.scalars().all()
    # ``Client`` declares lazy="selectin" on nat_mappings/tunnel_status, so the
    # relationships were already fetched in the same SELECT pipeline.
    return [_to_out(c) for c in rows]


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
async def create_client(
    body: ClientCreate,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ClientOut:
    _validate_slug(body.id)
    client = Client(
        id=body.id,
        name=body.name,
        vpn_type=body.vpn_type,
        virtual_cidr=body.virtual_cidr,
        real_cidr=body.real_cidr,
        dns_server=body.dns_server,
        description=body.description,
        config_text=body.config_text,
        vpn_username=body.vpn_username,
        vpn_password=body.vpn_password,
        **_resolve_auth_fields(body.auth_method, body.requires_otp),
    )
    for mapping in body.nat_mappings:
        client.nat_mappings.append(
            NatMapping(
                virtual_cidr=mapping.virtual_cidr,
                real_cidr=mapping.real_cidr,
                description=mapping.description,
            )
        )
    # Tunnel starts in 'stopped' until Phase 3 orchestrator brings it up.
    client.tunnel_status = TunnelStatus(state=TunnelState.STOPPED)
    session.add(client)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "cliente já existe ou viola restrição de unicidade",
            context={"id": body.id},
        ) from exc
    await session.refresh(client)
    return _to_out(client)


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ClientOut:
    client = await _load_client(session, client_id)
    await session.refresh(client)
    return _to_out(client)


@router.patch("/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: str,
    body: ClientUpdate,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ClientOut:
    client = await _load_client(session, client_id)
    updates = body.model_dump(exclude_unset=True, exclude_none=False)

    # nat_mappings é uma relação — lida separadamente. Substitui a lista
    # inteira quando informado.
    new_nat = updates.pop("nat_mappings", None)

    # auth_method ↔ requires_otp: se um foi tocado, sincroniza ambos.
    if "auth_method" in updates or "requires_otp" in updates:
        am = updates.pop("auth_method", None)
        ro = updates.pop("requires_otp", None)
        # Se ambos foram passados, auth_method vence; senão usa o que veio.
        resolved = _resolve_auth_fields(
            am if am is not None else (client.auth_method or "none"),
            ro if ro is not None else client.requires_otp,
        )
        if am is not None:
            resolved = _resolve_auth_fields(am, resolved.get("requires_otp"))  # type: ignore[arg-type]
        updates["auth_method"] = resolved["auth_method"]
        updates["requires_otp"] = resolved["requires_otp"]

    for field, value in updates.items():
        setattr(client, field, value)

    # Pós-merge: SAML/OTP exigem vpn_username; OTP também exige password.
    # vpn_password tem semântica "vazio = manter atual" no UI, então só
    # rejeita se o cliente também não tiver senha persistida no banco.
    final_method = client.auth_method or "none"
    final_user = (client.vpn_username or "").strip()
    if final_method in ("otp", "saml") and not final_user:
        raise ConflictError(
            f"vpn_username é obrigatório quando auth_method='{final_method}'",
            context={"client_id": client_id, "auth_method": final_method},
        )
    if final_method == "otp" and not (client.vpn_password or "").strip():
        raise ConflictError(
            "vpn_password é obrigatório quando auth_method='otp'",
            context={"client_id": client_id},
        )

    if new_nat is not None:
        # Remove os existentes e adiciona os novos. SQLAlchemy cascade cuida
        # do delete porque relationship tem cascade="all, delete-orphan".
        client.nat_mappings.clear()
        await session.flush()
        for entry in new_nat:
            client.nat_mappings.append(
                NatMapping(
                    virtual_cidr=entry["virtual_cidr"],
                    real_cidr=entry["real_cidr"],
                    description=entry.get("description"),
                )
            )

    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("violação de restrição na atualização") from exc
    await session.refresh(client)
    return _to_out(client)


class ClientConfigOut(BaseModel):
    """Snapshot completo dos campos sensíveis pra preencher o modal de edição.
    Inclui config_text e vpn_username; senha NUNCA é retornada."""

    config_text: str | None
    vpn_username: str | None


@router.get("/{client_id}/config", response_model=ClientConfigOut)
async def get_client_config(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ClientConfigOut:
    client = await _load_client(session, client_id)
    return ClientConfigOut(
        config_text=client.config_text,
        vpn_username=client.vpn_username,
    )


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    client = await _load_client(session, client_id)
    await session.delete(client)


def _derive_gateway_url(config_text: str | None) -> str | None:
    """Extrai URL do gateway SAML do config_text. Suporta:
    - openconnect/gp: linha "host=..." ou "server=..."
    - openfortivpn: "host=..." + "port=..." (porta default 10443)
    - openvpn: "remote <host> <port>" → https://<host>
    """
    if not config_text:
        return None
    host: str | None = None
    port: str | None = None
    for line in config_text.splitlines():
        m = re.match(r"^\s*(host|server)\s*[=:]?\s*(\S+)", line, re.IGNORECASE)
        if m:
            host = m.group(2).strip().strip('"').strip("'")
            continue
        m = re.match(r"^\s*port\s*[=:]?\s*(\d+)", line, re.IGNORECASE)
        if m:
            port = m.group(1)
            continue
        m = re.match(r"^\s*remote\s+(\S+)(?:\s+(\d+))?", line, re.IGNORECASE)
        if m:
            host = m.group(1)
            # openvpn UDP/TCP — pra SAML não faz sentido, mas mantem por compat.
            return f"https://{host}"
    if host:
        if host.startswith(("http://", "https://")):
            return host
        # Se o host não tem schema e tem port explícita, junta. Caso contrário
        # deixa schema padrão (https) com port default.
        if port:
            return f"https://{host}:{port}"
        return f"https://{host}"
    return None


@router.post("/{client_id}/saml/prelogin", response_model=SamlPreloginResponse)
async def saml_prelogin(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SamlPreloginResponse:
    """Faz o prelogin SAML do GP gateway com User-Agent spoof, decodifica
    a URL do IdP (Microsoft) e devolve pro frontend.

    O user abre essa URL no próprio browser, faz login Microsoft normal
    (com extensões/MFA/biometria), e o gateway GP captura o cookie. Depois
    o user copia o cookie de DevTools e cola via /saml/cookie.
    """
    import base64
    import re as _re
    from urllib.parse import urlparse

    import httpx

    client = await _load_client(session, client_id)
    gw = _derive_gateway_url(client.config_text)
    if not gw:
        raise ConflictError(
            "não consegui derivar URL do gateway",
            context={"client_id": client_id},
        )
    parsed = urlparse(gw)
    host = parsed.hostname
    if not host:
        raise ConflictError("host inválido", context={"gw": gw})

    prelogin_url = (
        f"https://{host}/ssl-vpn/prelogin.esp"
        "?tmp=tmp&kerberos-support=yes&ipv6-support=yes&clientVer=4100"
    )
    headers = {
        "User-Agent": "PAN GlobalProtect/6.0.1-19 (Windows 10)",
    }
    async with httpx.AsyncClient(verify=False, timeout=15.0) as h:
        r = await h.post(prelogin_url, headers=headers)
    if r.status_code != 200:
        raise ConflictError(
            f"gateway retornou {r.status_code} no prelogin",
            context={"url": prelogin_url, "status": r.status_code},
        )

    body = r.text
    m = _re.search(r"<saml-request>([^<]+)</saml-request>", body)
    if not m:
        raise ConflictError(
            "gateway não retornou saml-request — gateway pode não estar "
            "configurado pra SAML, ou retornou erro",
            context={"body_excerpt": body[:300]},
        )
    saml_request_b64 = m.group(1).strip()
    try:
        idp_url = base64.b64decode(saml_request_b64).decode("utf-8").strip()
    except Exception as exc:
        raise ConflictError(f"falha ao decodificar saml-request: {exc}") from exc

    method_match = _re.search(r"<saml-auth-method>([^<]+)</saml-auth-method>", body)
    method = method_match.group(1).strip() if method_match else "REDIRECT"

    return SamlPreloginResponse(
        idp_url=idp_url,
        method=method,
        gateway_host=host,
        cookie_capture_hint=(
            f"Após o login Microsoft, abra DevTools (F12) → Network. Procure "
            f"a última resposta XML do {host} contendo "
            f"<prelogin-cookie>VALOR</prelogin-cookie>. Copie o VALOR e cole "
            f"no campo de cookie aqui no painel."
        ),
    )


@router.post("/{client_id}/saml/start", response_model=SamlStartResponse)
async def saml_start(
    client_id: str,
    body: SamlStartRequest,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> SamlStartResponse:
    """Inicia browser remoto pra captura do cookie SAML (Azure AD / SSO).

    Frontend embute portal_url num iframe e o user faz login normal —
    quando o login completa, o helper dentro do container detecta e grava
    o cookie em /share/cookie. Frontend faz polling em /saml/poll até
    captured=True.
    """
    client = await _load_client(session, client_id)
    gw = body.gateway_url or _derive_gateway_url(client.config_text)
    if not gw:
        raise ConflictError(
            "não consegui derivar a URL do gateway SAML — informe gateway_url ou "
            "preencha config_text com 'host=...' ou 'server=...'",
            context={"client_id": client_id},
        )
    # Determina o "kind" do SAML portal pelo protocolo do cliente.
    # GP (GlobalProtect / PA) usa hierarquia de cookies (prelogin → portal-userauthcookie).
    # FortiGate usa um único SVPNCOOKIE — fluxo mais simples no addon mitmproxy.
    kind = "forti" if client.vpn_type == VpnType.OPENFORTIVPN else "gp"
    sess = await orchestrator.start_saml_portal(
        client_id=client_id, gateway_url=gw, kind=kind
    )
    return SamlStartResponse(
        portal_url=sess.portal_url,
        expires_at=sess.expires_at,
        container_id=sess.container_id,
    )


@router.get("/{client_id}/saml/poll", response_model=SamlPollResponse)
async def saml_poll(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> SamlPollResponse:
    """Polling pelo cookie capturado. Quando captured=True, salva no banco
    automaticamente e retorna a expiração."""
    client = await _load_client(session, client_id)
    poll = await orchestrator.poll_saml_cookie(client_id)
    if poll.captured and poll.cookie:
        client.saml_cookie = poll.cookie
        client.saml_cookie_expires_at = poll.cookie_expires_at
        await session.flush()
        # Para o portal: cookie já foi capturado.
        await orchestrator.stop_saml_portal(client_id)
    return SamlPollResponse(
        captured=poll.captured,
        cookie_expires_at=poll.cookie_expires_at,
        error=poll.error,
    )


@router.delete("/{client_id}/saml/cookie", status_code=status.HTTP_204_NO_CONTENT)
async def saml_clear_cookie(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> None:
    """Apaga cookie SAML salvo (forçar re-autenticação no próximo connect)."""
    client = await _load_client(session, client_id)
    client.saml_cookie = None
    client.saml_cookie_expires_at = None
    with contextlib.suppress(Exception):
        await orchestrator.stop_saml_portal(client_id)


# Nomes de cookie aceitos quando o user cola manualmente, em ORDEM DE
# PREFERÊNCIA pra cada protocolo. Se a paste tem mais de um nome conhecido
# (ex: full Cookie header), pega o primeiro da lista que existir.
_FORTI_COOKIE_NAMES = ("SVPNCOOKIE",)
_GP_COOKIE_NAMES = (
    "portal-userauthcookie",
    "prelogin-cookie",
    "portalusersso",
    "authcookie",
)
# Catch-all: outros gateways VPN que podem aparecer
_GENERIC_COOKIE_NAMES = (
    "webvpn",
    "VPNSESSION",
    "MSISAuthenticated",
    "FortiAuth",
    "FORTISTATEFUL",
    "SSL_VPN_AUTH",
    "webvpnx",
    "webvpn_login",
    "session_cookie",
)


class SamlCookiePasteRequest(BaseModel):
    """Aceita cookie SAML em vários formatos pra ser tolerante a copy/paste."""

    cookie: str = Field(
        min_length=4,
        max_length=8192,
        description=(
            "Cookie SAML em qualquer um destes formatos: "
            "raw value, name=value, full Cookie header (a=b; c=d; ...), "
            "ou JSON do DevTools 'Edit cookie' (com chaves name/value)."
        ),
    )
    expires_at: datetime | None = Field(
        default=None, description="Quando expira; default agora+12h (Azure AD default)"
    )


class SamlCookiePasteResponse(BaseModel):
    client_id: str
    cookie_name: str
    cookie_value_len: int
    expires_at: datetime
    detected_format: str


def _parse_pasted_cookie(
    raw: str, vpn_type: VpnType
) -> tuple[str, str, str]:
    """Parsea uma paste de cookie e devolve (cookie_name, cookie_value, detected_format).

    Tenta múltiplos formatos em ordem do mais específico pro mais frouxo:

      1. JSON DevTools (Edit cookie do Chrome): {"name": "X", "value": "Y", ...}
      2. Full Cookie header / multi-cookie: "a=b; SVPNCOOKIE=xxx; c=d"
      3. Single name=value: "SVPNCOOKIE=abc"
      4. Raw value (sem name=): "abc123..." — assume nome canônico do protocolo

    Levanta ValueError se nada bater.
    """
    text = raw.strip()
    if not text:
        raise ValueError("cookie vazio")

    # Lista de nomes preferenciais conforme o protocolo
    if vpn_type == VpnType.OPENFORTIVPN:
        preferred = _FORTI_COOKIE_NAMES
    elif vpn_type == VpnType.GLOBALPROTECT:
        preferred = _GP_COOKIE_NAMES
    else:
        preferred = ()
    candidates = preferred + _GENERIC_COOKIE_NAMES

    # Formato 1: JSON do DevTools
    if text.startswith("{"):
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            obj = json.loads(text)
            if isinstance(obj, dict) and "name" in obj and "value" in obj:
                return str(obj["name"]), str(obj["value"]), "devtools-json"

    # Formato 2: full Cookie header (multi-cookie separado por ;)
    if ";" in text and "=" in text:
        pairs = {}
        for part in text.split(";"):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                pairs[k.strip()] = v.strip()
        # Escolhe o melhor cookie conhecido
        for name in candidates:
            if name in pairs and pairs[name]:
                return name, pairs[name], "cookie-header"
        # Nenhum nome conhecido — pega o primeiro não-vazio se só tem 1
        if len(pairs) == 1:
            k, v = next(iter(pairs.items()))
            return k, v, "cookie-header-single"

    # Formato 3: single name=value
    if "=" in text and ";" not in text:
        k, _, v = text.partition("=")
        return k.strip(), v.strip(), "name-value"

    # Formato 4: raw value — usa nome canônico do protocolo se houver
    if preferred:
        return preferred[0], text, "raw-value-canonical"

    raise ValueError(
        f"formato de cookie irreconhecível e protocolo {vpn_type.value} "
        "não tem nome canônico — cole no formato 'NOME=valor'"
    )


@router.post("/{client_id}/saml/cookie", response_model=SamlCookiePasteResponse)
async def saml_paste_cookie(
    client_id: str,
    body: SamlCookiePasteRequest,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SamlCookiePasteResponse:
    """Aceita cookie SAML pasted manualmente pelo admin.

    Caminho **garantido** quando o auto-capture do saml-portal falha
    (cert pinning, IdP exotic, cookies HttpOnly memory-only, etc).

    Workflow esperado:
      1. Admin abre browser próprio (Chrome/Edge/Firefox)
      2. Navega pro URL SAML do gateway, completa login + MFA normalmente
      3. F12 → Application → Cookies → copia o cookie da sessão
      4. Cola aqui em qualquer formato (DevTools JSON, header, name=value, raw)
      5. VAGG detecta o formato, persiste como saml_cookie do cliente
      6. Connect via UI ou /connect usa o cookie pra subir tunnel

    Aceita cookies de qualquer gateway — vai automaticamente escolher o melhor
    nome conhecido pro protocolo do cliente, ou aceita name=value desconhecido.
    """
    client = await _load_client(session, client_id)
    try:
        name, value, fmt = _parse_pasted_cookie(body.cookie, client.vpn_type)
    except ValueError as exc:
        raise ConflictError(
            f"não consegui interpretar o cookie: {exc}",
            context={"client_id": client_id},
        ) from exc
    # Sanitiza valor — alguns formatos têm aspas externas
    value = value.strip().strip('"').strip("'")
    if not value:
        raise ConflictError(
            "cookie tem nome mas valor vazio — verifique se copiou o cookie completo",
            context={"client_id": client_id, "cookie_name": name},
        )
    # O orchestrator/entrypoint dos tunnels espera "name=value" (preserva
    # name pro caso de openconnect-saml precisar saber se é prelogin-cookie
    # vs portal-userauthcookie pra escolher --usergroup).
    client.saml_cookie = f"{name}={value}"
    client.saml_cookie_expires_at = body.expires_at or (
        datetime.now(UTC) + timedelta(hours=12)
    )
    return SamlCookiePasteResponse(
        client_id=client_id,
        cookie_name=name,
        cookie_value_len=len(value),
        expires_at=client.saml_cookie_expires_at,
        detected_format=fmt,
    )


class SamlSeenCookiesResponse(BaseModel):
    client_id: str
    entries: list[dict]
    hint: str


@router.get("/{client_id}/saml/seen-cookies", response_model=SamlSeenCookiesResponse)
async def saml_seen_cookies(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
    limit: int = Query(default=100, ge=1, le=500),
) -> SamlSeenCookiesResponse:
    """Diagnóstico: lista TODOS os cookies que o saml-portal viu o gateway
    setar durante a última sessão SAML — mesmo os que não bateram com a
    watchlist de captura automática.

    Use isto quando o auto-capture falhar pra descobrir o nome real do
    cookie de sessão e usar com /saml/cookie (paste manual).

    Cada entrada inclui: timestamp, host, path, lista de cookies com nome,
    tamanho do valor, primeiros 8 chars e flag in_watchlist.
    """
    await _load_client(session, client_id)
    entries = await orchestrator.saml_seen_cookies(client_id, limit=limit)
    if entries:
        unwatched = {
            c["name"]
            for e in entries
            for c in e.get("cookies", [])
            if not c.get("in_watchlist")
        }
        if unwatched:
            hint = (
                f"vistos {len(entries)} entradas. Cookies fora da watchlist: "
                f"{', '.join(sorted(unwatched))}. Considere paste manual."
            )
        else:
            hint = f"vistos {len(entries)} entradas — todos cookies na watchlist."
    else:
        hint = (
            "log vazio — saml-portal não rodou ou não viu Set-Cookie do gateway. "
            "Verifique se o gateway_url está correto."
        )
    return SamlSeenCookiesResponse(
        client_id=client_id, entries=entries, hint=hint
    )


@router.post("/{client_id}/saml/stop", status_code=status.HTTP_204_NO_CONTENT)
async def saml_stop_portal(
    client_id: str,
    _: Annotated[CurrentAdmin, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[TunnelOrchestratorProtocol, Depends(get_tunnel_orchestrator)],
) -> None:
    """Para o container do portal SAML, salvando o cookie se foi capturado
    entre o último poll e o stop. Usado pelo frontend quando o user fecha
    o modal de auth — caso ele feche logo depois do "Login Successful!" e
    antes do polling do frontend pegar o cookie, queremos persistir mesmo
    assim pra próxima conexão pegar."""
    client = await _load_client(session, client_id)
    poll = await orchestrator.poll_saml_cookie(client_id)
    if poll.captured and poll.cookie:
        client.saml_cookie = poll.cookie
        client.saml_cookie_expires_at = poll.cookie_expires_at
        await session.flush()
    with contextlib.suppress(Exception):
        await orchestrator.stop_saml_portal(client_id)
