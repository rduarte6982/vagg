"""Symmetric encryption-at-rest pra secrets sensíveis (TOTP seeds etc).

Usa Fernet (AES-128-CBC + HMAC-SHA256) da `cryptography`. A chave vem de
``VAGG_CORE_CRYPTO_KEY`` (32 bytes em urlsafe-base64). Se ausente:

  - dev / test: deriva do ``jwt_secret`` via HKDF-SHA256 + log de warning.
    Isso permite rodar sem configuração extra mas deixa o secret amarrado
    ao JWT secret — não use em prod (rotacionar JWT secret invalida os
    secrets armazenados).
  - production: erro fatal — install.sh é quem gera a chave dedicada.

Token Fernet inclui timestamp + versão; nunca decifra um secret rotacionado
sem nova chave + reencrypt (operação manual).
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Final

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from vagg_core.config import Settings, get_settings
from vagg_core.core.logging import get_logger

log = get_logger(__name__)

_HKDF_INFO: Final[bytes] = b"vagg-core/fernet-at-rest/v1"
_HKDF_SALT: Final[bytes] = b"vagg-core-crypto-salt-v1"


class CryptoConfigError(RuntimeError):
    """Configuração de criptografia inválida — secret faltando em produção."""


def _derive_key_from_jwt(jwt_secret: str) -> bytes:
    """HKDF-SHA256(jwt_secret) → 32 bytes urlsafe-base64 (formato Fernet)."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    )
    raw = hkdf.derive(jwt_secret.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def _build_fernet(settings: Settings) -> Fernet:
    raw_key = settings.crypto_key.get_secret_value() if settings.crypto_key else None
    if raw_key:
        try:
            # Aceita tanto a chave já em urlsafe-base64 (formato Fernet canonical)
            # quanto 32 bytes raw em hex/utf8 — normalizamos.
            key_bytes = raw_key.encode("ascii") if isinstance(raw_key, str) else raw_key
            # Tenta usar como veio; se Fernet rejeitar, encoda.
            try:
                return Fernet(key_bytes)
            except (ValueError, TypeError):
                decoded = base64.urlsafe_b64decode(key_bytes + b"=" * (-len(key_bytes) % 4))
                if len(decoded) != 32:
                    raise CryptoConfigError(
                        "VAGG_CORE_CRYPTO_KEY deve ter 32 bytes (urlsafe-base64)"
                    )
                return Fernet(base64.urlsafe_b64encode(decoded))
        except CryptoConfigError:
            raise
        except Exception as exc:
            raise CryptoConfigError(
                f"VAGG_CORE_CRYPTO_KEY inválida: {exc}"
            ) from exc

    if settings.environment == "production":
        raise CryptoConfigError(
            "VAGG_CORE_CRYPTO_KEY obrigatória em produção. "
            "Gere com: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )

    log.warning(
        "crypto.key_derived_from_jwt",
        environment=settings.environment,
        reason="VAGG_CORE_CRYPTO_KEY ausente — derivando do jwt_secret (NÃO use em prod)",
    )
    return Fernet(_derive_key_from_jwt(settings.jwt_secret.get_secret_value()))


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    return _build_fernet(get_settings())


def encrypt(plaintext: str) -> str:
    """Criptografa texto utf-8 → token Fernet (urlsafe base64). Idempotente
    de chamadas paralelas — usa singleton."""
    if not plaintext:
        raise ValueError("não cifrar string vazia — use None pra indicar ausência")
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Decifra token Fernet → texto utf-8. Levanta CryptoConfigError se a
    chave atual não conseguir validar — pode indicar rotação sem reencrypt."""
    try:
        return _get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise CryptoConfigError(
            "token cifrado inválido — chave foi rotacionada sem reencrypt?"
        ) from exc


def reset_cache_for_tests() -> None:
    """Tests que mudam `crypto_key` precisam invalidar o singleton."""
    _get_fernet.cache_clear()
