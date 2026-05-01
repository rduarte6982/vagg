"""Integration tests for /api/v1/clients (CRUD + tunnel actions)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import FakeTunnelOrchestrator
from vagg_core.db.models import TunnelState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


_OVPN_FIXTURE = """\
client
dev tun
proto udp
remote vpn.example.com 1194
resolv-retry infinite
nobind
persist-key
persist-tun
verb 3
"""


def _payload(slug: str = "petroleo", **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": slug,
        "name": "Cliente Petróleo",
        "vpn_type": "openvpn",
        "virtual_cidr": "10.200.1.0/24",
        "real_cidr": "192.168.1.0/24",
        "dns_server": "192.168.1.10",
        "description": "Tenant de teste",
        "config_text": _OVPN_FIXTURE,
        "vpn_username": "consultor1",
        "vpn_password": "s3nh4-do-cliente",
        "nat_mappings": [
            {"virtual_cidr": "10.200.1.0/24", "real_cidr": "192.168.1.0/24"},
        ],
    }
    base.update(overrides)
    return base


class TestClientsCRUD:
    async def test_create_then_get_then_list(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.post("/api/v1/clients", json=_payload())
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["id"] == "petroleo"
        assert body["tunnel_state"] == "stopped"
        assert body["has_config"] is True
        assert body["has_credentials"] is True
        assert len(body["nat_mappings"]) == 1

        get_resp = await auth_client.get("/api/v1/clients/petroleo")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "Cliente Petróleo"

        list_resp = await auth_client.get("/api/v1/clients")
        assert list_resp.status_code == 200
        ids = [c["id"] for c in list_resp.json()]
        assert "petroleo" in ids

    async def test_create_without_config_omits_credentials_flags(
        self, auth_client: AsyncClient
    ) -> None:
        resp = await auth_client.post(
            "/api/v1/clients",
            json=_payload(
                slug="sem-config", config_text=None, vpn_username=None, vpn_password=None
            ),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["has_config"] is False
        assert body["has_credentials"] is False

    async def test_create_duplicate_returns_409(self, auth_client: AsyncClient) -> None:
        await auth_client.post("/api/v1/clients", json=_payload(slug="dup"))
        resp = await auth_client.post("/api/v1/clients", json=_payload(slug="dup"))
        assert resp.status_code == 409
        assert resp.json()["code"] == "CONFLICT"

    async def test_invalid_slug_returns_409(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.post("/api/v1/clients", json=_payload(slug="Bad_Slug_With_Caps"))
        assert resp.status_code == 409
        assert resp.json()["code"] == "CONFLICT"

    async def test_patch_updates_name(self, auth_client: AsyncClient) -> None:
        await auth_client.post("/api/v1/clients", json=_payload(slug="varejo"))
        resp = await auth_client.patch(
            "/api/v1/clients/varejo", json={"name": "Cliente Varejo Renomeado"}
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Cliente Varejo Renomeado"

    async def test_delete_removes_client(self, auth_client: AsyncClient) -> None:
        await auth_client.post("/api/v1/clients", json=_payload(slug="industria"))
        del_resp = await auth_client.delete("/api/v1/clients/industria")
        assert del_resp.status_code == 204
        assert (await auth_client.get("/api/v1/clients/industria")).status_code == 404

    async def test_get_unknown_returns_404(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/api/v1/clients/nonexistent")
        assert resp.status_code == 404
        assert resp.json()["code"] == "NOT_FOUND"


class TestTunnelLifecycle:
    async def test_connect_calls_orchestrator_with_client_data(
        self, auth_client: AsyncClient, fake_orchestrator: FakeTunnelOrchestrator
    ) -> None:
        await auth_client.post("/api/v1/clients", json=_payload(slug="banco"))
        resp = await auth_client.post("/api/v1/clients/banco/connect")
        assert resp.status_code == 202
        body = resp.json()
        assert body["client_id"] == "banco"
        assert body["container_id"] == "fake-container-1"
        assert body["state"] == "starting"

        # Orchestrator received the right payload
        connect_calls = [c for c in fake_orchestrator.calls if c[0] == "connect"]
        assert len(connect_calls) == 1
        _, payload = connect_calls[0]
        assert payload["client_id"] == "banco"
        assert payload["protocol"] == "openvpn"
        assert payload["username"] == "consultor1"
        assert payload["has_password"] is True
        assert payload["config_text_len"] > 0

    async def test_connect_without_config_text_returns_409(
        self, auth_client: AsyncClient, fake_orchestrator: FakeTunnelOrchestrator
    ) -> None:
        await auth_client.post(
            "/api/v1/clients",
            json=_payload(slug="naoconfig", config_text=None, vpn_username=None, vpn_password=None),
        )
        resp = await auth_client.post("/api/v1/clients/naoconfig/connect")
        assert resp.status_code == 409
        assert resp.json()["code"] == "CONFLICT"
        # Orchestrator was never invoked
        assert not [c for c in fake_orchestrator.calls if c[0] == "connect"]

    async def test_disconnect_clears_status(
        self, auth_client: AsyncClient, fake_orchestrator: FakeTunnelOrchestrator
    ) -> None:
        await auth_client.post("/api/v1/clients", json=_payload(slug="seguros"))
        await auth_client.post("/api/v1/clients/seguros/connect")
        resp = await auth_client.post("/api/v1/clients/seguros/disconnect")
        assert resp.status_code == 202
        body = resp.json()
        assert body["state"] == "stopped"

        # Status row reflects 'stopped'
        status_resp = await auth_client.get("/api/v1/clients/seguros/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["state"] == "stopped"

    async def test_status_reflects_orchestrator_report(
        self, auth_client: AsyncClient, fake_orchestrator: FakeTunnelOrchestrator
    ) -> None:
        await auth_client.post("/api/v1/clients", json=_payload(slug="energia"))
        from vagg_core.services.tunnel_orchestrator import TunnelStatusReport

        fake_orchestrator.status_overrides["energia"] = TunnelStatusReport(
            state=TunnelState.UP,
            container_id="abc123",
            controller_state="connected",
            uptime_s=42,
        )
        resp = await auth_client.get("/api/v1/clients/energia/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "up"
        assert body["container_id"] == "abc123"
        assert body["controller_state"] == "connected"
        assert body["uptime_s"] == 42

    async def test_otp_forwarded_to_orchestrator(
        self, auth_client: AsyncClient, fake_orchestrator: FakeTunnelOrchestrator
    ) -> None:
        await auth_client.post("/api/v1/clients", json=_payload(slug="logistica"))
        resp = await auth_client.post("/api/v1/clients/logistica/otp", json={"code": "123456"})
        assert resp.status_code == 200
        assert resp.json()["forwarded"] is True
        otp_calls = [c for c in fake_orchestrator.calls if c[0] == "send_otp"]
        assert otp_calls == [("send_otp", {"client_id": "logistica", "code_len": 6})]

    async def test_otp_failure_surfaces_orchestration_error(
        self, auth_client: AsyncClient, fake_orchestrator: FakeTunnelOrchestrator
    ) -> None:
        await auth_client.post("/api/v1/clients", json=_payload(slug="rejeitam"))
        fake_orchestrator.fail_otp_for.add("rejeitam")
        resp = await auth_client.post("/api/v1/clients/rejeitam/otp", json={"code": "999999"})
        assert resp.status_code == 502
        assert resp.json()["code"] == "TUNNEL_ORCHESTRATION_ERROR"

    async def test_logs_returns_orchestrator_lines(
        self, auth_client: AsyncClient, fake_orchestrator: FakeTunnelOrchestrator
    ) -> None:
        await auth_client.post("/api/v1/clients", json=_payload(slug="industria-logs"))
        fake_orchestrator.logs["industria-logs"] = ["line a", "line b"]
        resp = await auth_client.get("/api/v1/clients/industria-logs/logs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["lines"] == ["line a", "line b"]
