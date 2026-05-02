"""CLI tests for vagg_core.scripts.verify_audit."""

from __future__ import annotations

import json
from pathlib import Path

from vagg_core.scripts.verify_audit import _hash, main, verify_file


def _line(prev: str | None, ev_type: str, payload: dict[str, object]) -> dict[str, object]:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = _hash(prev, ev_type, canonical)
    return {
        "id": f"id-{ev_type}",
        "event_type": ev_type,
        "actor_consultant_id": None,
        "payload": payload,
        "prev_hash": prev,
        "hash": digest,
        "occurred_at": "2026-01-01T00:00:00Z",
    }


def test_verify_passes_on_clean_chain(tmp_path: Path) -> None:
    a = _line(None, "a", {"i": 1})
    b = _line(a["hash"], "b", {"i": 2})  # type: ignore[arg-type]
    p = tmp_path / "audit.ndjson"
    p.write_text(json.dumps(a) + "\n" + json.dumps(b) + "\n", encoding="utf-8")

    ok, bad, count = verify_file(p)
    assert ok
    assert bad is None
    assert count == 2


def test_verify_fails_on_tampered_payload(tmp_path: Path) -> None:
    a = _line(None, "a", {"i": 1})
    b = _line(a["hash"], "b", {"i": 2})  # type: ignore[arg-type]
    b["payload"] = {"i": 999}  # tampered without recomputing hash
    p = tmp_path / "audit.ndjson"
    p.write_text(json.dumps(a) + "\n" + json.dumps(b) + "\n", encoding="utf-8")

    ok, bad, _ = verify_file(p)
    assert not ok
    assert bad == "id-b"


def test_main_exit_codes(tmp_path: Path, capsys) -> None:
    a = _line(None, "a", {"i": 1})
    p = tmp_path / "audit.ndjson"
    p.write_text(json.dumps(a) + "\n", encoding="utf-8")

    rc = main([str(p)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "OK" in captured.out

    # Now break the chain.
    bad = _line(None, "x", {})  # second row should have prev_hash != None
    p.write_text(json.dumps(a) + "\n" + json.dumps(bad) + "\n", encoding="utf-8")
    rc = main([str(p)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "FAIL" in captured.out
