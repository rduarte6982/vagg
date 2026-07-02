"""Integração: ações self-service do consultor no /me (modelo híbrido).

O admin sobe o túnel inicialmente; o consultor pode reconectar/reautenticar OTP
para clients que ele tem via Policy ativa, desde que seja operator/admin.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import FakeTunnelOrchestrator

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _make_client(admin: AsyncClient, slug: str) -> None:
    resp = await admin.post(
        "/api/v1/clients",
        json={
            "id": slug,
            "name": f"Cliente {slug}",
            "vpn_type": "openvpn",
            "virtual_cidr": "10.200.30.0/24",
            "real_cidr": "10.30.0.0/16",
            "config_text": "client\nremote host 1194\n",
        },
    )
    assert resp.status_code in (200, 201), resp.text


async def _make_consultant_token(
    admin: AsyncClient, *, email: str, role: str, authorized_slug: str | None
) -> str:
    """Cria consultor com senha (+ Policy opcional) e devolve o access token dele."""
    body = {
        "email": email,
        "name": email.split("@")[0],
        "openvpn_username": email.split("@")[0],
        "static_pool_ip": "10.8.0.90",
        "role": role,
        "active": True,
        "password": "consultorpass",
    }
    consultant = (await admin.post("/api/v1/consultants", json=body)).json()
    if authorized_slug is not None:
        await admin.post(
            "/api/v1/policies",
            json={
                "consultant_id": consultant["id"],
                "client_id": authorized_slug,
                "scope_kind": "full",
            },
        )
    login = await admin.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "consultorpass"},
        headers={"Authorization": ""},
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


class TestMeSelfServiceMetadata:
    async def test_my_clients_exposes_auth_metadata(self, auth_client: AsyncClient) -> None:
        await _make_client(auth_client, "metacli")
        token = await _make_consultant_token(
            auth_client, email="meta@x.example", role="operator", authorized_slug="metacli"
        )
        resp = await auth_client.get(
            "/api/v1/me/clients", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200, resp.text
        client = resp.json()["clients"][0]
        assert client["auth_method"] == "none"
        assert client["requires_otp"] is False
        assert client["has_saml_cookie"] is False
        assert client["saml_cookie_valid"] is None


class TestMeReconnect:
    async def test_operator_can_reconnect_authorized_client(
        self, auth_client: AsyncClient, fake_orchestrator: FakeTunnelOrchestrator
    ) -> None:
        await _make_client(auth_client, "recon")
        token = await _make_consultant_token(
            auth_client, email="op@x.example", role="operator", authorized_slug="recon"
        )
        resp = await auth_client.post(
            "/api/v1/me/clients/recon/reconnect",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202, resp.text
        assert resp.json()["state"] == "starting"
        connects = [c for c in fake_orchestrator.calls if c[0] == "connect"]
        assert [c[1]["client_id"] for c in connects] == ["recon"]

    async def test_reconnect_unauthorized_client_returns_404(
        self, auth_client: AsyncClient, fake_orchestrator: FakeTunnelOrchestrator
    ) -> None:
        await _make_client(auth_client, "secret")
        # Consultor sem Policy pro 'secret'.
        token = await _make_consultant_token(
            auth_client, email="noaccess@x.example", role="operator", authorized_slug=None
        )
        resp = await auth_client.post(
            "/api/v1/me/clients/secret/reconnect",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404, resp.text
        assert not [c for c in fake_orchestrator.calls if c[0] == "connect"]

    async def test_viewer_cannot_reconnect(self, auth_client: AsyncClient) -> None:
        await _make_client(auth_client, "viewcli")
        token = await _make_consultant_token(
            auth_client, email="view@x.example", role="viewer", authorized_slug="viewcli"
        )
        resp = await auth_client.post(
            "/api/v1/me/clients/viewcli/reconnect",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, resp.text


class TestMeOtp:
    async def test_operator_can_submit_otp_for_authorized_client(
        self, auth_client: AsyncClient, fake_orchestrator: FakeTunnelOrchestrator
    ) -> None:
        await _make_client(auth_client, "otpcli")
        token = await _make_consultant_token(
            auth_client, email="otp@x.example", role="operator", authorized_slug="otpcli"
        )
        resp = await auth_client.post(
            "/api/v1/me/clients/otpcli/otp",
            json={"code": "123456"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        otps = [c for c in fake_orchestrator.calls if c[0] == "send_otp"]
        assert [c[1]["client_id"] for c in otps] == ["otpcli"]

    async def test_otp_unauthorized_client_returns_404(
        self, auth_client: AsyncClient, fake_orchestrator: FakeTunnelOrchestrator
    ) -> None:
        await _make_client(auth_client, "otpsecret")
        token = await _make_consultant_token(
            auth_client, email="otpno@x.example", role="operator", authorized_slug=None
        )
        resp = await auth_client.post(
            "/api/v1/me/clients/otpsecret/otp",
            json={"code": "123456"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404, resp.text
        assert not [c for c in fake_orchestrator.calls if c[0] == "send_otp"]
