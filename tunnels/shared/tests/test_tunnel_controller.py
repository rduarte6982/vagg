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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import tunnel_controller as tc
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


# ----- Auto-discovery: routes + DNS via `discover` cmd -----


def _ip_route_proc(stdout: bytes, returncode: int = 0) -> AsyncMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    return AsyncMock(return_value=proc)


class TestDiscover:
    async def test_filters_only_tunnel_routes(self, tmp_path: Path) -> None:
        # ip -j route output: mistura de rotas via eth0 (host), tun0 (vpn) e ppp0.
        ip_json = json.dumps(
            [
                {"dst": "default", "gateway": "192.168.1.1", "dev": "eth0"},
                {"dst": "192.168.1.0/24", "dev": "eth0"},
                {"dst": "10.80.0.0/16", "dev": "ppp0", "gateway": "10.0.200.1"},
                {"dst": "10.123.55.10", "dev": "tun0"},  # /32 implícito
                {"dst": "172.16.0.0/12", "dev": "br-abc"},
            ]
        ).encode()
        resolv = tmp_path / "resolv.conf"
        resolv.write_text(
            "search corp.example.com\nnameserver 10.0.0.1\nnameserver 10.0.0.2\n",
            encoding="utf-8",
        )
        ctl = TunnelController(FakeManager(), started_at=time.time())
        with (
            patch("tunnel_controller.asyncio.create_subprocess_exec", _ip_route_proc(ip_json)),
            patch("tunnel_controller._read_resolv_conf", return_value=(["10.0.0.1", "10.0.0.2"], ["corp.example.com"])),
        ):
            resp = await ctl.dispatch({"cmd": "discover"})

        assert resp["ok"] is True
        cidrs = sorted(r["cidr"] for r in resp["routes"])
        assert cidrs == ["10.123.55.10/32", "10.80.0.0/16"]
        assert resp["dns_servers"] == ["10.0.0.1", "10.0.0.2"]
        assert resp["search_domains"] == ["corp.example.com"]

    async def test_handles_ip_command_failure(self) -> None:
        ctl = TunnelController(FakeManager(), started_at=time.time())
        with (
            patch("tunnel_controller.asyncio.create_subprocess_exec", _ip_route_proc(b"", returncode=1)),
            patch("tunnel_controller._read_resolv_conf", return_value=([], [])),
        ):
            resp = await ctl.dispatch({"cmd": "discover"})
        assert resp == {
            "ok": True,
            "routes": [],
            "dns_servers": [],
            "search_domains": [],
        }

    async def test_handles_invalid_json(self) -> None:
        ctl = TunnelController(FakeManager(), started_at=time.time())
        with (
            patch("tunnel_controller.asyncio.create_subprocess_exec", _ip_route_proc(b"<not json>")),
            patch("tunnel_controller._read_resolv_conf", return_value=([], [])),
        ):
            resp = await ctl.dispatch({"cmd": "discover"})
        assert resp["routes"] == []

    async def test_filters_preexisting_ifaces_from_other_containers(
        self, tmp_path: Path
    ) -> None:
        """Regressão crítica: vagg roda com network_mode=host. Quando 2
        tunnels estão UP, todos veem todas as ifaces no mesmo namespace.
        Brasanitas viu tun0 do Roit e copiou as rotas dele. Snapshot do
        entrypoint registra o que JÁ existia; discover filtra essas.
        """
        # ip -j route output: rotas via tun0 (PRÉ-EXISTENTE — outro tunnel)
        # e rotas via ppp0 (do tunnel atual).
        ip_json = json.dumps(
            [
                {"dst": "10.0.0.0/24", "dev": "tun0", "gateway": "10.0.200.1"},
                {"dst": "10.80.0.0/16", "dev": "ppp0", "gateway": "10.5.1.1"},
            ]
        ).encode()

        # Simula snapshot do entrypoint: tun0 já estava lá.
        snap = tmp_path / "snapshot.json"
        snap.write_text(
            json.dumps([{"ifname": "tun0", "operstate": "UP"}, {"ifname": "eth0"}]),
            encoding="utf-8",
        )

        ctl = TunnelController(FakeManager(), started_at=time.time())
        with (
            patch("tunnel_controller._PREEXISTING_IFACES_PATH", str(snap)),
            patch("tunnel_controller.asyncio.create_subprocess_exec", _ip_route_proc(ip_json)),
            patch("tunnel_controller._read_resolv_conf", return_value=([], [])),
        ):
            resp = await ctl.dispatch({"cmd": "discover"})

        # Só ppp0 — tun0 era pré-existente.
        assert [r["cidr"] for r in resp["routes"]] == ["10.80.0.0/16"]
        assert [r["dev"] for r in resp["routes"]] == ["ppp0"]


class TestLoadPreexistingIfaces:
    def test_extracts_tunnel_iface_names(self, tmp_path: Path) -> None:
        snap = tmp_path / "s.json"
        snap.write_text(
            json.dumps(
                [
                    {"ifname": "lo"},
                    {"ifname": "eth0"},
                    {"ifname": "tun0"},
                    {"ifname": "ppp0"},
                    {"ifname": "br-abc"},
                ]
            ),
            encoding="utf-8",
        )
        out = tc._load_preexisting_ifaces(str(snap))
        assert out == {"tun0", "ppp0"}

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert tc._load_preexisting_ifaces(str(tmp_path / "missing")) == set()

    def test_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        snap = tmp_path / "s.json"
        snap.write_text("not json", encoding="utf-8")
        assert tc._load_preexisting_ifaces(str(snap)) == set()


class TestReadResolvConf:
    def test_parses_nameservers_and_search(self, tmp_path: Path) -> None:
        path = tmp_path / "resolv.conf"
        path.write_text(
            "# generated by openfortivpn\n"
            "search lpht.com.br sap.lpht.com.br\n"
            "nameserver 10.0.50.10\n"
            "nameserver 10.0.50.11\n"
            "options edns0\n",
            encoding="utf-8",
        )
        ns, search = tc._read_resolv_conf(str(path))
        assert ns == ["10.0.50.10", "10.0.50.11"]
        assert search == ["lpht.com.br", "sap.lpht.com.br"]

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        ns, search = tc._read_resolv_conf(str(tmp_path / "missing"))
        assert (ns, search) == ([], [])


# ----- End-to-end test through the unix socket server -----


@pytest.mark.skipif(not hasattr(__import__("asyncio"), "start_unix_server"), reason="unix sockets")
class TestServer:
    async def test_round_trip_via_unix_socket(self, tmp_path: Path) -> None:
        socket_path = str(tmp_path / "control.sock")
        mgr = FakeManager(state="up")
        ctl = TunnelController(mgr, started_at=time.time())
        server = await _serve(ctl, socket_path)
        try:
            reader, writer = await asyncio.open_unix_connection(socket_path)  # type: ignore[attr-defined,unused-ignore]
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
            reader, writer = await asyncio.open_unix_connection(socket_path)  # type: ignore[attr-defined,unused-ignore]
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
