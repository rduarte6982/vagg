#!/bin/sh
# Entrypoint do vagg-tunnel-openconnect (Cisco AnyConnect / GlobalProtect).
# Contrato: SPEC §5.2 — mesmas env vars que vagg-tunnel-openvpn.
#
# Sequência:
#   1. Validar /dev/net/tun e config.
#   2. Extrair endpoint do TUNNEL_CONFIG_PATH (pode ser "host:porta" puro
#      ou um arquivo com a linha ``server <host>``).
#   3. Subir tunnel-controller em background (unix socket de controle).
#   4. Spawnar openconnect em background para que o controller fique no
#      foreground; openconnect grava PID em $TUNNEL_PID_FILE.
#
set -eu

log() { echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"src\":\"entrypoint\",\"msg\":\"$*\"}"; }

[ -e /dev/net/tun ] || { log "FATAL /dev/net/tun missing"; exit 1; }
[ -f "$TUNNEL_CONFIG_PATH" ] || { log "FATAL TUNNEL_CONFIG_PATH=$TUNNEL_CONFIG_PATH not found"; exit 1; }

# Endpoint: respeitar formato canônico ``server <host>`` ou usar o arquivo bruto.
SERVER=$(grep -E '^[[:space:]]*server[[:space:]=]' "$TUNNEL_CONFIG_PATH" \
    | head -1 \
    | sed -E 's/^[[:space:]]*server[[:space:]=]+//' \
    | tr -d '"' || true)
if [ -z "$SERVER" ]; then
    SERVER=$(head -1 "$TUNNEL_CONFIG_PATH" | tr -d '\r\n[:space:]')
fi
log "openconnect target=$SERVER"

mkdir -p "$(dirname "$TUNNEL_CONTROL_SOCKET")"

# FIFO usado pelo manager pra empurrar OTP em runtime. ``cat $TUNNEL_OTP_PIPE``
# poderia ser pipe-d no stdin do openconnect; em Fase 5 deixamos opt-in.
[ -p "$TUNNEL_OTP_PIPE" ] || mkfifo "$TUNNEL_OTP_PIPE"

iface_args=""
if [ -n "${TUNNEL_DEV:-}" ]; then
    iface_args="--interface $TUNNEL_DEV"
fi

# Lê senha do arquivo (mode 600 esperado), via --passwd-on-stdin.
password=""
if [ -f "$TUNNEL_PASSWORD_FILE" ]; then
    password=$(cat "$TUNNEL_PASSWORD_FILE")
fi

# Spawna openconnect em background; --background grava o pid no --pid-file.
log "starting openconnect (pid-file=$TUNNEL_PID_FILE)"
printf '%s\n' "$password" | openconnect \
    --user "${TUNNEL_USERNAME:-}" \
    --passwd-on-stdin \
    --pid-file "$TUNNEL_PID_FILE" \
    --background \
    --syslog \
    $iface_args \
    "$SERVER" &
openconnect_pid=$!

trap 'kill -TERM "$openconnect_pid" 2>/dev/null || true; exit 0' TERM INT

# Controller fica no foreground; SIGTERM no docker stop encerra ambos.
exec tunnel-controller \
    --control-socket "$TUNNEL_CONTROL_SOCKET" \
    --manager        openconnect \
    --pid-file       "$TUNNEL_PID_FILE" \
    --otp-pipe       "$TUNNEL_OTP_PIPE" \
    --log-level      "$TUNNEL_LOG_LEVEL"
