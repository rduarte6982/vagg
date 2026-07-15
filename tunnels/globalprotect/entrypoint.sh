#!/bin/bash
# Entrypoint do vagg-tunnel-globalprotect (yuezk/gpclient).
#
# Pré-requisitos via env:
#   TUNNEL_CONFIG_PATH — config com host=<gateway>
#   TUNNEL_USERNAME    — UPN/email do AD
#   TUNNEL_SAML_COOKIE — "portal-userauthcookie=VALUE" ou "prelogin-cookie=VALUE"
#                        (capturado via saml-portal/mitmproxy)
#
# gpclient docs: https://github.com/yuezk/GlobalProtect-openconnect
set -eu

log() { echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"src\":\"entrypoint\",\"msg\":\"$*\"}"; }

[ -e /dev/net/tun ] || { log "FATAL /dev/net/tun missing"; exit 1; }
[ -f "$TUNNEL_CONFIG_PATH" ] || { log "FATAL TUNNEL_CONFIG_PATH=$TUNNEL_CONFIG_PATH not found"; exit 1; }

# Endpoint do gateway
SERVER=$(grep -E '^[[:space:]]*(server|host)[[:space:]=]' "$TUNNEL_CONFIG_PATH" \
    | head -1 \
    | sed -E 's/^[[:space:]]*(server|host)[[:space:]=]+//' \
    | tr -d '"' || true)
if [ -z "$SERVER" ]; then
    SERVER=$(head -1 "$TUNNEL_CONFIG_PATH" | tr -d '\r\n[:space:]')
fi

mkdir -p "$(dirname "$TUNNEL_CONTROL_SOCKET")"
[ -p "$TUNNEL_OTP_PIPE" ] || mkfifo "$TUNNEL_OTP_PIPE"

USER_LOGIN="${TUNNEL_USERNAME:-vagg-saml}"

# Detecta tipo de cookie e extrai valor
COOKIE_VAL=""
COOKIE_NAME=""
if [ -n "${TUNNEL_SAML_COOKIE:-}" ]; then
    case "$TUNNEL_SAML_COOKIE" in
        "prelogin-cookie="*)
            COOKIE_VAL="${TUNNEL_SAML_COOKIE#prelogin-cookie=}"
            COOKIE_NAME="prelogin-cookie"
            ;;
        "portal-userauthcookie="*)
            COOKIE_VAL="${TUNNEL_SAML_COOKIE#portal-userauthcookie=}"
            COOKIE_NAME="portal-userauthcookie"
            ;;
        *)
            COOKIE_VAL="$TUNNEL_SAML_COOKIE"
            COOKIE_NAME="prelogin-cookie"
            ;;
    esac
    COOKIE_VAL="${COOKIE_VAL%\"}"
    COOKIE_VAL="${COOKIE_VAL#\"}"
fi

if [ -z "$COOKIE_VAL" ]; then
    log "FATAL TUNNEL_SAML_COOKIE not set — gpclient só faz auth SAML; cookie obrigatório"
    exit 1
fi

log "starting gpclient connect $SERVER (user=$USER_LOGIN cookie=$COOKIE_NAME len=${#COOKIE_VAL})"
log "gpclient version: $(gpclient --version 2>&1 | head -1)"

# gpclient --cookie-on-stdin espera JSON SamlAuthResult em camelCase:
#   {"success": {"username": "...", "preloginCookie": "...", "portalUserauthcookie": "..."}}
# Source: yuezk/GlobalProtect-openconnect crates/gpapi/src/auth.rs
# Construímos o JSON com python3 (já tá instalado) pra escapar o cookie
# corretamente.
COOKIE_JSON=$(CN="$COOKIE_NAME" U="$USER_LOGIN" CV="$COOKIE_VAL" python3 -c "
import json, os
field = 'preloginCookie' if os.environ['CN'] == 'prelogin-cookie' else 'portalUserauthcookie'
print(json.dumps({'success': {'username': os.environ['U'], field: os.environ['CV']}}))
")
log "auth-data JSON: $(echo "$COOKIE_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); s=d[\"success\"]; print({k: (v[:8]+\"...\" if isinstance(v,str) and len(v)>10 else v) for k,v in s.items()})')"

# gpclient connect com:
#   --as-gateway   pula portal selection, vai direto pro gateway
#   --user         UPN/email
#   --os Windows   spoof
#   --cookie-on-stdin  recebe SamlAuthResult JSON
#   --browser remote   headless (nunca tenta abrir webview)
#   -v             verbose pra debug
printf '%s\n' "$COOKIE_JSON" | gpclient connect "$SERVER" \
    --as-gateway \
    --user "$USER_LOGIN" \
    --os Windows \
    --os-version "Microsoft Windows 11 Pro , 64-bit" \
    --client-version "6.3.0-33" \
    --user-agent "PAN GlobalProtect/6.3.0-33 (Microsoft Windows 11 Pro , 64-bit)" \
    --cookie-on-stdin \
    --browser remote \
    --hip \
    -vv \
    > /tmp/gpclient.log 2>&1 &
GPCLIENT_PID=$!

# Salva PID pra controller poder matar
echo "$GPCLIENT_PID" > "$TUNNEL_PID_FILE" 2>/dev/null || true

trap 'kill -TERM "$GPCLIENT_PID" 2>/dev/null || true; gpclient disconnect 2>/dev/null || true; exit 0' TERM INT

# Aguarda 5s pra ver se subiu, loga primeiro snapshot
sleep 5
if kill -0 "$GPCLIENT_PID" 2>/dev/null; then
    log "gpclient still running after 5s (good sign)"
else
    log "gpclient exited; tail of log:"
    tail -30 /tmp/gpclient.log 2>&1 | sed 's/^/[gpclient] /'
fi

# tunnel-controller só conhece os managers do shared/. gpclient envolve
# openconnect internamente, então o manager observado externamente é
# openconnect mesmo.
exec tunnel-controller \
    --control-socket "$TUNNEL_CONTROL_SOCKET" \
    --manager        openconnect \
    --pid-file       "$TUNNEL_PID_FILE" \
    --otp-pipe       "$TUNNEL_OTP_PIPE" \
    --log-level      "$TUNNEL_LOG_LEVEL"
