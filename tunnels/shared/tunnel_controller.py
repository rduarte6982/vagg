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
    """Shared base: state from PID liveness, OTP via FIFO, signal via os.kill."""

    def __init__(self, *, pid_file: str, otp_pipe: str | None) -> None:
        self._pid_file = pid_file
        self._otp_pipe = otp_pipe

    def _state_from_pid(self) -> str:
        pid = _read_pid_file(self._pid_file)
        if pid is None:
            return "unknown"
        return "connected" if _process_alive(pid) else "down"

    async def query_state(self) -> dict[str, Any]:
        return {"state": self._state_from_pid()}

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
    socket_path.chmod(0o660)  # noqa: ASYNC240 — startup only
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
