"""Testes do TOTP RFC 6238 stdlib + parse de otpauth:// URI."""

from __future__ import annotations

import base64

import pytest

from vagg_core.services import totp


# ----- RFC 6238 test vectors (Appendix B) -----
# Seed canonical: ASCII "12345678901234567890" → base32
_RFC_SECRET = base64.b32encode(b"12345678901234567890").decode("ascii")


@pytest.mark.parametrize(
    ("timestamp", "expected_8", "expected_6"),
    [
        (59, "94287082", "287082"),
        (1111111109, "07081804", "081804"),
        (1111111111, "14050471", "050471"),
        (1234567890, "89005924", "005924"),
        (2000000000, "69279037", "279037"),
    ],
)
def test_rfc6238_sha1_vectors(timestamp: int, expected_8: str, expected_6: str) -> None:
    """Vetores oficiais do RFC 6238 § Appendix B (SHA-1, 30s window)."""
    assert (
        totp.generate(_RFC_SECRET, at=timestamp, digits=8, algorithm="sha1")
        == expected_8
    )
    assert (
        totp.generate(_RFC_SECRET, at=timestamp, digits=6, algorithm="sha1")
        == expected_6
    )


def test_verify_accepts_current_code() -> None:
    code = totp.generate(_RFC_SECRET, at=1111111111)
    assert totp.verify(_RFC_SECRET, code, at=1111111111)


def test_verify_window_pm_one() -> None:
    """Aceita código da janela anterior/próxima por padrão (window=1)."""
    code_prev = totp.generate(_RFC_SECRET, at=1111111111 - 30)
    assert totp.verify(_RFC_SECRET, code_prev, at=1111111111, window=1)


def test_verify_rejects_old_code_outside_window() -> None:
    code_old = totp.generate(_RFC_SECRET, at=1111111111 - 120)
    assert not totp.verify(_RFC_SECRET, code_old, at=1111111111, window=1)


def test_seconds_remaining_at_window_edges() -> None:
    # at=0 → estamos no início de uma janela; 30s restantes
    assert totp.seconds_remaining(period=30, at=0) == 30
    # at=29 → 1s restante
    assert totp.seconds_remaining(period=30, at=29) == 1
    # at=30 → começa janela nova; 30s restantes
    assert totp.seconds_remaining(period=30, at=30) == 30


# ----- parse_secret -----


def test_parse_secret_accepts_raw_base32() -> None:
    meta = totp.parse_secret("JBSWY3DPEHPK3PXP")
    assert meta.secret == "JBSWY3DPEHPK3PXP"
    assert meta.digits == 6
    assert meta.period == 30
    assert meta.algorithm == "sha1"


def test_parse_secret_strips_whitespace_and_uppercases() -> None:
    meta = totp.parse_secret(" jbswy 3dp\n ehpk3pxp ")
    assert meta.secret == "JBSWY3DPEHPK3PXP"


def test_parse_secret_accepts_otpauth_uri() -> None:
    uri = (
        "otpauth://totp/Acme%20Corp:alice%40acme.com"
        "?secret=JBSWY3DPEHPK3PXP&issuer=Acme%20Corp&period=30&digits=6&algorithm=SHA1"
    )
    meta = totp.parse_secret(uri)
    assert meta.secret == "JBSWY3DPEHPK3PXP"
    assert meta.issuer == "Acme Corp"
    assert meta.account == "alice@acme.com"
    assert meta.digits == 6
    assert meta.period == 30
    assert meta.algorithm == "sha1"


def test_parse_secret_uri_with_sha256() -> None:
    uri = "otpauth://totp/x?secret=JBSWY3DPEHPK3PXP&algorithm=SHA256&digits=8&period=60"
    meta = totp.parse_secret(uri)
    assert meta.algorithm == "sha256"
    assert meta.digits == 8
    assert meta.period == 60


def test_parse_secret_rejects_empty() -> None:
    with pytest.raises(totp.InvalidSecretError):
        totp.parse_secret("")


def test_parse_secret_rejects_non_base32() -> None:
    with pytest.raises(totp.InvalidSecretError):
        totp.parse_secret("not!base32@@")


def test_parse_secret_rejects_uri_without_secret() -> None:
    with pytest.raises(totp.InvalidSecretError):
        totp.parse_secret("otpauth://totp/x?issuer=Foo")


def test_parse_secret_rejects_uri_with_unsupported_algorithm() -> None:
    with pytest.raises(totp.InvalidSecretError):
        totp.parse_secret("otpauth://totp/x?secret=JBSWY3DPEHPK3PXP&algorithm=MD5")
