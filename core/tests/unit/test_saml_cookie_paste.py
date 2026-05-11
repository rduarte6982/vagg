"""Tests do parser de cookie SAML pasted manualmente.

Garante que o admin pode colar em vários formatos (DevTools JSON, full
Cookie header, name=value, raw value) e o backend extrai corretamente.
"""

from __future__ import annotations

import pytest

from vagg_core.api.v1.clients import _parse_pasted_cookie
from vagg_core.db.models import VpnType


class TestDevtoolsJsonFormat:
    """DevTools Chrome/Edge: 'Edit cookie' copy gera JSON com name/value."""

    def test_extracts_name_and_value(self) -> None:
        raw = '{"name":"SVPNCOOKIE","value":"abc123def456","domain":".vpn.example.com","path":"/"}'
        name, value, fmt = _parse_pasted_cookie(raw, VpnType.OPENFORTIVPN)
        assert name == "SVPNCOOKIE"
        assert value == "abc123def456"
        assert fmt == "devtools-json"

    def test_gp_cookie_in_devtools_json(self) -> None:
        raw = '{"name":"portal-userauthcookie","value":"hex32characters","httpOnly":true}'
        name, value, fmt = _parse_pasted_cookie(raw, VpnType.GLOBALPROTECT)
        assert name == "portal-userauthcookie"
        assert value == "hex32characters"
        assert fmt == "devtools-json"


class TestCookieHeaderFormat:
    """Full Cookie header: 'a=b; SVPNCOOKIE=xxx; c=d'."""

    def test_picks_svpncookie_for_forti(self) -> None:
        raw = "session=abc; SVPNCOOKIE=my-real-value-here; foo=bar"
        name, value, fmt = _parse_pasted_cookie(raw, VpnType.OPENFORTIVPN)
        assert name == "SVPNCOOKIE"
        assert value == "my-real-value-here"
        assert fmt == "cookie-header"

    def test_picks_portal_userauthcookie_over_prelogin(self) -> None:
        """Quando o header tem AMBOS, escolhe o de maior preferência GP."""
        raw = "prelogin-cookie=preval; portal-userauthcookie=portalval; junk=x"
        name, value, fmt = _parse_pasted_cookie(raw, VpnType.GLOBALPROTECT)
        assert name == "portal-userauthcookie"
        assert value == "portalval"

    def test_single_cookie_in_header_format(self) -> None:
        raw = "SVPNCOOKIE=onlyme"
        name, value, _ = _parse_pasted_cookie(raw, VpnType.OPENFORTIVPN)
        assert name == "SVPNCOOKIE"
        assert value == "onlyme"

    def test_unknown_single_cookie_in_header_form(self) -> None:
        """Header com um cookie só, nome desconhecido — aceita."""
        raw = "MYCUSTOM_AUTH=opaque-value-12345"
        name, value, fmt = _parse_pasted_cookie(raw, VpnType.OPENFORTIVPN)
        # SVPNCOOKIE não está no input mas é canônico do forti — deveria
        # devolver MYCUSTOM_AUTH como cookie-header-single ou name-value.
        # Como tem ; separator no preflight check? Aqui não tem, então cai
        # no formato single-name-value.
        assert value == "opaque-value-12345"


class TestNameValueFormat:
    def test_simple_name_value(self) -> None:
        raw = "SVPNCOOKIE=valor-do-cookie-aqui"
        name, value, fmt = _parse_pasted_cookie(raw, VpnType.OPENFORTIVPN)
        assert name == "SVPNCOOKIE"
        assert value == "valor-do-cookie-aqui"
        assert fmt == "name-value"

    def test_strips_whitespace_in_name_value(self) -> None:
        raw = "  SVPNCOOKIE = abc123  "
        name, value, _ = _parse_pasted_cookie(raw, VpnType.OPENFORTIVPN)
        assert name == "SVPNCOOKIE"
        assert value == "abc123"


class TestRawValueFormat:
    """Sem '=' nem ';' — só o valor cru. Assume nome canônico do protocolo."""

    def test_raw_value_for_forti_assumes_svpncookie(self) -> None:
        raw = "abc123def456hex"
        name, value, fmt = _parse_pasted_cookie(raw, VpnType.OPENFORTIVPN)
        assert name == "SVPNCOOKIE"
        assert value == "abc123def456hex"
        assert fmt == "raw-value-canonical"

    def test_raw_value_for_gp_assumes_portal_userauthcookie(self) -> None:
        raw = "deadbeefcafe1234"
        name, value, fmt = _parse_pasted_cookie(raw, VpnType.GLOBALPROTECT)
        assert name == "portal-userauthcookie"  # primeiro da lista preferred
        assert value == "deadbeefcafe1234"

    def test_raw_value_for_openvpn_raises(self) -> None:
        """openvpn não usa cookies SAML — raise."""
        with pytest.raises(ValueError, match="não tem nome canônico"):
            _parse_pasted_cookie("rawvalue", VpnType.OPENVPN)


class TestErrorCases:
    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="vazio"):
            _parse_pasted_cookie("", VpnType.OPENFORTIVPN)

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="vazio"):
            _parse_pasted_cookie("   \n\t  ", VpnType.OPENFORTIVPN)

    def test_invalid_json_falls_through(self) -> None:
        """JSON inválido cai pra outros formatos sem crashar."""
        raw = "{not really json=value}"  # tem = entao vira name-value
        # Cai pro name-value parser
        name, value, fmt = _parse_pasted_cookie(raw, VpnType.OPENFORTIVPN)
        assert fmt in ("name-value", "cookie-header-single")
