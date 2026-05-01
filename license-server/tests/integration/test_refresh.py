"""Integration tests for /api/v1/refresh (SPEC §6.3 + Phase 1 acceptance).

Phase 1 AC: "Cancelar subscription faz próximo refresh retornar 402".
"""

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


async def _post_webhook(client: AsyncClient, payload: dict[str, Any]) -> None:
    body = serialize(payload)
    sig = sign_stripe_payload(body, WEBHOOK_SECRET)
    resp = await client.post(
        "/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200


async def _seed_and_activate(
    client: AsyncClient,
    session_factory: async_sessionmaker[Any],
    subscription_id: str,
    customer_id: str,
    *,
    price_id: str = "price_professional_test",
) -> str:
    await _post_webhook(
        client,
        make_subscription_event(
            event_type="customer.subscription.created",
            subscription_id=subscription_id,
            customer_id=customer_id,
            price_id=price_id,
        ),
    )
    async with session_factory() as session:
        row = (
            await session.execute(
                select(License).where(License.stripe_subscription_id == subscription_id)
            )
        ).scalar_one()
        license_key = row.license_key

    resp = await client.post(
        "/api/v1/activate",
        json={
            "license_key": license_key,
            "instance_id": "inst-deadbeef",
            "fingerprint": "fp-cpu-mac",
        },
    )
    assert resp.status_code == 200
    return license_key


class TestRefreshHappyPath:
    async def test_refresh_returns_new_jwt(
        self,
        app_and_client: tuple[Any, AsyncClient],
        session_factory: async_sessionmaker[Any],
        jwt_signer: JWTSigner,
    ) -> None:
        _, client = app_and_client
        license_key = await _seed_and_activate(
            client, session_factory, "sub_ref_01", "cus_ref_01"
        )

        resp = await client.post(
            "/api/v1/refresh",
            json={
                "license_key": license_key,
                "instance_id": "inst-deadbeef",
                "fingerprint": "fp-cpu-mac",
            },
        )
        assert resp.status_code == 200
        decoded = jwt_signer.verify(resp.json()["jwt"])
        assert decoded["license_key"] == license_key
        assert decoded["plan"] == "professional"


class TestRefreshAfterCancel:
    async def test_canceled_subscription_returns_402(
        self,
        app_and_client: tuple[Any, AsyncClient],
        session_factory: async_sessionmaker[Any],
    ) -> None:
        """Phase 1 acceptance criterion: cancel → next /refresh returns 402."""
        _, client = app_and_client
        license_key = await _seed_and_activate(
            client, session_factory, "sub_ref_cancel", "cus_ref_cancel"
        )

        await _post_webhook(
            client,
            make_subscription_event(
                event_type="customer.subscription.deleted",
                subscription_id="sub_ref_cancel",
                customer_id="cus_ref_cancel",
                price_id="price_professional_test",
            ),
        )

        resp = await client.post(
            "/api/v1/refresh",
            json={
                "license_key": license_key,
                "instance_id": "inst-deadbeef",
                "fingerprint": "fp-cpu-mac",
            },
        )
        assert resp.status_code == 402
        assert resp.json()["code"] == "LICENSE_INACTIVE"


class TestRefreshRejections:
    async def test_unknown_license_returns_404(
        self, app_and_client: tuple[Any, AsyncClient]
    ) -> None:
        _, client = app_and_client
        resp = await client.post(
            "/api/v1/refresh",
            json={
                "license_key": "VAGG-NOPE-NOPE-NOPE",
                "instance_id": "inst-1",
                "fingerprint": "fp-1",
            },
        )
        assert resp.status_code == 404

    async def test_fingerprint_mismatch_returns_409(
        self,
        app_and_client: tuple[Any, AsyncClient],
        session_factory: async_sessionmaker[Any],
    ) -> None:
        _, client = app_and_client
        license_key = await _seed_and_activate(
            client, session_factory, "sub_ref_mm", "cus_ref_mm"
        )

        resp = await client.post(
            "/api/v1/refresh",
            json={
                "license_key": license_key,
                "instance_id": "inst-different",
                "fingerprint": "fp-cpu-mac",
            },
        )
        assert resp.status_code == 409

    async def test_unactivated_license_cannot_refresh(
        self,
        app_and_client: tuple[Any, AsyncClient],
        session_factory: async_sessionmaker[Any],
    ) -> None:
        _, client = app_and_client
        await _post_webhook(
            client,
            make_subscription_event(
                event_type="customer.subscription.created",
                subscription_id="sub_ref_unact",
                customer_id="cus_ref_unact",
                price_id="price_starter_test",
            ),
        )
        async with session_factory() as session:
            row = (
                await session.execute(
                    select(License).where(License.stripe_subscription_id == "sub_ref_unact")
                )
            ).scalar_one()
            license_key = row.license_key

        resp = await client.post(
            "/api/v1/refresh",
            json={
                "license_key": license_key,
                "instance_id": "inst-1",
                "fingerprint": "fp-1",
            },
        )
        assert resp.status_code == 404
