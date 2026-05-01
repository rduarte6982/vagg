"""Integration tests for /api/v1/policies."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _seed_client_and_consultant(
    client: AsyncClient,
    *,
    client_slug: str = "petroleo",
    consultant_email: str = "joao@x.example",
) -> tuple[str, int]:
    await client.post(
        "/api/v1/clients",
        json={
            "id": client_slug,
            "name": f"Cliente {client_slug}",
            "vpn_type": "openvpn",
            "virtual_cidr": "10.200.1.0/24",
            "real_cidr": "192.168.1.0/24",
        },
    )
    consultant = (
        await client.post(
            "/api/v1/consultants",
            json={
                "email": consultant_email,
                "name": "Consultor Teste",
                "openvpn_username": consultant_email.split("@")[0],
                "static_pool_ip": f"10.8.0.{hash(consultant_email) % 200 + 10}",
                "role": "operator",
            },
        )
    ).json()
    return client_slug, consultant["id"]


class TestPoliciesCRUD:
    async def test_create_full_scope_policy(self, auth_client: AsyncClient) -> None:
        client_id, consultant_id = await _seed_client_and_consultant(auth_client)
        resp = await auth_client.post(
            "/api/v1/policies",
            json={
                "consultant_id": consultant_id,
                "client_id": client_id,
                "scope_kind": "full",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["scope_kind"] == "full"
        assert body["scope_value"] is None

    async def test_create_subnet_scope_policy(self, auth_client: AsyncClient) -> None:
        client_id, consultant_id = await _seed_client_and_consultant(
            auth_client, client_slug="varejo", consultant_email="ana@x.example"
        )
        resp = await auth_client.post(
            "/api/v1/policies",
            json={
                "consultant_id": consultant_id,
                "client_id": client_id,
                "scope_kind": "subnet",
                "scope_value": "10.200.2.0/26",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["scope_value"] == "10.200.2.0/26"

    async def test_duplicate_policy_returns_409(self, auth_client: AsyncClient) -> None:
        client_id, consultant_id = await _seed_client_and_consultant(
            auth_client, client_slug="banco", consultant_email="dup@x.example"
        )
        first = await auth_client.post(
            "/api/v1/policies",
            json={"consultant_id": consultant_id, "client_id": client_id, "scope_kind": "full"},
        )
        assert first.status_code == 201
        second = await auth_client.post(
            "/api/v1/policies",
            json={"consultant_id": consultant_id, "client_id": client_id, "scope_kind": "full"},
        )
        assert second.status_code == 409

    async def test_unknown_consultant_returns_404(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.post(
            "/api/v1/policies",
            json={"consultant_id": 999999, "client_id": "anything", "scope_kind": "full"},
        )
        assert resp.status_code == 404

    async def test_unknown_client_returns_404(self, auth_client: AsyncClient) -> None:
        consultant = (
            await auth_client.post(
                "/api/v1/consultants",
                json={
                    "email": "lonely@x.example",
                    "name": "Lonely",
                    "openvpn_username": "lonely",
                    "static_pool_ip": "10.8.0.99",
                },
            )
        ).json()
        resp = await auth_client.post(
            "/api/v1/policies",
            json={
                "consultant_id": consultant["id"],
                "client_id": "no-such-client",
                "scope_kind": "full",
            },
        )
        assert resp.status_code == 404

    async def test_list_filters_by_consultant(self, auth_client: AsyncClient) -> None:
        c1, cons1 = await _seed_client_and_consultant(
            auth_client, client_slug="ind1", consultant_email="cons1@x.example"
        )
        c2, cons2 = await _seed_client_and_consultant(
            auth_client, client_slug="ind2", consultant_email="cons2@x.example"
        )
        await auth_client.post(
            "/api/v1/policies",
            json={"consultant_id": cons1, "client_id": c1, "scope_kind": "full"},
        )
        await auth_client.post(
            "/api/v1/policies",
            json={"consultant_id": cons2, "client_id": c2, "scope_kind": "full"},
        )
        resp = await auth_client.get(f"/api/v1/policies?consultant_id={cons1}")
        ids = {p["consultant_id"] for p in resp.json()}
        assert cons1 in ids
        assert cons2 not in ids

    async def test_delete_policy(self, auth_client: AsyncClient) -> None:
        client_id, consultant_id = await _seed_client_and_consultant(
            auth_client, client_slug="todelete", consultant_email="todel@x.example"
        )
        created = (
            await auth_client.post(
                "/api/v1/policies",
                json={
                    "consultant_id": consultant_id,
                    "client_id": client_id,
                    "scope_kind": "full",
                },
            )
        ).json()
        del_resp = await auth_client.delete(f"/api/v1/policies/{created['id']}")
        assert del_resp.status_code == 204
        get_resp = await auth_client.get(f"/api/v1/policies/{created['id']}")
        assert get_resp.status_code == 404
