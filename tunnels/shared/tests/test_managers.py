"""Unit tests for the per-protocol manager classes (Phase 5)."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import tunnel_controller as tc

pytestmark = pytest.mark.asyncio


# ============================================================
# Helpers
# ============================================================


def _write_pid_file(tmp_path: Path, pid: int) -> Path:
    pid_file = tmp_path / "tunnel.pid"
    pid_file.write_text(f"{pid}\n", encoding="utf-8")
    return pid_file


def _make_subprocess_mock(returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> AsyncMock:
    """Build an AsyncMock that imitates ``asyncio.create_subprocess_exec``."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return AsyncMock(return_value=proc)


# ============================================================
# OpenConnect / OpenFortiVPN (process+fifo) — same _ProcessFifoManager base
# ============================================================


class TestProcessFifoManagers:
    @pytest.mark.parametrize("manager_cls", [tc.OpenConnectManager, tc.OpenFortiVPNManager])
    async def test_query_state_returns_unknown_when_no_pid_file(
        self, tmp_path: Path, manager_cls: type
    ) -> None:
        m = manager_cls(pid_file=str(tmp_path / "missing.pid"), otp_pipe=None)
        assert (await m.query_state()) == {"state": "unknown"}

    @pytest.mark.parametrize("manager_cls", [tc.OpenConnectManager, tc.OpenFortiVPNManager])
    async def test_query_state_connected_when_process_alive_and_iface_up(
        self, tmp_path: Path, manager_cls: type
    ) -> None:
        # Use the test process's own PID — it's definitely alive.
        pid_file = _write_pid_file(tmp_path, os.getpid())
        m = manager_cls(pid_file=str(pid_file), otp_pipe=None)
        with patch("tunnel_controller._has_tunnel_iface", AsyncMock(return_value=True)):
            assert (await m.query_state()) == {"state": "connected"}

    @pytest.mark.parametrize("manager_cls", [tc.OpenConnectManager, tc.OpenFortiVPNManager])
    async def test_query_state_starting_when_alive_but_no_iface(
        self, tmp_path: Path, manager_cls: type
    ) -> None:
        """PID vivo SEM iface tun*/ppp* = ainda em handshake/auth-fail loop."""
        pid_file = _write_pid_file(tmp_path, os.getpid())
        m = manager_cls(pid_file=str(pid_file), otp_pipe=None)
        with patch("tunnel_controller._has_tunnel_iface", AsyncMock(return_value=False)):
            assert (await m.query_state()) == {"state": "starting"}

    @pytest.mark.parametrize("manager_cls", [tc.OpenConnectManager, tc.OpenFortiVPNManager])
    async def test_query_state_down_when_pid_dead(self, tmp_path: Path, manager_cls: type) -> None:
        # PID 99999 is virtually never live.
        pid_file = _write_pid_file(tmp_path, 999_999)
        m = manager_cls(pid_file=str(pid_file), otp_pipe=None)
        assert (await m.query_state()) == {"state": "down"}

    async def test_signal_calls_oskill(self, tmp_path: Path) -> None:
        pid_file = _write_pid_file(tmp_path, 4242)
        m = tc.OpenConnectManager(pid_file=str(pid_file), otp_pipe=None)
        with patch("tunnel_controller.os.kill") as kill_mock:
            await m.signal("SIGUSR1")
        kill_mock.assert_called_once()
        args, _ = kill_mock.call_args
        assert args[0] == 4242

    async def test_signal_raises_without_pid_file(self, tmp_path: Path) -> None:
        m = tc.OpenConnectManager(
            pid_file=str(tmp_path / "missing.pid"),
            otp_pipe=None,
        )
        with pytest.raises(OSError, match="no PID file"):
            await m.signal("SIGTERM")

    async def test_submit_otp_writes_to_fifo(self, tmp_path: Path) -> None:
        pipe_path = tmp_path / "otp.pipe"
        os.mkfifo(pipe_path)  # type: ignore[attr-defined,unused-ignore]

        # Reader: drains the FIFO so writer doesn't block forever.
        reader_buf: list[str] = []

        def _reader() -> None:
            with open(pipe_path, encoding="utf-8") as fifo:
                reader_buf.append(fifo.read())

        loop = asyncio.get_running_loop()
        reader_task = loop.run_in_executor(None, _reader)

        m = tc.OpenConnectManager(
            pid_file=str(tmp_path / "tunnel.pid"),
            otp_pipe=str(pipe_path),
        )
        await m.submit_otp("123456")
        await reader_task
        assert reader_buf == ["123456\n"]

    async def test_submit_otp_raises_without_pipe(self, tmp_path: Path) -> None:
        m = tc.OpenConnectManager(
            pid_file=str(tmp_path / "tunnel.pid"),
            otp_pipe=None,
        )
        with pytest.raises(OSError, match="not configured"):
            await m.submit_otp("123")


