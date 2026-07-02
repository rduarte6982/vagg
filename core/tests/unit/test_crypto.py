"""Testes do encryption-at-rest Fernet wrapper."""

from __future__ import annotations

import base64

import pytest
from cryptography.fernet import Fernet

from vagg_core.config import Settings
from vagg_core.core import crypto


def _build_settings(*, crypto_key: str | None, environment: str = "test") -> Settings:
    """Settings mínima — só o que o crypto importa."""
    return Settings(  # type: ignore[call-arg]
        environment=environment,  # type: ignore[arg-type]
        admin_password_hash="$argon2id$v=19$m=65536,t=3,p=4$abcd$efgh",  # type: ignore[arg-type]
        jwt_secret="test-jwt-secret-xyz",  # type: ignore[arg-type]
        crypto_key=crypto_key,  # type: ignore[arg-type]
    )


def test_roundtrip_with_explicit_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """encrypt → decrypt devolve o plaintext original."""
    key = Fernet.generate_key().decode("ascii")
    settings = _build_settings(crypto_key=key)
    monkeypatch.setattr(crypto, "get_settings", lambda: settings)
    crypto.reset_cache_for_tests()

    cipher = crypto.encrypt("hello-totp-seed-JBSWY3DPEHPK3PXP")
    assert cipher != "hello-totp-seed-JBSWY3DPEHPK3PXP"
    assert crypto.decrypt(cipher) == "hello-totp-seed-JBSWY3DPEHPK3PXP"


def test_dev_mode_derives_from_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem CRYPTO_KEY em dev/test, deriva do jwt_secret e ainda funciona."""
    settings = _build_settings(crypto_key=None, environment="dev")
    monkeypatch.setattr(crypto, "get_settings", lambda: settings)
    crypto.reset_cache_for_tests()

    cipher = crypto.encrypt("xpto")
    assert crypto.decrypt(cipher) == "xpto"


def test_production_requires_explicit_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Em produção sem CRYPTO_KEY → falha explícita."""
    settings = _build_settings(crypto_key=None, environment="production")
    monkeypatch.setattr(crypto, "get_settings", lambda: settings)
    crypto.reset_cache_for_tests()

    with pytest.raises(crypto.CryptoConfigError):
        crypto.encrypt("x")


def test_different_keys_cannot_decrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cifrar com chave A, decifrar com B → CryptoConfigError."""
    key_a = Fernet.generate_key().decode("ascii")
    settings_a = _build_settings(crypto_key=key_a)
    monkeypatch.setattr(crypto, "get_settings", lambda: settings_a)
    crypto.reset_cache_for_tests()
    cipher = crypto.encrypt("secret")

    key_b = Fernet.generate_key().decode("ascii")
    settings_b = _build_settings(crypto_key=key_b)
    monkeypatch.setattr(crypto, "get_settings", lambda: settings_b)
    crypto.reset_cache_for_tests()
    with pytest.raises(crypto.CryptoConfigError):
        crypto.decrypt(cipher)


def test_rejects_empty_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build_settings(crypto_key=Fernet.generate_key().decode("ascii"))
    monkeypatch.setattr(crypto, "get_settings", lambda: settings)
    crypto.reset_cache_for_tests()
    with pytest.raises(ValueError):
        crypto.encrypt("")


def test_accepts_raw_32_byte_base64_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aceita chave em urlsafe-base64 sem padding 'standard' Fernet."""
    raw = b"\x00" * 32
    key = base64.urlsafe_b64encode(raw).decode("ascii")
    settings = _build_settings(crypto_key=key)
    monkeypatch.setattr(crypto, "get_settings", lambda: settings)
    crypto.reset_cache_for_tests()
    assert crypto.decrypt(crypto.encrypt("ok")) == "ok"
