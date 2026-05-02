"""Verifier CLI for portal-signed reports (SPEC §5.6 / Fase 11).

Usage::

    python -m vagg_core.scripts.verify_portal_report \
        --canonical canonical.json \
        --signature signature.b64 \
        --public-key pubkey.b64

The portal embeds (canonical, signature, public_key) in the PDF footer in
human-readable form. To verify offline, copy each into a file and run this
script. Exit 0 = signature valid, 1 = invalid or missing inputs.

Stdlib + cryptography only — single-file, distributable.
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a portal-signed transparency report")
    parser.add_argument("--canonical", required=True, type=Path, help="Canonical JSON file")
    parser.add_argument("--signature", required=True, type=Path, help="Signature base64 file")
    parser.add_argument("--public-key", required=True, type=Path, help="Public key base64 file")
    args = parser.parse_args(argv)

    canonical = args.canonical.read_bytes()
    signature_b64 = args.signature.read_text(encoding="utf-8").strip()
    pub_b64 = args.public_key.read_text(encoding="utf-8").strip()

    try:
        signature = base64.b64decode(signature_b64)
        pub_raw = base64.b64decode(pub_b64)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL — base64 decode error: {exc}")
        return 1

    pub = Ed25519PublicKey.from_public_bytes(pub_raw)
    try:
        pub.verify(signature, canonical)
    except Exception as exc:  # noqa: BLE001 — catches InvalidSignature and friends
        print(f"FAIL — signature invalid: {exc}")
        return 1

    print(f"OK — signature valid for {len(canonical)} bytes of canonical data")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
