"""TOTP (RFC 6238) stdlib-only implementation pra geração server-side de
códigos MFA usados em ``/clients/{id}/connect``.

Por que stdlib? — pra evitar nova dep (pyotp) quando 30 linhas de hmac/struct
fazem o serviço. Compatível com Google Authenticator, Microsoft Authenticator,
FortiToken, FreeOTP, 1Password, Authy, etc. — todos seguem RFC 6238 com
SHA1/6 dígitos/janela 30s por default.

Aceita ``otpauth://`` URI (formato padrão de QR code) ou base32 puro como
input — facilita o admin colar direto o conteúdo de qualquer fonte.

Uso:

    >>> meta = parse_secret("otpauth://totp/Acme:alice?secret=JBSWY3DPEHPK3PXP&issuer=Acme")
    >>> meta.secret
    'JBSWY3DPEHPK3PXP'
    >>> generate(meta.secret, at=0)
    '282760'
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import struct
import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, unquote, urlparse

Algorithm = Literal["sha1", "sha256", "sha512"]

_ALGORITHMS: dict[Algorithm, "hashlib._Hash"] = {
    "sha1": hashlib.sha1,  # type: ignore[dict-item]
    "sha256": hashlib.sha256,  # type: ignore[dict-item]
    "sha512": hashlib.sha512,  # type: ignore[dict-item]
}

_BASE32_RE = re.compile(r"^[A-Z2-7]+=*$")


@dataclass(frozen=True)
class TotpMetadata:
    """Resultado de parse_secret — secret canonical + dicas do issuer."""

    secret: str  # base32 sem espaço, sem padding extra (Fernet-safe ASCII)
    issuer: str | None = None
    account: str | None = None
    digits: int = 6
    period: int = 30
    algorithm: Algorithm = "sha1"


class InvalidSecretError(ValueError):
    """Secret/URI fornecido não é parseable."""


def _normalize_base32(raw: str) -> str:
    """Tira whitespace, normaliza pra uppercase, padding com '=' até múltiplo de 8."""
    cleaned = re.sub(r"\s+", "", raw).upper()
    if not cleaned:
        raise InvalidSecretError("secret vazio")
    # base32 pode vir sem padding ('=') — adiciona até comprimento ser múltiplo de 8.
    pad_needed = (-len(cleaned)) % 8
    candidate = cleaned + ("=" * pad_needed)
    if not _BASE32_RE.match(candidate):
        raise InvalidSecretError("secret deve ser base32 (A-Z + 2-7)")
    try:
        base64.b32decode(candidate, casefold=False)
    except Exception as exc:
        raise InvalidSecretError(f"secret base32 inválido: {exc}") from exc
    return candidate.rstrip("=")  # armazena sem padding (mais curto)


def parse_secret(raw: str) -> TotpMetadata:
    """Aceita ``otpauth://totp/...?secret=XXX&issuer=...`` ou base32 puro."""
    if not raw:
        raise InvalidSecretError("secret vazio")
    raw = raw.strip()

    if raw.lower().startswith("otpauth://"):
        return _parse_otpauth(raw)
    return TotpMetadata(secret=_normalize_base32(raw))


def _parse_otpauth(uri: str) -> TotpMetadata:
    parsed = urlparse(uri)
    if parsed.scheme.lower() != "otpauth" or parsed.netloc.lower() != "totp":
        raise InvalidSecretError("URI deve ser otpauth://totp/...")
    qs = parse_qs(parsed.query, keep_blank_values=False)
    secret_q = qs.get("secret")
    if not secret_q:
        raise InvalidSecretError("URI otpauth sem ?secret=")
    secret = _normalize_base32(secret_q[0])

    # Label = "Issuer:Account" ou só "Account"
    label = unquote(parsed.path.lstrip("/"))
    issuer_label, account = (label.split(":", 1) + [""])[:2] if ":" in label else (None, label)
    issuer = (qs.get("issuer") or [issuer_label or ""])[0].strip() or None
    account = account.strip() or None

    digits = int((qs.get("digits") or ["6"])[0])
    if digits not in (6, 7, 8):
        raise InvalidSecretError(f"digits deve ser 6/7/8 (recebido {digits})")
    period = int((qs.get("period") or ["30"])[0])
    if period <= 0:
        raise InvalidSecretError(f"period deve ser > 0 (recebido {period})")
    alg_raw = (qs.get("algorithm") or ["SHA1"])[0].lower()
    if alg_raw not in _ALGORITHMS:
        raise InvalidSecretError(f"algorithm não suportado: {alg_raw}")

    return TotpMetadata(
        secret=secret,
        issuer=issuer,
        account=account,
        digits=digits,
        period=period,
        algorithm=alg_raw,  # type: ignore[arg-type]
    )


def _hotp(secret_base32: str, counter: int, digits: int, algorithm: Algorithm) -> str:
    """HOTP base — RFC 4226."""
    # Re-aplica padding pra base32 decode.
    padded = secret_base32 + ("=" * ((-len(secret_base32)) % 8))
    key = base64.b32decode(padded, casefold=False)
    msg = struct.pack(">Q", counter)
    hasher = _ALGORITHMS[algorithm]
    digest = hmac.new(key, msg, hasher).digest()
    offset = digest[-1] & 0x0F
    code_int = (
        ((digest[offset] & 0x7F) << 24)
        | ((digest[offset + 1] & 0xFF) << 16)
        | ((digest[offset + 2] & 0xFF) << 8)
        | (digest[offset + 3] & 0xFF)
    )
    return str(code_int % (10**digits)).zfill(digits)


def generate(
    secret_base32: str,
    *,
    at: float | None = None,
    digits: int = 6,
    period: int = 30,
    algorithm: Algorithm = "sha1",
) -> str:
    """Gera código TOTP RFC 6238 pro instante ``at`` (default: time.time())."""
    now = time.time() if at is None else at
    counter = int(now) // period
    return _hotp(secret_base32, counter, digits, algorithm)


def seconds_remaining(period: int = 30, at: float | None = None) -> int:
    """Quantos segundos faltam pra rolar pra próxima janela TOTP."""
    now = time.time() if at is None else at
    return period - (int(now) % period)


def verify(
    secret_base32: str,
    code: str,
    *,
    at: float | None = None,
    digits: int = 6,
    period: int = 30,
    algorithm: Algorithm = "sha1",
    window: int = 1,
) -> bool:
    """True se ``code`` bate com ±``window`` janelas (default ±30s)."""
    now = time.time() if at is None else at
    counter = int(now) // period
    expected = code.strip()
    for delta in range(-window, window + 1):
        candidate = _hotp(secret_base32, counter + delta, digits, algorithm)
        if hmac.compare_digest(candidate, expected):
            return True
    return False
