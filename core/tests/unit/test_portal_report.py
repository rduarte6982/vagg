"""Tests for the portal report Ed25519 signing (SPEC §5.6 / Fase 11)."""

from __future__ import annotations

import base64
import hashlib
import json
import types
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vagg_core.portal.report import (
    load_or_create_signing_key,
    public_key_b64,
    signed_canonical_for_verify,
    verify_signature,
)


def _ev(idx: int, *, payload: dict[str, object] | None = None) -> object:
    return types.SimpleNamespace(
        id=f"id-{idx}",
        hash=f"deadbeef{idx:04d}",
        occurred_at=datetime(2026, 5, 1, idx, 0, tzinfo=UTC),
        payload=payload or {},
        event_type="tunnel.access",
    )


class TestSigningKey:
    def test_creates_pem_when_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "sk.pem"
        key = load_or_create_signing_key(path)
        assert path.exists()
        assert isinstance(key, Ed25519PrivateKey)
        assert path.read_bytes().startswith(b"-----BEGIN PRIVATE KEY-----")

    def test_loads_existing_key(self, tmp_path: Path) -> None:
        path = tmp_path / "sk.pem"
        first = load_or_create_signing_key(path)
        second = load_or_create_signing_key(path)
        assert public_key_b64(first) == public_key_b64(second)


class TestSignatureRoundTrip:
    def test_canonical_then_sign_then_verify(self, tmp_path: Path) -> None:
        key = load_or_create_signing_key(tmp_path / "sk.pem")
        events = [_ev(1), _ev(2)]
        canonical = signed_canonical_for_verify(
            client_id="petroleo",
            since=None,
            until=None,
            summary={"consultants": 0},
            events=events,
            chain_anchor="abc",
        )
        signature = key.sign(canonical.encode("utf-8"))
        b64sig = base64.b64encode(signature).decode("ascii")

        ok = verify_signature(public_key_b64(key), canonical.encode("utf-8"), b64sig)
        assert ok

    def test_tampering_breaks_verification(self, tmp_path: Path) -> None:
        key = load_or_create_signing_key(tmp_path / "sk.pem")
        canonical = signed_canonical_for_verify(
            client_id="petroleo",
            since=None,
            until=None,
            summary={"consultants": 0},
            events=[_ev(1)],
            chain_anchor=None,
        )
        signature = key.sign(canonical.encode("utf-8"))
        b64sig = base64.b64encode(signature).decode("ascii")
        tampered = canonical.replace("petroleo", "varejo")
        assert not verify_signature(public_key_b64(key), tampered.encode("utf-8"), b64sig)

    def test_canonical_is_deterministic(self) -> None:
        a = signed_canonical_for_verify(
            client_id="x",
            since=None,
            until=None,
            summary={"a": 1, "b": 2},
            events=[_ev(1)],
            chain_anchor=None,
        )
        b = signed_canonical_for_verify(
            client_id="x",
            since=None,
            until=None,
            summary={"b": 2, "a": 1},  # different insertion order
            events=[_ev(1)],
            chain_anchor=None,
        )
        # Sorted keys → same bytes, so the signature is reproducible.
        assert a == b
        # Hash of the canonical string is the same too — used as the report's
        # public integrity hash.
        assert (
            hashlib.sha256(a.encode("utf-8")).hexdigest()
            == hashlib.sha256(b.encode("utf-8")).hexdigest()
        )
        # And it really is sorted.
        parsed = json.loads(a)
        assert list(parsed["summary"].keys()) == ["a", "b"]
