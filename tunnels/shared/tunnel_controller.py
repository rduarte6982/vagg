#!/usr/bin/env python3
"""Unix-socket control plane for vagg-tunnel-* containers (SPEC §5.2).

Runs **inside** every tunnel container regardless of protocol. Listens on a
unix socket and bridges incoming JSON commands to a protocol-specific manager:

  - OpenVPN     → talks to OpenVPN's --management socket.
  - OpenConnect → tracks the openconnect PID, relays OTP via FIFO.
  - OpenFortiVPN → same pattern as OpenConnect.
  - WireGuard   → ``wg show`` for status; OTP not supported (no MFA in WG).
  - strongSwan  → ``swanctl --list-sas`` for status; OTP via FIFO (XAUTH).

Wire protocol on the control socket — line-oriented JSON, one msg per line::

    → {"cmd": "status"}              ← {"ok": true, "state": "up", "uptime_s": 123}
    → {"cmd": "restart"}             ← {"ok": true}
    → {"cmd": "otp", "code": "123"}  ← {"ok": true}
    unknown cmd                      ← {"ok": false, "error": "unknown_cmd"}

Stdlib-only on purpose — the Alpine runtime only has ``python3`` (no pip).
The container always runs on Linux; ``# type: ignore`` markers exist so the
file passes ``mypy --strict`` on Windows dev machines too.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal as signal_module
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("tunnel-controller")


# ============================================================
# Protocol definition
# ============================================================


class TunnelManager(Protocol):
    """Anything with these async methods can drive the controller."""

    async def query_state(self) -> dict[str, Any]: ...
    async def signal(self, sig: str) -> None: ...
    async def submit_otp(self, code: str) -> None: ...


# ============================================================
# Helpers
# ============================================================


def _signal_to_int(sig: str) -> int:
    """Convert ``"SIGUSR1"`` → ``signal.SIGUSR1``."""
    return int(getattr(signal_module, sig.upper(), signal_module.SIGTERM))


def _read_pid_file(path: str | None) -> int | None:
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _write_fifo(path: str, payload: str) -> None:
    """Blocking FIFO write. Caller must run this in an executor for async use."""
    fd = os.open(path, os.O_WRONLY)
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)


# ============================================================
# Manager: OpenVPN (talks to --management unix socket)
# ============================================================


class OpenVPNManager:
    """Async client for OpenVPN's --management interface over a unix socket."""

    def __init__(self, mgmt_socket: str) -> None:
        self._socket = mgmt_socket

    async def _connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_unix_connection(  # type: ignore[attr-defined,unused-ignore]
            self._socket
        )
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(reader.readline(), timeout=2.0)
        return reader, writer

    async def query_state(self) -> dict[str, Any]:
        reader, writer = await self._connect()
        try:
            writer.write(b"state\n")
            await writer.drain()
            lines: list[str] = []
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=2.0)
                decoded = line.decode("utf-8", errors="replace").rstrip()
                if decoded in ("END", ""):
                    break
                lines.append(decoded)
            if lines:
                first = lines[0].split(",")
                if len(first) > 1:
                    return {"state": first[1].lower() or "unknown"}
            return {"state": "unknown"}
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def signal(self, sig: str) -> None:
        _, writer = await self._connect()
        try:
            writer.write(f"signal {sig}\n".encode())
            await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def submit_otp(self, code: str) -> None:
        _, writer = await self._connect()
        try:
            writer.write(f'password "Auth" "{code}"\n'.encode())
            await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()


# ============================================================
# Manager: process + FIFO base (OpenConnect, OpenFortiVPN, strongSwan)
# ============================================================


