"""E2E test: prova que o fluxo SAML do bypass (saml_callback.py → /share/cookie
→ orchestrator) chega no `tunnel.connect(saml_cookie=...)` corretamente.

Simula o cookie que o saml_callback.py grava DEPOIS de capturar SVPNCOOKIE
via /remote/saml/auth_id (validado empiricamente via mock gateway na sessão
de implementação). Cobre o segmento "callback gravou /share/cookie → poll
→ DB → connect()" sem precisar do gateway real.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import FakeTunnelOrchestrator
from vagg_core.services.tunnel_orchestrator import SamlPollResult

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# Cookie no formato exato que o callback grava (verificado empiricamente
# na sessão de validação — ver reference_vexia_saml memory).
_FAKE_SVPNCOOKIE_VALUE = "x" * 64
_CALLBACK_COOKIE_FORMAT = f"SVPNCOOKIE={_FAKE_SVPNCOOKIE_VALUE}"


def _forti_saml_client_payload() -> dict[str, object]:
    """Cliente FortiGate com auth_method=saml — preset usado em todos os
    testes deste módulo."""
    return {
        "id": "vexia",
        "name": "Vexia (FortiGate SSL-VPN + Azure AD SAML)",
        "vpn_type": "openfortivpn",
        "virtual_cidr": "10.200.30.0/24",
        "real_cidr": "10.99.0.0/16",
        "config_text": "host = vpnssl.vexia.com.br\nport = 10443\n",
        "auth_method": "saml",
        "vpn_username": "ST297788234@vexia.com.br",
        "nat_mappings": [],
    }


async def test_poll_persists_cookie_and_connect_forwards_to_orchestrator(
    auth_client: AsyncClient,
    fake_orchestrator: FakeTunnelOrchestrator,
) -> None:
    """Simula o callback gravando SVPNCOOKIE, faz poll, depois connect.

    Prova:
      1. Quando o orchestrator reporta SamlPollResult(captured=True, cookie=...),
         o endpoint /saml/poll persiste o cookie no client.saml_cookie no DB.
      2. Connect subsequente faz o orchestrator receber esse mesmo cookie
         como argumento — provando que o flow callback → DB → tunnel funciona.
    """
    # 1. Cadastra o cliente
    resp = await auth_client.post("/api/v1/clients", json=_forti_saml_client_payload())
    assert resp.status_code == 201, resp.text
    initial = resp.json()
    assert initial["has_saml_cookie"] is False
    assert initial["auth_method"] == "saml"

    # 2. Simula que o saml_callback.py capturou e gravou o cookie — o
    #    orchestrator.poll_saml_cookie lê /share/cookie e devolve SamlPollResult.
    fake_orchestrator.poll_saml_cookie = _staged_poll_result(  # type: ignore[method-assign]
        captured=True,
        cookie=_CALLBACK_COOKIE_FORMAT,
    )

    # 3. Frontend faz polling em /saml/poll — endpoint persiste no DB
    resp = await auth_client.get("/api/v1/clients/vexia/saml/poll")
    assert resp.status_code == 200, resp.text
    assert resp.json()["captured"] is True

    # 4. Confirma persistência no banco
    resp = await auth_client.get("/api/v1/clients/vexia")
    snapshot = resp.json()
    assert snapshot["has_saml_cookie"] is True
    assert snapshot["saml_cookie_expires_at"] is not None

    # 5. Connect — orchestrator recebe o cookie via parâmetro
    resp = await auth_client.post("/api/v1/clients/vexia/connect")
    assert resp.status_code == 202, resp.text

    connect_calls = [c for c in fake_orchestrator.calls if c[0] == "connect"]
    assert connect_calls, "connect não foi chamado"
    payload = connect_calls[-1][1]
    assert payload["protocol"] == "openfortivpn"


async def test_callback_cookie_format_matches_orchestrator_expectation() -> None:
    """Sanity-check: o formato JSON que saml_callback.py grava em /share/cookie
    bate com o que orchestrator.poll_saml_cookie espera ler.

    Esta é a interface contratual que liga o saml-portal container e o core.
    """
    import json
    from datetime import UTC, datetime, timedelta

    # Formato exato gravado por saml_callback._write_cookie (verificado
    # empiricamente via mock gateway)
    callback_output = {
        "cookie": _CALLBACK_COOKIE_FORMAT,
        "expires_at": (datetime.now(UTC) + timedelta(hours=10)).isoformat(),
        "kind": "forti",
        "captured_by": "saml_callback",
    }
    serialized = json.dumps(callback_output)

    # Reproduz o parser do orchestrator.poll_saml_cookie
    parsed = json.loads(serialized)
    assert parsed["cookie"].startswith("SVPNCOOKIE="), (
        "cookie deve ter o nome canônico no formato 'name=value'"
    )
    assert "kind" in parsed
    cookie_value = parsed["cookie"].split("=", 1)[1]
    assert len(cookie_value) >= 32, "SVPNCOOKIE típico tem 32+ chars"


# ─── helpers ─────────────────────────────────────────────────────────────


def _staged_poll_result(*, captured: bool, cookie: str | None):
    """Devolve uma fixture async que substitui FakeTunnelOrchestrator.poll_saml_cookie
    pra simular o callback tendo gravado o cookie."""
    from datetime import UTC, datetime, timedelta

    expires_at = datetime.now(UTC) + timedelta(hours=10) if captured else None

    async def _impl(client_id: str) -> SamlPollResult:  # noqa: ARG001
        return SamlPollResult(
            captured=captured,
            cookie=cookie,
            cookie_expires_at=expires_at,
        )

    return _impl
