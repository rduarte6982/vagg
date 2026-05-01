"""Integration tests for /api/v1/activate (SPEC §6.2 + Phase 1 acceptance)."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.helpers import make_subscription_event, serialize, sign_stripe_payload
from vagg_license.db.models import License
from vagg_license.services.jwt_signer import JWTSigner

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
WEBHOOK_SECRET = "whsec_test_dummy"


async def _seed_license_via_webhook(
    client: AsyncClient,
    *,
    subscription_id: str,
    customer_id: str,
    price_id: str = "price_professional_test",
) -> None:
    event = make_subscription_event(
        event_type="customer.subscription.created",
        subscription_id=subscription_id,
        customer_id=customer_id,
        price_id=price_id,
    )
    body = serialize(event)
    sig = sign_stripe_payload(body, WEBHOOK_SECRET)
    resp = await client.post(
        "/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200


async def _get_license_key(session_factory: async_sessionmaker[Any], subscription_id: str) -> str:
    async with session_factory() as session:
        result = await session.execute(
            select(License).where(License.stripe_subscription_id == subscription_id)
        )
        return result.scalar_one().license_key


class TestActivateHappyPath:
    async def test_activate_returns_jwt_that_verifies_with_public_key(
        self,
        app_and_client: tuple[Any, AsyncClient],
        session_factory: async_sessionmaker[Any],
        jwt_signer: JWTSigner,
    ) -> None:
        _, client = app_and_client
        await _seed_license_via_webhook(
            client, subscription_id="sub_act_01", customer_id="cus_act_01"
        )
        license_key = await _get_license_key(session_factory, "sub_act_01")

        resp = await client.post(
            "/api/v1/activate",
            json={
                "license_key": license_key,
                "instance_id": "inst-deadbeef",
                "fingerprint": "cpu123-mac456",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan"] == "professional"
        assert "expires_at" in data

        # AC: JWT valida com a public key
        decoded = jwt_signer.verify(data["jwt"])
        assert decoded["license_key"] == license_key
        assert decoded["instance_id"] == "inst-deadbeef"
        assert decoded["plan"] == "professional"

    async def test_activate_persists_instance_binding(
        self,
        app_and_client: tuple[Any, AsyncClient],
        session_factory: async_sessionmaker[Any],
    ) -> None:
        _, client = app_and_client
        await _seed_license_via_webhook(
            client, subscription_id="sub_act_02", customer_id="cus_act_02"
        )
        license_key = await _get_license_key(session_factory, "sub_act_02")

        await client.post(
            "/api/v1/activate",
            json={
                "license_key": license_key,
                "instance_id": "inst-001",
                "fingerprint": "fp-001",
            },
        )
        async with session_factory() as session:
            row = (
                await session.execute(select(License).where(License.license_key == license_key))
            ).scalar_one()
        assert row.instance_id == "inst-001"
        assert row.fingerprint_hash is not None
        assert row.activated_at is not None


class TestActivateRejections:
    async def test_unknown_license_key_returns_404(
        self, app_and_client: tuple[Any, AsyncClient]
    ) -> None:
        _, client = app_and_client
        resp = await client.post(
            "/api/v1/activate",
            json={
                "license_key": "VAGG-XXXX-XXXX-XXXX",
                "instance_id": "inst-1",
                "fingerprint": "fp-1",
            },
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "LICENSE_NOT_FOUND"

    async def test_fingerprint_mismatch_returns_409(
        self,
        app_and_client: tuple[Any, AsyncClient],
        session_factory: async_sessionmaker[Any],
    ) -> None:
        _, client = app_and_client
        await _seed_license_via_webhook(
            client, subscription_id="sub_act_mm", customer_id="cus_act_mm"
        )
        license_key = await _get_license_key(session_factory, "sub_act_mm")

        await client.post(
            "/api/v1/activate",
            json={
                "license_key": license_key,
                "instance_id": "inst-A",
                "fingerprint": "fp-A",
            },
        )
        resp = await client.post(
            "/api/v1/activate",
            json={
                "license_key": license_key,
                "instance_id": "inst-B",
                "fingerprint": "fp-B",
            },
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == "FINGERPRINT_MISMATCH"

    async def test_canceled_license_returns_402(
        self,
        app_and_client: tuple[Any, AsyncClient],
        session_factory: async_sessionmaker[Any],
    ) -> None:
        _, client = app_and_client
        await _seed_license_via_webhook(
            client, subscription_id="sub_act_canceled", customer_id="cus_act_canceled"
        )
        # Cancel via webhook
        cancel_event = make_subscription_event(
            event_type="customer.subscription.deleted",
            subscription_id="sub_act_canceled",
            customer_id="cus_act_canceled",
            price_id="price_professional_test",
        )
        body = serialize(cancel_event)
        sig = sign_stripe_payload(body, WEBHOOK_SECRET)
        await client.post(
            "/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
        )

        license_key = await _get_license_key(session_factory, "sub_act_canceled")
        resp = await client.post(
            "/api/v1/activate",
            json={
                "license_key": license_key,
                "instance_id": "inst-1",
                "fingerprint": "fp-1",
            },
        )
        assert resp.status_code == 402
        assert resp.json()["code"] == "LICENSE_INACTIVE"
