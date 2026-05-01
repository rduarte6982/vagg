"""Persistence layer for licenses, license_events and webhook idempotency."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vagg_license.core.id_gen import new_license_key, uuid7
from vagg_license.db.models import (
    License,
    LicenseEvent,
    LicenseStatus,
    Plan,
    StripeWebhookDelivery,
)
from vagg_license.services.stripe_client import SubscriptionView


class LicenseStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ----- Reads -----

    async def get_by_license_key(self, license_key: str) -> License | None:
        result = await self._session.execute(
            select(License).where(License.license_key == license_key)
        )
        return result.scalar_one_or_none()

    async def get_by_subscription_id(self, subscription_id: str) -> License | None:
        result = await self._session.execute(
            select(License).where(License.stripe_subscription_id == subscription_id)
        )
        return result.scalar_one_or_none()

    # ----- Writes: subscription lifecycle -----

    async def upsert_from_subscription(
        self, view: SubscriptionView, *, event_type: str, event_payload: dict[str, Any]
    ) -> License:
        """Create or update the license row tied to a Stripe subscription."""
        existing = await self.get_by_subscription_id(view.id)
        if existing is None:
            license_obj = License(
                id=uuid7(),
                license_key=new_license_key(),
                stripe_customer_id=view.customer_id,
                stripe_subscription_id=view.id,
                plan=view.plan,
                status=view.status,
                email=view.customer_email,
                company_name=view.customer_company_name,
                cnpj=view.cnpj,
            )
            self._session.add(license_obj)
            await self._session.flush()
        else:
            existing.plan = view.plan
            existing.status = view.status
            existing.email = view.customer_email
            existing.company_name = view.customer_company_name
            existing.cnpj = view.cnpj
            license_obj = existing

        await self._record_event(license_obj.id, event_type, event_payload)
        return license_obj

    async def mark_status(
        self,
        subscription_id: str,
        new_status: LicenseStatus,
        *,
        event_type: str,
        event_payload: dict[str, Any],
    ) -> License | None:
        license_obj = await self.get_by_subscription_id(subscription_id)
        if license_obj is None:
            return None
        license_obj.status = new_status
        await self._record_event(license_obj.id, event_type, event_payload)
        return license_obj

    # ----- Writes: activate / refresh -----

    async def bind_instance(
        self, license_obj: License, *, instance_id: str, fingerprint_hash: str
    ) -> None:
        """Set instance binding on first activation; subsequent calls are validated externally."""
        license_obj.instance_id = instance_id
        license_obj.fingerprint_hash = fingerprint_hash
        license_obj.activated_at = datetime.now(UTC)
        license_obj.last_refresh_at = datetime.now(UTC)
        await self._record_event(
            license_obj.id,
            "license.activated",
            {"instance_id": instance_id, "fingerprint_hash": fingerprint_hash},
        )

    async def touch_last_refresh(self, license_obj: License) -> None:
        license_obj.last_refresh_at = datetime.now(UTC)
        await self._record_event(license_obj.id, "license.refreshed", {})

    # ----- Webhook idempotency -----

    async def webhook_already_processed(self, event_id: str) -> bool:
        result = await self._session.execute(
            select(StripeWebhookDelivery).where(StripeWebhookDelivery.event_id == event_id)
        )
        return result.scalar_one_or_none() is not None

    async def mark_webhook_processed(self, event_id: str, event_type: str) -> None:
        self._session.add(StripeWebhookDelivery(event_id=event_id, event_type=event_type))
        await self._session.flush()

    # ----- Internal -----

    async def _record_event(
        self, license_id: Any, event_type: str, payload: dict[str, Any]
    ) -> None:
        self._session.add(
            LicenseEvent(
                id=uuid7(),
                license_id=license_id,
                event_type=event_type,
                payload=payload,
            )
        )
        await self._session.flush()


def plan_from_status_and_default(view: SubscriptionView) -> Plan:
    """Tiny helper to keep callers concise. Currently a passthrough."""
    return view.plan
