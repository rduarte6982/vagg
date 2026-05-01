"""ID generation helpers.

- ``uuid7()``: time-ordered UUIDv7 (RFC 9562). Stdlib gains this in 3.13; we ship
  a small implementation so the project runs on 3.12.
- ``new_license_key()``: Stripe-customer-friendly format ``VAGG-XXXX-XXXX-XXXX``.
"""

from __future__ import annotations

import os
import secrets
import time
import uuid

_LICENSE_KEY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, no 1/I/L


def uuid7() -> uuid.UUID:
    """Generate a UUIDv7 per RFC 9562 (48-bit unix-ms timestamp + 74 random bits)."""
    timestamp_ms = int(time.time() * 1000)
    rand = os.urandom(10)
    ts_bytes = timestamp_ms.to_bytes(6, "big")
    # version=7 in the high nibble of byte 6; lower 12 bits are random
    byte6 = 0x70 | (rand[0] & 0x0F)
    byte7 = rand[1]
    # variant=10 in the top 2 bits of byte 8; lower 6 bits are random
    byte8 = 0x80 | (rand[2] & 0x3F)
    payload = ts_bytes + bytes([byte6, byte7, byte8]) + rand[3:10]
    return uuid.UUID(bytes=payload)


def new_license_key() -> str:
    """Return a license key formatted as ``VAGG-XXXX-XXXX-XXXX``.

    Uses a 32-char unambiguous alphabet (no 0/O/1/I/L) so customers can
    re-type from a printed invoice without confusion.
    """
    chunks = ["".join(secrets.choice(_LICENSE_KEY_ALPHABET) for _ in range(4)) for _ in range(3)]
    return "VAGG-" + "-".join(chunks)
