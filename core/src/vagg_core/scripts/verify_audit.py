"""Standalone CLI to verify an exported audit chain (SPEC §8 / Fase 9).

Usage::

    python -m vagg_core.scripts.verify_audit audit.ndjson

Reads an NDJSON export produced by ``GET /api/v1/audit/export.ndjson``
and recomputes the hash chain. Exits 0 if intact, 1 otherwise — suitable
for cron / pipeline jobs.

Stdlib-only on purpose so it can be shipped as a single file to
auditors who don't want to install the whole vagg-core package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def _canonical(payload: dict[str, Any] | None) -> str:
    return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)


def _hash(prev_hash: str | None, event_type: str, payload_canonical: str) -> str:
    h = hashlib.sha256()
    h.update((prev_hash or "").encode("ascii"))
    h.update(b"|")
    h.update(event_type.encode("utf-8"))
    h.update(b"|")
    h.update(payload_canonical.encode("utf-8"))
    return h.hexdigest()


def verify_file(path: Path) -> tuple[bool, str | None, int]:
    """Return ``(ok, first_bad_id_or_None, count)``."""
    prev: str | None = None
    count = 0
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            ev = json.loads(raw)
            count += 1
            canonical = _canonical(ev.get("payload"))
            expected = _hash(prev, ev["event_type"], canonical)
            if expected != ev["hash"]:
                return False, ev["id"], count
            if (ev.get("prev_hash") or None) != prev:
                return False, ev["id"], count
            prev = ev["hash"]
    return True, None, count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a vagg-core audit NDJSON export")
    parser.add_argument("path", type=Path, help="Path to the .ndjson file")
    args = parser.parse_args(argv)

    ok, bad, count = verify_file(args.path)
    if ok:
        print(f"OK — {count} events, chain intact")
        return 0
    print(f"FAIL — chain broken at event {bad} (after {count} events scanned)")
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
