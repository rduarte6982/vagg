"""Tunnel container lifecycle (SPEC §5.2).

The orchestrator is the only place that talks to Docker. API endpoints depend
on it via the dependency layer. Tests inject a fake to avoid needing a Docker
daemon.

Container layout per client:

    /var/lib/vagg/clients/<id>/tunnel.conf      # the .ovpn (read-only mount)
    /var/lib/vagg/clients/<id>/password         # plaintext, mode 600 (RO mount)
    /var/run/vagg/<id>/control.sock             # tunnel-controller socket (RW)

Phase 3 supports OpenVPN. The image lookup table is keyed on ``VpnType`` so
adding new protocols in Phase 5 is just an entry plus the corresponding image.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import aiodocker
from aiodocker.exceptions import DockerError

from vagg_core.core.errors import ConflictError, CoreError, NotFoundError
from vagg_core.core.logging import get_logger
from vagg_core.db.models import TunnelState, VpnType
from vagg_core.services.dns_manager import DnsManagerProtocol
from vagg_core.services.network_manager import NetworkManagerProtocol
from vagg_core.services.network_plan import iface_name

log = get_logger(__name__)

# Reserved name pattern, ``vagg-tunnel-<client-id>`` (SPEC §2.3 naming).
_CONTAINER_PREFIX = "vagg-tunnel-"


class DockerUnavailableError(CoreError):
    code = "DOCKER_UNAVAILABLE"
    default_status = 503


class TunnelOrchestrationError(CoreError):
    code = "TUNNEL_ORCHESTRATION_ERROR"
    default_status = 502


@dataclass(frozen=True)
class TunnelStatusReport:
    state: TunnelState
    container_id: str | None = None
    controller_state: str | None = None
    uptime_s: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "container_id": self.container_id,
            "controller_state": self.controller_state,
            "uptime_s": self.uptime_s,
            "error": self.error,
        }


@dataclass(frozen=True)
class SamlPortalSession:
    """Resultado de start_saml_portal — frontend mostra a URL no iframe."""

    client_id: str
    container_id: str
    portal_url: str   # ex: "http://192.168.68.102:14500" — xpra-html5 servido
    expires_at: datetime  # auto-cleanup do container depois disso


@dataclass(frozen=True)
class SamlPollResult:
    """Resultado de poll_saml_cookie — frontend faz polling até captured=True."""

    captured: bool
    cookie: str | None = None
    cookie_expires_at: datetime | None = None
    error: str | None = None


@dataclass(frozen=True)
class DiscoveredRoute:
    cidr: str
    dev: str
    gateway: str | None = None


@dataclass(frozen=True)
class DiscoveryReport:
    """Resultado de ``discover`` — rotas e DNS empurrados pelo gateway.

    Vazio (routes/dns_servers/search_domains tudo vazio) quando o controller
    não respondeu, o socket sumiu, ou o gateway não pushou nada (raro mas
    possível em VPNs route-based onde o admin do cliente não habilitou push).
    """

    routes: tuple[DiscoveredRoute, ...]
    dns_servers: tuple[str, ...]
    search_domains: tuple[str, ...]

    def is_empty(self) -> bool:
        return not (self.routes or self.dns_servers or self.search_domains)


class TunnelOrchestratorProtocol(Protocol):
    """Public interface — endpoints depend on this, tests can supply a fake."""

    async def connect(
        self,
        *,
        client_id: str,
        protocol: VpnType,
        config_text: str,
        username: str | None = None,
        password: str | None = None,
        requires_otp: bool = False,
        saml_cookie: str | None = None,
    ) -> str: ...

    async def disconnect(self, client_id: str) -> None: ...

    async def status(self, client_id: str) -> TunnelStatusReport: ...

    async def send_otp(self, client_id: str, code: str) -> None: ...

    async def tail_logs(self, client_id: str, *, lines: int = 100) -> list[str]: ...

    async def start_saml_portal(
        self,
        *,
        client_id: str,
        gateway_url: str,
        kind: str = "gp",
    ) -> "SamlPortalSession": ...

    async def poll_saml_cookie(self, client_id: str) -> "SamlPollResult": ...

    async def stop_saml_portal(self, client_id: str) -> None: ...

    async def discover(self, client_id: str) -> "DiscoveryReport": ...

    async def saml_seen_cookies(self, client_id: str, *, limit: int = 200) -> list[dict[str, Any]]: ...


class TunnelOrchestrator:
    """Concrete orchestrator backed by a real Docker daemon."""

    def __init__(
        self,
        *,
        docker: aiodocker.Docker,
        config_dir: Path,
        sockets_dir: Path,
        image_by_protocol: dict[VpnType, str],
        network_name: str = "host",
        restart_policy: str = "unless-stopped",
        controller_timeout_s: float = 2.0,
        network_manager: NetworkManagerProtocol | None = None,
        dns_manager: DnsManagerProtocol | None = None,
    ) -> None:
        self._docker = docker
        self._config_dir = config_dir
        self._sockets_dir = sockets_dir
        self._image_by_protocol = image_by_protocol
        # SPEC §3.4 + §4.3: tunnel containers must share the host network namespace
        # so the openvpn process creates ``tun-<hash>`` directly on the host, where
        # the host's iptables can route packets to it.
        self._network = network_name
        self._restart = restart_policy
        self._controller_timeout = controller_timeout_s
        self._network_manager = network_manager
        self._dns_manager = dns_manager

    # ----- Helpers -----

    @staticmethod
    def container_name(client_id: str) -> str:
        return f"{_CONTAINER_PREFIX}{client_id}"

    def _client_config_dir(self, client_id: str) -> Path:
        return self._config_dir / client_id

    def _client_socket_dir(self, client_id: str) -> Path:
        return self._sockets_dir / client_id

    def _client_socket_path(self, client_id: str) -> Path:
        return self._client_socket_dir(client_id) / "control.sock"

    def _stage_config(
        self,
        client_id: str,
        *,
        config_text: str,
        username: str | None,
        password: str | None,
    ) -> tuple[Path, dict[str, str]]:
        """Persist the protocol config + creds to disk; return (mount_dir, env_overrides)."""
        cfg_dir = self._client_config_dir(client_id)
        cfg_dir.mkdir(parents=True, exist_ok=True)
        # Best-effort restrict permissions on POSIX; on Windows ``chmod`` is a no-op.
        with contextlib.suppress(NotImplementedError, OSError):
            cfg_dir.chmod(0o700)

        cfg_file = cfg_dir / "tunnel.conf"
        cfg_file.write_text(config_text, encoding="utf-8")

        env: dict[str, str] = {}
        if username:
            env["TUNNEL_USERNAME"] = username
        if password:
            pwd_file = cfg_dir / "password"
            pwd_file.write_text(password, encoding="utf-8")
            with contextlib.suppress(NotImplementedError, OSError):
                pwd_file.chmod(0o600)
        # Deterministic iface name so the host's iptables / ip-route rules can
        # reference it without coordinating through a shared file (SPEC §4.3).
        env["TUNNEL_DEV"] = iface_name(client_id)

        return cfg_dir, env

    def _build_container_config(
        self,
        *,
        image: str,
        cfg_dir: Path,
        sock_dir: Path,
        env: dict[str, str],
    ) -> dict[str, Any]:
        env_pairs = [f"{k}={v}" for k, v in env.items()]
        # /dev/net/tun é necessário pra openvpn/openconnect/wireguard.
        # /dev/ppp é necessário pro openfortivpn (que usa pppd internamente).
        # Sempre incluímos os dois — se host não tem /dev/ppp (ex: kernel sem
        # ppp_generic), o Docker falha o create com erro claro. Não dá pra
        # checar via Path() porque este código roda DENTRO do vagg-core, que
        # só vê /dev mediado pelo Docker; só o host tem o device real.
        devices: list[dict[str, str]] = [
            {
                "PathOnHost": "/dev/net/tun",
                "PathInContainer": "/dev/net/tun",
                "CgroupPermissions": "rwm",
            },
            {
                "PathOnHost": "/dev/ppp",
                "PathInContainer": "/dev/ppp",
                "CgroupPermissions": "rwm",
            },
        ]
        return {
            "Image": image,
            "Env": env_pairs,
            "HostConfig": {
                "CapAdd": ["NET_ADMIN"],
                "Devices": devices,
                "SecurityOpt": ["no-new-privileges:true"],
                "RestartPolicy": {"Name": self._restart},
                "Binds": [
                    f"{cfg_dir}:/config:ro",
                    f"{sock_dir}:/var/run/vagg",
                ],
                "NetworkMode": self._network,
                "AutoRemove": False,
            },
            "Labels": {
                "vagg.managed": "true",
                "vagg.protocol": image.split("/")[-1].split(":")[0],
            },
        }

    # ----- Public API -----

    async def connect(
        self,
        *,
        client_id: str,
        protocol: VpnType,
        config_text: str,
        username: str | None = None,
        password: str | None = None,
        requires_otp: bool = False,
        saml_cookie: str | None = None,
    ) -> str:
        image = self._image_by_protocol.get(protocol)
        if image is None:
            raise ConflictError(
                f"protocolo {protocol.value} ainda não suportado pelo orchestrator",
                context={"protocol": protocol.value},
            )
        # GP + SAML cookie usa imagem ESPECIALIZADA (vagg/tunnel-openconnect-saml)
        # com openconnect compilado from source + 2 patches locais (host-id +
        # VAGG_GP_COOKIE env injection). Necessário pra gateways MS Azure AD
        # (tipo MRV) que rejeitam openconnect upstream com HTTP 512.
        # Resto (Cisco AnyConnect, Pulse, GP sem SAML) usa o openconnect
        # vanilla padrão da imagem vagg/tunnel-openconnect.
        if protocol == VpnType.GLOBALPROTECT and saml_cookie:
            tag = image.rsplit(":", 1)[-1] if ":" in image else "test"
            image = f"vagg/tunnel-openconnect-saml:{tag}"
        # FortiGate + SAML cookie usa imagem ESPECIALIZADA com openfortivpn
        # 1.23.1 (Debian trixie) que aceita --cookie-on-stdin. Fluxo:
        # saml-portal captura SVPNCOOKIE, escreve em /share/cookie, este
        # container lê e injeta via stdin. Habilita auth Azure AD + MFA
        # via Microsoft Authenticator (push ou TOTP) sem precisar de senha
        # no env do container.
        elif protocol == VpnType.OPENFORTIVPN and saml_cookie:
            tag = image.rsplit(":", 1)[-1] if ":" in image else "test"
            image = f"vagg/tunnel-openfortivpn-saml:{tag}"

        cfg_dir, env = self._stage_config(
            client_id,
            config_text=config_text,
            username=username,
            password=password,
        )
        # Override de protocolo (e.g. GLOBALPROTECT → openconnect com --protocol=gp)
        if protocol_env := PROTOCOL_ENV_OVERRIDES.get(protocol):
            env["TUNNEL_PROTOCOL"] = protocol_env
        # MFA push: o entrypoint vai pipear o FIFO /run/otp.pipe no stdin
        # do client VPN, esperando bloqueado até que /tunnels/{id}/otp envie
        # o código.
        if requires_otp:
            env["TUNNEL_REQUIRES_OTP"] = "true"
        # SAML/SSO: se há cookie capturado pelo browser remoto, usa ele em
        # vez de user/password (modo --cookie-on-stdin do openconnect).
        if saml_cookie:
            env["TUNNEL_SAML_COOKIE"] = saml_cookie

        sock_dir = self._client_socket_dir(client_id)
        sock_dir.mkdir(parents=True, exist_ok=True)

        container_cfg = self._build_container_config(
            image=image, cfg_dir=cfg_dir, sock_dir=sock_dir, env=env
        )
        try:
            container = await self._docker.containers.create_or_replace(
                name=self.container_name(client_id),
                config=container_cfg,
            )
            await container.start()
        except DockerError as exc:
            log.error(
                "tunnel.connect.failed",
                client_id=client_id,
                status=exc.status,
                message=exc.message,
            )
            raise TunnelOrchestrationError(
                f"docker recusou criar/iniciar o container: {exc.message}",
                context={"docker_status": exc.status},
            ) from exc

        log.info("tunnel.connect.ok", client_id=client_id, container_id=container.id)
        # Rebuild the host's NAT / routing state to include this client (SPEC §4.2).
        # Failure here doesn't roll back the container — the health worker re-tries.
        if self._network_manager is not None:
            try:
                await self._network_manager.rebuild()
            except CoreError as exc:
                log.warning(
                    "tunnel.connect.network_rebuild_failed",
                    client_id=client_id,
                    error=str(exc.detail),
                )
        if self._dns_manager is not None:
            try:
                await self._dns_manager.regenerate_and_reload()
            except CoreError as exc:
                log.warning(
                    "tunnel.connect.dns_reload_failed",
                    client_id=client_id,
                    error=str(exc.detail),
                )
        return str(container.id)

    async def disconnect(self, client_id: str) -> None:
        try:
            container = await self._docker.containers.get(self.container_name(client_id))
        except DockerError as exc:
            if exc.status == 404:
                log.info("tunnel.disconnect.noop_no_container", client_id=client_id)
                return
            raise TunnelOrchestrationError(str(exc.message)) from exc

        try:
            await container.stop(timeout=10)
        except DockerError as exc:
            # Already stopped is fine; bubble other errors.
            if exc.status not in (304, 404):
                log.warning("tunnel.disconnect.stop_warn", client_id=client_id, status=exc.status)
        try:
            await container.delete(force=True)
        except DockerError as exc:
            if exc.status != 404:
                raise TunnelOrchestrationError(str(exc.message)) from exc
        log.info("tunnel.disconnect.ok", client_id=client_id)
        # Rebuild network so this client's rules are dropped from the host.
        if self._network_manager is not None:
            try:
                await self._network_manager.rebuild()
            except CoreError as exc:
                log.warning(
                    "tunnel.disconnect.network_rebuild_failed",
                    client_id=client_id,
                    error=str(exc.detail),
                )
        if self._dns_manager is not None:
            try:
                await self._dns_manager.regenerate_and_reload()
            except CoreError as exc:
                log.warning(
                    "tunnel.disconnect.dns_reload_failed",
                    client_id=client_id,
                    error=str(exc.detail),
                )

    async def status(self, client_id: str) -> TunnelStatusReport:
        try:
            container = await self._docker.containers.get(self.container_name(client_id))
            inspect = await container.show()
        except DockerError as exc:
            if exc.status == 404:
                return TunnelStatusReport(state=TunnelState.STOPPED)
            raise TunnelOrchestrationError(str(exc.message)) from exc

        state_obj = inspect.get("State", {})
        running = bool(state_obj.get("Running"))
        error = state_obj.get("Error") or None

        controller = await self._query_controller(client_id)

        if not running and state_obj.get("Status") == "exited":
            tunnel_state = TunnelState.ERRORED if error else TunnelState.DOWN
        elif running and controller and controller.get("state") in {"connected", "up"}:
            tunnel_state = TunnelState.UP
        elif running:
            tunnel_state = TunnelState.STARTING
        else:
            tunnel_state = TunnelState.STOPPED

        return TunnelStatusReport(
            state=tunnel_state,
            container_id=str(container.id),
            controller_state=(controller or {}).get("state"),
            uptime_s=(controller or {}).get("uptime_s"),
            error=error,
        )

    async def send_otp(self, client_id: str, code: str) -> None:
        socket_path = self._client_socket_path(client_id)
        if not socket_path.exists():
            raise NotFoundError(
                "control socket não existe (container não está rodando?)",
                context={"client_id": client_id, "socket": str(socket_path)},
            )
        response = await self._talk_to_controller(socket_path, {"cmd": "otp", "code": code})
        if not response.get("ok"):
            raise TunnelOrchestrationError(
                f"controller recusou OTP: {response.get('error', 'unknown')}",
                context={"client_id": client_id},
            )

    async def tail_logs(self, client_id: str, *, lines: int = 100) -> list[str]:
        try:
            container = await self._docker.containers.get(self.container_name(client_id))
        except DockerError as exc:
            if exc.status == 404:
                return []
            raise TunnelOrchestrationError(str(exc.message)) from exc
        try:
            # ``container.log`` is typed as ``list[str]`` in aiodocker, but at runtime
            # returns ``str`` when ``stream=False`` and the daemon emits a single chunk.
            output: Any = await container.log(stdout=True, stderr=True, tail=lines)
        except DockerError as exc:
            raise TunnelOrchestrationError(str(exc.message)) from exc
        if isinstance(output, str):
            return [line for line in output.splitlines() if line]
        return [str(line).rstrip("\n") for line in output if line]

    async def discover(self, client_id: str) -> DiscoveryReport:
        """Pede ao tunnel-controller (dentro do container) que faça scan
        das rotas e DNS push do gateway.

        Retorna DiscoveryReport vazio quando:
          - container não está rodando (socket inexistente)
          - controller respondeu mas com payload inválido
          - controller respondeu com ok=False
        Não levanta exceção pra cima — o caller (worker) só ignora ciclos
        em que ainda não há nada pra descobrir.
        """
        socket_path = self._client_socket_path(client_id)
        if not socket_path.exists():
            return DiscoveryReport(routes=(), dns_servers=(), search_domains=())
        try:
            response = await self._talk_to_controller(socket_path, {"cmd": "discover"})
        except (TimeoutError, OSError) as exc:
            log.debug("tunnel.discover.socket_failed", client_id=client_id, error=str(exc))
            return DiscoveryReport(routes=(), dns_servers=(), search_domains=())
        if not response.get("ok"):
            return DiscoveryReport(routes=(), dns_servers=(), search_domains=())

        raw_routes = response.get("routes") or []
        routes: list[DiscoveredRoute] = []
        for r in raw_routes:
            if not isinstance(r, dict):
                continue
            cidr = r.get("cidr")
            dev = r.get("dev")
            if not cidr or not dev:
                continue
            routes.append(DiscoveredRoute(cidr=cidr, dev=dev, gateway=r.get("gateway")))
        dns_raw = response.get("dns_servers") or []
        search_raw = response.get("search_domains") or []
        return DiscoveryReport(
            routes=tuple(routes),
            dns_servers=tuple(s for s in dns_raw if isinstance(s, str)),
            search_domains=tuple(s for s in search_raw if isinstance(s, str)),
        )

    # ----- Internal: control socket -----

    async def _query_controller(self, client_id: str) -> dict[str, Any] | None:
        socket_path = self._client_socket_path(client_id)
        if not socket_path.exists():
            return None
        try:
            return await self._talk_to_controller(socket_path, {"cmd": "status"})
        except (TimeoutError, OSError):
            return None

    async def _talk_to_controller(self, socket_path: Path, msg: dict[str, Any]) -> dict[str, Any]:
        if not hasattr(asyncio, "open_unix_connection"):
            # Windows path — orchestrator never reaches here in production. Tests mock.
            raise NotImplementedError("unix sockets indisponíveis nesta plataforma")
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(socket_path)),
                timeout=self._controller_timeout,
            )
        except (TimeoutError, OSError) as exc:
            raise TunnelOrchestrationError(
                f"timeout/erro ao conectar no control socket: {exc}",
                context={"socket": str(socket_path)},
            ) from exc

        try:
            writer.write((json.dumps(msg) + "\n").encode("utf-8"))
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=self._controller_timeout)
            if not line:
                raise TunnelOrchestrationError(
                    "control socket fechou sem resposta",
                    context={"socket": str(socket_path)},
                )
            return json.loads(line)  # type: ignore[no-any-return]
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    # ----- SAML portal (browser remoto pra captura de cookie SSO) -----

    def _saml_container_name(self, client_id: str) -> str:
        return f"vagg-saml-{client_id}"

    def _saml_image(self) -> str:
        # Tag global pro saml portal — separado do mapa de protocols porque
        # não é VPN. Em produção sai do registry; em dev é local.
        return os.environ.get("VAGG_SAML_PORTAL_IMAGE", "vagg/saml-portal:test")

    async def start_saml_portal(
        self,
        *,
        client_id: str,
        gateway_url: str,
        kind: str = "gp",
    ) -> SamlPortalSession:
        """Cria container com firefox+xpra apontando pro IdP Microsoft.

        kind:
          - "gp"    → GlobalProtect (cookie hierarchy: prelogin → portal-userauthcookie)
          - "forti" → FortiGate (single SVPNCOOKIE cookie)

        Em vez de mandar o Firefox bater no gateway GP (que mostra a página
        de download do agente quando o User-Agent não é PAN GlobalProtect),
        fazemos o prelogin server-side com UA spoofado, decodificamos o
        SAMLRequest, e abrimos o iframe direto no IdP. O Firefox completa
        o login Microsoft e segue o redirect natural pra
        /SAML20/SP/AssertionConsumerService no gateway, onde o mitmproxy
        captura prelogin-cookie/portal-userauthcookie do Set-Cookie.
        """
        # Mata QUALQUER portal SAML rodando (porta 14500 é fixa — só um pode
        # estar ativo). Itera pelos containers com label vagg.role=saml-portal
        # e força remoção.
        with contextlib.suppress(DockerError):
            existing = await self._docker.containers.list(
                filters=json.dumps({"label": ["vagg.role=saml-portal"]}),
                all=True,
            )
            for c in existing:
                with contextlib.suppress(DockerError):
                    await c.delete(force=True)

        # cookies expiram em ~12h por default no Azure AD
        expires_at = datetime.now(UTC) + timedelta(minutes=20)

        # diretório compartilhado pra o helper escrever o cookie
        share_dir = self._client_socket_dir(client_id).parent / f"saml-{client_id}"
        share_dir.mkdir(parents=True, exist_ok=True)

        # Porta fixa 14500 no host. Como só 1 SAML portal pode estar ativo
        # por vez (start_saml_portal mata o anterior), não precisamos variar
        # por client. Porta fixa simplifica liberação de firewall.
        host_port = 14500

        # Resolve a URL do IdP via prelogin server-side com UA spoofado. Se
        # falhar (gateway não SAML, network, etc) cai pro fluxo antigo de
        # mandar o Firefox direto no gateway URL.
        # Pra FortiGate (kind=forti), pula o resolve_idp porque o gateway
        # FortiGate só precisa que o user navegue pra /remote/saml/start
        # ou /remote/login — o FortiGate redireciona pra Azure AD sozinho.
        if kind == "forti":
            idp_url = None
            # Para FortiGate, abrir direto a URL de SAML start. Aceita tanto
            # gateway_url já apontando pro endpoint /remote/saml quanto URL
            # base — neste último caso anexa /remote/saml/start.
            if "/remote/" in gateway_url or gateway_url.endswith("/remote/saml"):
                open_url = gateway_url
            else:
                base = gateway_url.rstrip("/")
                open_url = f"{base}/remote/saml/start"
        else:
            idp_url = await self._resolve_saml_idp_url(gateway_url)
            open_url = idp_url or gateway_url
        log.info(
            "saml.portal.open_url_resolved",
            gateway_url=gateway_url,
            using_idp=bool(idp_url),
            kind=kind,
        )

        # User-Agent spoof: GP gateways exigem PAN client UA. FortiGate
        # aceita qualquer UA "browser-like" — manter Firefox default.
        ff_ua_pref = (
            'FF_PREF_general.useragent.override=PAN GlobalProtect/6.0.1-19 (Windows 10)'
            if kind == "gp"
            else "FF_PREF_dummy=1"
        )

        config = {
            "Image": self._saml_image(),
            "Env": [
                f"VAGG_SAML_GATEWAY_URL={gateway_url}",
                f"VAGG_SAML_COOKIE_OUT=/share/cookie",
                f"VAGG_SAML_KIND={kind}",
                f"VAGG_SAML_PORT={host_port}",
                # jlesage/firefox usa noVNC + TigerVNC (canvas+websocket).
                # Funciona em HTTP plano — secure context não é requerido.
                "WEB_LISTENING_PORT=14500",
                "DISPLAY_WIDTH=1280",
                "DISPLAY_HEIGHT=800",
                "SECURE_CONNECTION=0",
                "KEEP_APP_RUNNING=1",
                "DARK_MODE=1",
                # Homepage = IdP Microsoft direto (resolvido via prelogin).
                # Pular o gateway evita a tela /global-protect/getsoftwarepage.esp
                # quando o user-agent do Firefox não é reconhecido como
                # cliente PAN GlobalProtect.
                f"FF_OPEN_URL={open_url}",
                # Spoof User-Agent só pra GP — FortiGate aceita Firefox padrão.
                ff_ua_pref,
            ],
            "HostConfig": {
                # AutoRemove desabilitado pra preservar logs em caso de erro.
                # `stop_saml_portal` cuida da cleanup.
                "AutoRemove": False,
                "PortBindings": {"14500/tcp": [{"HostPort": str(host_port)}]},
                "Binds": [f"{share_dir}:/share:rw"],
                "RestartPolicy": {"Name": "no"},
            },
            "ExposedPorts": {"14500/tcp": {}},
            "Labels": {
                "vagg.client_id": client_id,
                "vagg.role": "saml-portal",
                "vagg.expires_at": expires_at.isoformat(),
            },
        }

        container = await self._docker.containers.create_or_replace(
            name=self._saml_container_name(client_id),
            config=config,
        )
        await container.start()
        log.info("saml.portal.started", client_id=client_id, container_id=container.id)

        # Espera o KasmVNC ficar pronto. linuxserver/firefox demora ~6-15s
        # pra subir Selkies + Firefox. Sem essa espera o iframe do frontend
        # carrega prematuramente e bate em 502/connection refused.
        await self._wait_saml_portal_ready(host_port=host_port, timeout_s=45)

        # URL HTTP direto na porta 14500 — jlesage/firefox usa noVNC simples
        # que funciona sem secure context. User precisa que firewall libere
        # 14500 da rede dele até 192.168.68.102.
        portal_host = os.environ.get("VAGG_PUBLIC_HOST", "192.168.68.102")
        return SamlPortalSession(
            client_id=client_id,
            container_id=str(container.id),
            portal_url=f"http://{portal_host}:{host_port}/",
            expires_at=expires_at,
        )

    async def _resolve_saml_idp_url(self, gateway_url: str) -> str | None:
        """Faz prelogin no GP gateway com User-Agent PAN GlobalProtect e
        decodifica o SAMLRequest pra retornar a URL do IdP (Microsoft).

        Retorna None se não der pra resolver — caller volta pra fluxo
        antigo (abrir o gateway URL direto). Não levanta exceção; orquestrar
        não pode falhar só porque o prelogin deu ruim, frontend ainda
        precisa de saml-portal subindo.
        """
        import base64
        import re as _re
        from urllib.parse import urlparse

        try:
            import httpx  # type: ignore[import-not-found]
        except Exception:
            return None

        parsed = urlparse(gateway_url)
        host = parsed.hostname
        if not host:
            return None
        prelogin_url = (
            f"https://{host}/ssl-vpn/prelogin.esp"
            "?tmp=tmp&kerberos-support=yes&ipv6-support=yes&clientVer=4100"
        )
        headers = {"User-Agent": "PAN GlobalProtect/6.0.1-19 (Windows 10)"}
        try:
            async with httpx.AsyncClient(verify=False, timeout=12.0) as h:
                r = await h.post(prelogin_url, headers=headers)
        except Exception as exc:
            log.warning("saml.portal.prelogin_failed", host=host, error=str(exc))
            return None
        if r.status_code != 200:
            log.warning(
                "saml.portal.prelogin_non_200",
                host=host,
                status=r.status_code,
            )
            return None
        body = r.text
        m = _re.search(r"<saml-request>([^<]+)</saml-request>", body)
        if not m:
            return None
        saml_request_b64 = m.group(1).strip()
        try:
            return base64.b64decode(saml_request_b64).decode("utf-8").strip()
        except Exception as exc:
            log.warning("saml.portal.idp_decode_failed", host=host, error=str(exc))
            return None

    async def _wait_saml_portal_ready(self, *, host_port: int, timeout_s: int = 60) -> None:
        """Polling até o container saml-portal responder em / (raiz).

        jlesage/firefox serve noVNC no path raiz da porta WEB_LISTENING_PORT
        (14500 aqui). 200 OK significa noVNC pronto. Aceita 30x também porque
        às vezes redireciona pra /vnc.html. Sem isso o frontend carrega o
        iframe antes do Firefox subir → tela branca/connection refused.
        Falha silenciosamente após timeout — frontend pode dar retry.
        """
        import asyncio as _asyncio
        import socket as _socket

        deadline = _asyncio.get_event_loop().time() + timeout_s
        # Tenta tanto localhost (vagg-core em host net) quanto host gateway
        targets = [("127.0.0.1", host_port), ("172.17.0.1", host_port)]
        accept_prefixes = (
            b"HTTP/1.1 200",
            b"HTTP/1.0 200",
            b"HTTP/1.1 30",
            b"HTTP/1.0 30",
        )

        while _asyncio.get_event_loop().time() < deadline:
            for host, port in targets:
                try:
                    fut = _asyncio.open_connection(host, port)
                    reader, writer = await _asyncio.wait_for(fut, timeout=1.5)
                    writer.write(
                        b"GET / HTTP/1.1\r\nHost: localhost\r\n"
                        b"Connection: close\r\n\r\n"
                    )
                    await writer.drain()
                    line = await _asyncio.wait_for(reader.readline(), timeout=2.0)
                    writer.close()
                    with contextlib.suppress(OSError):
                        await writer.wait_closed()
                    if any(line.startswith(p) for p in accept_prefixes):
                        log.info("saml.portal.ready", host_port=host_port, target=host)
                        return
                except (TimeoutError, ConnectionError, OSError, _socket.error):
                    pass
            await _asyncio.sleep(1.0)

        log.warning(
            "saml.portal.not_ready_after_timeout",
            host_port=host_port,
            timeout_s=timeout_s,
        )

    async def poll_saml_cookie(self, client_id: str) -> SamlPollResult:
        """Verifica se o helper capturou o cookie. Retorna captured=False
        enquanto não — o frontend faz polling até captured=True.
        """
        share_dir = self._client_socket_dir(client_id).parent / f"saml-{client_id}"
        cookie_file = share_dir / "cookie"
        if not cookie_file.exists():
            return SamlPollResult(captured=False)
        try:
            data = cookie_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            return SamlPollResult(captured=False, error=str(exc))
        if not data:
            return SamlPollResult(captured=False)

        # cookie pode vir como JSON ou texto puro; aceitamos ambos
        cookie_value = data
        expires_at: datetime | None = None
        with contextlib.suppress(json.JSONDecodeError):
            obj = json.loads(data)
            cookie_value = obj.get("cookie", data)
            if exp := obj.get("expires_at"):
                expires_at = datetime.fromisoformat(exp)

        if expires_at is None:
            # default 12h — Azure AD típico
            expires_at = datetime.now(UTC) + timedelta(hours=12)

        return SamlPollResult(
            captured=True, cookie=cookie_value, cookie_expires_at=expires_at
        )

    async def stop_saml_portal(self, client_id: str) -> None:
        with contextlib.suppress(DockerError):
            container = await self._docker.containers.get(
                self._saml_container_name(client_id)
            )
            await container.delete(force=True)

    async def saml_seen_cookies(
        self, client_id: str, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Lê o log /share/cookies-seen.log gerado pelo cookie_addon do
        saml-portal. Útil pra debug quando auto-capture falha — admin pode
        ver QUAIS nomes de cookie o gateway setou e usar isso pra paste manual.

        Retorna até `limit` entradas mais recentes (JSONL parsed) ou lista
        vazia se o portal nunca rodou ou nada foi visto.
        """
        share_dir = self._client_socket_dir(client_id).parent / f"saml-{client_id}"
        log_file = share_dir / "cookies-seen.log"
        if not log_file.exists():
            return []
        try:
            raw = log_file.read_text(encoding="utf-8")
        except OSError:
            return []
        entries: list[dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            with contextlib.suppress(json.JSONDecodeError):
                entries.append(json.loads(line))
        return entries[-limit:]


def default_image_map(tag: str = "dev") -> dict[VpnType, str]:
    """Return the canonical ``vagg/tunnel-<protocol>:<tag>`` mapping for known protocols.

    GlobalProtect compartilha a imagem do openconnect (mesma binary) — o que
    diferencia é a env var TUNNEL_PROTOCOL=gp setada no _stage_config.
    """
    return {
        VpnType.OPENVPN: f"vagg/tunnel-openvpn:{tag}",
        VpnType.OPENCONNECT: f"vagg/tunnel-openconnect:{tag}",
        VpnType.OPENFORTIVPN: f"vagg/tunnel-openfortivpn:{tag}",
        VpnType.WIREGUARD: f"vagg/tunnel-wireguard:{tag}",
        VpnType.STRONGSWAN: f"vagg/tunnel-strongswan:{tag}",
        VpnType.GLOBALPROTECT: f"vagg/tunnel-openconnect:{tag}",
    }


# Mapa protocol → env TUNNEL_PROTOCOL passada ao container openconnect.
# Vazio = anyconnect (default); "gp" = GlobalProtect; etc.
PROTOCOL_ENV_OVERRIDES: dict[VpnType, str] = {
    VpnType.GLOBALPROTECT: "gp",
}


def docker_from_env() -> aiodocker.Docker:
    """Build a Docker client honoring ``DOCKER_HOST`` (Linux unix socket by default)."""
    return aiodocker.Docker(url=os.environ.get("DOCKER_HOST"))
