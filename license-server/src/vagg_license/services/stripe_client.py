"""Thin wrapper around the Stripe SDK.

We call Stripe in two situations:
  1. Inbound: webhook signature verification (SPEC §6.7).
  2. Outbound: subscription lookup during ``/refresh`` to confirm status (SPEC §6.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import stripe

from vagg_license.core.errors import StripeIntegrationError, WebhookSignatureInvalidError
from vagg_license.db.models import LicenseStatus, Plan


@dataclass(frozen=True)
class SubscriptionView:
    """Subset of stripe.Subscription that we actually use."""

    id: str
    customer_id: str
    status: LicenseStatus
    plan: Plan
    customer_email: str
    customer_company_name: str
    cnpj: str | None


class StripeClient:
    def __init__(
        self,
        *,
        api_key: str,
        webhook_secret: str,
        webhook_tolerance_seconds: int,
        plan_by_price_id: dict[str, Plan],
    ) -> None:
        self._client = stripe.StripeClient(api_key=api_key)
        self._webhook_secret = webhook_secret
        self._webhook_tolerance = webhook_tolerance_seconds
        self._plan_by_price_id = plan_by_price_id

    # ----- Webhook signature -----

    def construct_event(self, payload: bytes, signature_header: str) -> stripe.Event:
        """Verify Stripe-Signature against payload. Raises on tampering."""
        try:
            event: stripe.Event = stripe.Webhook.construct_event(  # type: ignore[no-untyped-call]
                payload=payload,
                sig_header=signature_header,
                secret=self._webhook_secret,
                tolerance=self._webhook_tolerance,
            )
        except (stripe.SignatureVerificationError, ValueError) as exc:
            raise WebhookSignatureInvalidError(detail=str(exc)) from exc
        return event

    # ----- Subscription lookup -----

    async def fetch_subscription(self, subscription_id: str) -> SubscriptionView:
        """Synchronously call Stripe to read subscription state.

        ``async`` for caller ergonomics; the underlying SDK is sync. For Phase 1
        the call cost is bounded (one-per-refresh) and not hot-path.
        """
        try:
            sub = self._client.subscriptions.retrieve(subscription_id)
            customer = self._client.customers.retrieve(sub.customer)  # type: ignore[arg-type]
        except stripe.StripeError as exc:
            raise StripeIntegrationError(detail=str(exc)) from exc
        return self._project_subscription(sub, customer)

    # ----- Helpers -----

    def project_event_subscription(self, event: stripe.Event) -> SubscriptionView:
        """Build SubscriptionView from a webhook event payload (no extra API call).

        Falls back to a Stripe API call only when the event lacks customer expansion.
        """
        sub = event["data"]["object"]
        customer_obj = sub.get("customer")
        if isinstance(customer_obj, str):
            try:
                customer = self._client.customers.retrieve(customer_obj)
            except stripe.StripeError as exc:
                raise StripeIntegrationError(detail=str(exc)) from exc
        else:
            customer = customer_obj
        return self._project_subscription(sub, customer)

    def _project_subscription(self, sub: Any, customer: Any) -> SubscriptionView:
        # Subscription items[0].price.id maps to a plan.
        items = sub["items"]["data"] if isinstance(sub, dict) else sub.items.data
        if not items:
            raise StripeIntegrationError(detail="subscription has no items")
        first = items[0]
        price_id = first["price"]["id"] if isinstance(first, dict) else first.price.id

        plan = self._plan_by_price_id.get(price_id)
        if plan is None:
            raise StripeIntegrationError(
                detail=f"unknown stripe price_id: {price_id}",
                context={"price_id": price_id},
            )

        sub_status = sub["status"] if isinstance(sub, dict) else sub.status
        try:
            status = LicenseStatus(sub_status)
        except ValueError as exc:
            # Stripe has more states (trialing, incomplete...). Map conservatively.
            mapped = self._map_stripe_status(sub_status)
            if mapped is None:
                raise StripeIntegrationError(
                    detail=f"unsupported stripe status: {sub_status}",
                    context={"status": sub_status},
                ) from exc
            status = mapped

        cust_id = sub["customer"] if isinstance(sub, dict) else sub.customer
        if not isinstance(cust_id, str):
            cust_id = cust_id["id"] if isinstance(cust_id, dict) else cust_id.id

        email = customer["email"] if isinstance(customer, dict) else customer.email
        name = customer["name"] if isinstance(customer, dict) else customer.name
        metadata = customer["metadata"] if isinstance(customer, dict) else customer.metadata
        cnpj = (metadata or {}).get("cnpj") if metadata else None

        return SubscriptionView(
            id=sub["id"] if isinstance(sub, dict) else sub.id,
            customer_id=cust_id,
            status=status,
            plan=plan,
            customer_email=email or "",
            customer_company_name=name or "",
            cnpj=cnpj,
        )

    @staticmethod
    def _map_stripe_status(stripe_status: str) -> LicenseStatus | None:
        """Map auxiliary Stripe states onto our four-state model (SPEC §6.7)."""
        mapping = {
            "trialing": LicenseStatus.ACTIVE,
            "incomplete": LicenseStatus.PAST_DUE,
            "incomplete_expired": LicenseStatus.CANCELED,
            "unpaid": LicenseStatus.PAST_DUE,
        }
        return mapping.get(stripe_status)
