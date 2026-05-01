"""Password hashing (argon2) and JWT (HS256) for admin sessions.

SPEC §2.2: argon2 for passwords, HS256 JWT for admin sessions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt as pyjwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"  # noqa: S105 — token type label, not a password


def hash_password(password: str) -> str:
    """Return an argon2-encoded hash of ``password``."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time-ish verify; ``False`` for any mismatch or malformed hash."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, Exception):  # argon2 raises various subclasses
        return False


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_at: datetime
    token_type: TokenType


class JWTSigner:
    """HS256 JWT issuer/verifier."""

    def __init__(
        self,
        *,
        secret: str,
        issuer: str,
        access_ttl_seconds: int,
        refresh_ttl_seconds: int,
    ) -> None:
        self._secret = secret
        self._issuer = issuer
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds

    def issue(
        self,
        *,
        subject: str,
        token_type: TokenType,
        extra_claims: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> IssuedToken:
        now = now or datetime.now(UTC)
        ttl = self._access_ttl if token_type is TokenType.ACCESS else self._refresh_ttl
        exp = now + timedelta(seconds=ttl)
        payload: dict[str, Any] = {
            "iss": self._issuer,
            "sub": subject,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "type": token_type.value,
        }
        if extra_claims:
            payload.update(extra_claims)
        return IssuedToken(
            token=pyjwt.encode(payload, self._secret, algorithm="HS256"),
            expires_at=exp,
            token_type=token_type,
        )

    def decode(self, token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
        """Verify signature, expiry and issuer; optionally enforce token_type.

        Raises pyjwt exceptions on any failure (caller maps to HTTP 401).
        """
        claims: dict[str, Any] = pyjwt.decode(
            token,
            self._secret,
            algorithms=["HS256"],
            issuer=self._issuer,
            options={"require": ["exp", "iat", "iss", "sub", "type"]},
        )
        if expected_type is not None and claims.get("type") != expected_type.value:
            raise pyjwt.InvalidTokenError(
                f"unexpected token type: got {claims.get('type')}, want {expected_type.value}"
            )
        return claims
