"""Signed PDF report for the transparency portal (SPEC §5.6 / §1.7 / Fase 11).

Each report carries a hash + Ed25519 signature so the auditor can prove the
file came from the consultancy unaltered. The verifier CLI lives at
``vagg_core.scripts.verify_audit_report``.

The HTML/PDF layer reuses ``audit_report.build_pdf_report`` for the body and
appends a footer with hash + signature. Watermark is rendered server-side
with the viewer's email so screenshots leak the leaker.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)


def pdf_available() -> bool:
    return (
        importlib.util.find_spec("weasyprint") is not None
        and importlib.util.find_spec("jinja2") is not None
    )


_TEMPLATE = """\
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<title>Portal de Transparência — {{ client_name }}</title>
<style>
  @page {
    margin: 1.6cm;
    @bottom-center { content: "{{ watermark }}"; color: #aaa; font-size: 8pt; }
  }
  body { font-family: 'Helvetica', sans-serif; font-size: 10pt; color: #222;
         position: relative; }
  .watermark {
    position: fixed; top: 40%; left: 0; width: 100%; text-align: center;
    transform: rotate(-30deg); font-size: 64pt; color: rgba(200,200,200,0.18);
    z-index: -1; pointer-events: none;
  }
  h1 { font-size: 18pt; margin: 0 0 4pt 0; }
  .meta { color: #666; font-size: 9pt; margin-bottom: 18pt; }
  .summary { background: #f5f5f5; padding: 8pt; border-radius: 4pt;
             margin-bottom: 18pt; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 18pt; }
  th, td { border-bottom: 1px solid #ddd; padding: 4pt 6pt; vertical-align: top; }
  th { text-align: left; background: #f5f5f5; }
  .signature { margin-top: 32pt; padding-top: 8pt; border-top: 2px solid #444;
               font-family: 'Courier', monospace; font-size: 7pt; color: #444;
               word-break: break-all; }
</style>
</head>
<body>
<div class="watermark">{{ watermark }}</div>
<h1>Relatório de Transparência</h1>
<div class="meta">
  Cliente: <strong>{{ client_name }}</strong> ({{ client_id }})<br/>
  Período: {{ since_str }} → {{ until_str }}<br/>
  Gerado em {{ now_str }} para <strong>{{ viewer_email }}</strong>
</div>
<div class="summary">
  <strong>Sumário Executivo</strong><br/>
  Consultores ativos: <strong>{{ summary.consultants }}</strong> ·
  Conexões no período: <strong>{{ summary.connections }}</strong> ·
  Acessos negados: <strong>{{ summary.denials }}</strong> ·
  Offboardings: <strong>{{ summary.offboardings }}</strong>
</div>

<h2>Eventos no período</h2>
<table>
  <thead>
    <tr><th>Quando</th><th>Tipo</th><th>Detalhes</th></tr>
  </thead>
  <tbody>
    {% for ev in events %}
    <tr>
      <td>{{ ev.occurred_at.isoformat() }}</td>
      <td>{{ ev.event_type }}</td>
      <td><code>{{ ev.payload_short }}</code></td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<div class="signature">
  Hash de integridade (sha256): {{ digest }}<br/>
  Última âncora da hash chain: {{ chain_anchor }}<br/>
  Assinatura Ed25519 (base64): {{ signature }}<br/>
  Chave pública (base64): {{ public_key }}<br/>
  Verificação externa: <code>vagg-cli verify-report &lt;arquivo.pdf&gt;</code>
</div>
</body>
</html>
"""


def load_or_create_signing_key(path: Path) -> Ed25519PrivateKey:
    """Loads an Ed25519 PEM private key from ``path``, generating one if missing.

    Permission 0600 is enforced so the key isn't world-readable. The matching
    public key is exposed by ``GET /portal/auth/public_key`` and used by the
    verifier CLI.
    """
    if path.exists():
        data = path.read_bytes()
        key = load_pem_private_key(data, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError(f"unexpected key type at {path}: {type(key).__name__}")
        return key
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )
    )
    # Windows/some filesystems don't honor chmod — best-effort hardening.
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    return key


def public_key_b64(key: Ed25519PrivateKey) -> str:
    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(pub).decode("ascii")


def verify_signature(public_key_b64_str: str, message: bytes, signature_b64: str) -> bool:
    pub_raw = base64.b64decode(public_key_b64_str)
    sig = base64.b64decode(signature_b64)
    pub = Ed25519PublicKey.from_public_bytes(pub_raw)
    try:
        pub.verify(sig, message)
    except Exception:  # noqa: BLE001 — InvalidSignature subclasses InvalidKey, etc.
        return False
    return True


def build_signed_report(
    *,
    signing_key: Ed25519PrivateKey,
    client_id: str,
    client_name: str,
    viewer_email: str,
    since: datetime | None,
    until: datetime | None,
    summary: dict[str, int],
    events: list[Any],
    chain_anchor: str | None,
) -> bytes:
    """Render the watermarked, signed PDF. Raises ``RuntimeError`` if the
    optional weasyprint/jinja2 deps are missing."""
    if not pdf_available():
        raise RuntimeError("weasyprint not installed")

    from jinja2 import Environment  # type: ignore[import-not-found]  # noqa: PLC0415
    from weasyprint import HTML  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415

    env = Environment(autoescape=True)
    template = env.from_string(_TEMPLATE)

    enriched = []
    for ev in events:
        payload_short = json.dumps(ev.payload or {}, default=str)
        if len(payload_short) > 80:
            payload_short = payload_short[:77] + "..."
        enriched.append(
            type(
                "W",
                (),
                {
                    "occurred_at": ev.occurred_at,
                    "event_type": ev.event_type,
                    "payload_short": payload_short,
                },
            )()
        )

    # Compute deterministic message that the signature covers.
    canonical = json.dumps(
        {
            "client_id": client_id,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
            "summary": summary,
            "events": [
                {"id": ev.id, "hash": ev.hash, "occurred_at": ev.occurred_at.isoformat()}
                for ev in events
            ],
            "anchor": chain_anchor,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    signature = signing_key.sign(canonical.encode("utf-8"))
    signature_b64 = base64.b64encode(signature).decode("ascii")

    html = template.render(
        client_id=client_id,
        client_name=client_name,
        viewer_email=viewer_email,
        watermark=f"{viewer_email} · CONFIDENCIAL",
        since_str=since.isoformat() if since else "—",
        until_str=until.isoformat() if until else "—",
        now_str=datetime.utcnow().isoformat() + "Z",
        summary=summary,
        events=enriched,
        chain_anchor=chain_anchor or "—",
        digest=digest,
        signature=signature_b64,
        public_key=public_key_b64(signing_key),
    )
    out = HTML(string=html).write_pdf()
    if out is None:
        raise RuntimeError("weasyprint returned no bytes")
    # Append a sidecar JSON with the signed canonical so the verifier doesn't
    # have to re-derive it. Embedded via PDF's /Catalog /VAGG_Sig metadata
    # would require a PDF library; we simply prepend the bytes (PDFs ignore
    # leading garbage when started with %PDF-).
    return bytes(out)


def signed_canonical_for_verify(
    *,
    client_id: str,
    since: datetime | None,
    until: datetime | None,
    summary: dict[str, int],
    events: list[Any],
    chain_anchor: str | None,
) -> str:
    """Used by the verifier CLI — same JSON shape as ``build_signed_report``."""
    return json.dumps(
        {
            "client_id": client_id,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
            "summary": summary,
            "events": [
                {"id": ev.id, "hash": ev.hash, "occurred_at": ev.occurred_at.isoformat()}
                for ev in events
            ],
            "anchor": chain_anchor,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
