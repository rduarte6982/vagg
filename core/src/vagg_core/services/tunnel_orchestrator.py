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
from pathlib import Path
from typing import Any, Protocol

import aiodocker
from aiodocker.exceptions import DockerError

from vagg_core.core.errors import ConflictError, CoreError, NotFoundError
from vagg_core.core.logging import get_logger
from vagg_core.db.models import TunnelState, VpnType
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
    ) -> str: ...

    async def disconnect(self, client_id: str) -> None: ...

    async def status(self, client_id: str) -> TunnelStatusReport: ...

    async def send_otp(self, client_id: str, code: str) -> None: ...

    async def tail_logs(self, client_id: str, *, lines: int = 100) -> list[str]: ...


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
        return {
            "Image": image,
            "Env": env_pairs,
            "HostConfig": {
                "CapAdd": ["NET_ADMIN"],
                "Devices": [
                    {
                        "PathOnHost": "/dev/net/tun",
                        "PathInContainer": "/dev/net/tun",
                        "CgroupPermissions": "rwm",
                    }
                ],
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
    ) -> str:
        image = self._image_by_protocol.get(protocol)
        if image is None:
            raise ConflictError(
                f"protocolo {protocol.value} ainda não suportado pelo orchestrator",
                context={"protocol": protocol.value},
            )

        cfg_dir, env = self._stage_config(
            client_id,
            config_text=config_text,
            username=username,
            password=password,
        )
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


def default_image_map(tag: str = "dev") -> dict[VpnType, str]:
    """Return the canonical ``vagg/tunnel-<protocol>:<tag>`` mapping for known protocols."""
    return {VpnType.OPENVPN: f"vagg/tunnel-openvpn:{tag}"}


def docker_from_env() -> aiodocker.Docker:
    """Build a Docker client honoring ``DOCKER_HOST`` (Linux unix socket by default)."""
    return aiodocker.Docker(url=os.environ.get("DOCKER_HOST"))
