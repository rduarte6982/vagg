"""Unit tests for password hashing and JWT signing."""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest

from vagg_core.core.security import (
    JWTSigner,
    TokenType,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_is_argon2_format(self) -> None:
        h = hash_password("hello-world")
        assert h.startswith("$argon2")

    def test_verify_correct_password(self) -> None:
        h = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", h) is True

    def test_verify_wrong_password(self) -> None:
        h = hash_password("correct-horse-battery-staple")
        assert verify_password("wrong-password", h) is False

    def test_verify_malformed_hash(self) -> None:
        assert verify_password("anything", "not-a-real-hash") is False

    def test_two_hashes_of_same_password_differ(self) -> None:
        # argon2 includes a random salt; same input → different hashes
        a = hash_password("same-password")
        b = hash_password("same-password")
        assert a != b
        # Both still verify
        assert verify_password("same-password", a)
        assert verify_password("same-password", b)


class TestJWTSigner:
    @pytest.fixture
    def signer(self) -> JWTSigner:
        return JWTSigner(
            secret="test-secret-do-not-use",
            issuer="vagg-core-test",
            access_ttl_seconds=300,
            refresh_ttl_seconds=600,
        )

    def test_access_token_round_trip(self, signer: JWTSigner) -> None:
        issued = signer.issue(subject="admin@test.local", token_type=TokenType.ACCESS)
        claims = signer.decode(issued.token, expected_type=TokenType.ACCESS)
        assert claims["sub"] == "admin@test.local"
        assert claims["type"] == "access"
        assert claims["iss"] == "vagg-core-test"

    def test_refresh_token_round_trip(self, signer: JWTSigner) -> None:
        issued = signer.issue(subject="admin@test.local", token_type=TokenType.REFRESH)
        claims = signer.decode(issued.token, expected_type=TokenType.REFRESH)
        assert claims["type"] == "refresh"

    def test_access_token_rejected_when_refresh_expected(self, signer: JWTSigner) -> None:
        issued = signer.issue(subject="x", token_type=TokenType.ACCESS)
        with pytest.raises(pyjwt.InvalidTokenError):
            signer.decode(issued.token, expected_type=TokenType.REFRESH)

    def test_other_secret_cannot_verify(self, signer: JWTSigner) -> None:
        issued = signer.issue(subject="x", token_type=TokenType.ACCESS)
        attacker = JWTSigner(
            secret="different-secret",
            issuer="vagg-core-test",
            access_ttl_seconds=300,
            refresh_ttl_seconds=600,
        )
        with pytest.raises(pyjwt.InvalidSignatureError):
            attacker.decode(issued.token)

    def test_other_issuer_rejected(self, signer: JWTSigner) -> None:
        issued = signer.issue(subject="x", token_type=TokenType.ACCESS)
        wrong_issuer = JWTSigner(
            secret="test-secret-do-not-use",
            issuer="another-service",
            access_ttl_seconds=300,
            refresh_ttl_seconds=600,
        )
        with pytest.raises(pyjwt.InvalidIssuerError):
            wrong_issuer.decode(issued.token)

    def test_expired_token_rejected(self) -> None:
        short = JWTSigner(
            secret="test-secret-do-not-use",
            issuer="vagg-core-test",
            access_ttl_seconds=1,
            refresh_ttl_seconds=600,
        )
        issued = short.issue(subject="x", token_type=TokenType.ACCESS)
        time.sleep(2)
        with pytest.raises(pyjwt.ExpiredSignatureError):
            short.decode(issued.token)
