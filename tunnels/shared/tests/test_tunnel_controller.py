"""Tests for the in-container tunnel controller.

Mocks the protocol-specific manager so we exercise the dispatch + serialization
without needing OpenVPN running.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest

from tunnel_controller import TunnelController, _serve, parse_args


class FakeManager:
    """Stand-in for ``OpenVPNManager`` driven entirely from tests."""

    def __init__(
        self,
        *,
        state: str = "connected",
        raise_on_otp: Exception | None = None,
        raise_on_signal: Exception | None = None,
    ) -> None:
        self._state = state
        self._raise_otp = raise_on_otp
        self._raise_signal = raise_on_signal
        self.signals: list[str] = []
        self.otps: list[str] = []

    async def query_state(self) -> dict[str, Any]:
        return {"state": self._state}

    async def signal(self, sig: str) -> None:
        if self._raise_signal:
            raise self._raise_signal
        self.signals.append(sig)

    async def submit_otp(self, code: str) -> None:
        if self._raise_otp:
            raise self._raise_otp
        self.otps.append(code)


# ----- Dispatch unit tests -----


class TestStatus:
    async def test_returns_state_and_uptime(self) -> None:
        mgr = FakeManager(state="connected")
        ctl = TunnelController(mgr, started_at=time.time() - 5)
        resp = await ctl.dispatch({"cmd": "status"})
        assert resp["ok"] is True
        assert resp["state"] == "connected"
        assert resp["uptime_s"] >= 5

    async def test_state_unknown_when_mgmt_unreachable(self) -> None:
        class Broken:
            async def query_state(self) -> dict[str, Any]:
                raise ConnectionRefusedError("mgmt not ready")

            async def signal(self, sig: str) -> None: ...
            async def submit_otp(self, code: str) -> None: ...

        ctl = TunnelController(Broken(), started_at=time.time())
        resp = await ctl.dispatch({"cmd": "status"})
        assert resp["ok"] is True
        assert resp["state"] == "unknown"


class TestRestart:
    async def test_sends_sigusr1(self) -> None:
        mgr = FakeManager()
        ctl = TunnelController(mgr, started_at=time.time())
        resp = await ctl.dispatch({"cmd": "restart"})
        assert resp == {"ok": True}
        assert mgr.signals == ["SIGUSR1"]

    async def test_oserror_returns_error_envelope(self) -> None:
        mgr = FakeManager(raise_on_signal=OSError("broken pipe"))
        ctl = TunnelController(mgr, started_at=time.time())
        resp = await ctl.dispatch({"cmd": "restart"})
        assert resp["ok"] is False
        assert "broken pipe" in resp["error"]


class TestOtp:
    async def test_forwards_code(self) -> None:
        mgr = FakeManager()
        ctl = TunnelController(mgr, started_at=time.time())
        resp = await ctl.dispatch({"cmd": "otp", "code": "123456"})
        assert resp == {"ok": True}
        assert mgr.otps == ["123456"]

    async def test_missing_code_rejected(self) -> None:
        mgr = FakeManager()
        ctl = TunnelController(mgr, started_at=time.time())
        resp = await ctl.dispatch({"cmd": "otp"})
        assert resp == {"ok": False, "error": "missing_code"}

    async def test_oserror_returns_error_envelope(self) -> None:
        mgr = FakeManager(raise_on_otp=OSError("auth socket gone"))
        ctl = TunnelController(mgr, started_at=time.time())
        resp = await ctl.dispatch({"cmd": "otp", "code": "1"})
        assert resp["ok"] is False


class TestUnknown:
    async def test_unknown_cmd_returns_error(self) -> None:
        ctl = TunnelController(FakeManager(), started_at=time.time())
        resp = await ctl.dispatch({"cmd": "spaceship"})
        assert resp == {"ok": False, "error": "unknown_cmd", "cmd": "spaceship"}


# ----- End-to-end test through the unix socket server -----


@pytest.mark.skipif(not hasattr(__import__("asyncio"), "start_unix_server"), reason="unix sockets")
class TestServer:
    async def test_round_trip_via_unix_socket(self, tmp_path: Path) -> None:
        socket_path = str(tmp_path / "control.sock")
        mgr = FakeManager(state="up")
        ctl = TunnelController(mgr, started_at=time.time())
        server = await _serve(ctl, socket_path)
        try:
            reader, writer = await asyncio.open_unix_connection(socket_path)  # type: ignore[attr-defined]
            writer.write(b'{"cmd":"status"}\n')
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=2.0)
            writer.close()
            await writer.wait_closed()
            response = json.loads(line)
            assert response["ok"] is True
            assert response["state"] == "up"
        finally:
            server.close()
            await server.wait_closed()

    async def test_invalid_json_returns_error(self, tmp_path: Path) -> None:
        socket_path = str(tmp_path / "control.sock")
        ctl = TunnelController(FakeManager(), started_at=time.time())
        server = await _serve(ctl, socket_path)
        try:
            reader, writer = await asyncio.open_unix_connection(socket_path)  # type: ignore[attr-defined]
            writer.write(b"not-json\n")
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=2.0)
            writer.close()
            await writer.wait_closed()
            response = json.loads(line)
            assert response["ok"] is False
            assert response["error"].startswith("invalid_json")
        finally:
            server.close()
            await server.wait_closed()


class TestArgparse:
    def test_defaults(self) -> None:
        ns = parse_args([])
        assert ns.manager == "openvpn"
        assert ns.control_socket.endswith("control.sock")

    def test_overrides(self) -> None:
        ns = parse_args(["--control-socket", "/tmp/x.sock", "--manager", "openvpn"])
        assert ns.control_socket == "/tmp/x.sock"
