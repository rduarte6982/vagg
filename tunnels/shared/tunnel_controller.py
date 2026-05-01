#!/usr/bin/env python3
"""Unix-socket control plane for vagg-tunnel-* containers (SPEC §5.2).

Runs **inside** the tunnel container. Listens on a unix socket and bridges
external commands to the protocol-specific manager:

  - For OpenVPN: talks to OpenVPN's --management socket.
  - Other protocols (Phase 5) plug in via ``--manager`` flag.

Wire protocol on the control socket — line-oriented JSON, one msg per line::

    → {"cmd": "status"}              ← {"ok": true, "state": "up", "uptime_s": 123}
    → {"cmd": "restart"}             ← {"ok": true}
    → {"cmd": "otp", "code": "123"}  ← {"ok": true}
    unknown cmd                      ← {"ok": false, "error": "unknown_cmd"}

Stdlib-only on purpose — the runtime image (Alpine) only has ``python3``.
The container always runs on Linux; the ``# type: ignore`` markers around
``asyncio.open_unix_connection`` exist purely so ``mypy --strict`` is portable
to dev machines without unix-socket support.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("tunnel-controller")


class TunnelManager(Protocol):
    """Anything with these async methods can drive the controller."""

    async def query_state(self) -> dict[str, Any]: ...
    async def signal(self, sig: str) -> None: ...
    async def submit_otp(self, code: str) -> None: ...


class OpenVPNManager:
    """Async client for OpenVPN's --management interface over a unix socket."""

    def __init__(self, mgmt_socket: str) -> None:
        self._socket = mgmt_socket

    async def _connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_unix_connection(self._socket)  # type: ignore[attr-defined]
        # Eat the welcome banner; it's a single line ending with \r\n.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(reader.readline(), timeout=2.0)
        return reader, writer

    async def query_state(self) -> dict[str, Any]:
        """Return ``{"state": "<openvpn-state>"}`` from the ``state`` command."""
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
                # state line: <unix-ts>,<state>,...
                first = lines[0].split(",")
                if len(first) > 1:
                    return {"state": first[1].lower() or "unknown"}
            return {"state": "unknown"}
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def signal(self, sig: str) -> None:
        """Send a signal to OpenVPN via mgmt (e.g. ``SIGUSR1`` to restart)."""
        _, writer = await self._connect()
        try:
            writer.write(f"signal {sig}\n".encode())
            await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def submit_otp(self, code: str) -> None:
        """Push the OTP into OpenVPN's pending password prompt.

        OpenVPN's prompt name varies; we send to ``Auth`` which matches the
        default static-challenge flow most clients use.
        """
        _, writer = await self._connect()
        try:
            payload = f'password "Auth" "{code}"\n'.encode()
            writer.write(payload)
            await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()


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

    server: asyncio.AbstractServer = await asyncio.start_unix_server(  # type: ignore[attr-defined]
        _client_handler, path=str(socket_path)
    )
    socket_path.chmod(0o660)  # noqa: ASYNC240 — startup only
    return server


def _make_manager(kind: str, mgmt_socket: str) -> TunnelManager:
    if kind == "openvpn":
        return OpenVPNManager(mgmt_socket)
    raise SystemExit(f"unsupported manager kind: {kind}")


async def _main(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format='{"ts":"%(asctime)s","lvl":"%(levelname)s","msg":"%(message)s"}',
    )

    started = time.time()
    manager = _make_manager(args.manager, args.openvpn_mgmt)
    controller = TunnelController(manager, started_at=started)
    server = await _serve(controller, args.control_socket)

    log.info("tunnel-controller listening on %s", args.control_socket)

    loop = asyncio.get_running_loop()
    stop: asyncio.Future[Any] = loop.create_future()
    for sig_name in ("SIGTERM", "SIGINT"):
        try:
            import signal as _signal

            sig = getattr(_signal, sig_name)
            loop.add_signal_handler(sig, _shutdown_factory(stop, sig_name))
        except (ImportError, NotImplementedError, ValueError):
            pass

    try:
        async with server:
            await stop
    finally:
        log.info("tunnel-controller stopping")
    return 0


def _shutdown_factory(stop: asyncio.Future[Any], name: str) -> Callable[[], None]:
    def _on_signal() -> None:
        if not stop.done():
            stop.set_result(name)

    return _on_signal


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
    parser.add_argument("--manager", choices=["openvpn"], default="openvpn")
    parser.add_argument(
        "--log-level",
        default=os.environ.get("TUNNEL_LOG_LEVEL", "INFO"),
    )
    return parser.parse_args(argv)


def main() -> int:
    return asyncio.run(_main(parse_args()))


if __name__ == "__main__":
    sys.exit(main())
