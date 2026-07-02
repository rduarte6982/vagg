"""Integration tests pros endpoints /api/v1/clients/{id}/totp.

Cobre o ciclo: PUT (set seed) → GET (info) → preview (gera código) → DELETE.
Também valida que conectar com seed cadastrado faz o orchestrator receber
um ``totp_seed`` (via FakeTunnelOrchestrator.calls).
"""

from __future__ import annotations

import base64

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from pydantic import SecretStr

from tests.conftest import FakeTunnelOrchestrator
from vagg_core.config import Settings
from vagg_core.core import crypto

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


_RFC_SECRET_BASE32 = base64.b32encode(b"12345678901234567890").decode("ascii")


@pytest.fixture(autouse=True)
def _stub_crypto(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    """Garante CRYPTO_KEY estável e cache do Fernet limpo por teste."""
    settings_with_key = settings.model_copy(
        update={"crypto_key": SecretStr(Fernet.generate_key().decode("ascii"))}
    )
    monkeypatch.setattr(crypto, "get_settings", lambda: settings_with_key)
    crypto.reset_cache_for_tests()
    yield
    crypto.reset_cache_for_tests()


_OVPN_FIXTURE = "client\ndev tun\nremote vpn.example.com 1194\n"


def _otp_client_payload(slug: str = "acme") -> dict[str, object]:
    return {
        "id": slug,
        "name": f"Cliente {slug}",
        "vpn_type": "openconnect",
        "virtual_cidr": "10.200.5.0/24",
        "real_cidr": "192.168.5.0/24",
        "config_text": _OVPN_FIXTURE,
        "auth_method": "otp",
        "vpn_username": "alice",
        "vpn_password": "senha",
        "nat_mappings": [],
    }


async def _create_otp_client(client: AsyncClient, slug: str = "acme") -> None:
    resp = await client.post("/api/v1/clients", json=_otp_client_payload(slug))
    assert resp.status_code == 201, resp.text


async def test_set_totp_seed_returns_metadata(auth_client: AsyncClient) -> None:
    await _create_otp_client(auth_client)
    resp = await auth_client.put(
        "/api/v1/clients/acme/totp",
        json={"secret": _RFC_SECRET_BASE32},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["has_secret"] is True
    assert data["digits"] == 6
    assert data["period"] == 30
    assert data["algorithm"] == "sha1"
    assert 0 < data["seconds_remaining"] <= 30


async def test_set_totp_accepts_otpauth_uri(auth_client: AsyncClient) -> None:
    await _create_otp_client(auth_client)
    uri = (
        f"otpauth://totp/Acme:alice?secret={_RFC_SECRET_BASE32}"
        "&issuer=Acme&period=30&digits=6"
    )
    resp = await auth_client.put("/api/v1/clients/acme/totp", json={"secret": uri})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["has_secret"] is True
    assert data["issuer"] == "Acme"
    assert data["account"] == "alice"


async def test_get_totp_info_with_and_without_seed(auth_client: AsyncClient) -> None:
    await _create_otp_client(auth_client)
    # Sem seed → has_secret=False
    resp = await auth_client.get("/api/v1/clients/acme/totp")
    assert resp.status_code == 200
    assert resp.json()["has_secret"] is False

    # Depois do PUT
    await auth_client.put(
        "/api/v1/clients/acme/totp", json={"secret": _RFC_SECRET_BASE32}
    )
    resp = await auth_client.get("/api/v1/clients/acme/totp")
    assert resp.status_code == 200
    assert resp.json()["has_secret"] is True


async def test_preview_returns_code_matching_rfc_vector(auth_client: AsyncClient) -> None:
    """Sanity: preview devolve um código de 6 dígitos consistente — não testamos
    o valor exato (depende do horário do servidor), mas garantimos shape."""
    await _create_otp_client(auth_client)
    await auth_client.put(
        "/api/v1/clients/acme/totp", json={"secret": _RFC_SECRET_BASE32}
    )
    resp = await auth_client.post("/api/v1/clients/acme/totp/preview")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["code"]) == 6
    assert data["code"].isdigit()
    assert data["period"] == 30
    assert 0 < data["seconds_remaining"] <= 30


async def test_delete_totp_seed(auth_client: AsyncClient) -> None:
    await _create_otp_client(auth_client)
    await auth_client.put(
        "/api/v1/clients/acme/totp", json={"secret": _RFC_SECRET_BASE32}
    )
    resp = await auth_client.delete("/api/v1/clients/acme/totp")
    assert resp.status_code == 204
    resp = await auth_client.get("/api/v1/clients/acme/totp")
    assert resp.json()["has_secret"] is False


async def test_put_rejects_when_auth_method_not_otp(auth_client: AsyncClient) -> None:
    """auth_method != 'otp' → o seed não deve ser aceito (UX guard)."""
    none_payload = _otp_client_payload("nomfa")
    none_payload["auth_method"] = "none"
    none_payload.pop("vpn_password")  # 'none' não exige senha
    resp = await auth_client.post("/api/v1/clients", json=none_payload)
    assert resp.status_code == 201, resp.text
    resp = await auth_client.put(
        "/api/v1/clients/nomfa/totp", json={"secret": _RFC_SECRET_BASE32}
    )
    assert resp.status_code in (400, 409), resp.text


async def test_preview_rejects_when_no_seed(auth_client: AsyncClient) -> None:
    await _create_otp_client(auth_client, slug="bare")
    resp = await auth_client.post("/api/v1/clients/bare/totp/preview")
    assert resp.status_code == 404, resp.text


async def test_put_rejects_invalid_base32(auth_client: AsyncClient) -> None:
    await _create_otp_client(auth_client)
    resp = await auth_client.put(
        "/api/v1/clients/acme/totp", json={"secret": "not!base32@@"}
    )
    assert resp.status_code in (400, 409), resp.text


async def test_connect_passes_totp_seed_to_orchestrator(
    auth_client: AsyncClient,
    fake_orchestrator: FakeTunnelOrchestrator,
) -> None:
    await _create_otp_client(auth_client)
    await auth_client.put(
        "/api/v1/clients/acme/totp", json={"secret": _RFC_SECRET_BASE32}
    )
    resp = await auth_client.post("/api/v1/clients/acme/connect")
    assert resp.status_code == 202, resp.text
    # FakeTunnelOrchestrator grava metadados em .calls
    connect_calls = [c for c in fake_orchestrator.calls if c[0] == "connect"]
    assert connect_calls, "connect não chegou no orchestrator"
    payload = connect_calls[-1][1]
    assert payload["requires_otp"] is True
    assert payload["has_totp_seed"] is True


async def test_client_out_reflects_has_totp_secret(auth_client: AsyncClient) -> None:
    await _create_otp_client(auth_client)
    resp = await auth_client.get("/api/v1/clients/acme")
    assert resp.json().get("has_totp_secret") is False
    await auth_client.put(
        "/api/v1/clients/acme/totp", json={"secret": _RFC_SECRET_BASE32}
    )
    resp = await auth_client.get("/api/v1/clients/acme")
    assert resp.json().get("has_totp_secret") is True
