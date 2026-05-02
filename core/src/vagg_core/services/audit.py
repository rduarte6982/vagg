"""Append-only audit logger with hash chain (SPEC §8 / Fase 9 building block).

Each event hashes ``prev.hash || canonical(payload)`` so any tampering breaks
the chain. UUIDv7 (timestamp-prefixed) is used as the event id so insertion
order is preserved even if the wall clock skews.

The Phase 8 RBAC hooks call ``record_event`` from inside the same async
session that mutated the policy table, so the audit row commits with the
business change. Phase 9 adds export endpoints and PDF generation on top.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vagg_core.db.models import AuditEvent

_HASH_HEX_LEN = 64  # sha256


def _canonical(payload: dict[str, Any] | None) -> str:
    """JSON with sorted keys + no whitespace — stable across Python runs."""
    return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)


def _hash(prev_hash: str | None, event_type: str, payload_canonical: str) -> str:
    h = hashlib.sha256()
    h.update((prev_hash or "").encode("ascii"))
    h.update(b"|")
    h.update(event_type.encode("utf-8"))
    h.update(b"|")
    h.update(payload_canonical.encode("utf-8"))
    return h.hexdigest()


def _uuid7() -> str:
    """Stdlib backfill of UUIDv7 (Python 3.12 doesn't expose it as a method).

    Format: 48 bits of unix-ms + 4 version + 12 random + 2 variant + 62 random.
    Strict-mode UUID parsers (Postgres etc.) accept it as a regular UUID.
    """
    ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    int128 = (ts_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=int128))


async def _last_hash(session: AsyncSession) -> str | None:
    stmt = select(AuditEvent.hash).order_by(AuditEvent.occurred_at.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def record_event(
    session: AsyncSession,
    *,
    event_type: str,
    actor_consultant_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append a row to ``audit_events`` linked to the previous row's hash.

    The caller's transaction must commit for the row to land. Tests assert
    on the returned object after a session.flush() / commit.
    """
    canonical = _canonical(payload)
    prev = await _last_hash(session)
    event_id = _uuid7()
    digest = _hash(prev, event_type, canonical)
    row = AuditEvent(
        id=event_id,
        event_type=event_type,
        actor_consultant_id=actor_consultant_id,
        payload=payload,
        prev_hash=prev,
        hash=digest,
    )
    session.add(row)
    await session.flush()
    return row


def verify_chain(events: list[AuditEvent]) -> tuple[bool, str | None]:
    """Recompute hashes from oldest → newest; return (ok, first-bad-id).

    ``events`` MUST be sorted by ``occurred_at`` ascending. Used by the
    export script (Fase 9) and by tests.
    """
    prev: str | None = None
    for ev in events:
        canonical = _canonical(ev.payload)
        expected = _hash(prev, ev.event_type, canonical)
        if expected != ev.hash:
            return False, ev.id
        if ev.prev_hash != prev:
            return False, ev.id
        prev = ev.hash
    return True, None
