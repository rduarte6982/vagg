#!/bin/sh
# Entrypoint do vagg-tunnel-strongswan (IPsec via charon + swanctl).
#
# Sequência:
#   1. Validar config (formato swanctl.conf).
#   2. Subir charon em background (daemon IKE/ESP).
#   3. swanctl --load-all → carrega connections, secrets, pools, etc.
#   4. swanctl --initiate --child <name>  (vagg-conn por convenção).
#   5. tunnel-controller no foreground.
#
set -eu

log() { echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"src\":\"entrypoint\",\"msg\":\"$*\"}"; }

[ -e /dev/net/tun ] || { log "FATAL /dev/net/tun missing"; exit 1; }
[ -f "$TUNNEL_CONFIG_PATH" ] || { log "FATAL TUNNEL_CONFIG_PATH=$TUNNEL_CONFIG_PATH not found"; exit 1; }

mkdir -p "$(dirname "$TUNNEL_CONTROL_SOCKET")"
[ -p "$TUNNEL_OTP_PIPE" ] || mkfifo "$TUNNEL_OTP_PIPE"

# Coloca a config no caminho que swanctl espera.
ln -sf "$TUNNEL_CONFIG_PATH" /etc/swanctl/swanctl.conf

log "starting charon"
charon &
charon_pid=$!

trap 'kill -TERM "$charon_pid" 2>/dev/null || true; exit 0' TERM INT

# Espera o socket VICI ficar disponível antes de carregar config.
for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ -S /var/run/charon.vici ] && break
    sleep 0.5
done

log "swanctl --load-all"
swanctl --load-all || log "warn: load-all returned non-zero"

CHILD_NAME="${TUNNEL_STRONGSWAN_CHILD:-vagg-conn}"
log "swanctl --initiate --child $CHILD_NAME"
swanctl --initiate --child "$CHILD_NAME" || log "warn: initiate returned non-zero"

exec tunnel-controller \
    --control-socket "$TUNNEL_CONTROL_SOCKET" \
    --manager        strongswan \
    --otp-pipe       "$TUNNEL_OTP_PIPE" \
    --log-level      "$TUNNEL_LOG_LEVEL"
