#!/bin/sh
# Entrypoint do vagg-tunnel-openvpn (SPEC §5.2).
#
# Sequência:
#   1. Validar que /dev/net/tun e o config existem.
#   2. Montar arquivo de auth se houver credenciais (sem deixar em RAM aberta).
#   3. Subir tunnel-controller em background (unix socket de controle).
#   4. exec openvpn no foreground — PID 1 → recebe sinais do docker stop.
#
set -eu

log() { echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"src\":\"entrypoint\",\"msg\":\"$*\"}"; }

[ -e /dev/net/tun ] || { log "FATAL /dev/net/tun missing — run with --device=/dev/net/tun"; exit 1; }
[ -f "$TUNNEL_CONFIG_PATH" ] || { log "FATAL TUNNEL_CONFIG_PATH=$TUNNEL_CONFIG_PATH not found"; exit 1; }

# Snapshot das tunnel ifaces pré-existentes (network_mode=host expõe ifaces
# de outros tunnels — auto-discovery precisa filtrar).
ip -j link show 2>/dev/null > /run/tunnel-iface-snapshot.json || echo '[]' > /run/tunnel-iface-snapshot.json

mkdir -p "$(dirname "$TUNNEL_CONTROL_SOCKET")"

# Build auth-user-pass file when credentials are mounted as files.
auth_args=""
if [ -f "$TUNNEL_PASSWORD_FILE" ] && [ -n "${TUNNEL_USERNAME:-}" ]; then
    umask 077
    {
        printf '%s\n' "$TUNNEL_USERNAME"
        cat "$TUNNEL_PASSWORD_FILE"
    } > /tmp/openvpn-auth
    auth_args="--auth-user-pass /tmp/openvpn-auth"
    log "credentials staged at /tmp/openvpn-auth"
fi

# Start the in-container controller.
tunnel-controller \
    --control-socket "$TUNNEL_CONTROL_SOCKET" \
    --openvpn-mgmt   "$TUNNEL_OPENVPN_MGMT_SOCKET" \
    --manager        openvpn \
    --log-level      "$TUNNEL_LOG_LEVEL" &
controller_pid=$!
log "tunnel-controller started pid=$controller_pid"

# Forward SIGTERM to controller too.
trap 'kill -TERM "$controller_pid" 2>/dev/null || true; exit 0' TERM INT

# OpenVPN runs as PID 1's child via exec. Management socket is unix so the
# controller can talk to it without exposing TCP.
dev_args=""
if [ -n "${TUNNEL_DEV:-}" ]; then
    # Override the .ovpn's --dev so the host's iptables / ip-route can address
    # the tun interface by a deterministic name (SPEC §4.3).
    dev_args="--dev $TUNNEL_DEV"
fi

exec openvpn \
    --config "$TUNNEL_CONFIG_PATH" \
    --management "$TUNNEL_OPENVPN_MGMT_SOCKET" unix \
    --management-query-passwords \
    --auth-nocache \
    --verb 3 \
    $dev_args \
    $auth_args
# (removido --management-hold: o tunnel-controller não emite 'hold release',
# então openvpn ficava em "Need hold release from management interface,
# waiting..." pra sempre. Sem hold, openvpn conecta direto, e o controller
# usa o management socket pra status/OTP/restart como antes.
# Item §11.5 do MANUAL.md.)
