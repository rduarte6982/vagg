"""PDF report generator (SPEC §8.4 / Fase 9).

WeasyPrint + jinja2 are *optional* dependencies — installed only in
production deploys, not in the dev/test extras. Importing this module is
cheap; ``pdf_available()`` reflects whether the optional deps are present
so the API can return 503 instead of crashing on startup.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from typing import Any  # noqa: I001 — keep import block stable

_REPORT_TEMPLATE = """\
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<title>Audit report — {{ client_id or 'all clients' }}</title>
<style>
  body { font-family: 'Helvetica', sans-serif; font-size: 10pt; color: #222; }
  h1 { font-size: 18pt; margin: 0 0 4pt 0; }
  .meta { color: #666; font-size: 9pt; margin-bottom: 24pt; }
  table { width: 100%; border-collapse: collapse; }
  th, td { border-bottom: 1px solid #ddd; padding: 4pt 6pt; vertical-align: top; }
  th { text-align: left; background: #f5f5f5; }
  td.payload { font-family: 'Courier', monospace; font-size: 8pt; word-break: break-all; }
  .footer { color: #999; font-size: 8pt; margin-top: 24pt; }
  @page { margin: 1.6cm; }
</style>
</head>
<body>
<h1>VPN Aggregator — Audit report</h1>
<div class="meta">
  Domain: <strong>{{ domain }}</strong><br/>
  Client: <strong>{{ client_id or 'all' }}</strong><br/>
  Range: {{ since_str }} → {{ until_str }}<br/>
  Events: <strong>{{ events|length }}</strong> · Generated at {{ now_str }}
</div>
<table>
  <thead>
    <tr>
      <th>occurred_at</th>
      <th>event_type</th>
      <th>actor</th>
      <th>payload</th>
    </tr>
  </thead>
  <tbody>
    {% for ev in events %}
    <tr>
      <td>{{ ev.occurred_at.isoformat() }}</td>
      <td>{{ ev.event_type }}</td>
      <td>{{ ev.actor_consultant_id if ev.actor_consultant_id is not none else '—' }}</td>
      <td class="payload">{{ ev.payload_json }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
<div class="footer">
  Hash chain anchor (last event): <code>{{ events[-1].hash if events else '—' }}</code><br/>
  Verify with <code>vagg-cli verify-report &lt;file.pdf&gt;</code>.
</div>
</body>
</html>
"""


def pdf_available() -> bool:
    """Return True iff weasyprint and jinja2 are importable."""
    return (
        importlib.util.find_spec("weasyprint") is not None
        and importlib.util.find_spec("jinja2") is not None
    )


def build_pdf_report(
    *,
    events: list[Any],
    client_id: str | None,
    since: datetime | None,
    until: datetime | None,
    domain: str,
) -> bytes:
    """Render the PDF. Raises ``RuntimeError`` if weasyprint isn't available.

    ``events`` are SQLAlchemy AuditEvent instances; only attribute access is
    used so a list of mocks works in tests too.
    """
    if not pdf_available():
        raise RuntimeError("weasyprint not installed — cannot render PDF")

    # Deferred import: importing weasyprint top-level would crash on systems
    # without its native dependencies (cairo, pango).
    from jinja2 import Environment  # type: ignore[import-not-found]  # noqa: PLC0415
    from weasyprint import HTML  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415

    env = Environment(autoescape=True)
    template = env.from_string(_REPORT_TEMPLATE)
    enriched = [
        type(
            "Wrapped",
            (),
            {
                "occurred_at": ev.occurred_at,
                "event_type": ev.event_type,
                "actor_consultant_id": ev.actor_consultant_id,
                "hash": ev.hash,
                "payload_json": json.dumps(ev.payload or {}, default=str),
            },
        )()
        for ev in events
    ]
    html = template.render(
        events=enriched,
        client_id=client_id,
        since_str=since.isoformat() if since else "—",
        until_str=until.isoformat() if until else "—",
        now_str=datetime.utcnow().isoformat() + "Z",
        domain=domain,
    )
    out = HTML(string=html).write_pdf()
    if out is None:
        raise RuntimeError("weasyprint returned no bytes")
    return bytes(out)
