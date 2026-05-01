"""Integration tests for /api/v1/clients (CRUD + tunnel sub-routes)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _payload(slug: str = "petroleo", **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": slug,
        "name": "Cliente Petróleo",
        "vpn_type": "openvpn",
        "virtual_cidr": "10.200.1.0/24",
        "real_cidr": "192.168.1.0/24",
        "dns_server": "192.168.1.10",
        "description": "Tenant de teste",
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
        assert len(body["nat_mappings"]) == 1

        get_resp = await auth_client.get("/api/v1/clients/petroleo")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "Cliente Petróleo"

        list_resp = await auth_client.get("/api/v1/clients")
        assert list_resp.status_code == 200
        ids = [c["id"] for c in list_resp.json()]
        assert "petroleo" in ids

    async def test_create_duplicate_returns_409(self, auth_client: AsyncClient) -> None:
        await auth_client.post("/api/v1/clients", json=_payload(slug="dup"))
        resp = await auth_client.post("/api/v1/clients", json=_payload(slug="dup"))
        assert resp.status_code == 409
        assert resp.json()["code"] == "CONFLICT"

    async def test_invalid_slug_returns_409(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.post("/api/v1/clients", json=_payload(slug="Bad_Slug_With_Caps"))
        # Pydantic accepts the string (max_length=64), but our explicit slug rule rejects it.
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


class TestTunnelStubRoutes:
    async def test_connect_marks_starting(self, auth_client: AsyncClient) -> None:
        await auth_client.post("/api/v1/clients", json=_payload(slug="banco"))
        resp = await auth_client.post("/api/v1/clients/banco/connect")
        assert resp.status_code == 202
        assert resp.json()["status"] == "accepted_stub"

        status_resp = await auth_client.get("/api/v1/clients/banco/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["state"] == "starting"

    async def test_disconnect_marks_stopped(self, auth_client: AsyncClient) -> None:
        await auth_client.post("/api/v1/clients", json=_payload(slug="seguros"))
        await auth_client.post("/api/v1/clients/seguros/connect")
        resp = await auth_client.post("/api/v1/clients/seguros/disconnect")
        assert resp.status_code == 202
        status_resp = await auth_client.get("/api/v1/clients/seguros/status")
        assert status_resp.json()["state"] == "stopped"

    async def test_otp_returns_501_with_stub_code(self, auth_client: AsyncClient) -> None:
        await auth_client.post("/api/v1/clients", json=_payload(slug="energia"))
        resp = await auth_client.post("/api/v1/clients/energia/otp", json={"code": "123456"})
        assert resp.status_code == 501
        assert resp.json()["code"] == "NOT_IMPLEMENTED_YET"

    async def test_logs_returns_empty_array(self, auth_client: AsyncClient) -> None:
        await auth_client.post("/api/v1/clients", json=_payload(slug="logistica"))
        resp = await auth_client.get("/api/v1/clients/logistica/logs")
        assert resp.status_code == 200
        assert resp.json()["lines"] == []
