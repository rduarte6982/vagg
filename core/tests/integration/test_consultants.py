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


class TestConsultantPasswordAuth:
    """Cobertura do fluxo: criar consultor com senha → login direto pelo VAGG Client."""

    async def test_create_with_password_then_login_succeeds(
        self, auth_client: AsyncClient
    ) -> None:
        from typing import Any

        # 1) Cria via admin com senha já no payload.
        body = _payload(
            email="rduarte@vagg.example",
            name="rduarte",
            openvpn_username="rduarte_vpn",
            static_pool_ip="10.8.0.99",
            role="admin",
        )
        body["password"] = "123456"
        create = await auth_client.post("/api/v1/consultants", json=body)
        assert create.status_code == 201, create.text
        created = create.json()
        assert created["has_password"] is True

        # 2) Login com email + senha funciona.
        client: Any = auth_client
        login = await client.post(
            "/api/v1/auth/login",
            data={"username": "rduarte@vagg.example", "password": "123456"},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "",  # remove bearer admin pra simular cliente fresh
            },
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]

        # 3) Login com nome (rduarte) também funciona.
        login_by_name = await client.post(
            "/api/v1/auth/login",
            data={"username": "rduarte", "password": "123456"},
            headers={"Authorization": ""},
        )
        assert login_by_name.status_code == 200

        # 4) Senha errada → 401.
        wrong = await client.post(
            "/api/v1/auth/login",
            data={"username": "rduarte@vagg.example", "password": "errado"},
            headers={"Authorization": ""},
        )
        assert wrong.status_code == 401

        # 5) Token de consultor pode chamar /me/clients.
        me = await client.get(
            "/api/v1/me/clients", headers={"Authorization": f"Bearer {token}"}
        )
        assert me.status_code == 200
        body = me.json()
        assert body["user"] == "rduarte"
        assert body["is_admin"] is True

    async def test_create_without_password_then_set_later(
        self, auth_client: AsyncClient
    ) -> None:
        # 1) Cria sem senha → has_password=False, login deve falhar.
        body = _payload(
            email="paulo@x.example",
            name="paulo",
            openvpn_username="paulo_vpn",
            static_pool_ip="10.8.0.55",
        )
        create = await auth_client.post("/api/v1/consultants", json=body)
        assert create.status_code == 201
        created = create.json()
        assert created["has_password"] is False

        login_fail = await auth_client.post(
            "/api/v1/auth/login",
            data={"username": "paulo@x.example", "password": "qualquer"},
            headers={"Authorization": ""},
        )
        assert login_fail.status_code == 401

        # 2) Admin define a senha via PUT /password.
        setpw = await auth_client.put(
            f"/api/v1/consultants/{created['id']}/password",
            json={"password": "novasenha"},
        )
        assert setpw.status_code == 200
        assert setpw.json()["has_password"] is True

        # 3) Agora login funciona.
        login_ok = await auth_client.post(
            "/api/v1/auth/login",
            data={"username": "paulo@x.example", "password": "novasenha"},
            headers={"Authorization": ""},
        )
        assert login_ok.status_code == 200

    async def test_inactive_consultant_cannot_login(self, auth_client: AsyncClient) -> None:
        body = _payload(
            email="inactive_user@x.example",
            name="inactive_user",
            openvpn_username="inactive_user",
            static_pool_ip="10.8.0.56",
            active=False,
        )
        body["password"] = "abcdef"
        create = await auth_client.post("/api/v1/consultants", json=body)
        assert create.status_code == 201

        login = await auth_client.post(
            "/api/v1/auth/login",
            data={"username": "inactive_user@x.example", "password": "abcdef"},
            headers={"Authorization": ""},
        )
        assert login.status_code == 401

    async def test_non_admin_consultant_only_sees_authorized_clients(
        self, auth_client: AsyncClient
    ) -> None:
        """Consultor com role=viewer só vê clientes via Policy."""
        from vagg_core.db.models import Client as ClientModel
        from vagg_core.db.models import Policy as PolicyModel
        from vagg_core.db.models import VpnType

        # Cria 2 clients direto na sessão.
        # (Pula: o test infra não dá acesso fácil; usa endpoint admin.)
        c1 = await auth_client.post(
            "/api/v1/clients",
            json={
                "id": "longping",
                "name": "LongPing",
                "vpn_type": VpnType.OPENVPN.value,
                "virtual_cidr": "10.200.10.0/24",
                "real_cidr": "10.80.0.0/16",
                "config_text": "client\nremote x 1194\n",
            },
        )
        assert c1.status_code in (200, 201), c1.text
        c2 = await auth_client.post(
            "/api/v1/clients",
            json={
                "id": "roit",
                "name": "Roit",
                "vpn_type": VpnType.OPENVPN.value,
                "virtual_cidr": "10.200.20.0/24",
                "real_cidr": "10.0.0.0/16",
                "config_text": "client\nremote y 1194\n",
            },
        )
        assert c2.status_code in (200, 201), c2.text

        # Consultor viewer com senha.
        body = _payload(
            email="viewer1@x.example",
            name="viewer1",
            openvpn_username="viewer1_vpn",
            static_pool_ip="10.8.0.57",
            role="viewer",
        )
        body["password"] = "viewerpass"
        consultant = (
            await auth_client.post("/api/v1/consultants", json=body)
        ).json()

        # Policy ligando viewer1 só ao longping.
        await auth_client.post(
            "/api/v1/policies",
            json={
                "consultant_id": consultant["id"],
                "client_id": "longping",
                "scope_kind": "full",
            },
        )

        # Login do viewer.
        login = await auth_client.post(
            "/api/v1/auth/login",
            data={"username": "viewer1@x.example", "password": "viewerpass"},
            headers={"Authorization": ""},
        )
        token = login.json()["access_token"]

        # /me/clients vê só longping.
        me = await auth_client.get(
            "/api/v1/me/clients", headers={"Authorization": f"Bearer {token}"}
        )
        assert me.status_code == 200
        body = me.json()
        assert body["is_admin"] is False
        ids = [c["id"] for c in body["clients"]]
        assert ids == ["longping"]
        assert all(r["client_id"] == "longping" for r in body["routes"])

        # Mesmo viewer NÃO consegue chamar listas de admin.
        forbidden = await auth_client.get(
            "/api/v1/consultants", headers={"Authorization": f"Bearer {token}"}
        )
        assert forbidden.status_code == 401
        # Mas consegue chamar /me/clients (require_user, não require_admin).
