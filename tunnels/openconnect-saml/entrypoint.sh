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

# Self-heal CONTÍNUO da default route do host (watchdog em background).
# openconnect/openfortivpn hijackam `default` quando conectam — ao cair,
# default some e o reconnect falha "Network is unreachable". Re-injeta
# default via ens18 com metric alta — kernel prefere ppp (metric 0)
# quando ativo; usa este fallback quando ppp some.
VAGG_GW="${VAGG_HOST_DEFAULT_GW:-192.168.68.1}"
VAGG_DEV="${VAGG_HOST_DEFAULT_DEV:-ens18}"
(
    while true; do
        if ! ip route show default | grep -q "via $VAGG_GW"; then
            ip route add default via "$VAGG_GW" dev "$VAGG_DEV" metric 1000 2>/dev/null || true
        fi
        sleep 5
    done
) &

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

# Detecta tipo de cookie e extrai valor. Formato combinado suporta
# multi-cookie (portal-userauthcookie + portal-prelogonuserauthcookie):
#   "portal-userauthcookie=A|portal-prelogonuserauthcookie=B"
# Necessário pra portal-flow (alguns PA configs exigem ambos pra autorizar
# /ssl-vpn/login.esp).
COOKIE_VAL=""
COOKIE_PRELOGON_VAL=""
USERGROUP=""
PRIMARY="${TUNNEL_SAML_COOKIE%%|*}"
case "$PRIMARY" in
    "prelogin-cookie="*)
        COOKIE_VAL="${PRIMARY#prelogin-cookie=}"
        USERGROUP="prelogin-cookie"
        ;;
    "portal-userauthcookie="*)
        COOKIE_VAL="${PRIMARY#portal-userauthcookie=}"
        USERGROUP="portal-userauthcookie"
        ;;
    "")
        log "FATAL TUNNEL_SAML_COOKIE não setado — use vagg/tunnel-openconnect:test pra non-SAML"
        exit 1
        ;;
    *)
        COOKIE_VAL="$PRIMARY"
        USERGROUP="prelogin-cookie"
        ;;
esac
COOKIE_VAL="${COOKIE_VAL%\"}"
COOKIE_VAL="${COOKIE_VAL#\"}"
# Segundo cookie (prelogon) — opcional
if [ "$TUNNEL_SAML_COOKIE" != "$PRIMARY" ]; then
    SECONDARY="${TUNNEL_SAML_COOKIE#*|}"
    case "$SECONDARY" in
        "portal-prelogonuserauthcookie="*)
            COOKIE_PRELOGON_VAL="${SECONDARY#portal-prelogonuserauthcookie=}"
            ;;
    esac
fi

mkdir -p "$(dirname "$TUNNEL_CONTROL_SOCKET")"
[ -p "$TUNNEL_OTP_PIPE" ] || mkfifo "$TUNNEL_OTP_PIPE"

iface_args=""
if [ -n "${TUNNEL_DEV:-}" ]; then
    iface_args="--interface $TUNNEL_DEV"
fi

# URL com sufixo :prelogin-cookie ou :portal-userauthcookie diz ao
# openconnect qual form field receberá o cookie.
#
# Interface (portal vs gateway/ssl-vpn) determina QUAL endpoint posta:
#   /global-protect → POST getconfig.esp (config COMPLETO: ACLs+rotas+gw list)
#   /ssl-vpn        → POST login.esp     (só autenticação, rotas mínimas)
#
# Pra paridade com GP nativo (que sempre passa pelo portal pra puxar config),
# default é /global-protect quando o cookie veio do flow SAML do portal.
# Override explícito via TUNNEL_GP_INTERFACE=ssl-vpn (legacy) ou
# TUNNEL_GP_INTERFACE=global-protect.
case "$SERVER" in
    */ssl-vpn|*/global-protect) SERVER_BASE="$SERVER" ;;
    *)
        # Default ssl-vpn (gateway flow — funciona com cookie do SAML gateway).
        # Portal flow (TUNNEL_GP_INTERFACE=global-protect) só funciona depois
        # do patch condicional no openconnect (TODO).
        case "${TUNNEL_GP_INTERFACE:-ssl-vpn}" in
            global-protect) SERVER_BASE="$SERVER/global-protect" ;;
            *)              SERVER_BASE="$SERVER/ssl-vpn" ;;
        esac
        ;;
esac
SERVER_URL="$SERVER_BASE:$USERGROUP"

GP_UA="PAN GlobalProtect/6.0.1-19 (Windows 10)"

# Portal flow lista 1+ gateways e pede seleção interativa via stdin.
# Como rodamos --background sem TTY, openconnect trava no fgets.
# --authgroup pré-seleciona. Default: hostname do portal (geralmente
# o gateway primário com mesmo nome). Override via TUNNEL_GP_GATEWAY.
GATEWAY_NAME="${TUNNEL_GP_GATEWAY:-${SERVER%%:*}}"
GATEWAY_NAME="${GATEWAY_NAME%%/*}"  # tira sufixo /ssl-vpn ou /global-protect se tiver

log "openconnect (SAML — server=$SERVER_URL usergroup=$USERGROUP cookie_len=${#COOKIE_VAL} gateway=$GATEWAY_NAME)"

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
    --authgroup="$GATEWAY_NAME" \
    --os=win \
    --csd-wrapper=/usr/local/bin/hip-report.sh \
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