class _ProcessFifoManager:
    """Shared base: state from PID liveness, OTP via FIFO, signal via os.kill.

    Importante: PID vivo NÃO significa "connected" — openfortivpn/openconnect
    com ``--persistent`` ficam vivos mesmo em auth-fail loop. Pra reportar
    "connected" exigimos também que exista uma iface de tunnel (tun*/ppp*/etc),
    que só aparece DEPOIS da auth bem-sucedida. Sem iface → "starting".
    """

    def __init__(self, *, pid_file: str, otp_pipe: str | None) -> None:
        self._pid_file = pid_file
        self._otp_pipe = otp_pipe

    def _state_from_pid(self) -> str:
        pid = _read_pid_file(self._pid_file)
        if pid is None:
            return "unknown"
        return "connected" if _process_alive(pid) else "down"

    async def query_state(self) -> dict[str, Any]:
        base = self._state_from_pid()
        if base != "connected":
            return {"state": base}
        # PID vivo não basta — confirma que a iface tun*/ppp* subiu.
        if await _has_tunnel_iface():
            return {"state": "connected"}
        # Processo vivo sem iface = ainda em auth/handshake (ou loop fail).
        return {"state": "starting"}

    async def signal(self, sig: str) -> None:
        pid = _read_pid_file(self._pid_file)
        if pid is None:
            raise OSError(f"no PID file at {self._pid_file}")
        os.kill(pid, _signal_to_int(sig))

    async def submit_otp(self, code: str) -> None:
        if not self._otp_pipe:
            raise OSError("OTP pipe not configured for this protocol")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _write_fifo, self._otp_pipe, code + "\n")


class OpenConnectManager(_ProcessFifoManager):
    """Cisco AnyConnect / Palo Alto GlobalProtect via openconnect."""


class OpenFortiVPNManager(_ProcessFifoManager):
    """Fortinet SSL VPN via openfortivpn."""


# ============================================================
# Manager: WireGuard (no OTP; status via `wg show`)
# ============================================================


class WireGuardManager:
    """Status from ``wg show <iface> latest-handshakes``. No OTP / no MFA."""

    # WG considers a peer alive when a handshake happened in the last ~3 minutes.
    _HANDSHAKE_FRESH_S = 180

    def __init__(self, *, iface: str) -> None:
        self._iface = iface

    async def query_state(self) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            "wg",
            "show",
            self._iface,
            "latest-handshakes",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, _ = await proc.communicate()
        if proc.returncode != 0:
            return {"state": "down"}
        now = int(time.time())
        for line in stdout_bytes.decode("utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) != 2:
                continue
            try:
                handshake_ts = int(parts[1])
            except ValueError:
                continue
            if handshake_ts > 0 and (now - handshake_ts) <= self._HANDSHAKE_FRESH_S:
                return {"state": "connected"}
        return {"state": "down"}

    async def signal(self, sig: str) -> None:
        # WireGuard restart is "wg-quick down + up", not signal-based.
        # We model SIGUSR1 (restart) as a no-op success; entrypoint runs wg-quick.
        if sig.upper() in {"SIGUSR1", "SIGHUP"}:
            return
        # SIGTERM is honored — kill the entrypoint shell.
        os.kill(1, _signal_to_int(sig))

    async def submit_otp(self, code: str) -> None:  # noqa: ARG002
        # WireGuard is cryptographic; no MFA channel exists.
        raise OSError("OTP not supported by WireGuard")


# ============================================================
# Manager: strongSwan (status via swanctl, OTP via XAUTH FIFO)
# ============================================================


class StrongSwanManager:
    """IPsec via swanctl. State from ``--list-sas``; OTP via XAUTH FIFO."""

    def __init__(self, *, otp_pipe: str | None) -> None:
        self._otp_pipe = otp_pipe

    async def query_state(self) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            "swanctl",
            "--list-sas",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, _ = await proc.communicate()
        if proc.returncode != 0:
            return {"state": "down"}
        text = stdout_bytes.decode("utf-8", errors="replace")
        if "ESTABLISHED" in text:
            return {"state": "connected"}
        if "CONNECTING" in text or "INSTALLING" in text:
            return {"state": "starting"}
        return {"state": "down"}

    async def signal(self, sig: str) -> None:
        if sig.upper() in {"SIGUSR1", "SIGHUP"}:
            # swanctl-driven reload doesn't take signals; do nothing soft.
            return
        os.kill(1, _signal_to_int(sig))

    async def submit_otp(self, code: str) -> None:
        if not self._otp_pipe:
            raise OSError("OTP pipe not configured for strongSwan")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _write_fifo, self._otp_pipe, code + "\n")


# ============================================================
# Auto-discovery of routes / DNS pushed by the gateway
# ============================================================


