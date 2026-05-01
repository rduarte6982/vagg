"""Integration tests for /webhooks/stripe (SPEC §6.7 + Phase 1 acceptance)."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.helpers import (
    make_invoice_event,
    make_subscription_event,
    serialize,
    sign_stripe_payload,
)
from vagg_license.db.models import License, LicenseStatus, Plan

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

WEBHOOK_SECRET = "whsec_test_dummy"


async def _post(
    client: AsyncClient, payload: dict[str, Any], *, secret: str = WEBHOOK_SECRET
) -> Any:
    body = serialize(payload)
    sig = sign_stripe_payload(body, secret)
    return await client.post(
        "/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
    )


class TestSubscriptionLifecycle:
    async def test_created_event_creates_license_and_emits_key(
        self,
        app_and_client: tuple[Any, AsyncClient],
        session_factory: async_sessionmaker[Any],
    ) -> None:
        _, client = app_and_client
        event = make_subscription_event(
            event_type="customer.subscription.created",
            subscription_id="sub_001",
            customer_id="cus_001",
            price_id="price_professional_test",
        )
        resp = await _post(client, event)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        async with session_factory() as session:
            result = await session.execute(
                select(License).where(License.stripe_subscription_id == "sub_001")
            )
            license_obj = result.scalar_one()

        assert license_obj.license_key.startswith("VAGG-")
        assert license_obj.plan == Plan.PROFESSIONAL
        assert license_obj.status == LicenseStatus.ACTIVE
        assert license_obj.email == "ti@consultoria.example"
        assert license_obj.cnpj == "12.345.678/0001-90"

    async def test_updated_event_changes_plan(
        self,
        app_and_client: tuple[Any, AsyncClient],
        session_factory: async_sessionmaker[Any],
    ) -> None:
        _, client = app_and_client
        await _post(
            client,
            make_subscription_event(
                event_type="customer.subscription.created",
                subscription_id="sub_002",
                customer_id="cus_002",
                price_id="price_starter_test",
            ),
        )
        await _post(
            client,
            make_subscription_event(
                event_type="customer.subscription.updated",
                subscription_id="sub_002",
                customer_id="cus_002",
                price_id="price_enterprise_test",
            ),
        )

        async with session_factory() as session:
            result = await session.execute(
                select(License).where(License.stripe_subscription_id == "sub_002")
            )
            assert result.scalar_one().plan == Plan.ENTERPRISE

    async def test_deleted_event_marks_canceled(
        self,
        app_and_client: tuple[Any, AsyncClient],
        session_factory: async_sessionmaker[Any],
    ) -> None:
        _, client = app_and_client
        await _post(
            client,
            make_subscription_event(
                event_type="customer.subscription.created",
                subscription_id="sub_003",
                customer_id="cus_003",
                price_id="price_starter_test",
            ),
        )
        await _post(
            client,
            make_subscription_event(
                event_type="customer.subscription.deleted",
                subscription_id="sub_003",
                customer_id="cus_003",
                price_id="price_starter_test",
            ),
        )

        async with session_factory() as session:
            result = await session.execute(
                select(License).where(License.stripe_subscription_id == "sub_003")
            )
            assert result.scalar_one().status == LicenseStatus.CANCELED

    async def test_invoice_payment_failed_marks_past_due(
        self,
        app_and_client: tuple[Any, AsyncClient],
        session_factory: async_sessionmaker[Any],
    ) -> None:
        _, client = app_and_client
        await _post(
            client,
            make_subscription_event(
                event_type="customer.subscription.created",
                subscription_id="sub_004",
                customer_id="cus_004",
                price_id="price_professional_test",
            ),
        )
        await _post(
            client,
            make_invoice_event(
                event_type="invoice.payment_failed",
                subscription_id="sub_004",
            ),
        )
        async with session_factory() as session:
            result = await session.execute(
                select(License).where(License.stripe_subscription_id == "sub_004")
            )
            assert result.scalar_one().status == LicenseStatus.PAST_DUE


class TestSignatureVerification:
    async def test_invalid_signature_returns_400(
        self, app_and_client: tuple[Any, AsyncClient]
    ) -> None:
        _, client = app_and_client
        event = make_subscription_event(
            event_type="customer.subscription.created",
            subscription_id="sub_invalid",
            customer_id="cus_invalid",
            price_id="price_starter_test",
        )
        body = serialize(event)
        sig = sign_stripe_payload(body, "whsec_wrong_secret")
        resp = await client.post(
            "/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "WEBHOOK_SIGNATURE_INVALID"

    async def test_missing_signature_header_rejected(
        self, app_and_client: tuple[Any, AsyncClient]
    ) -> None:
        _, client = app_and_client
        body = serialize(
            make_subscription_event(
                event_type="customer.subscription.created",
                subscription_id="sub_x",
                customer_id="cus_x",
                price_id="price_starter_test",
            )
        )
        resp = await client.post(
            "/webhooks/stripe",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        # FastAPI returns 422 on missing required header; either 422 or 400 is acceptable.
        assert resp.status_code in (400, 422)


class TestIdempotency:
    async def test_same_event_id_processed_once(
        self,
        app_and_client: tuple[Any, AsyncClient],
        session_factory: async_sessionmaker[Any],
    ) -> None:
        _, client = app_and_client
        event = make_subscription_event(
            event_type="customer.subscription.created",
            subscription_id="sub_idem",
            customer_id="cus_idem",
            price_id="price_starter_test",
            event_id="evt_idempotent_001",
        )
        first = await _post(client, event)
        second = await _post(client, event)

        assert first.status_code == 200
        assert first.json()["status"] == "ok"
        assert second.status_code == 200
        assert second.json()["status"] == "duplicate"

        async with session_factory() as session:
            result = await session.execute(
                select(License).where(License.stripe_subscription_id == "sub_idem")
            )
            licenses = result.scalars().all()
            assert len(licenses) == 1
