#!/bin/sh
# Entrypoint do vagg-tunnel-openconnect-saml — caminho dedicado pra
# GlobalProtect com SAML SSO + cookie pré-capturado pelo saml-portal.
#
# openconnect aqui é o CUSTOM (compilado from source) com 2 patches:
#   - host-id field injection
#   - VAGG_GP_COOKIE env-driven cookie body injection
#
# Pré-requisitos via env:
#   TUNNEL_CONFIG_PATH — config com host=<gateway>
#   TUNNEL_USERNAME    — UPN/email do AD
#   TUNNEL_SAML_COOKIE — "prelogin-cookie=VALUE" ou "portal-userauthcookie=VALUE"
set -eu

log() { echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"src\":\"entrypoint\",\"msg\":\"$*\"}"; }

[ -e /dev/net/tun ] || { log "FATAL /dev/net/tun missing"; exit 1; }
[ -f "$TUNNEL_CONFIG_PATH" ] || { log "FATAL TUNNEL_CONFIG_PATH=$TUNNEL_CONFIG_PATH not found"; exit 1; }

# Snapshot das tunnel ifaces pré-existentes (network_mode=host expõe ifaces
# de outros tunnels — auto-discovery precisa filtrar).
ip -j link show 2>/dev/null > /run/tunnel-iface-snapshot.json || echo '[]' > /run/tunnel-iface-snapshot.json

# Endpoint do gateway — aceita "host=", "server=" ou linha bruta.
SERVER=$(grep -E '^[[:space:]]*(server|host)[[:space:]=]' "$TUNNEL_CONFIG_PATH" \
    | head -1 \
    | sed -E 's/^[[:space:]]*(server|host)[[:space:]=]+//' \
    | tr -d '"' || true)
if [ -z "$SERVER" ]; then
    SERVER=$(head -1 "$TUNNEL_CONFIG_PATH" | tr -d '\r\n[:space:]')
fi

# Detecta tipo de cookie e extrai valor.
COOKIE_VAL=""
USERGROUP=""
case "${TUNNEL_SAML_COOKIE:-}" in
    "prelogin-cookie="*)
        COOKIE_VAL="${TUNNEL_SAML_COOKIE#prelogin-cookie=}"
        USERGROUP="prelogin-cookie"
        ;;
    "portal-userauthcookie="*)
        COOKIE_VAL="${TUNNEL_SAML_COOKIE#portal-userauthcookie=}"
        USERGROUP="portal-userauthcookie"
        ;;
    "")
        log "FATAL TUNNEL_SAML_COOKIE não setado — use vagg/tunnel-openconnect:test pra non-SAML"
        exit 1
        ;;
    *)
        COOKIE_VAL="$TUNNEL_SAML_COOKIE"
        USERGROUP="prelogin-cookie"
        ;;
esac
COOKIE_VAL="${COOKIE_VAL%\"}"
COOKIE_VAL="${COOKIE_VAL#\"}"

mkdir -p "$(dirname "$TUNNEL_CONTROL_SOCKET")"
[ -p "$TUNNEL_OTP_PIPE" ] || mkfifo "$TUNNEL_OTP_PIPE"

iface_args=""
if [ -n "${TUNNEL_DEV:-}" ]; then
    iface_args="--interface $TUNNEL_DEV"
fi

# URL com sufixo :prelogin-cookie ou :portal-userauthcookie diz ao
# openconnect qual form field receberá o cookie.
case "$SERVER" in
    */ssl-vpn|*/global-protect) SERVER_BASE="$SERVER" ;;
    *)                          SERVER_BASE="$SERVER/ssl-vpn" ;;
esac
SERVER_URL="$SERVER_BASE:$USERGROUP"

GP_UA="PAN GlobalProtect/6.0.1-19 (Windows 10)"

log "openconnect (SAML — server=$SERVER_URL usergroup=$USERGROUP cookie_len=${#COOKIE_VAL})"

# VAGG_GP_COOKIE acionado pelo patch local em auth-globalprotect.c:
# - opt2 da prelogin form é renomeado pra vagg_unused (sem conflito)
# - prelogin-cookie=$COOKIE injetado direto no request body
# shellcheck disable=SC2086
VAGG_GP_COOKIE="$COOKIE_VAL" \
VAGG_GP_COOKIE_NAME="$USERGROUP" \
openconnect \
    --protocol=gp \
    --useragent="$GP_UA" \
    --user "${TUNNEL_USERNAME:-vagg-saml}" \
    --os=win \
    --pid-file "$TUNNEL_PID_FILE" \
    --background \
    --syslog \
    $iface_args \
    "$SERVER_URL" &
openconnect_pid=$!

trap 'kill -TERM "$openconnect_pid" 2>/dev/null || true; exit 0' TERM INT

exec tunnel-controller \
    --control-socket "$TUNNEL_CONTROL_SOCKET" \
    --manager        openconnect \
    --pid-file       "$TUNNEL_PID_FILE" \
    --otp-pipe       "$TUNNEL_OTP_PIPE" \
    --log-level      "$TUNNEL_LOG_LEVEL"
