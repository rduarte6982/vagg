"""Test helpers for building and signing fake Stripe webhook payloads."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any


def sign_stripe_payload(payload: bytes, secret: str, *, t: int | None = None) -> str:
    """Build a Stripe-Signature header for a payload using the same scheme as Stripe."""
    timestamp = t if t is not None else int(time.time())
    signed = f"{timestamp}.{payload.decode('utf-8')}".encode()
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def make_subscription_event(
    *,
    event_type: str,
    subscription_id: str,
    customer_id: str,
    price_id: str,
    status: str = "active",
    customer_email: str = "ti@consultoria.example",
    customer_name: str = "Consultoria Exemplo",
    cnpj: str | None = "12.345.678/0001-90",
    event_id: str | None = None,
) -> dict[str, Any]:
    """Build a subscription event payload with the customer object expanded inline.

    Inlining the customer avoids needing an outbound Stripe API call from the
    webhook handler during tests.
    """
    return {
        "id": event_id or f"evt_{uuid.uuid4().hex[:24]}",
        "object": "event",
        "api_version": "2024-09-30.acacia",
        "created": int(time.time()),
        "type": event_type,
        "livemode": False,
        "data": {
            "object": {
                "id": subscription_id,
                "object": "subscription",
                "status": status,
                "customer": {
                    "id": customer_id,
                    "object": "customer",
                    "email": customer_email,
                    "name": customer_name,
                    "metadata": {"cnpj": cnpj} if cnpj else {},
                },
                "items": {
                    "object": "list",
                    "data": [
                        {
                            "id": f"si_{uuid.uuid4().hex[:24]}",
                            "object": "subscription_item",
                            "price": {
                                "id": price_id,
                                "object": "price",
                                "currency": "brl",
                            },
                        }
                    ],
                },
            }
        },
    }


def make_invoice_event(
    *,
    event_type: str,
    subscription_id: str,
    event_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": event_id or f"evt_{uuid.uuid4().hex[:24]}",
        "object": "event",
        "api_version": "2024-09-30.acacia",
        "created": int(time.time()),
        "type": event_type,
        "livemode": False,
        "data": {
            "object": {
                "id": f"in_{uuid.uuid4().hex[:24]}",
                "object": "invoice",
                "subscription": subscription_id,
            }
        },
    }


def serialize(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")
