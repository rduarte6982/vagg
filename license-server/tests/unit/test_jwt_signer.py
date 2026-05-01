"""Unit tests for JWTSigner. Run anywhere — no DB or Docker required."""

from __future__ import annotations

import time
import uuid

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vagg_license.db.models import Plan
from vagg_license.services.jwt_signer import (
    LICENSE_VERSION,
    PLAN_LIMITS,
    JWTSigner,
    hash_fingerprint,
)


@pytest.fixture
def signer(ed25519_keypair_pem: tuple[str, str]) -> JWTSigner:
    private_pem, public_pem = ed25519_keypair_pem
    return JWTSigner(
        private_key_pem=private_pem,
        public_key_pem=public_pem,
        issuer="vagg-license-server-test",
        ttl_seconds=300,
    )


class TestJWTSigner:
    def test_issued_token_has_required_claims(self, signer: JWTSigner) -> None:
        license_id = str(uuid.uuid4())
        issued = signer.issue(
            license_key="VAGG-AAAA-BBBB-CCCC",
            license_id=license_id,
            plan=Plan.PROFESSIONAL,
            instance_id="instance-1",
            fingerprint_hash="0" * 64,
        )
        decoded = signer.verify(issued.token)
        assert decoded["iss"] == "vagg-license-server-test"
        assert decoded["sub"] == license_id
        assert decoded["lv"] == LICENSE_VERSION
        assert decoded["plan"] == "professional"
        assert decoded["limits"] == PLAN_LIMITS[Plan.PROFESSIONAL]
        assert decoded["license_key"] == "VAGG-AAAA-BBBB-CCCC"
        assert decoded["instance_id"] == "instance-1"
        assert decoded["fingerprint_hash"] == "0" * 64
        assert decoded["warning"] is None

    def test_warning_field_propagates(self, signer: JWTSigner) -> None:
        issued = signer.issue(
            license_key="VAGG-AAAA-BBBB-CCCC",
            license_id=str(uuid.uuid4()),
            plan=Plan.STARTER,
            instance_id="instance-1",
            fingerprint_hash="0" * 64,
            warning="past_due",
        )
        decoded = signer.verify(issued.token)
        assert decoded["warning"] == "past_due"

    def test_token_is_signed_with_ed25519(
        self, signer: JWTSigner, ed25519_keypair_pem: tuple[str, str]
    ) -> None:
        _, public_pem = ed25519_keypair_pem
        issued = signer.issue(
            license_key="VAGG-AAAA-BBBB-CCCC",
            license_id=str(uuid.uuid4()),
            plan=Plan.STARTER,
            instance_id="instance-1",
            fingerprint_hash="0" * 64,
        )
        # Verify with raw public key (simulates aggregator-side verification path).
        public_key = serialization.load_pem_public_key(public_pem.encode())
        decoded = pyjwt.decode(
            issued.token, public_key, algorithms=["EdDSA"], issuer="vagg-license-server-test"
        )
        assert decoded["plan"] == "starter"

    def test_other_keypair_cannot_verify(self, signer: JWTSigner) -> None:
        issued = signer.issue(
            license_key="VAGG-AAAA-BBBB-CCCC",
            license_id=str(uuid.uuid4()),
            plan=Plan.STARTER,
            instance_id="instance-1",
            fingerprint_hash="0" * 64,
        )
        attacker_pub = (
            Ed25519PrivateKey.generate()
            .public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        with pytest.raises(pyjwt.InvalidSignatureError):
            pyjwt.decode(issued.token, attacker_pub, algorithms=["EdDSA"])

    def test_expired_token_rejected(
        self, ed25519_keypair_pem: tuple[str, str]
    ) -> None:
        private_pem, public_pem = ed25519_keypair_pem
        short_signer = JWTSigner(
            private_key_pem=private_pem,
            public_key_pem=public_pem,
            issuer="vagg-license-server-test",
            ttl_seconds=1,
        )
        issued = short_signer.issue(
            license_key="VAGG-AAAA-BBBB-CCCC",
            license_id=str(uuid.uuid4()),
            plan=Plan.STARTER,
            instance_id="instance-1",
            fingerprint_hash="0" * 64,
        )
        time.sleep(2)
        with pytest.raises(pyjwt.ExpiredSignatureError):
            short_signer.verify(issued.token)


class TestHashFingerprint:
    def test_deterministic(self) -> None:
        assert hash_fingerprint("cpu123-mac456") == hash_fingerprint("cpu123-mac456")

    def test_different_inputs_produce_different_hashes(self) -> None:
        assert hash_fingerprint("a") != hash_fingerprint("b")

    def test_output_is_64_hex_chars(self) -> None:
        h = hash_fingerprint("anything")
        assert len(h) == 64
        int(h, 16)  # raises if not hex
