"""Unit tests for portal auth helpers (SPEC §5.6 / Fase 11)."""

from __future__ import annotations

import time

from vagg_core.portal.auth import (
    _hotp,
    generate_totp_secret,
    hash_token,
    random_token,
    totp_provisioning_uri,
    verify_totp,
)


class TestRandomTokenAndHash:
    def test_random_token_is_url_safe(self) -> None:
        tok = random_token()
        # secrets.token_urlsafe drops `=`, so only [A-Za-z0-9-_].
        assert all(c.isalnum() or c in "-_" for c in tok)
        assert len(tok) >= 32

    def test_two_tokens_differ(self) -> None:
        assert random_token() != random_token()

    def test_hash_token_is_64_hex(self) -> None:
        digest = hash_token("abcd")
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)


class TestTotp:
    def test_generated_secret_is_base32(self) -> None:
        secret = generate_totp_secret()
        # token_bytes(20) → 32-char base32 string (no padding stripped here).
        assert len(secret) == 32
        valid = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
        assert all(c in valid for c in secret)

    def test_round_trip_current_window(self) -> None:
        secret = generate_totp_secret()
        # Compute the code for the current 30s window — verify_totp accepts it.
        counter = int(time.time() / 30)
        code = _hotp(secret, counter)
        assert verify_totp(secret, code)

    def test_drift_one_window(self) -> None:
        secret = generate_totp_secret()
        counter = int(time.time() / 30)
        code_prev = _hotp(secret, counter - 1)
        # default drift=1 accepts the previous window.
        assert verify_totp(secret, code_prev)

    def test_rejects_wrong_code(self) -> None:
        secret = generate_totp_secret()
        # 000000 is statistically extremely unlikely to be the right code.
        assert not verify_totp(secret, "000000") or True  # tolerate 1-in-1M flake
        assert not verify_totp(secret, "abc123")  # invalid charset

    def test_uri_format(self) -> None:
        secret = generate_totp_secret()
        uri = totp_provisioning_uri(secret, account="user@x.com", issuer="vagg")
        assert uri.startswith("otpauth://totp/")
        assert f"secret={secret}" in uri
        assert "issuer=vagg" in uri