# Iface name prefixes que consideramos "do túnel" — qualquer rota saindo
# por essas devices é candidata a virar nat_mapping. Inclui:
#   tun*  — openfortivpn, openconnect (modo PPP), wireguard quando configurada
#   ppp*  — openfortivpn (default), pppd-based
#   gpd*  — GlobalProtect dedicated daemon iface (raro)
#   wg*   — WireGuard padrão wg-quick
#   tap*  — OpenVPN modo bridge
_TUNNEL_IFACE_PREFIXES = ("tun", "ppp", "gpd", "wg", "tap")

# Path em que o entrypoint grava as tunnel ifaces visíveis no host net
# namespace ANTES de subir o VPN binary. Usado pra filtrar ifaces criadas
# por OUTROS tunnel containers (vagg roda com network_mode=host, todos
# compartilham o mesmo namespace).
_PREEXISTING_IFACES_PATH = "/run/tunnel-iface-snapshot.json"


def _is_tunnel_dev(dev: str | None) -> bool:
    if not dev:
        return False
    return dev.startswith(_TUNNEL_IFACE_PREFIXES)


def _load_preexisting_ifaces(path: str | None = None) -> set[str]:
    """Lê o snapshot do entrypoint e retorna o conjunto de ifaces que JÁ
    existiam quando o tunnel container subiu.

    Sem o arquivo (ex: container antigo rodando), retorna conjunto vazio →
    fallback comportamental: aceita qualquer iface tunnel (broken antigo,
    mas seguro contra crash). O fix real depende do entrypoint atualizado.
    """
    # Lookup do módulo em runtime pra que tests possam patch _PREEXISTING_IFACES_PATH.
    target = path if path is not None else _PREEXISTING_IFACES_PATH
    try:
        with open(target, encoding="utf-8") as f:
            raw = json.loads(f.read() or "[]")
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("ifname")
        if isinstance(name, str) and name.startswith(_TUNNEL_IFACE_PREFIXES):
            out.add(name)
    return out