# ============================================================
# WireGuard
# ============================================================


class TestWireGuardManager:
    async def test_state_connected_when_handshake_recent(self) -> None:
        ts = int(time.time()) - 30  # 30s ago, well within freshness window
        stdout = f"abcdEFGH=  {ts}\n".encode()
        m = tc.WireGuardManager(iface="wg0")
        with patch(
            "tunnel_controller.asyncio.create_subprocess_exec",
            _make_subprocess_mock(0, stdout=stdout),
        ):
            result = await m.query_state()
        assert result == {"state": "connected"}

    async def test_state_down_when_handshake_stale(self) -> None:
        # Handshake from 1h ago — outside freshness window.
        ts = int(time.time()) - 3600
        stdout = f"abcd=  {ts}\n".encode()
        m = tc.WireGuardManager(iface="wg0")
        with patch(
            "tunnel_controller.asyncio.create_subprocess_exec",
            _make_subprocess_mock(0, stdout=stdout),
        ):
            result = await m.query_state()
        assert result == {"state": "down"}

    async def test_state_down_when_no_handshakes(self) -> None:
        m = tc.WireGuardManager(iface="wg0")
        with patch(
            "tunnel_controller.asyncio.create_subprocess_exec",
            _make_subprocess_mock(0, stdout=b""),
        ):
            result = await m.query_state()
        assert result == {"state": "down"}

    async def test_state_down_when_wg_show_fails(self) -> None:
        m = tc.WireGuardManager(iface="wg0")
        with patch(
            "tunnel_controller.asyncio.create_subprocess_exec",
            _make_subprocess_mock(1, stderr=b"iface not found"),
        ):
            result = await m.query_state()
        assert result == {"state": "down"}

    async def test_otp_not_supported(self) -> None:
        m = tc.WireGuardManager(iface="wg0")
        with pytest.raises(OSError, match="not supported"):
            await m.submit_otp("123")

    async def test_signal_sigusr1_restarts_via_wg_quick(self) -> None:
        # restart real: down + up (não mais no-op). Sem os.kill.
        m = tc.WireGuardManager(iface="wg0")
        exec_mock = _make_subprocess_mock(0)
        with (
            patch("tunnel_controller.asyncio.create_subprocess_exec", exec_mock),
            patch("tunnel_controller.os.kill") as kill_mock,
        ):
            await m.signal("SIGUSR1")
        kill_mock.assert_not_called()
        actions = [c.args for c in exec_mock.call_args_list]
        assert actions == [("wg-quick", "down", "wg0"), ("wg-quick", "up", "wg0")]

    async def test_signal_sigusr1_raises_when_up_fails(self) -> None:
        m = tc.WireGuardManager(iface="wg0")
        proc_down = MagicMock(returncode=0)
        proc_down.communicate = AsyncMock(return_value=(b"", b""))
        proc_up = MagicMock(returncode=1)
        proc_up.communicate = AsyncMock(return_value=(b"", b""))
        exec_mock = AsyncMock(side_effect=[proc_down, proc_up])
        with (  # noqa: SIM117
            patch("tunnel_controller.asyncio.create_subprocess_exec", exec_mock),
        ):
            with pytest.raises(OSError, match="wg-quick up"):
                await m.signal("SIGUSR1")

    async def test_signal_sigterm_still_kills(self) -> None:
        m = tc.WireGuardManager(iface="wg0")
        with patch("tunnel_controller.os.kill") as kill_mock:
            await m.signal("SIGTERM")
        kill_mock.assert_called_once()


