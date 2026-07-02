#!/usr/bin/env python3
"""HTTP server local que reproduz o callback `--saml-login` do openfortivpn.

**Por quê isto existe.** Quando o FortiGate é configurado com `host check`
habilitado (e/ou SSL-VPN web mode desabilitado), o callback do SAML em
``POST /remote/saml/login`` retorna **403 Forbidden** pra qualquer browser
puro — o gateway só seta SVPNCOOKIE pro **FortiClient nativo** depois de
verificar postura do host.

Pra contornar sem agente nativo, o FortiGate suporta um modo de redirect
que é usado pelo openfortivpn `--saml-login`:

    1. Abrir ``https://gateway/remote/saml/start?redirect=1`` no browser
    2. Browser completa login Microsoft no IdP
    3. Após sucesso, o FortiGate **substitui o 403 hostcheck** por um
       302 ``Location: http://127.0.0.1:8020/?id=<session-id>``
    4. Este servidor recebe a request, extrai ``id``, faz GET autenticado
       pra ``https://gateway/remote/saml/auth_id?id=<id>`` com User-Agent
       FortiClient, e o gateway responde com ``Set-Cookie: SVPNCOOKIE=...``
    5. SVPNCOOKIE é gravado em /share/cookie pro orchestrator pegar
    6. Browser recebe uma página "Login concluído — pode fechar" e o
       container saml-portal é terminado pelo watcher externo

Stdlib-only — o jlesage/firefox base usa Alpine sem pip extra disponível.
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ─── Config via env ────────────────────────────────────────────────────────

GATEWAY_URL = os.environ.get("VAGG_SAML_GATEWAY_URL", "").rstrip("/")
COOKIE_OUT = Path(os.environ.get("VAGG_SAML_COOKIE_OUT", "/share/cookie"))
LISTEN_HOST = os.environ.get("VAGG_CALLBACK_LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("VAGG_CALLBACK_LISTEN_PORT", "8020"))
LOG_PATH = Path(os.environ.get("VAGG_CALLBACK_LOG", "/share/callback.log"))

# User-Agent FortiClient. Alguns FortiGates exigem isso pra aceitar o
# /remote/saml/auth_id sem hostcheck. Não custa caro mandar sempre.
FORTI_UA = "FortiSSLVPNclient/7.4.0.1310"

# Quanto tempo aceitar o SVPNCOOKIE — FortiGate típico mantém sessão 8-12h.
COOKIE_TTL_HOURS = 10

# ─── Logging ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[saml-callback %(asctime)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(LOG_PATH, mode="a"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("saml-callback")


# ─── HTTPS client com SSL relaxado (gateway pode ter cert internal) ───────

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def _exchange_id_for_cookie(session_id: str) -> tuple[str | None, str]:
    """Troca o ``id`` do redirect pelo SVPNCOOKIE via /remote/saml/auth_id.

    Retorna (cookie_value, debug) — debug é uma string com diagnóstico
    pra logar ou devolver pro browser em caso de falha.
    """
    if not GATEWAY_URL:
        return None, "VAGG_SAML_GATEWAY_URL não setado"

    url = f"{GATEWAY_URL}/remote/saml/auth_id?id={urllib.parse.quote(session_id)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": FORTI_UA,
            "Accept": "*/*",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=_ssl_ctx) as resp:  # noqa: S310
            status = resp.status
            set_cookie_headers = resp.headers.get_all("Set-Cookie") or []
            body_excerpt = resp.read(2048).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        # Mesmo em erro, headers podem trazer Set-Cookie útil (depende do FW).
        status = exc.code
        try:
            set_cookie_headers = exc.headers.get_all("Set-Cookie") or []
        except Exception:
            set_cookie_headers = []
        try:
            body_excerpt = exc.read(2048).decode("utf-8", errors="replace")
        except Exception:
            body_excerpt = ""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, f"falha ao chamar auth_id: {exc}"

    log.info("auth_id status=%s set_cookies=%d", status, len(set_cookie_headers))
    # LOG TODOS os cookies pra debug — não apenas SVPNCOOKIE
    for raw in set_cookie_headers:
        m = re.match(r"\s*([A-Za-z0-9_-]+)\s*=\s*([^;]*)", raw)
        if m:
            name = m.group(1)
            val_len = len(m.group(2).strip())
            log.info("  set-cookie: %s (len=%d)", name, val_len)

    # Procura SVPNCOOKIE em qualquer header Set-Cookie do response.
    for raw in set_cookie_headers:
        m = re.match(r"\s*SVPNCOOKIE\s*=\s*([^;\s]+)", raw, re.IGNORECASE)
        if m:
            return m.group(1).strip(), f"OK status={status}"

    return (
        None,
        f"auth_id status={status} sem SVPNCOOKIE no Set-Cookie. "
        f"Headers: {set_cookie_headers}. Body[:300]={body_excerpt[:300]!r}",
    )


def _write_cookie(cookie_value: str) -> None:
    """Escreve o SVPNCOOKIE no formato consumido pelo orchestrator."""
    expires_at = datetime.now(UTC) + timedelta(hours=COOKIE_TTL_HOURS)
    payload = {
        "cookie": f"SVPNCOOKIE={cookie_value}",
        "expires_at": expires_at.isoformat(),
        "kind": "forti",
        "captured_by": "saml_callback",
    }
    COOKIE_OUT.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_OUT.write_text(json.dumps(payload), encoding="utf-8")
    log.info("wrote SVPNCOOKIE (%d chars) → %s", len(cookie_value), COOKIE_OUT)


# ─── HTML responses ───────────────────────────────────────────────────────

_OK_HTML = (
    "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
    "<title>VAGG · login concluído</title>"
    "<style>body{font-family:system-ui,sans-serif;background:#0a1530;color:#e8eaf6;"
    "display:flex;align-items:center;justify-content:center;height:100vh;margin:0}"
    "div{text-align:center;padding:2rem;border:1px solid #2a3a5c;border-radius:8px;"
    "background:#0f1d3a}h1{margin:0 0 .5rem;color:#d4af37}p{margin:.25rem 0}</style>"
    "</head><body><div><h1>✓ Login concluído</h1>"
    "<p>Cookie de sessão capturado.</p>"
    "<p>Você pode fechar esta janela — o túnel vai subir automaticamente.</p>"
    "</div></body></html>"
)

def _render_error_html(debug: str) -> str:
    """Renderiza a página de erro. Usa concat em vez de .format() pra não
    conflitar com chaves `{}` literais do CSS embutido."""
    import html as _html
    return (
        "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
        "<title>VAGG · falha</title>"
        "<style>body{font-family:system-ui,sans-serif;background:#0a1530;color:#e8eaf6;"
        "display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:2rem}"
        "div{max-width:640px;padding:2rem;border:1px solid #5c2a2a;border-radius:8px;"
        "background:#1d0f0f}h1{margin:0 0 .5rem;color:#ff8a80}"
        "pre{overflow:auto;background:#0a0606;padding:1rem;border-radius:4px;color:#ccc;"
        "font-size:12px;white-space:pre-wrap;word-break:break-all}</style>"
        "</head><body><div><h1>✗ Falha no callback SAML</h1>"
        "<p>O gateway respondeu mas não retornou SVPNCOOKIE válido. Diagnóstico:</p>"
        "<pre>" + _html.escape(debug) + "</pre>"
        "</div></body></html>"
    )


# ─── Server ───────────────────────────────────────────────────────────────


class _CallbackHandler(BaseHTTPRequestHandler):
    # silencia logging duplo do BaseHTTPServer (já temos nosso log)
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        log.info("http %s", format % args)

    def _send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/healthz", "/health"):
            self._send(200, "ok", content_type="text/plain")
            return

        qs = urllib.parse.parse_qs(parsed.query)
        session_id = (qs.get("id") or [""])[0].strip()
        if not session_id:
            log.warning("request sem ?id= — path=%s qs=%s", parsed.path, parsed.query)
            self._send(
                400,
                _render_error_html(
                    f"sem parâmetro ?id= na URL. Path: {parsed.path}, query: {parsed.query}"
                ),
            )
            return

        # Não loga o id em texto cheio — pode ser sensível.
        log.info("received callback ?id=<%d chars>", len(session_id))
        cookie_value, debug = _exchange_id_for_cookie(session_id)
        if cookie_value is None:
            log.error("exchange falhou: %s", debug)
            self._send(502, _render_error_html(debug))
            return

        try:
            _write_cookie(cookie_value)
        except OSError as exc:
            log.error("falha ao escrever cookie: %s", exc)
            self._send(500, _render_error_html(f"falha ao gravar /share/cookie: {exc}"))
            return

        self._send(200, _OK_HTML)


def main() -> int:
    if not GATEWAY_URL:
        log.error("VAGG_SAML_GATEWAY_URL não setado — abortando")
        return 2
    log.info(
        "starting callback server on %s:%d gateway=%s cookie_out=%s",
        LISTEN_HOST,
        LISTEN_PORT,
        GATEWAY_URL,
        COOKIE_OUT,
    )
    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), _CallbackHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("interrupted")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
