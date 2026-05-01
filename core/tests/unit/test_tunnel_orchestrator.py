"""Unit tests for TunnelOrchestrator with mocked aiodocker."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiodocker.exceptions import DockerError

from vagg_core.db.models import TunnelState, VpnType
from vagg_core.services.tunnel_orchestrator import (
    TunnelOrchestrationError,
    TunnelOrchestrator,
)

pytestmark = pytest.mark.asyncio


def _make_orchestrator(tmp_path: Path, docker: Any | None = None) -> tuple[TunnelOrchestrator, Any]:
    docker = docker or MagicMock()
    docker.containers = MagicMock()
    docker.containers.create_or_replace = AsyncMock()
    docker.containers.get = AsyncMock()
    orch = TunnelOrchestrator(
        docker=docker,
        config_dir=tmp_path / "clients",
        sockets_dir=tmp_path / "sockets",
        image_by_protocol={VpnType.OPENVPN: "vagg/tunnel-openvpn:test"},
        network_name="vagg-net-test",
        restart_policy="unless-stopped",
        controller_timeout_s=0.5,
    )
    return orch, docker


class TestConnect:
    async def test_creates_container_with_caps_and_mounts(self, tmp_path: Path) -> None:
        orch, docker = _make_orchestrator(tmp_path)
        container_mock = MagicMock()
        container_mock.id = "cid-123"
        container_mock.start = AsyncMock()
        docker.containers.create_or_replace.return_value = container_mock

        cid = await orch.connect(
            client_id="petroleo",
            protocol=VpnType.OPENVPN,
            config_text="client\ndev tun\nremote vpn.x.example 1194\n",
            username="consultor1",
            password="secret",
        )

        assert cid == "cid-123"
        # Container creation was called once with the right name
        call = docker.containers.create_or_replace.call_args
        assert call.kwargs["name"] == "vagg-tunnel-petroleo"
        config = call.kwargs["config"]
        assert config["Image"] == "vagg/tunnel-openvpn:test"
        assert config["HostConfig"]["CapAdd"] == ["NET_ADMIN"]
        assert config["HostConfig"]["RestartPolicy"]["Name"] == "unless-stopped"
        assert config["HostConfig"]["NetworkMode"] == "vagg-net-test"
        # Devices include /dev/net/tun
        devices = config["HostConfig"]["Devices"]
        assert any(d["PathInContainer"] == "/dev/net/tun" for d in devices)
        # Binds include both config and sockets
        binds = config["HostConfig"]["Binds"]
        assert any(":/config:ro" in b for b in binds)
        assert any(":/var/run/vagg" in b for b in binds)
        # Env passes username
        env = config["Env"]
        assert "TUNNEL_USERNAME=consultor1" in env

        # Files were staged on disk
        assert (tmp_path / "clients" / "petroleo" / "tunnel.conf").exists()
        assert (tmp_path / "clients" / "petroleo" / "password").exists()

        container_mock.start.assert_awaited_once()

    async def test_unsupported_protocol_returns_409(self, tmp_path: Path) -> None:
        orch, _ = _make_orchestrator(tmp_path)
        # Empty image map for WIREGUARD; only OPENVPN is wired
        with pytest.raises(Exception) as info:  # noqa: PT011 — generic on purpose
            await orch.connect(
                client_id="x",
                protocol=VpnType.WIREGUARD,
                config_text="...",
            )
        assert info.value.status_code == 409  # type: ignore[attr-defined]

    async def test_docker_error_wrapped(self, tmp_path: Path) -> None:
        orch, docker = _make_orchestrator(tmp_path)
        docker.containers.create_or_replace.side_effect = DockerError(
            500, {"message": "image not found"}
        )
        with pytest.raises(TunnelOrchestrationError):
            await orch.connect(
                client_id="x",
                protocol=VpnType.OPENVPN,
                config_text="client\n",
            )


class TestDisconnect:
    async def test_stops_and_removes(self, tmp_path: Path) -> None:
        orch, docker = _make_orchestrator(tmp_path)
        container = MagicMock()
        container.stop = AsyncMock()
        container.delete = AsyncMock()
        docker.containers.get.return_value = container

        await orch.disconnect("petroleo")
        container.stop.assert_awaited_once()
        container.delete.assert_awaited_once_with(force=True)

    async def test_missing_container_is_noop(self, tmp_path: Path) -> None:
        orch, docker = _make_orchestrator(tmp_path)
        docker.containers.get.side_effect = DockerError(404, {"message": "not found"})
        # Must not raise
        await orch.disconnect("missing")


class TestStatus:
    async def _make_with_inspect(
        self, tmp_path: Path, inspect: dict[str, Any]
    ) -> TunnelOrchestrator:
        orch, docker = _make_orchestrator(tmp_path)
        container = MagicMock()
        container.id = "cid-abc"
        container.show = AsyncMock(return_value=inspect)
        docker.containers.get.return_value = container
        return orch

    async def test_running_with_no_controller_socket_means_starting(self, tmp_path: Path) -> None:
        orch = await self._make_with_inspect(
            tmp_path, {"State": {"Running": True, "Status": "running"}}
        )
        report = await orch.status("xpto")
        assert report.state == TunnelState.STARTING

    async def test_exited_with_error_means_errored(self, tmp_path: Path) -> None:
        orch = await self._make_with_inspect(
            tmp_path,
            {"State": {"Running": False, "Status": "exited", "Error": "openvpn died"}},
        )
        report = await orch.status("xpto")
        assert report.state == TunnelState.ERRORED
        assert report.error == "openvpn died"

    async def test_exited_no_error_means_down(self, tmp_path: Path) -> None:
        orch = await self._make_with_inspect(
            tmp_path, {"State": {"Running": False, "Status": "exited"}}
        )
        report = await orch.status("xpto")
        assert report.state == TunnelState.DOWN

    async def test_missing_container_means_stopped(self, tmp_path: Path) -> None:
        orch, docker = _make_orchestrator(tmp_path)
        docker.containers.get.side_effect = DockerError(404, {"message": "not found"})
        report = await orch.status("xpto")
        assert report.state == TunnelState.STOPPED


class TestTailLogs:
    async def test_returns_log_lines(self, tmp_path: Path) -> None:
        orch, docker = _make_orchestrator(tmp_path)
        container = MagicMock()
        container.log = AsyncMock(return_value=["line 1\n", "line 2\n"])
        docker.containers.get.return_value = container
        out = await orch.tail_logs("xpto", lines=50)
        assert out == ["line 1", "line 2"]

    async def test_handles_string_output(self, tmp_path: Path) -> None:
        orch, docker = _make_orchestrator(tmp_path)
        container = MagicMock()
        container.log = AsyncMock(return_value="line a\nline b\n")
        docker.containers.get.return_value = container
        out = await orch.tail_logs("xpto")
        assert out == ["line a", "line b"]

    async def test_missing_container_returns_empty(self, tmp_path: Path) -> None:
        orch, docker = _make_orchestrator(tmp_path)
        docker.containers.get.side_effect = DockerError(404, {"message": "not found"})
        out = await orch.tail_logs("xpto")
        assert out == []


class TestSendOtp:
    async def test_missing_socket_returns_404(self, tmp_path: Path) -> None:
        orch, _ = _make_orchestrator(tmp_path)
        with pytest.raises(Exception) as info:  # noqa: PT011
            await orch.send_otp("xpto", "123456")
        assert info.value.status_code == 404  # type: ignore[attr-defined]
