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
import hashlib
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
from vagg_core.services import totp as totp_svc
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
class TotpSeedSpec:
    """Seed TOTP decifrado + parâmetros de geração — orchestrator usa pra gerar
    códigos automáticos a cada connect/reconnect.

    O caller (endpoint /connect) decifra o secret do banco e monta esta struct;
    o orchestrator nunca toca em Fernet diretamente.
    """

    secret: str  # base32 normalizado (sem padding)
    digits: int = 6
    period: int = 30
    algorithm: str = "sha1"

    def current_code(self) -> str:
        return totp_svc.generate(
            self.secret,
            digits=self.digits,
            period=self.period,
            algorithm=self.algorithm,  # type: ignore[arg-type]
        )


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
        totp_seed: "TotpSeedSpec | None" = None,
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

    async def start_saml_login(
        self,
        *,
        client_id: str,
        gateway_url: str,
        config_text: str,
        port: int = 8020,
    ) -> dict[str, Any]: ...

    async def relay_saml_id(
        self,
        *,
        client_id: str,
        saml_id: str,
        port: int = 8020,
    ) -> dict[str, Any]: ...


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
        # client_id → task em background que regera código TOTP e empurra no
        # FIFO enquanto state != connected. Cancelada por disconnect.
        self._otp_tasks: dict[str, asyncio.Task[None]] = {}

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
        totp_seed: TotpSeedSpec | None = None,
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

        # Auto-OTP: se o cliente tem TOTP seed cadastrado, lança task que
        # regenera o código a cada janela e empurra no FIFO até o controller
        # reportar connected. Sem isso, container fica travado esperando
        # alguém digitar 6 dígitos na UI — incompatível com modelo "túneis
        # sempre up". Task cancelada por disconnect ou quando state vira UP.
        if requires_otp and totp_seed is not None:
            self._cancel_otp_task(client_id)
            task = asyncio.create_task(
                self._auto_otp_push_loop(client_id, totp_seed),
                name=f"vagg-auto-otp-{client_id}",
            )
            self._otp_tasks[client_id] = task

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
        # Para o auto-OTP push primeiro — não adianta empurrar código pra
        # container que vai morrer.
        self._cancel_otp_task(client_id)
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

    # ----- Auto-OTP loop (TOTP seed cadastrado) -----

    # Tempo máximo de tentativa de auth bem-sucedida. Depois disso o loop
    # encerra mesmo sem conectar — auth tá quebrada e ficar empurrando
    # códigos só polui o log.
    _AUTO_OTP_MAX_DURATION_S = 180.0
    # Intervalo entre tentativas — abaixo do period TOTP (30s) pra cobrir o
    # caso "estamos a 2s do fim da janela e a auth vai cair no segundo seguinte".
    # Não muito agressivo: send_otp escreve no FIFO bloqueante, queremos
    # evitar acumular escritas em fila.
    _AUTO_OTP_INTERVAL_S = 5.0
    # Espera inicial pra container subir + controller começar a aceitar
    # comandos. Empiricamente 1.5s cobre o docker create+start+entrypoint
    # nos protocolos suportados.
    _AUTO_OTP_INITIAL_DELAY_S = 1.5

    def _cancel_otp_task(self, client_id: str) -> None:
        task = self._otp_tasks.pop(client_id, None)
        if task is not None and not task.done():
            task.cancel()

    async def _auto_otp_push_loop(
        self, client_id: str, seed: TotpSeedSpec
    ) -> None:
        """Bg task: enquanto state != UP, gera código TOTP fresh e empurra
        via send_otp. Para quando state vira UP ou após _AUTO_OTP_MAX_DURATION_S.

        Idempotente: empurrar o mesmo código duas vezes na mesma janela é
        seguro — openconnect/openfortivpn consomem o stdin uma vez; escritas
        extras ficam no pipe pra próximo prompt (que aparece na reconexão
        --persistent=10 do forti, por exemplo). Em prática isso resolve
        reconexão automática sem intervenção humana.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._AUTO_OTP_MAX_DURATION_S
        await asyncio.sleep(self._AUTO_OTP_INITIAL_DELAY_S)
        last_code: str | None = None
        last_sent_at: float = 0.0
        while loop.time() < deadline:
            try:
                report = await self.status(client_id)
            except CoreError as exc:
                log.debug(
                    "tunnel.auto_otp.status_failed",
                    client_id=client_id,
                    error=str(exc.detail),
                )
                report = None
            if report is not None and report.state == TunnelState.UP:
                log.info("tunnel.auto_otp.connected", client_id=client_id)
                return
            if report is not None and report.state in {
                TunnelState.STOPPED,
                TunnelState.DOWN,
                TunnelState.ERRORED,
            }:
                # Container morreu ou foi parado — não tem o que empurrar.
                log.info(
                    "tunnel.auto_otp.giving_up",
                    client_id=client_id,
                    state=report.state.value,
                )
                return

            try:
                code = seed.current_code()
            except Exception as exc:
                log.error(
                    "tunnel.auto_otp.generate_failed",
                    client_id=client_id,
                    error=str(exc),
                )
                return

            now = loop.time()
            # Evita repetir o MESMO código no mesmo ciclo (gateway que faz
            # anti-replay rejeitaria o segundo envio). Mas se o código mudou
            # OU passou tempo suficiente, manda — cobre reconnect que precisa
            # de prompt novo.
            should_send = (
                code != last_code or (now - last_sent_at) >= seed.period
            )
            if should_send:
                try:
                    await self.send_otp(client_id, code)
                    last_code = code
                    last_sent_at = now
                    log.info(
                        "tunnel.auto_otp.pushed",
                        client_id=client_id,
                        seconds_remaining=totp_svc.seconds_remaining(seed.period),
                    )
                except (NotFoundError, TunnelOrchestrationError) as exc:
                    # Socket pode não estar pronto ainda; tenta no próximo ciclo.
                    log.debug(
                        "tunnel.auto_otp.push_failed",
                        client_id=client_id,
                        error=str(exc.detail),
                    )
            await asyncio.sleep(self._AUTO_OTP_INTERVAL_S)
        log.warning(
            "tunnel.auto_otp.timeout",
            client_id=client_id,
            max_duration_s=self._AUTO_OTP_MAX_DURATION_S,
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
        # Mata APENAS o saml-portal anterior DESSE client. Outros clients
        # podem ter portais paralelos rodando em portas dinâmicas.
        with contextlib.suppress(DockerError):
            existing = await self._docker.containers.list(
                filters=json.dumps({
                    "label": ["vagg.role=saml-portal", f"vagg.client_id={client_id}"],
                }),
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

        # Porta dinâmica por client (14500-15000 range). Vexia mantém 14500
        # backward-compat. Permite N clients SAML simultâneos.
        host_port = self.saml_portal_port_for(client_id)

        # Resolve a URL do IdP via prelogin server-side com UA spoofado. Se
        # falhar (gateway não SAML, network, etc) cai pro fluxo antigo de
        # mandar o Firefox direto no gateway URL.
        # Pra FortiGate (kind=forti), pula o resolve_idp porque o gateway
        # FortiGate só precisa que o user navegue pra /remote/saml/start
        # ou /remote/login — o FortiGate redireciona pra Azure AD sozinho.
        if kind == "forti":
            idp_url = None
            # Para FortiGate, abrir o endpoint SAML com **?redirect=1**:
            # esse modo faz o gateway redirecionar pro nosso callback local
            # (http://127.0.0.1:8020/?id=<id>) APÓS o login Microsoft, em
            # vez de tentar hostcheck e devolver 403. O saml_callback.py
            # dentro do container intercepta o redirect, troca o ?id= pelo
            # SVPNCOOKIE via /remote/saml/auth_id, e grava /share/cookie.
            # Sem isso, gateways com host-check habilitado (ex: Vexia)
            # bloqueiam qualquer browser puro com 403 /hostcheck_install.
            if "/remote/" in gateway_url:
                # admin já especificou path custom — preserva mas garante
                # que tem ?redirect=1.
                sep = "&" if "?" in gateway_url else "?"
                if "redirect=" not in gateway_url:
                    open_url = f"{gateway_url}{sep}redirect=1"
                else:
                    open_url = gateway_url
            else:
                base = gateway_url.rstrip("/")
                open_url = f"{base}/remote/saml/start?redirect=1"
        else:
            # GlobalProtect: NÃO ir direto pro IdP — gateway precisa iniciar
            # o flow pra criar session interna. Quando user POSTa SAMLResponse
            # pro /SAML20/SP/ACS, gateway só seta cookies se foi ele quem
            # iniciou. Abrir gateway = redirect pro Microsoft = session ok.
            #
            # Resolve IdP pra logging/diagnóstico mas usa o gateway URL.
            idp_url = await self._resolve_saml_idp_url(gateway_url)
            base = gateway_url.rstrip("/")
            # Endpoint que dispara SAML SSO no gateway PA.
            open_url = f"{base}/global-protect/login.esp"
        log.info(
            "saml.portal.open_url_resolved",
            gateway_url=gateway_url,
            using_idp=bool(idp_url),
            kind=kind,
        )

        # User-Agent spoof: GP gateways exigem PAN client UA. Pra FortiGate
        # alguns deployments (ex: Vexia 2026-05) exigem UA do FortiClient pra
        # **pular hostcheck**: sem isso, o POST callback /remote/saml/login
        # redireciona pro /remote/hostcheck_install e retorna 403. Spoofando
        # o UA do FortiClient o gateway aceita o cookie SAML como se viesse
        # do cliente nativo — descoberta no debug do gateway vpnssl.vexia.
        ff_ua_pref = (
            'FF_PREF_general.useragent.override=PAN GlobalProtect/6.0.1-19 (Windows 10)'
            if kind == "gp"
            else "FF_PREF_general.useragent.override=FortiSSLVPNclient/7.4.0.1310"
        )

        config = {
            "Image": self._saml_image(),
            "Env": [
                f"VAGG_SAML_GATEWAY_URL={gateway_url}",
                f"VAGG_SAML_COOKIE_OUT=/share/cookie",
                f"VAGG_SAML_KIND={kind}",
                f"VAGG_SAML_PORT={host_port}",
                # jlesage/firefox usa noVNC + TigerVNC. WEB_LISTENING_PORT é a
                # porta do nginx do container (HTTP+noVNC websockify) — em
                # network=host expõe direto no host (host_port dinâmico).
                f"WEB_LISTENING_PORT={host_port}",
                # VNC_LISTENING_PORT=-1: desabilita TCP rfbport do Xvnc. Sem
                # isso, MULTIPLOS containers em network=host colidem em :5900.
                # Nginx interno usa unix socket → noVNC websockify continua OK.
                "VNC_LISTENING_PORT=-1",
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
                # Spoof User-Agent — necessário pra GP (PAN client UA) e pra
                # FortiGate com hostcheck habilitado (FortiSSLVPNclient UA).
                ff_ua_pref,
            ],
            "HostConfig": {
                # AutoRemove desabilitado pra preservar logs em caso de erro.
                # `stop_saml_portal` cuida da cleanup.
                "AutoRemove": False,
                # network=host: WEB_LISTENING_PORT dinâmico expõe direto.
                # Sem PortBindings → sem DNAT (chain DOCKER iptables-nft
                # incompatibility resolved). Xvnc TCP desabilitado via
                # VNC_LISTENING_PORT=-1 evita colisão de :5900.
                "NetworkMode": "host",
                "Binds": [f"{share_dir}:/share:rw"],
                "RestartPolicy": {"Name": "no"},
            },
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

    # ────────────────────────────────────────────────────────────────────
    # SAML-LOGIN MODE (FortiGate openfortivpn --saml-login=PORT)
    # ────────────────────────────────────────────────────────────────────
    #
    # Caminho NOVO pra FortiGate Vexia (e gateways com host-check ativo).
    # Não usa Firefox embutido/noVNC — o user loga no browser DELE, e
    # quando o gateway redireciona pra http://127.0.0.1:PORT/?id=X, o
    # frontend captura essa URL e chama relay_saml_id. O id é entregue
    # ao openfortivpn que escuta na MESMA TLS session — sem TLS pinning.

    # Alocadores determinísticos de porta — N clientes SAML simultâneos sem
    # colisão. Base + hash(client_id) % range. Idempotente: mesmo client
    # sempre recebe mesma porta. Cliente backward-compat "vexia" mantém 8020.
    _SAML_LOGIN_PORT_BASE = 8020
    _SAML_LOGIN_PORT_RANGE = 500
    _SAML_PORTAL_PORT_BASE = 14500
    _SAML_PORTAL_PORT_RANGE = 500

    @classmethod
    def saml_login_port_for(cls, client_id: str) -> int:
        """Porta loopback do openfortivpn --saml-login pra esse client.
        Vexia mantém 8020 (legacy); demais espalham em 8021..8520."""
        if client_id == "vexia":
            return cls._SAML_LOGIN_PORT_BASE
        h = int(hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:8], 16)
        offset = (h % (cls._SAML_LOGIN_PORT_RANGE - 1)) + 1
        return cls._SAML_LOGIN_PORT_BASE + offset

    @classmethod
    def saml_portal_port_for(cls, client_id: str) -> int:
        """Porta host do saml-portal (Firefox+noVNC) pra esse client.
        Vexia mantém 14500 (legacy); demais espalham em 14501..15000."""
        if client_id == "vexia":
            return cls._SAML_PORTAL_PORT_BASE
        h = int(hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:8], 16)
        offset = (h % (cls._SAML_PORTAL_PORT_RANGE - 1)) + 1
        return cls._SAML_PORTAL_PORT_BASE + offset

    async def start_saml_login(
        self,
        *,
        client_id: str,
        gateway_url: str,
        config_text: str,
        port: int | None = None,
    ) -> dict[str, Any]:
        """Sobe vagg-tunnel-<client_id> com openfortivpn --saml-login=PORT.

        `port` default é alocado dinamicamente por client_id (vexia=8020 backward-compat).
        Retorna dict com start_url, port, expected_callback_prefix, container_id, portal_url.
        """
        if port is None:
            port = self.saml_login_port_for(client_id)
        cfg_dir, env = self._stage_config(
            client_id,
            config_text=config_text,
            username=None,
            password=None,
        )
        env["TUNNEL_SAML_LOGIN_PORT"] = str(port)
        # Pula auto-OTP — saml-login não precisa de OTP em runtime, o MFA
        # acontece dentro do flow SAML do Microsoft.

        sock_dir = self._client_socket_dir(client_id)
        sock_dir.mkdir(parents=True, exist_ok=True)

        # Imagem especializada (mesma usada pelo connect() saml legacy)
        # tem openfortivpn 1.23.1 que suporta --saml-login.
        image = self._image_by_protocol.get(VpnType.OPENFORTIVPN, "")
        tag = image.rsplit(":", 1)[-1] if ":" in image else "test"
        image = f"vagg/tunnel-openfortivpn-saml:{tag}"

        container_cfg = self._build_container_config(
            image=image, cfg_dir=cfg_dir, sock_dir=sock_dir, env=env
        )
        # Usa o entrypoint da imagem (entrypoint.sh) que detecta o env
        # TUNNEL_SAML_LOGIN_PORT e roda openfortivpn --saml-login=PORT,
        # ao mesmo tempo iniciando tunnel-controller pra responder no
        # control socket (sem isso, /status nunca reporta state=up).

        try:
            container = await self._docker.containers.create_or_replace(
                name=self.container_name(client_id),
                config=container_cfg,
            )
            await container.start()
        except DockerError as exc:
            log.error(
                "tunnel.saml_login.start.failed",
                client_id=client_id,
                status=exc.status,
                message=exc.message,
            )
            raise TunnelOrchestrationError(
                f"docker recusou criar/iniciar tunnel SAML-login: {exc.message}",
                context={"docker_status": exc.status},
            ) from exc

        log.info(
            "tunnel.saml_login.start.ok",
            client_id=client_id,
            container_id=container.id,
            port=port,
        )

        # Dispara task de auto-route em background ASSIM QUE container sobe.
        # Mesmo que o /saml-login/relay não seja chamado (caso o Firefox
        # embarcado siga o redirect direto pro openfortivpn em network=host),
        # essa task vai detectar ppp aparecer e aplicar 172.16/12 + MASQUERADE.
        asyncio.create_task(self._post_saml_login_route_setup(client_id))

        # gateway_url já vem do client config no formato
        # https://host:port — só anexa /remote/saml/start?redirect=1.
        # ?redirect=1 instrui o FortiGate a redirecionar o SAMLResponse
        # pra 127.0.0.1:PORT em vez de tentar hostcheck via browser.
        gw = gateway_url.rstrip("/")
        start_url = f"{gw}/remote/saml/start?redirect=1"

        # Sobe saml-portal embarcado (Firefox + noVNC no servidor) em
        # network=host, MESMO loopback do tunnel openfortivpn. Quando o
        # FortiGate redireciona pra http://127.0.0.1:{port}/?id=X, o
        # Firefox segue o redirect e bate direto no openfortivpn — sem
        # precisar de copy/paste pelo user nem cert manual no browser DELE.
        # Saml-portal tem `VAGG_SAML_DISABLE_CALLBACK=1` pra não tentar
        # ouvir :8020 (que pertence ao openfortivpn).
        portal_url: str | None = None
        with contextlib.suppress(Exception):
            portal_url = await self._start_saml_portal_for_saml_login(
                client_id=client_id,
                gateway_url=gateway_url,
                start_url=start_url,
            )

        return {
            "start_url": start_url,
            "portal_url": portal_url,
            "port": port,
            "expected_callback_prefix": f"http://127.0.0.1:{port}/?id=",
            "container_id": str(container.id),
        }

    async def _start_saml_portal_for_saml_login(
        self,
        *,
        client_id: str,
        gateway_url: str,
        start_url: str,
    ) -> str:
        """Sobe Firefox + noVNC remoto em network=host pareado com o tunnel
        openfortivpn (também network=host). User vê noVNC servido pelo
        VAGG nginx (sem erro de cert), Firefox interno tem cert store próprio
        e segue redirect 127.0.0.1:8020 direto pro openfortivpn local."""
        # Mata qualquer portal anterior
        # Mata APENAS o saml-portal anterior DESSE client (label vagg.client_id)
        # — preserva portais de outros clients rodando em paralelo.
        with contextlib.suppress(DockerError):
            existing = await self._docker.containers.list(
                filters=json.dumps({
                    "label": ["vagg.role=saml-portal", f"vagg.client_id={client_id}"],
                }),
                all=True,
            )
            for c in existing:
                with contextlib.suppress(DockerError):
                    await c.delete(force=True)

        share_dir = self._client_socket_dir(client_id).parent / f"saml-{client_id}"
        share_dir.mkdir(parents=True, exist_ok=True)
        host_port = self.saml_portal_port_for(client_id)

        config = {
            "Image": self._saml_image(),
            "Env": [
                f"VAGG_SAML_GATEWAY_URL={gateway_url}",
                f"VAGG_SAML_COOKIE_OUT=/share/cookie",
                "VAGG_SAML_KIND=forti",
                f"VAGG_SAML_PORT={host_port}",
                # CRÍTICO: desabilita saml_callback embutido. Em network=host
                # com openfortivpn ao lado, :PORT já é dele.
                "VAGG_SAML_DISABLE_CALLBACK=1",
                f"WEB_LISTENING_PORT={host_port}",
                # VNC_LISTENING_PORT=-1: desabilita TCP rfbport do Xvnc.
                # Sem isso, multiplos saml-portals em network=host colidem :5900.
                "VNC_LISTENING_PORT=-1",
                "DISPLAY_WIDTH=1280",
                "DISPLAY_HEIGHT=800",
                "SECURE_CONNECTION=0",
                "KEEP_APP_RUNNING=1",
                "DARK_MODE=1",
                f"FF_OPEN_URL={start_url}",
                # Anti session-restore: garante que FF_OPEN_URL é honrado
                # mesmo com profile persistente. Apenas prefs sem chars
                # especiais (sed-friendly) — homepage URL vai por FF_OPEN_URL.
                "FF_PREF_browser.sessionstore.resume_from_crash=false",
                "FF_PREF_browser.sessionstore.max_resumed_crashes=0",
                "FF_PREF_toolkit.startup.max_resumed_crashes=-1",
            ],
            "HostConfig": {
                "AutoRemove": False,
                # network=host: compartilha loopback com openfortivpn.
                # WEB_LISTENING_PORT acima é dinâmico por client → cada saml-portal
                # ocupa uma porta única no host (14500-15000 range).
                "NetworkMode": "host",
                "Binds": [f"{share_dir}:/share:rw"],
                "RestartPolicy": {"Name": "no"},
            },
            "Labels": {
                "vagg.client_id": client_id,
                "vagg.role": "saml-portal",
                "vagg.mode": "saml-login-embedded",
            },
        }

        container = await self._docker.containers.create_or_replace(
            name=self._saml_container_name(client_id),
            config=config,
        )
        await container.start()
        log.info(
            "saml.portal.saml_login.started",
            client_id=client_id,
            container_id=container.id,
            host_port=host_port,
        )

        # Aguarda noVNC pronto (até 45s) — Firefox demora pra subir
        try:
            await self._wait_saml_portal_ready(host_port=host_port, timeout_s=45)
        except Exception:
            # não-fatal — frontend ainda pode mostrar com retry
            log.warning("saml.portal.saml_login.not_ready_yet", client_id=client_id)

        portal_host = os.environ.get("VAGG_PUBLIC_HOST", "192.168.68.102")
        return f"http://{portal_host}:{host_port}/"

    async def relay_saml_id(
        self,
        *,
        client_id: str,
        saml_id: str,
        port: int = 8020,
    ) -> dict[str, Any]:
        """Encaminha o SAML session id pro openfortivpn local.

        Vagg-core está em network=host, então 127.0.0.1:PORT é o mesmo
        loopback que openfortivpn (também network=host) está ouvindo.
        Um simples GET resolve.
        """
        # Validate: id deve ser ascii printable, < 200 chars, sem injection.
        if not saml_id or len(saml_id) > 200:
            raise ConflictError(
                "saml_id inválido (vazio ou >200 chars)",
                context={"client_id": client_id},
            )
        if not all(32 < ord(c) < 127 for c in saml_id):
            raise ConflictError(
                "saml_id contém caracteres não-imprimíveis",
                context={"client_id": client_id},
            )

        url = f"http://127.0.0.1:{port}/?id={saml_id}"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.get(url)
        except httpx.HTTPError as exc:
            raise TunnelOrchestrationError(
                f"falha ao relayar SAML id pro openfortivpn: {exc}",
                context={"client_id": client_id, "url": url},
            ) from exc

        log.info(
            "tunnel.saml_login.relay.ok",
            client_id=client_id,
            saml_id_len=len(saml_id),
            status=resp.status_code,
        )

        # Background task: aguarda ppp surgir e aplica rotas/masquerade FortiGate.
        # openfortivpn rodou com --set-routes=0, então o aggregator precisa
        # empurrar rotas pros ranges internos do gateway. Default 172.16/12
        # cobre Vexia (172.19.x) e outras Forti corporativas comuns.
        asyncio.create_task(self._post_saml_login_route_setup(client_id))

        return {
            "client_id": client_id,
            "relayed": True,
            "status_code": resp.status_code,
        }

    async def _post_saml_login_route_setup(self, client_id: str) -> None:
        """Após relay SAML, aguarda nova ppp iface surgir e pusha
        172.16.0.0/12 + MASQUERADE pra alcançar ranges internos do gateway."""
        # Snapshot atual de pppN
        before_res = await self._run_host_cmd(
            ["ip", "-br", "link", "show"], description="snapshot ppp"
        )
        before_ppps = set()
        if before_res is not None:
            for line in before_res.splitlines():
                tok = line.split()[:1]
                if tok and tok[0].startswith("ppp"):
                    before_ppps.add(tok[0].split("@", 1)[0])

        # Aguarda até 25s pra ppp novo aparecer
        new_ppp: str | None = None
        for _ in range(25):
            await asyncio.sleep(1)
            res = await self._run_host_cmd(
                ["ip", "-br", "link", "show"], description="poll ppp"
            )
            if res is None:
                continue
            for line in res.splitlines():
                cols = line.split()
                if not cols:
                    continue
                name = cols[0].split("@", 1)[0]
                if name.startswith("ppp") and name not in before_ppps and "LOWER_UP" in line:
                    new_ppp = name
                    break
            if new_ppp:
                break

        if not new_ppp:
            log.warning(
                "tunnel.saml_login.route_setup.no_new_ppp",
                client_id=client_id,
                before=list(before_ppps),
            )
            return

        log.info("tunnel.saml_login.route_setup.found_ppp", client_id=client_id, iface=new_ppp)

        # Aplica rotas + iptables idempotente
        for cmd, desc in [
            (
                ["ip", "route", "replace", "172.16.0.0/12", "dev", new_ppp],
                "route 172.16/12",
            ),
            (
                ["iptables", "-t", "nat", "-C", "POSTROUTING",
                 "-d", "172.16.0.0/12", "-o", new_ppp, "-j", "MASQUERADE"],
                "check masquerade",
            ),
        ]:
            await self._run_host_cmd(cmd, description=desc)
        # Idempotent ADDs (check antes pra não duplicar)
        check_fwd = await self._run_host_cmd(
            ["iptables", "-C", "FORWARD", "-o", new_ppp, "-j", "ACCEPT"],
            description="check forward out",
        )
        if check_fwd is None or "iptables: Bad rule" in (check_fwd or ""):
            await self._run_host_cmd(
                ["iptables", "-A", "FORWARD", "-o", new_ppp, "-j", "ACCEPT"],
                description="forward out",
            )
        check_fwd_in = await self._run_host_cmd(
            ["iptables", "-C", "FORWARD", "-i", new_ppp, "-j", "ACCEPT"],
            description="check forward in",
        )
        if check_fwd_in is None or "iptables: Bad rule" in (check_fwd_in or ""):
            await self._run_host_cmd(
                ["iptables", "-A", "FORWARD", "-i", new_ppp, "-j", "ACCEPT"],
                description="forward in",
            )
        check_masq = await self._run_host_cmd(
            ["iptables", "-t", "nat", "-C", "POSTROUTING",
             "-d", "172.16.0.0/12", "-o", new_ppp, "-j", "MASQUERADE"],
            description="check masquerade",
        )
        if check_masq is None or "iptables: Bad rule" in (check_masq or ""):
            await self._run_host_cmd(
                ["iptables", "-t", "nat", "-A", "POSTROUTING",
                 "-d", "172.16.0.0/12", "-o", new_ppp, "-j", "MASQUERADE"],
                description="masquerade 172.16/12",
            )

        log.info(
            "tunnel.saml_login.route_setup.ok",
            client_id=client_id,
            iface=new_ppp,
        )

    async def _run_host_cmd(self, argv: list[str], *, description: str) -> str | None:
        """Executa comando no host namespace (vagg-core em network=host)
        com privilégios elevados, via `docker exec --user root` no próprio
        container vagg-core (mesma namespace)."""
        own_name = await self._get_own_container_name()
        # Usa Docker client fresh pra não compartilhar conn pool com a
        # instância principal (que pode estar em meio de outras operações).
        d = aiodocker.Docker()
        try:
            container = await d.containers.get(own_name)
            execu = await container.exec(
                cmd=argv,
                user="root",
                stdout=True,
                stderr=True,
            )
            stream = execu.start(detach=False)
            async with stream:
                output_parts: list[bytes] = []
                while True:
                    msg = await stream.read_out()
                    if msg is None:
                        break
                    output_parts.append(msg.data)
            out = b"".join(output_parts).decode("utf-8", errors="replace")
            inspect = await execu.inspect()
            rc = inspect.get("ExitCode") if isinstance(inspect, dict) else None
            log.info(
                "tunnel.host_cmd.done",
                desc=description,
                argv=argv,
                rc=rc,
                out_len=len(out),
                out_preview=out[:200],
            )
            if rc not in (0, None):
                return None
            return out
        except (DockerError, OSError, asyncio.CancelledError) as exc:
            log.warning("tunnel.host_cmd.failed", desc=description, argv=argv, error=str(exc))
            return None
        finally:
            with contextlib.suppress(Exception):
                await d.close()

    _own_container_name_cache: str | None = None

    async def _get_own_container_name(self) -> str:
        """Descobre o nome do container vagg-core dinamicamente. Estratégia:
        env override > pegar pelo label 'com.docker.compose.service=vagg-core' >
        /proc/self/cgroup (container ID) > hostname > hardcoded fallback."""
        if self._own_container_name_cache:
            return self._own_container_name_cache

        # 1. env override
        name = os.environ.get("VAGG_CORE_CONTAINER_NAME")
        if name:
            self._own_container_name_cache = name
            return name

        # 2. /proc/self/cgroup contém o container ID
        try:
            with open("/proc/self/cgroup", encoding="utf-8") as f:
                cgroup = f.read()
            # cgroup v1: "12:cpuset:/docker/<id>"  v2: "0::/docker/<id>"
            import re as _re
            m = _re.search(r"/docker[/-]([0-9a-f]{12,64})", cgroup)
            if m:
                cid = m.group(1)
                try:
                    container = await self._docker.containers.get(cid)
                    inspect = await container.show()
                    full_name = inspect.get("Name", "").lstrip("/")
                    if full_name:
                        self._own_container_name_cache = full_name
                        return full_name
                except DockerError:
                    pass
        except OSError:
            pass

        # 3. busca pelo label compose
        try:
            containers = await self._docker.containers.list(
                filters=json.dumps({"label": ["com.docker.compose.service=vagg-core"]}),
            )
            if containers:
                inspect = await containers[0].show()
                full_name = inspect.get("Name", "").lstrip("/")
                if full_name:
                    self._own_container_name_cache = full_name
                    return full_name
        except DockerError:
            pass

        # 4. fallback hardcoded
        self._own_container_name_cache = "vagg-vagg-core-1"
        return self._own_container_name_cache

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
