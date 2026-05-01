"""POST /webhooks/stripe — Stripe webhook handler (SPEC §6.7)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, status

from vagg_license.api.deps import get_license_store, get_stripe_client
from vagg_license.core.logging import get_logger
from vagg_license.db.models import LicenseStatus
from vagg_license.services.license_store import LicenseStore
from vagg_license.services.stripe_client import StripeClient

router = APIRouter(prefix="/webhooks", tags=["webhook"])

log = get_logger(__name__)


@router.post("/stripe", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    stripe_client: Annotated[StripeClient, Depends(get_stripe_client)],
    store: Annotated[LicenseStore, Depends(get_license_store)],
    stripe_signature: Annotated[str, Header(alias="Stripe-Signature")],
) -> dict[str, Any]:
    raw = await request.body()
    event = stripe_client.construct_event(raw, stripe_signature)

    # Idempotency: each Stripe event_id processed at most once (Stripe retries on 5xx).
    if await store.webhook_already_processed(event["id"]):
        log.info("stripe_webhook.duplicate", event_id=event["id"], type=event["type"])
        return {"status": "duplicate", "event_id": event["id"]}

    event_type = event["type"]
    event_payload: dict[str, Any] = {"event_id": event["id"], "raw_type": event_type}

    if event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        view = stripe_client.project_event_subscription(event)
        license_obj = await store.upsert_from_subscription(
            view, event_type=event_type, event_payload=event_payload
        )
        log.info(
            "stripe_webhook.upsert",
            event_id=event["id"],
            license_id=str(license_obj.id),
            status=license_obj.status.value,
            plan=license_obj.plan.value,
        )
    elif event_type == "customer.subscription.deleted":
        sub = event["data"]["object"]
        await store.mark_status(
            sub["id"], LicenseStatus.CANCELED, event_type=event_type, event_payload=event_payload
        )
    elif event_type == "customer.subscription.paused":
        sub = event["data"]["object"]
        await store.mark_status(
            sub["id"], LicenseStatus.PAUSED, event_type=event_type, event_payload=event_payload
        )
    elif event_type == "invoice.payment_failed":
        invoice = event["data"]["object"]
        sub_id = invoice.get("subscription")
        if sub_id:
            await store.mark_status(
                sub_id,
                LicenseStatus.PAST_DUE,
                event_type=event_type,
                event_payload=event_payload,
            )
    elif event_type == "invoice.payment_succeeded":
        invoice = event["data"]["object"]
        sub_id = invoice.get("subscription")
        if sub_id:
            existing = await store.get_by_subscription_id(sub_id)
            # Only recover from past_due / paused. Never resurrect a canceled subscription
            # — Stripe can emit a final payment_succeeded after deletion.
            if existing and existing.status in (LicenseStatus.PAST_DUE, LicenseStatus.PAUSED):
                await store.mark_status(
                    sub_id,
                    LicenseStatus.ACTIVE,
                    event_type=event_type,
                    event_payload=event_payload,
                )
    else:
        log.info("stripe_webhook.ignored", event_id=event["id"], type=event_type)

    await store.mark_webhook_processed(event["id"], event_type)
    return {"status": "ok", "event_id": event["id"]}