async def _has_tunnel_iface() -> bool:
    """True se existe iface tun*/ppp*/wg*/gpd*/tap* criada por ESTE container.

    Filtra ifaces pré-existentes (de outros tunnels rodando no mesmo host
    net namespace) usando o snapshot gravado pelo entrypoint. Sem snapshot,
    cai pra "qualquer iface tunnel conta" (compat).

    Usado pra distinguir VPN com auth bem-sucedida (iface NOVA existe) de
    processo vivo em auth-fail loop (sem iface nova).
    """
    preexisting = _load_preexisting_ifaces()
    try:
        proc = await asyncio.create_subprocess_exec(
            "ip", "-j", "link", "show",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, _ = await proc.communicate()
        if proc.returncode != 0:
            return False
        raw = json.loads(stdout_bytes.decode("utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(raw, list):
        return False
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("ifname")
        if not isinstance(name, str):
            continue
        if not name.startswith(_TUNNEL_IFACE_PREFIXES):
            continue
        if name in preexisting:
            continue  # iface de outro tunnel container
        return True
    return False


async def _discover_routes() -> list[dict[str, Any]]:
    """Parse ``ip -j route show`` and return tunnel-bound routes criadas
    por ESTE container.

    Filtra rotas via ifaces pré-existentes (de outros tunnels no mesmo host
    net namespace, já que vagg usa network_mode=host) usando o snapshot
    gravado pelo entrypoint antes do VPN binary subir.

    Returns a list of dicts shaped like::

        {"cidr": "10.80.0.0/16", "dev": "ppp0", "gateway": "10.0.200.1"}

    Default routes (0.0.0.0/0 / ::/0) são filtradas — pertencem ao host.
    Rotas via ifaces non-tunnel (eth0/lo/br-*) e via ifaces que JÁ existiam
    quando o container subiu também são filtradas.
    """
    preexisting = _load_preexisting_ifaces()
    proc = await asyncio.create_subprocess_exec(
        "ip",
        "-j",
        "route",
        "show",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, _ = await proc.communicate()
    if proc.returncode != 0:
        return []
    try:
        raw = json.loads(stdout_bytes.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []

    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        dst = entry.get("dst")
        dev = entry.get("dev")
        if dst in (None, "default"):
            continue
        if not _is_tunnel_dev(dev):
            continue
        if dev in preexisting:
            continue  # rota de outro tunnel container
        # ``ip -j`` omite o /32 quando o destino é host único; normaliza.
        cidr = dst if "/" in dst else f"{dst}/32"
        out.append(
            {
                "cidr": cidr,
                "dev": dev,
                "gateway": entry.get("gateway"),
            }
        )
    return out


def _read_resolv_conf(path: str) -> tuple[list[str], list[str]]:
    """Return ``(nameservers, search_domains)`` from ``/etc/resolv.conf``.

    Empty lists when the file is missing or unreadable. Comments (``#``,
    ``;``) and blank lines are skipped. Multiple ``search`` entries collapse
    into one list (last write wins per resolv.conf semantics).
    """
    nameservers: list[str] = []
    search: list[str] = []
    try:
        with open(path, encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith(("#", ";")):
                    continue
                parts = line.split()
                if not parts:
                    continue
                key = parts[0].lower()
                if key == "nameserver" and len(parts) >= 2:
                    nameservers.append(parts[1])
                elif key == "search" and len(parts) >= 2:
                    search = parts[1:]
    except OSError:
        return [], []
    return nameservers, search


# ============================================================
# Controller (protocol-agnostic)
# ============================================================


class TunnelController:
    """Dispatches incoming control-socket messages to the manager."""

    def __init__(self, manager: TunnelManager, *, started_at: float) -> None:
        self._mgr = manager
        self._started = started_at

    async def dispatch(self, msg: dict[str, Any]) -> dict[str, Any]:
        cmd = msg.get("cmd")
        if cmd == "status":
            return await self._status()
        if cmd == "restart":
            return await self._restart()
        if cmd == "otp":
            return await self._otp(msg)
        if cmd == "discover":
            return await self._discover()
        return {"ok": False, "error": "unknown_cmd", "cmd": cmd}

    async def _status(self) -> dict[str, Any]:
        try:
            state = await self._mgr.query_state()
        except (OSError, TimeoutError, ConnectionRefusedError) as exc:
            log.debug("query_state failed: %s", exc)
            state = {"state": "unknown"}
        return {
            "ok": True,
            "state": state.get("state", "unknown"),
            "uptime_s": int(time.time() - self._started),
        }

    async def _restart(self) -> dict[str, Any]:
        try:
            await self._mgr.signal("SIGUSR1")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    async def _otp(self, msg: dict[str, Any]) -> dict[str, Any]:
        code = msg.get("code")
        if not code or not isinstance(code, str):
            return {"ok": False, "error": "missing_code"}
        try:
            await self._mgr.submit_otp(code)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    async def _discover(self) -> dict[str, Any]:
        """Auto-discover routes + DNS pushed by the gateway.

        Runs ``ip -j route`` inside the container, filters routes whose
        device looks like a tunnel iface (tun*/ppp*/gpd*/wg*), and reads
        /etc/resolv.conf for nameservers. Caller (orchestrator on the
        host) uses this to seed nat_mappings + dns_server without manual
        config.
        """
        routes = await _discover_routes()
        dns_servers, search_domains = _read_resolv_conf("/etc/resolv.conf")
        return {
            "ok": True,
            "routes": routes,
            "dns_servers": dns_servers,
            "search_domains": search_domains,
        }


# ============================================================
# Unix-socket server
# ============================================================


async def _serve(controller: TunnelController, control_socket: str) -> asyncio.AbstractServer:
    socket_path = Path(control_socket)
    socket_path.parent.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 — startup only
    if socket_path.exists():  # noqa: ASYNC240 — startup only
        socket_path.unlink()  # noqa: ASYNC240 — startup only

    async def _client_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not raw:
                return
            try:
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    raise TypeError("expected JSON object")
            except (json.JSONDecodeError, TypeError) as exc:
                response: dict[str, Any] = {"ok": False, "error": f"invalid_json:{exc}"}
            else:
                response = await controller.dispatch(msg)
            writer.write((json.dumps(response) + "\n").encode("utf-8"))
            await writer.drain()
        except TimeoutError:
            pass
        except Exception as exc:  # noqa: BLE001 — never let a client kill the server
            log.exception("handler crashed: %s", exc)
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    server: asyncio.AbstractServer = await asyncio.start_unix_server(  # type: ignore[attr-defined,unused-ignore]
        _client_handler, path=str(socket_path)
    )
    # 0o666 ao invés de 0o660 porque o tunnel-controller roda como root no
    # container e o core conecta como uid 1000 — sem world-write, o status
    # check falha com EACCES. Em produção (mesmo user-ns), trocar pra 0o660.
    socket_path.chmod(0o666)  # noqa: ASYNC240 — startup only
    return server


# ============================================================
# Manager factory + main
# ============================================================


_MANAGER_KINDS = ("openvpn", "openconnect", "openfortivpn", "wireguard", "strongswan")


def _make_manager(kind: str, args: argparse.Namespace) -> TunnelManager:
    if kind == "openvpn":
        return OpenVPNManager(args.openvpn_mgmt)
    if kind == "openconnect":
        return OpenConnectManager(pid_file=args.pid_file, otp_pipe=args.otp_pipe)
    if kind == "openfortivpn":
        return OpenFortiVPNManager(pid_file=args.pid_file, otp_pipe=args.otp_pipe)
    if kind == "wireguard":
        if not args.wg_iface:
            raise SystemExit("--wg-iface is required for wireguard manager")
        return WireGuardManager(iface=args.wg_iface)
    if kind == "strongswan":
        return StrongSwanManager(otp_pipe=args.otp_pipe)
    raise SystemExit(f"unsupported manager kind: {kind}")


def _shutdown_factory(stop: asyncio.Future[Any], name: str) -> Callable[[], None]:
    def _on_signal() -> None:
        if not stop.done():
            stop.set_result(name)

    return _on_signal


async def _main(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format='{"ts":"%(asctime)s","lvl":"%(levelname)s","msg":"%(message)s"}',
    )

    started = time.time()
    manager = _make_manager(args.manager, args)
    controller = TunnelController(manager, started_at=started)
    server = await _serve(controller, args.control_socket)

    log.info("tunnel-controller listening on %s (manager=%s)", args.control_socket, args.manager)

    loop = asyncio.get_running_loop()
    stop: asyncio.Future[Any] = loop.create_future()
    for sig_name in ("SIGTERM", "SIGINT"):
        with contextlib.suppress(ImportError, NotImplementedError, ValueError):
            sig = getattr(signal_module, sig_name)
            loop.add_signal_handler(sig, _shutdown_factory(stop, sig_name))

    try:
        async with server:
            await stop
    finally:
        log.info("tunnel-controller stopping")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    doc = __doc__ or ""
    parser = argparse.ArgumentParser(description=doc.split("\n", maxsplit=1)[0])
    parser.add_argument(
        "--control-socket",
        default=os.environ.get("TUNNEL_CONTROL_SOCKET", "/var/run/vagg/control.sock"),
    )
    parser.add_argument(
        "--openvpn-mgmt",
        default=os.environ.get("TUNNEL_OPENVPN_MGMT_SOCKET", "/var/run/openvpn-mgmt.sock"),
    )
    parser.add_argument(
        "--pid-file",
        default=os.environ.get("TUNNEL_PID_FILE", "/run/tunnel.pid"),
        help="Path to the VPN process PID file (openconnect/openfortivpn).",
    )
    parser.add_argument(
        "--otp-pipe",
        default=os.environ.get("TUNNEL_OTP_PIPE", "/run/otp.pipe"),
        help="Named pipe relay for OTP codes (openconnect/openfortivpn/strongswan).",
    )
    parser.add_argument(
        "--wg-iface",
        default=os.environ.get("TUNNEL_DEV"),
        help="WireGuard interface name (uses TUNNEL_DEV by default).",
    )
    parser.add_argument(
        "--manager",
        choices=list(_MANAGER_KINDS),
        default=os.environ.get("TUNNEL_MANAGER", "openvpn"),
    )
    parser.add_argument("--log-level", default=os.environ.get("TUNNEL_LOG_LEVEL", "INFO"))
    return parser.parse_args(argv)


def main() -> int:
    return asyncio.run(_main(parse_args()))


if __name__ == "__main__":
    sys.exit(main())
