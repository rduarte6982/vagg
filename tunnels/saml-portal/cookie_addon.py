"""mitmproxy addon — captura cookies SAML conforme passam pelo proxy.

Estratégia: acumula cookies vistos durante toda a sessão e quando o último
request da fase SAML termina, escolhe o melhor pra openconnect:

  - portal-userauthcookie (PREFERIDO): sessão persistente do GP, válida
    por horas. Setada APÓS a troca prelogin-cookie → session.

  - prelogin-cookie (FALLBACK): token one-time-use que o gateway seta no
    response do /SAML20/SP/AssertionConsumerService. Se o Firefox já
    consumiu (por seguir um redirect implícito), vira inválido.

  - <prelogin-cookie> em XML body (legacy): formato antigo, raro.

Quando captura, escreve JSON em VAGG_COOKIE_OUT:
    {"cookie": "name=value", "expires_at": "ISO8601", "kind": "<gp|cisco|...>"}

O entrypoint do tunnel-openconnect parseia "name=value" pra escolher o
--usergroup correto (prelogin-cookie ou portal-userauthcookie).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mitmproxy import ctx, http

# Mitmproxy 11+ deprecou ctx.log — logs agora vão pelo logging stdlib.
# Configuramos o logger pra ir pro stdout (capturado pelo /share/mitm.log).
log = logging.getLogger("vagg-saml")
log.setLevel(logging.INFO)
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S"))
    log.addHandler(_handler)
    log.propagate = False

# Padrões em body XML (legacy / fallback).
GP_BODY_PATTERNS = [
    ("prelogin-cookie", re.compile(r"<prelogin-cookie>([^<]+)</prelogin-cookie>")),
    (
        "portal-userauthcookie",
        re.compile(r"<portal-userauthcookie>([^<]+)</portal-userauthcookie>"),
    ),
]

# Layout posicional do JNLP que o /ssl-vpn/login.esp retorna ao GP client.
# Verificado empiricamente com MRV (3 logins, valores estáveis):
#   arg[0]: "" (vazio)
#   arg[1]: authcookie - 32 chars hex MD5 (per-session)
#   arg[2]: portal-prelogonuserauthcookie - 40 chars hex SHA1 (estático)
#   arg[3]: auth method name (e.g. "GlobalProtectPW-N")
#   arg[4]: username (email/UPN)
#   arg[5]: portal name (e.g. "AP-2FA-AZURE")
#   arg[6]: vsys (e.g. "vsys1")
#   arg[7]: domain (e.g. "(empty_domain)")
JNLP_ARG_RE = re.compile(r"<argument>([^<]*)</argument>")
JNLP_AUTHCOOKIE_INDEX = 1
JNLP_PRELOGON_INDEX = 2

# Nomes de cookies do GP em ordem de PREFERÊNCIA (melhor primeiro):
# - portal-userauthcookie é a sessão persistente, válida por horas, e é o
#   que o openconnect quer pra subir o tunel sem fazer prelogin de novo.
# - prelogin-cookie é one-time, usado pra trocar por portal-userauthcookie.
#   Se Firefox já consumiu (por seguir redirect implícito após SAML), vira
#   inválido — por isso só usamos como fallback se portal-userauthcookie
#   nunca apareceu.
# - portalusersso é variante legacy.
GP_PREFERENCE_ORDER = ("portal-userauthcookie", "prelogin-cookie", "portalusersso")

# Cookies HTTP de outros gateways VPN.
OTHER_VPN_COOKIE_NAMES = ("webvpn", "SVPNCOOKIE", "VPNSESSION", "MSISAuthenticated")

# FortiGate (openfortivpn): SVPNCOOKIE é o cookie de sessão setado pelo
# gateway depois do SAML callback bem-sucedido. Diferente do GP, NÃO há
# prelogin-cookie — o gateway retorna direto SVPNCOOKIE no Set-Cookie do
# response final do /remote/saml/login ou /remote/login.
FORTI_COOKIE_NAMES = ("SVPNCOOKIE",)

# Sufixos no path da request que indicam que estamos voltando do SAML
# (gateway processou a SAMLResponse e seta o cookie de sessão).
SAML_RETURN_PATHS = (
    "/SAML20/SP/ACS",
    "/SAML20/SP/AssertionConsumerService",
    "/global-protect/getconfig.esp",
    "/ssl-vpn/getconfig.esp",
)


def load(loader: object) -> None:
    loader.add_option(
        name="vagg_cookie_out",
        typespec=str,
        default="/share/cookie",
        help="Caminho onde escrever o cookie capturado",
    )
    loader.add_option(
        name="vagg_gateway_host",
        typespec=str,
        default="",
        help="Host do gateway VPN — só inspeciona respostas dele",
    )
    loader.add_option(
        name="vagg_kind",
        typespec=str,
        default="gp",
        help="Tipo de gateway: 'gp' (GlobalProtect) ou 'forti' (FortiGate SVPNCOOKIE)",
    )


# Cookies acumulados durante a sessão. Resetado a cada execução da addon.
# Não precisamos persistir — o container saml-portal vive segundos e quando
# captura o cookie escreve em /share/cookie e o orchestrator deleta.
_seen_cookies: dict[str, str] = {}


def _maybe_write_forti_cookie() -> None:
    """Escreve SVPNCOOKIE (FortiGate) no arquivo de saída assim que vermos.
    Diferente do GP que tem hierarquia de cookies, o forti usa só SVPNCOOKIE
    e ele é estável durante toda a sessão — primeira vez que aparecer já
    serve. Idempotente: não sobrescreve se já houver SVPNCOOKIE no arquivo.
    """
    if "SVPNCOOKIE" not in _seen_cookies:
        return
    out_path = Path(ctx.options.vagg_cookie_out)
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            if existing.get("cookie", "").startswith("SVPNCOOKIE="):
                return  # já temos
        except (OSError, json.JSONDecodeError):
            pass
    expires_at = datetime.now(UTC) + timedelta(hours=10)  # FortiGate session ~12h
    cookie_value = _seen_cookies["SVPNCOOKIE"]
    payload = {
        "cookie": f"SVPNCOOKIE={cookie_value}",
        "expires_at": expires_at.isoformat(),
        "kind": "forti",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload), encoding="utf-8")
    log.info(f"[vagg] captured forti cookie SVPNCOOKIE=({len(cookie_value)} chars) → {out_path}")


def _maybe_write_best_cookie(kind_hint: str = "gp") -> None:
    """Escolhe o melhor cookie acumulado e escreve. Idempotente — se já
    houver um portal-userauthcookie no arquivo e chega um prelogin-cookie
    depois, ignora (o portal-userauthcookie é melhor)."""
    out_path = Path(ctx.options.vagg_cookie_out)

    # Escolhe o cookie de maior preferência que tenhamos visto
    chosen = None
    for name in GP_PREFERENCE_ORDER:
        if name in _seen_cookies:
            chosen = name
            break
    if chosen is None:
        return

    # Se já existe arquivo e ele tem cookie de maior preferência que o
    # novo candidato, mantem o existente. Caso contrário, sobrescreve
    # (caso de upgrade prelogin-cookie → portal-userauthcookie).
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            existing_name = existing.get("cookie", "").split("=", 1)[0]
            if existing_name in GP_PREFERENCE_ORDER:
                existing_rank = GP_PREFERENCE_ORDER.index(existing_name)
                new_rank = GP_PREFERENCE_ORDER.index(chosen)
                if existing_rank <= new_rank:
                    return  # existente é igual ou melhor
        except (OSError, json.JSONDecodeError):
            pass  # arquivo corrompido — sobrescreve

    expires_at = datetime.now(UTC) + timedelta(hours=10)  # AAD default
    payload = {
        "cookie": f"{chosen}={_seen_cookies[chosen]}",
        "expires_at": expires_at.isoformat(),
        "kind": kind_hint,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload), encoding="utf-8")
    log.info(
        f"[vagg] captured {kind_hint} cookie {chosen}=({len(_seen_cookies[chosen])} chars) → {out_path}"
    )


def _extract_saml_username(body: str) -> str:
    """Extrai o user do body do SAML callback. MRV (e GP em geral) embute
    como <saml-username>email@dominio</saml-username> dentro de comentário
    HTML ou XML wrapper. Sem esse user, getconfig.esp não emite cookies."""
    if not body:
        return ""
    m = re.search(r"<saml-username>\s*([^<\s]+)\s*</saml-username>", body)
    if m:
        return m.group(1).strip()
    # Fallback genérico — algumas variantes usam saml:NameID ou similar
    m = re.search(
        r"(?:saml-username|saml:nameid|name-id)[\"'\s:=>]+([\w.+-]+@[\w.-]+)",
        body,
        re.IGNORECASE,
    )
    return m.group(1).strip() if m else ""


def _scan_set_cookie(headers: list[str]) -> dict[str, str]:
    """Devolve dict {name: value} de TODOS os cookies de interesse vistos
    em Set-Cookie do gateway. Não lança."""
    found: dict[str, str] = {}
    candidates = GP_PREFERENCE_ORDER + OTHER_VPN_COOKIE_NAMES
    for sc in headers:
        for name in candidates:
            m = re.match(
                rf"\s*{re.escape(name)}\s*=\s*([^;\s]+)",
                sc,
                re.IGNORECASE,
            )
            if m:
                found[name] = m.group(1).strip()
                break  # cookie casa um nome só
    return found


# Cookie jar HTTP global pra preservar SESSID entre calls do gateway.
# Real GP client faz login.esp → recebe SESSID + authcookie → getconfig.esp
# precisa do MESMO SESSID. Sem isso o gateway rejeita getconfig.esp.
import http.cookiejar as _cookiejar
import ssl as _ssl
import urllib.error
import urllib.parse
import urllib.request

_http_cookies = _cookiejar.CookieJar()
_ssl_ctx = _ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = _ssl.CERT_NONE
_http_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(_http_cookies),
    urllib.request.HTTPSHandler(context=_ssl_ctx),
)


def _post_with_cookie(url: str, params: dict[str, str]) -> tuple[int, dict, bytes] | None:
    """Faz POST com User-Agent PAN GP, preservando SESSID entre calls.
    Retorna (status, headers_dict, body) ou None."""
    try:
        body = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "User-Agent": "PAN GlobalProtect/6.0.1-19 (Windows 10)",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "*/*",
            },
            method="POST",
        )
        with _http_opener.open(req, timeout=10) as r:
            return (
                r.status,
                {k: r.headers.get_all(k) for k in {"Set-Cookie", "Content-Type", "Location"}},
                r.read()[:3000],
            )
    except urllib.error.HTTPError as e:
        try:
            body_bytes = e.read()[:3000]
        except Exception:
            body_bytes = b""
        return (e.code, dict(e.headers), body_bytes)
    except Exception as exc:
        log.warning(f"[vagg] POST {url} failed: {exc}")
        return None


def _trigger_login_exchange(gateway_host: str, prelogin_cookie: str, user_hint: str = "") -> None:
    """Tenta múltiplos endpoints com o prelogin-cookie pra forçar o gateway
    a emitir portal-userauthcookie ou retornar gateway list utilizável.
    Ignora falhas — se nenhum funcionar, o cookie original ainda fica como
    fallback.

    Endpoints testados (em ordem):
      1. /global-protect/getconfig.esp (portal — emite portal-userauthcookie)
      2. /ssl-vpn/getconfig.esp (gateway — também pode aceitar prelogin-cookie)
      3. /ssl-vpn/login.esp (gateway login)
    """
    base_params = {
        "prelogin-cookie": prelogin_cookie,
        "user": user_hint or "",
        "clientos": "Windows",
        "clientVer": "4100",
        "os-version": "Microsoft Windows 10 Pro , 64-bit",
        "computer": "VAGG-SAML-PORTAL",
        "host-id": "vagg-saml-portal-uuid",
        "prot": "https:",
        "server": gateway_host,
        "inputStr": "",
        "jnlpReady": "jnlpReady",
        "ok": "Login",
        "direct": "yes",
        "ipv6-support": "yes",
    }
    # ORDEM CANÔNICA do GP client real (https://www.infradead.org/openconnect/globalprotect.html):
    # 1) /global-protect/getconfig.esp (PORTAL) com prelogin-cookie + user
    #    → retorna portal config XML com <portal-userauthcookie> e
    #      <portal-prelogonuserauthcookie>. Sem esse passo, o gateway
    #      getconfig.esp do passo 3 falha porque não tem prelogon cookie.
    # 2) /ssl-vpn/login.esp (GATEWAY) com portal-userauthcookie + user
    #    → retorna JNLP com authcookie per-gateway (arg[1]).
    # 3) /ssl-vpn/getconfig.esp (GATEWAY) com authcookie + portal-prelogon
    #    → retorna tunnel config XML (rotas, DNS, MTU, etc).
    endpoints = [
        f"https://{gateway_host}/global-protect/getconfig.esp",
        f"https://{gateway_host}/ssl-vpn/login.esp",
        f"https://{gateway_host}/ssl-vpn/getconfig.esp",
    ]
    captured_authcookie: str | None = None
    captured_portal_userauth: str | None = None
    captured_portal_prelogon: str | None = None
    captured_jnlp_args: list[str] = []
    for url in endpoints:
        # Cada endpoint tem combinação de params específica baseada no
        # estado acumulado dos calls anteriores. Real GP client faz isso.
        params = dict(base_params)
        if "global-protect/getconfig.esp" in url:
            # Step 1 — portal getconfig com prelogin-cookie + user
            params.pop("ok", None)
            params.pop("jnlpReady", None)
        elif "/ssl-vpn/login.esp" in url:
            # Step 2 — gateway login. Se já temos portal-userauthcookie do
            # step 1, usa ele. Senão usa prelogin-cookie como fallback.
            if captured_portal_userauth:
                params.pop("prelogin-cookie", None)
                params["portal-userauthcookie"] = captured_portal_userauth
                if captured_portal_prelogon:
                    params["portal-prelogonuserauthcookie"] = captured_portal_prelogon
        elif "/ssl-vpn/getconfig.esp" in url:
            # Step 3 — gateway getconfig com authcookie do JNLP do login.esp.
            params.pop("prelogin-cookie", None)
            params.pop("ok", None)
            params.pop("jnlpReady", None)
            if captured_authcookie:
                params["authcookie"] = captured_authcookie
            if captured_portal_userauth:
                params["portal-userauthcookie"] = captured_portal_userauth
            if captured_portal_prelogon:
                params["portal-prelogonuserauthcookie"] = captured_portal_prelogon
            # Campos extraídos do JNLP que real GP client re-envia:
            #   arg[3] = portal/gw-name (ex: GlobalProtectPW-N)
            #   arg[4] = user (já temos)
            #   arg[5] = auth source (ex: AP-2FA-AZURE)
            #   arg[6] = vsys (ex: vsys1)
            #   arg[7] = domain (ex: (empty_domain))
            if len(captured_jnlp_args) > 7:
                params["portal"] = captured_jnlp_args[3] or ""
                params["authentication-source"] = captured_jnlp_args[5] or ""
                params["vsys"] = captured_jnlp_args[6] or ""
                domain_val = captured_jnlp_args[7] or ""
                if domain_val:
                    params["domain"] = domain_val
                params["internal"] = "no"
        log.info(f"[vagg] follow-up POST {url} user={user_hint or '(empty)'}")
        result = _post_with_cookie(url, params)
        if result is None:
            continue
        status, headers, body_bytes = result
        body_excerpt = body_bytes.decode("utf-8", errors="replace")[:600]
        log.info(
            f"[vagg] follow-up {url} → status={status} "
            f"set-cookie={headers.get('Set-Cookie')} body={body_excerpt!r}"
        )
        # Verifica Set-Cookie do response
        sc_headers = headers.get("Set-Cookie") or []
        if isinstance(sc_headers, str):
            sc_headers = [sc_headers]
        new_cookies = _scan_set_cookie(sc_headers)
        # Verifica também body XML (formato legacy <prelogin-cookie>...)
        for cookie_name, pat in GP_BODY_PATTERNS:
            m = pat.search(body_excerpt)
            if m:
                new_cookies[cookie_name] = m.group(1).strip()

        # Step 1 (portal getconfig) retorna portal config XML que pode ter:
        #   <portal-userauthcookie>...</portal-userauthcookie>
        #   <portal-prelogonuserauthcookie>...</portal-prelogonuserauthcookie>
        # Captura ambos pra usar nos próximos steps.
        if "global-protect/getconfig.esp" in url and status == 200:
            m = re.search(
                r"<portal-userauthcookie>([^<]+)</portal-userauthcookie>",
                body_excerpt,
            )
            if m:
                captured_portal_userauth = m.group(1).strip()
                new_cookies["portal-userauthcookie"] = captured_portal_userauth
                log.info(
                    f"[vagg] portal getconfig → portal-userauthcookie "
                    f"({len(captured_portal_userauth)} chars)"
                )
            m = re.search(
                r"<portal-prelogonuserauthcookie>([^<]+)</portal-prelogonuserauthcookie>",
                body_excerpt,
            )
            if m:
                captured_portal_prelogon = m.group(1).strip()
                log.info(
                    f"[vagg] portal getconfig → portal-prelogonuserauthcookie "
                    f"({len(captured_portal_prelogon)} chars)"
                )
        # JNLP response do /ssl-vpn/login.esp — formato proprietário do GP.
        # arg[1] = authcookie (= portal-userauthcookie pro openconnect).
        # arg[3] = portal-prelogonuserauthcookie (alternativa).
        if status == 200 and "<jnlp>" in body_excerpt:
            args = JNLP_ARG_RE.findall(body_excerpt)
            log.info(f"[vagg] JNLP response with {len(args)} arguments")
            captured_jnlp_args = args  # disponível pra próximos endpoints
            if len(args) > JNLP_AUTHCOOKIE_INDEX:
                authcookie = args[JNLP_AUTHCOOKIE_INDEX].strip()
                if authcookie:
                    new_cookies["portal-userauthcookie"] = authcookie
                    captured_authcookie = authcookie  # usado nos próximos endpoints
                    log.info(
                        f"[vagg] JNLP arg[{JNLP_AUTHCOOKIE_INDEX}] = "
                        f"portal-userauthcookie ({len(authcookie)} chars)"
                    )
            if len(args) > JNLP_PRELOGON_INDEX:
                prelogon = args[JNLP_PRELOGON_INDEX].strip()
                if re.match(r"^[a-f0-9]{16,}$", prelogon, re.IGNORECASE):
                    _seen_cookies["portal-prelogonuserauthcookie"] = prelogon
                    captured_portal_prelogon = prelogon
                    log.info(
                        f"[vagg] JNLP arg[{JNLP_PRELOGON_INDEX}] = "
                        f"portal-prelogonuserauthcookie ({len(prelogon)} chars)"
                    )

        if new_cookies:
            for name, value in new_cookies.items():
                _seen_cookies[name] = value
            log.info(f"[vagg] follow-up captured {list(new_cookies.keys())} from {url}")
            _maybe_write_best_cookie(kind_hint="gp")
        # Se getconfig.esp retornou tunnel config XML real (não erro),
        # dumpa o body inteiro pra /share/tunnel-config.xml — útil pra
        # validar que o auth funcionou E como base pra um openconnect
        # alternativo / cliente custom.
        if (
            "getconfig.esp" in url
            and status == 200
            and (b"<response" in body_bytes or b"<getconfig" in body_bytes)
            and b"errors getting" not in body_bytes
        ):
            try:
                tunnel_path = Path(ctx.options.vagg_cookie_out).parent / "tunnel-config.xml"
                tunnel_path.write_bytes(body_bytes)
                log.info(f"[vagg] dumped tunnel config XML to {tunnel_path}")
            except Exception as exc:
                log.warning(f"[vagg] failed to write tunnel-config.xml: {exc}")
    log.info("[vagg] follow-up sequence complete")


# DESABILITADO: openconnect agora envia host-id graças ao patch local em
# auth-globalprotect.c. Queremos preservar prelogin-cookie pro openconnect
# consumir em /ssl-vpn/login.esp (sem ser invalidado pelo nosso follow-up).
# Setando True desde o início, response() pula chamada a _trigger_login_exchange.
_followup_done = True


def response(flow: http.HTTPFlow) -> None:
    global _followup_done
    target_host = (ctx.options.vagg_gateway_host or "").lower()
    flow_host = flow.request.pretty_host.lower()

    # Só inspeciona o gateway VPN — login.microsoftonline.com não importa
    if target_host and target_host not in flow_host:
        return

    set_cookie_headers = flow.response.headers.get_all("Set-Cookie")
    body = flow.response.get_text(strict=False) or ""
    path = flow.request.path or ""

    # Acumula TODOS os cookies vistos no caminho. Quando portal-userauthcookie
    # finalmente aparecer (após Firefox seguir o flow completo), upgradamos.
    new_cookies = _scan_set_cookie(set_cookie_headers)
    if new_cookies:
        for name, value in new_cookies.items():
            _seen_cookies[name] = value
        log.info(
            f"[vagg] saw cookies {list(new_cookies.keys())} at {flow_host}{path}"
        )
        # Roteamento por kind: forti tem fluxo simples (só SVPNCOOKIE),
        # GP tem hierarquia complexa (prelogin → portal-userauthcookie).
        if (ctx.options.vagg_kind or "gp").lower() == "forti":
            _maybe_write_forti_cookie()
            return
        _maybe_write_best_cookie(kind_hint="gp")

        # Se vimos prelogin-cookie mas ainda não temos portal-userauthcookie,
        # dispara request /ssl-vpn/login.esp pra forçar a troca. Firefox
        # não faz isso sozinho — a página "Login Successful!" é o fim do
        # view dele. Sem essa troca, o prelogin-cookie pode ser one-time
        # e ficar inválido quando openconnect for usar.
        if (
            not _followup_done
            and "prelogin-cookie" in _seen_cookies
            and "portal-userauthcookie" not in _seen_cookies
            and path.startswith(("/SAML20/SP/", "/global-protect/", "/ssl-vpn/"))
        ):
            _followup_done = True
            # Tenta extrair user hint do body — algumas respostas de
            # SAML success têm o user nele.
            user_hint = ""
            user_match = re.search(
                r'(?:saml-username|user|email)["\s:=>]+([\w@.-]+)',
                body,
                re.IGNORECASE,
            )
            if user_match:
                user_hint = user_match.group(1)
            _trigger_login_exchange(
                gateway_host=target_host or flow_host,
                prelogin_cookie=_seen_cookies["prelogin-cookie"],
                user_hint=user_hint,
            )
        return

    # Fallback: cookies em XML body (formato MRV usa esse — embute
    # <prelogin-cookie>...</prelogin-cookie> e/ou
    # <portal-userauthcookie>...</portal-userauthcookie> dentro da HTML
    # "Login Successful!" no /SAML20/SP/ACS).
    body_hits: list[str] = []
    for cookie_name, pat in GP_BODY_PATTERNS:
        m = pat.search(body)
        if m:
            _seen_cookies[cookie_name] = m.group(1).strip()
            body_hits.append(cookie_name)

    if body_hits:
        log.info(f"[vagg] body match {body_hits} at {flow_host}{path}")
        # Diagnóstico extra: dumpa primeiros 800 chars do body em endpoints
        # SAML — útil pra eu ver o formato exato que o gateway usa.
        if any(path.endswith(p) or p in path for p in SAML_RETURN_PATHS):
            log.info(
                f"[vagg] SAML body dump at {flow_host}{path}: {body[:800]!r}"
            )
        _maybe_write_best_cookie(kind_hint="gp")

        # Mesmo trigger de follow-up que no path de Set-Cookie.
        if (
            not _followup_done
            and "prelogin-cookie" in _seen_cookies
            and "portal-userauthcookie" not in _seen_cookies
        ):
            _followup_done = True
            user_hint = _extract_saml_username(body)
            _trigger_login_exchange(
                gateway_host=target_host or flow_host,
                prelogin_cookie=_seen_cookies["prelogin-cookie"],
                user_hint=user_hint,
            )
        return

    # Diagnóstico: passou por endpoint relevante e não capturou nada.
    if any(path.endswith(p) or p in path for p in SAML_RETURN_PATHS):
        cookie_names_in_response = [
            re.match(r"\s*([^=]+)=", sc).group(1).strip()
            for sc in set_cookie_headers
            if "=" in sc
        ]
        log.warning(
            f"[vagg] SAML return at {flow_host}{path} status={flow.response.status_code} "
            f"but no known cookie matched. Set-Cookie names: {cookie_names_in_response}. "
            f"Body excerpt: {body[:400]!r}"
        )
