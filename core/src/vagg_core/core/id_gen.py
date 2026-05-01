"""UUIDv7 helper (RFC 9562). Stdlib gains it in 3.13; we ship our own for 3.12."""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    timestamp_ms = int(time.time() * 1000)
    rand = os.urandom(10)
    ts_bytes = timestamp_ms.to_bytes(6, "big")
    byte6 = 0x70 | (rand[0] & 0x0F)
    byte7 = rand[1]
    byte8 = 0x80 | (rand[2] & 0x3F)
    payload = ts_bytes + bytes([byte6, byte7, byte8]) + rand[3:10]
    return uuid.UUID(bytes=payload)
