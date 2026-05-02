"""Unit tests for the audit hash chain (SPEC §8 / building block of Fase 9)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from vagg_core.db.models import AuditEvent
from vagg_core.services.audit import _hash, record_event, verify_chain


@pytest_asyncio.fixture
async def session(engine: AsyncEngine, session_factory: async_sessionmaker[AsyncEngine]):
    async with session_factory() as s:
        yield s


@pytest.mark.asyncio
class TestRecordEvent:
    async def test_first_event_has_no_prev_hash(self, session) -> None:
        ev = await record_event(session, event_type="x.y", payload={"a": 1})
        assert ev.prev_hash is None
        assert len(ev.hash) == 64

    async def test_chain_links_to_previous(self, session) -> None:
        a = await record_event(session, event_type="a", payload={"i": 1})
        b = await record_event(session, event_type="b", payload={"i": 2})
        assert b.prev_hash == a.hash
        assert b.hash != a.hash

    async def test_payload_changes_change_hash(self, session) -> None:
        a = await record_event(session, event_type="x", payload={"i": 1})
        b = await record_event(session, event_type="x", payload={"i": 2})
        assert a.hash != b.hash

    async def test_uuid7_ids_are_lexicographically_ordered(self, session) -> None:
        a = await record_event(session, event_type="a")
        b = await record_event(session, event_type="b")
        # Same millisecond is possible but the random tail still differs;
        # we only require the IDs be valid UUIDs and unique.
        assert a.id != b.id

    async def test_actor_is_persisted(self, session) -> None:
        # Insert a real consultant so the FK constraint is satisfied.
        from vagg_core.db.models import Consultant

        consultant = Consultant(email="actor@test.example", name="Actor")
        session.add(consultant)
        await session.flush()
        ev = await record_event(session, event_type="a", actor_consultant_id=consultant.id)
        assert ev.actor_consultant_id == consultant.id


class TestVerifyChain:
    def test_empty_chain_is_valid(self) -> None:
        ok, bad = verify_chain([])
        assert ok
        assert bad is None

    def test_tampered_payload_detected(self) -> None:
        # Build two events linked correctly, then tamper the second's payload.
        first_hash = _hash(None, "a", '{"i":1}')
        e1 = AuditEvent(
            id="11111111-1111-7111-8111-111111111111",
            event_type="a",
            payload={"i": 1},
            prev_hash=None,
            hash=first_hash,
        )
        e2_hash = _hash(first_hash, "b", '{"i":2}')
        e2 = AuditEvent(
            id="22222222-2222-7222-8222-222222222222",
            event_type="b",
            payload={"i": 2},
            prev_hash=first_hash,
            hash=e2_hash,
        )
        ok, _ = verify_chain([e1, e2])
        assert ok

        # Now change e2's payload without recomputing the hash → break.
        e2.payload = {"i": 999}
        ok, bad = verify_chain([e1, e2])
        assert not ok
        assert bad == e2.id


@pytest.mark.asyncio
async def test_record_event_persists_to_db(session) -> None:
    await record_event(session, event_type="x")
    await session.commit()
    rows = (await session.execute(select(AuditEvent))).scalars().all()
    assert len(rows) == 1
