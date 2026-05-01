"""Ed25519-signed JWT issuance and verification (SPEC §6.5).

Uses PyJWT with the ``cryptography`` backend. Algorithm: EdDSA (Ed25519).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from vagg_license.db.models import Plan

# Embedded in vagg-core at compile time (SPEC §6.6). Increment when changing claim shape.
LICENSE_VERSION = 1

# Plan limits (SPEC §6.1). ``None`` means unlimited; aggregator interprets as "no cap".
PLAN_LIMITS: dict[Plan, dict[str, Any]] = {
    Plan.STARTER: {
        "max_clients": 5,
        "max_consultants": 15,
        "audit_export": False,
        "sso": False,
    },
    Plan.PROFESSIONAL: {
        "max_clients": 20,
        "max_consultants": 60,
        "audit_export": True,
        "sso": False,
    },
    Plan.ENTERPRISE: {
        "max_clients": None,
        "max_consultants": None,
        "audit_export": True,
        "sso": True,
    },
}


@dataclass(frozen=True)
class IssuedJWT:
    token: str
    expires_at: datetime
    issued_at: datetime


def hash_fingerprint(fingerprint: str) -> str:
    """SHA-256 of the raw fingerprint string the client computed (CPU+MAC).

    The server never stores the raw fingerprint, only the digest (SPEC §6.5).
    """
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


class JWTSigner:
    """Issues and locally verifies Ed25519 JWTs."""

    def __init__(
        self,
        *,
        private_key_pem: str,
        public_key_pem: str,
        issuer: str,
        ttl_seconds: int,
    ) -> None:
        self._private_key = self._load_private_key(private_key_pem)
        self._public_key = self._load_public_key(public_key_pem)
        self._issuer = issuer
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def _load_private_key(pem: str) -> Ed25519PrivateKey:
        loaded = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            raise ValueError("Expected Ed25519 private key")
        return loaded

    @staticmethod
    def _load_public_key(pem: str) -> Ed25519PublicKey:
        loaded = serialization.load_pem_public_key(pem.encode("utf-8"))
        if not isinstance(loaded, Ed25519PublicKey):
            raise ValueError("Expected Ed25519 public key")
        return loaded

    def issue(
        self,
        *,
        license_key: str,
        license_id: str,
        plan: Plan,
        instance_id: str,
        fingerprint_hash: str,
        warning: str | None = None,
        now: datetime | None = None,
    ) -> IssuedJWT:
        """Sign a license JWT. Payload follows SPEC §6.5."""
        now = now or datetime.now(UTC)
        exp = now + timedelta(seconds=self._ttl_seconds)
        payload = {
            "iss": self._issuer,
            "sub": license_id,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "lv": LICENSE_VERSION,
            "plan": plan.value,
            "limits": PLAN_LIMITS[plan],
            "license_key": license_key,
            "instance_id": instance_id,
            "fingerprint_hash": fingerprint_hash,
            "warning": warning,
        }
        token = pyjwt.encode(payload, self._private_key, algorithm="EdDSA")
        return IssuedJWT(token=token, expires_at=exp, issued_at=now)

    def verify(self, token: str) -> dict[str, Any]:
        """Verify a previously-issued token. Used by tests and self-check on issue."""
        return pyjwt.decode(  # type: ignore[no-any-return]
            token,
            self._public_key,
            algorithms=["EdDSA"],
            issuer=self._issuer,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