# ============================================================
# strongSwan
# ============================================================


class TestStrongSwanManager:
    async def test_state_connected_when_established(self) -> None:
        m = tc.StrongSwanManager(otp_pipe=None)
        with patch(
            "tunnel_controller.asyncio.create_subprocess_exec",
            _make_subprocess_mock(0, stdout=b"vagg-conn: ESTABLISHED 5 seconds ago\n"),
        ):
            assert (await m.query_state()) == {"state": "connected"}

    async def test_state_starting_when_connecting(self) -> None:
        m = tc.StrongSwanManager(otp_pipe=None)
        with patch(
            "tunnel_controller.asyncio.create_subprocess_exec",
            _make_subprocess_mock(0, stdout=b"vagg-conn: CONNECTING\n"),
        ):
            assert (await m.query_state()) == {"state": "starting"}

    async def test_state_down_when_swanctl_fails(self) -> None:
        m = tc.StrongSwanManager(otp_pipe=None)
        with patch(
            "tunnel_controller.asyncio.create_subprocess_exec",
            _make_subprocess_mock(1, stderr=b"connection refused"),
        ):
            assert (await m.query_state()) == {"state": "down"}

    async def test_otp_writes_to_fifo(self, tmp_path: Path) -> None:
        pipe_path = tmp_path / "otp.pipe"
        os.mkfifo(pipe_path)  # type: ignore[attr-defined,unused-ignore]
        reader_buf: list[str] = []

        def _reader() -> None:
            with open(pipe_path, encoding="utf-8") as fifo:
                reader_buf.append(fifo.read())

        loop = asyncio.get_running_loop()
        reader_task = loop.run_in_executor(None, _reader)

        m = tc.StrongSwanManager(otp_pipe=str(pipe_path))
        await m.submit_otp("999000")
        await reader_task
        assert reader_buf == ["999000\n"]

    async def test_otp_without_pipe_raises(self) -> None:
        m = tc.StrongSwanManager(otp_pipe=None)
        with pytest.raises(OSError, match="not configured"):
            await m.submit_otp("123")


# ============================================================
# Manager factory
# ============================================================


class TestMakeManager:
    def _ns(self, **overrides: object) -> object:
        from argparse import Namespace

        return Namespace(
            manager="openvpn",
            openvpn_mgmt="/tmp/mgmt.sock",
            pid_file="/run/tunnel.pid",
            otp_pipe="/run/otp.pipe",
            wg_iface=None,
            **overrides,
        )

    def test_dispatch_each_kind(self) -> None:
        for kind in ("openvpn", "openconnect", "openfortivpn", "strongswan"):
            ns = self._ns(manager=kind)
            mgr = tc._make_manager(kind, ns)  # type: ignore[arg-type]
            assert hasattr(mgr, "query_state")

    def test_wireguard_requires_iface(self) -> None:
        ns = self._ns(manager="wireguard", wg_iface=None)
        with pytest.raises(SystemExit, match="wg-iface"):
            tc._make_manager("wireguard", ns)  # type: ignore[arg-type]

    def test_wireguard_with_iface_ok(self) -> None:
        ns = self._ns(manager="wireguard", wg_iface="tun-abc")
        mgr = tc._make_manager("wireguard", ns)  # type: ignore[arg-type]
        assert isinstance(mgr, tc.WireGuardManager)

    def test_unknown_kind_raises(self) -> None:
        ns = self._ns()
        with pytest.raises(SystemExit, match="unsupported"):
            tc._make_manager("nonsense", ns)  # type: ignore[arg-type]
