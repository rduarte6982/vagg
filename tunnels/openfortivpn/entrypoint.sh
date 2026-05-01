#!/bin/sh
# Entrypoint do vagg-tunnel-openfortivpn (Fortinet SSL VPN).
#
# openfortivpn aceita um arquivo de config no formato chave-valor::
#
#   host = vpn.example.com
#   port = 443
#   username = consultor1
#   password = (vamos sobrescrever via stdin)
#   trusted-cert = ...
#
# Escrevemos uma cópia em /tmp/openfortivpn.conf e chamamos com -c.
#
set -eu

log() { echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"src\":\"entrypoint\",\"msg\":\"$*\"}"; }

[ -e /dev/net/tun ] || { log "FATAL /dev/net/tun missing"; exit 1; }
[ -f "$TUNNEL_CONFIG_PATH" ] || { log "FATAL TUNNEL_CONFIG_PATH=$TUNNEL_CONFIG_PATH not found"; exit 1; }

mkdir -p "$(dirname "$TUNNEL_CONTROL_SOCKET")"
[ -p "$TUNNEL_OTP_PIPE" ] || mkfifo "$TUNNEL_OTP_PIPE"

# Compor a config final: a fornecida + (opcional) username/password do env/file.
config_file=/tmp/openfortivpn.conf
umask 077
cp "$TUNNEL_CONFIG_PATH" "$config_file"
if [ -n "${TUNNEL_USERNAME:-}" ]; then
    echo "username = $TUNNEL_USERNAME" >> "$config_file"
fi
if [ -f "$TUNNEL_PASSWORD_FILE" ]; then
    echo "password = $(cat "$TUNNEL_PASSWORD_FILE")" >> "$config_file"
fi

# openfortivpn não tem flag para PID file; vamos capturar o PID após spawn.
log "starting openfortivpn"
openfortivpn -c "$config_file" --persistent=10 &
ofvpn_pid=$!
echo "$ofvpn_pid" > "$TUNNEL_PID_FILE"

trap 'kill -TERM "$ofvpn_pid" 2>/dev/null || true; exit 0' TERM INT

exec tunnel-controller \
    --control-socket "$TUNNEL_CONTROL_SOCKET" \
    --manager        openfortivpn \
    --pid-file       "$TUNNEL_PID_FILE" \
    --otp-pipe       "$TUNNEL_OTP_PIPE" \
    --log-level      "$TUNNEL_LOG_LEVEL"
