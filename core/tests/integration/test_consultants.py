"""Integration tests for /api/v1/consultants."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _payload(email: str = "joao@consultoria.example", **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "email": email,
        "name": "João Silva",
        "openvpn_username": email.split("@")[0],
        "static_pool_ip": "10.8.0.10",
        "role": "operator",
        "active": True,
    }
    base.update(overrides)
    return base


class TestConsultantsCRUD:
    async def test_create_then_get_then_list(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.post("/api/v1/consultants", json=_payload())
        assert resp.status_code == 201, resp.text
        consultant = resp.json()
        assert consultant["email"] == "joao@consultoria.example"
        assert consultant["role"] == "operator"
        assert consultant["active"] is True

        cid = consultant["id"]
        get_resp = await auth_client.get(f"/api/v1/consultants/{cid}")
        assert get_resp.status_code == 200

        list_resp = await auth_client.get("/api/v1/consultants")
        assert list_resp.status_code == 200
        assert any(c["id"] == cid for c in list_resp.json())

    async def test_duplicate_email_returns_409(self, auth_client: AsyncClient) -> None:
        await auth_client.post(
            "/api/v1/consultants",
            json=_payload(
                email="dup@x.example", openvpn_username="dup1", static_pool_ip="10.8.0.20"
            ),
        )
        resp = await auth_client.post(
            "/api/v1/consultants",
            json=_payload(
                email="dup@x.example", openvpn_username="dup2", static_pool_ip="10.8.0.21"
            ),
        )
        assert resp.status_code == 409

    async def test_patch_deactivates(self, auth_client: AsyncClient) -> None:
        created = (
            await auth_client.post(
                "/api/v1/consultants",
                json=_payload(
                    email="ana@x.example", openvpn_username="ana", static_pool_ip="10.8.0.30"
                ),
            )
        ).json()
        resp = await auth_client.patch(
            f"/api/v1/consultants/{created['id']}", json={"active": False}
        )
        assert resp.status_code == 200
        assert resp.json()["active"] is False

    async def test_filter_by_active(self, auth_client: AsyncClient) -> None:
        a = (
            await auth_client.post(
                "/api/v1/consultants",
                json=_payload(
                    email="active@x.example",
                    openvpn_username="active1",
                    static_pool_ip="10.8.0.40",
                    active=True,
                ),
            )
        ).json()
        b = (
            await auth_client.post(
                "/api/v1/consultants",
                json=_payload(
                    email="inactive@x.example",
                    openvpn_username="inactive1",
                    static_pool_ip="10.8.0.41",
                    active=False,
                ),
            )
        ).json()

        resp = await auth_client.get("/api/v1/consultants?active=true")
        ids = {c["id"] for c in resp.json()}
        assert a["id"] in ids
        assert b["id"] not in ids

    async def test_delete_removes_consultant(self, auth_client: AsyncClient) -> None:
        created = (
            await auth_client.post(
                "/api/v1/consultants",
                json=_payload(
                    email="todelete@x.example",
                    openvpn_username="todelete",
                    static_pool_ip="10.8.0.50",
                ),
            )
        ).json()
        del_resp = await auth_client.delete(f"/api/v1/consultants/{created['id']}")
        assert del_resp.status_code == 204
        get_resp = await auth_client.get(f"/api/v1/consultants/{created['id']}")
        assert get_resp.status_code == 404

    async def test_get_unknown_returns_404(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/api/v1/consultants/999999")
        assert resp.status_code == 404
