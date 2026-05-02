"""Portal auth: magic link + opcional TOTP (SPEC §5.6).

Magic link flow:
  1. Auditor envia email em ``POST /portal/auth/request_magic_link``.
  2. Sistema cria ``ExternalViewerToken(kind='magic')``, retorna 202.
  3. Email enviado contendo ``GET /portal/auth/consume?token={raw}``.
     Em dev, o token aparece nos logs (``LOG_MAGIC_LINK_TO_STDOUT=true``).
  4. Consume troca o token magic por um session token (kind='session').
  5. Se TOTP habilitado, ``POST /portal/auth/totp`` upgrade a sessão.

O design intencionalmente NÃO usa o `JWTSigner` do admin para evitar que
um vazamento de chave do portal comprometa a sessão de admin.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import UTC, datetime, timedelta
from typing import Final

MAGIC_TTL = timedelta(minutes=15)
SESSION_TTL = timedelta(hours=8)
TOTP_PERIOD: Final[int] = 30
TOTP_DIGITS: Final[int] = 6


def random_token() -> str:
    """URL-safe random token (32 bytes → ~43 chars base64)."""
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """SHA-256 do token. O token cru nunca toca o DB — só o hash."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("ascii"), b.encode("ascii"))


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def magic_expires_at() -> datetime:
    return now_utc() + MAGIC_TTL


def session_expires_at() -> datetime:
    return now_utc() + SESSION_TTL


# ----- TOTP (RFC 6238) — stdlib only -----


def generate_totp_secret() -> str:
    """20 random bytes encoded as base32 — what most TOTP apps expect."""
    raw = secrets.token_bytes(20)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    """RFC 4226 HOTP — used by RFC 6238 TOTP."""
    pad = "=" * ((-len(secret_b32)) % 8)
    key = base64.b32decode(secret_b32 + pad, casefold=True)
    counter_bytes = struct.pack(">Q", counter)
    digest = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = (
        ((digest[offset] & 0x7F) << 24)
        | ((digest[offset + 1] & 0xFF) << 16)
        | ((digest[offset + 2] & 0xFF) << 8)
        | (digest[offset + 3] & 0xFF)
    )
    return str(binary % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)


def verify_totp(secret_b32: str, code: str, *, drift: int = 1) -> bool:
    """True if ``code`` matches the current 30s window or +/- ``drift`` windows."""
    if len(code) != TOTP_DIGITS or not code.isdigit():
        return False
    counter = int(time.time() / TOTP_PERIOD)
    for offset in range(-drift, drift + 1):
        if hmac.compare_digest(_hotp(secret_b32, counter + offset), code):
            return True
    return False


def totp_provisioning_uri(secret_b32: str, *, account: str, issuer: str) -> str:
    """``otpauth://`` URI for QR-code apps (Google Authenticator, etc.)."""
    label = f"{issuer}:{account}".replace(" ", "%20")
    return (
        f"otpauth://totp/{label}?secret={secret_b32}"
        f"&issuer={issuer.replace(' ', '%20')}&digits={TOTP_DIGITS}&period={TOTP_PERIOD}"
    )
