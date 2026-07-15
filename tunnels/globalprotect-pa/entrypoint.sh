#!/bin/bash
# Entrypoint do vagg-tunnel-globalprotect-pa (cliente oficial Palo Alto GP).
#
# Pré-requisitos via env:
#   TUNNEL_CONFIG_PATH — config com host=<gateway>
#   TUNNEL_USERNAME    — UPN/email do AD
#   TUNNEL_SAML_COOKIE — "portal-userauthcookie=VALUE" ou "prelogin-cookie=VALUE"
#                        (capturado via saml-portal/mitmproxy)
#
# Arquitetura PA: PanGPS daemon + globalprotect CLI (talk via local socket).
set -eu

log() { echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"src\":\"entrypoint\",\"msg\":\"$*\"}"; }

[ -e /dev/net/tun ] || { log "FATAL /dev/net/tun missing"; exit 1; }
[ -f "$TUNNEL_CONFIG_PATH" ] || { log "FATAL TUNNEL_CONFIG_PATH=$TUNNEL_CONFIG_PATH not found"; exit 1; }

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

GP_DIR=/opt/paloaltonetworks/globalprotect
GP_BIN=$GP_DIR/globalprotect   # CLI canônica
GP_DAEMON=$GP_DIR/PanGPS

log "starting PanGPS daemon (server=$SERVER user=$USER_LOGIN cookie=$COOKIE_NAME)"
# Limpa estado de execuções anteriores — PanGPS detecta PID file e recusa
# rodar achando que tem outra instância.
mkdir -p /var/run
rm -f /var/run/PanGPS.pid /tmp/PanGPS.pid \
      "$GP_DIR/PanGPS.log" "$GP_DIR/pan_gp_event.log"
cd "$GP_DIR"
# CLI faz `ps -U $USER | grep globalprotect`. ps mostra:
#   - daemon (path /opt/paloaltonetworks/globalprotect/PanGPS) → match (BAD, queremos não match)
#   - sh -c parent (cmdline tem "globalprotect") → match (esperado)
#   - grep self → match (esperado)
# Real PA install em Ubuntu daemon é "PanGPS" sem path no ps → não match.
# Pra emular: copiamos PanGPS pra /usr/local/bin/PanGPS, daemon roda a partir
# de path sem "globalprotect" → 2 matches (sh + grep) → CLI aceita.
export USER=root
export LOGNAME=root
export HOME=/root
DAEMON_RUN=/usr/local/bin/PanGPS-runtime
cp -f "$GP_DAEMON" "$DAEMON_RUN"
chmod +x "$DAEMON_RUN"
"$DAEMON_RUN" > /tmp/pangps.log 2>&1 &
PANGPS_PID=$!
echo "$PANGPS_PID" > "$TUNNEL_PID_FILE"

# espera daemon abrir o socket local
i=0
while [ $i -lt 15 ]; do
    if "$GP_BIN" --status >/dev/null 2>&1; then
        log "PanGPS ready on attempt $i"
        break
    fi
    sleep 1
    i=$((i+1))
done

if ! kill -0 "$PANGPS_PID" 2>/dev/null; then
    log "PanGPS exited; dumping logs"
    tail -50 /tmp/pangps.log 2>&1 | sed 's/^/[pangps] /'
    cat /opt/paloaltonetworks/globalprotect/PanGPS.log 2>/dev/null | tail -50 | sed 's/^/[PanGPS.log] /'
    log "sleeping 60s before container restart loop"
    sleep 60
    exit 1
fi

# CLI é a copy 'gpcli' (não match no grep globalprotect). Roda como root.
log "$GP_BIN connect --portal=$SERVER --username=$USER_LOGIN"
if [ -n "$COOKIE_VAL" ]; then
    "$GP_BIN" connect \
        --portal="$SERVER" \
        --username="$USER_LOGIN" \
        --passcode="$COOKIE_VAL" \
        > /tmp/gp-connect.log 2>&1 &
else
    "$GP_BIN" connect \
        --portal="$SERVER" \
        --username="$USER_LOGIN" \
        > /tmp/gp-connect.log 2>&1 &
fi

trap 'kill -TERM "$PANGPS_PID" 2>/dev/null || true; "$GP_BIN" disconnect 2>/dev/null || true; exit 0' TERM INT

sleep 6
log "post-connect snapshot:"
"$GP_BIN" --status 2>&1 | head -20 | sed 's/^/[gp-status] /'
log "connect log tail:"
tail -30 /tmp/gp-connect.log 2>&1 | sed 's/^/[gp-connect] /'
log "PanGPS log tail:"
tail -30 /tmp/pangps.log 2>&1 | sed 's/^/[pangps] /'

# tunnel-controller só conhece managers do shared/. PanGPS não é, então
# usamos openconnect como label externa (PA roda openconnect-equivalent
# por baixo).
exec tunnel-controller \
    --control-socket "$TUNNEL_CONTROL_SOCKET" \
    --manager        openconnect \
    --pid-file       "$TUNNEL_PID_FILE" \
    --otp-pipe       "$TUNNEL_OTP_PIPE" \
    --log-level      "$TUNNEL_LOG_LEVEL"
