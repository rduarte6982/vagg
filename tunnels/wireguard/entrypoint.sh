#!/bin/sh
# Entrypoint do vagg-tunnel-wireguard.
#
# WireGuard® é puramente criptográfico — sem MFA. tunnel-controller fica no
# foreground; o ``wg-quick up`` é one-shot (configura interface e sai).
# Reconexão é feita pelo próprio kernel/handshake protocol; em caso de falha
# de keepalive prolongada, ``--restart=unless-stopped`` recria o container.
#
set -eu

log() { echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"src\":\"entrypoint\",\"msg\":\"$*\"}"; }

[ -e /dev/net/tun ] || { log "FATAL /dev/net/tun missing"; exit 1; }
[ -f "$TUNNEL_CONFIG_PATH" ] || { log "FATAL TUNNEL_CONFIG_PATH=$TUNNEL_CONFIG_PATH not found"; exit 1; }
[ -n "${TUNNEL_DEV:-}" ] || { log "FATAL TUNNEL_DEV must be set (Linux IFNAMSIZ ≤ 15)"; exit 1; }

mkdir -p "$(dirname "$TUNNEL_CONTROL_SOCKET")"

# wg-quick exige que o config esteja em /etc/wireguard/<name>.conf.
ln -sf "$TUNNEL_CONFIG_PATH" "/etc/wireguard/$TUNNEL_DEV.conf"

log "wg-quick up $TUNNEL_DEV"
wg-quick up "$TUNNEL_DEV"

trap 'wg-quick down "$TUNNEL_DEV" 2>/dev/null || true; exit 0' TERM INT

exec tunnel-controller \
    --control-socket "$TUNNEL_CONTROL_SOCKET" \
    --manager        wireguard \
    --wg-iface       "$TUNNEL_DEV" \
    --log-level      "$TUNNEL_LOG_LEVEL"
