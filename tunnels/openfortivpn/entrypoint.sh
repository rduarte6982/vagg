#!/bin/sh
# Entrypoint do vagg-tunnel-openfortivpn (Fortinet SSL VPN).
#
# Modos de operação:
#  - Sem MFA (TUNNEL_REQUIRES_OTP unset/false):
#       password vai no arquivo de config, openfortivpn lê normalmente.
#  - Com MFA (TUNNEL_REQUIRES_OTP=true):
#       password é REMOVIDO do arquivo. Stdin do openfortivpn recebe:
#         linha 1: senha
#         linha 2: código OTP (vem do FIFO /run/otp.pipe — bloqueante até
#                   o backend chamar POST /api/v1/tunnels/{id}/otp)
#       openfortivpn é executado com --otp-prompt pra forçar o prompt extra.
#
set -eu

log() { echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"src\":\"entrypoint\",\"msg\":\"$*\"}"; }

[ -e /dev/net/tun ] || { log "FATAL /dev/net/tun missing"; exit 1; }
[ -f "$TUNNEL_CONFIG_PATH" ] || { log "FATAL TUNNEL_CONFIG_PATH=$TUNNEL_CONFIG_PATH not found"; exit 1; }

# Self-heal CONTÍNUO da default route do host. openfortivpn HIJACKA
# `default dev pppN` quando conecta — quando o tunnel cai, ppp some
# levando o default e o reconnect loopa em "Network is unreachable".
# Watchdog em background re-injeta `default dev ens18` se sumir, em
# prioridade mais baixa que o pppN (metric maior), mas presente como
# fallback pra openfortivpn alcançar o gateway sempre.
# Override env: VAGG_HOST_DEFAULT_GW/_DEV.
VAGG_GW="${VAGG_HOST_DEFAULT_GW:-192.168.68.1}"
VAGG_DEV="${VAGG_HOST_DEFAULT_DEV:-ens18}"
(
    while true; do
        # metric 1000 = sempre menor prioridade que default do pppN (metric 0)
        # Quando ppp existe, kernel usa ppp. Quando ppp some, usa este.
        if ! ip route show default | grep -q "via $VAGG_GW"; then
            ip route add default via "$VAGG_GW" dev "$VAGG_DEV" metric 1000 2>/dev/null || true
        fi
        sleep 5
    done
) &

mkdir -p "$(dirname "$TUNNEL_CONTROL_SOCKET")"
[ -p "$TUNNEL_OTP_PIPE" ] || mkfifo "$TUNNEL_OTP_PIPE"

# Snapshot das tunnel ifaces visíveis no host net namespace ANTES do
# openfortivpn subir. Como vagg roda com network_mode=host, todas as
# tunnel containers veem todas as ifaces (tun0/ppp0/etc) do host. Sem
# este snapshot, o auto-discovery do tunnel-controller não consegue
# distinguir o que ESTE container criou vs o que outros tunnels já
# tinham subido.
ip -j link show 2>/dev/null > /run/tunnel-iface-snapshot.json || echo '[]' > /run/tunnel-iface-snapshot.json
log "snapshotted $(grep -oE '\"ifname\":\"[^\"]+\"' /run/tunnel-iface-snapshot.json | wc -l) pre-existing ifaces"

config_file=/tmp/openfortivpn.conf
umask 077
cp "$TUNNEL_CONFIG_PATH" "$config_file"
if [ -n "${TUNNEL_USERNAME:-}" ]; then
    # remove qualquer username pré-existente e injeta o do env
    sed -i '/^[[:space:]]*username[[:space:]]*=/d' "$config_file"
    echo "username = $TUNNEL_USERNAME" >> "$config_file"
fi

# set-dns = 1 faz o openfortivpn (via pppd) reescrever /etc/resolv.conf do
# container com os DNS empurrados pelo gateway. Necessário pro auto-discovery
# capturar os nameservers internos via /etc/resolv.conf depois que a sessão
# sobe. Não usar `pppd-use-peerdns` aqui — é flag de pppd, não do openfortivpn.
if ! grep -qE '^[[:space:]]*set-dns[[:space:]]*=' "$config_file"; then
    echo "set-dns = 1" >> "$config_file"
fi

# Auto-trust do cert do gateway (TOFU). Só roda se config não tem trusted-cert
# definido — admin que setou explicitamente no FortiClient export quer aquele
# valor exato. Pra clientes vindos da UI sem digest pré-configurado, fetcha
# do gateway via openssl s_client e injeta. Trade-off: TOFU é vulnerável a
# MITM no PRIMEIRO connect; depois disso a chave fica pinada no config.
if ! grep -qE '^[[:space:]]*trusted-cert[[:space:]]*=' "$config_file"; then
    HOST=$(grep -E '^[[:space:]]*host[[:space:]]*=' "$config_file" | head -1 \
        | sed -E 's/^[[:space:]]*host[[:space:]]*=[[:space:]]*//' | tr -d '"\r' | tr -d ' ')
    PORT=$(grep -E '^[[:space:]]*port[[:space:]]*=' "$config_file" | head -1 \
        | sed -E 's/^[[:space:]]*port[[:space:]]*=[[:space:]]*//' | tr -d '"\r' | tr -d ' ')
    PORT="${PORT:-443}"
    if [ -n "$HOST" ]; then
        log "TOFU: fetching cert digest from $HOST:$PORT"
        DIGEST=$(echo | timeout 10 openssl s_client \
            -connect "$HOST:$PORT" -servername "$HOST" 2>/dev/null \
            | openssl x509 -noout -fingerprint -sha256 2>/dev/null \
            | sed 's/.*=//;s/://g' | tr 'A-Z' 'a-z')
        if [ -n "$DIGEST" ] && [ ${#DIGEST} -eq 64 ]; then
            echo "trusted-cert = $DIGEST" >> "$config_file"
            log "TOFU: pinned cert digest=$DIGEST"
        else
            log "TOFU: failed to fetch cert digest from $HOST:$PORT — openfortivpn may reject unknown cert"
        fi
    fi
fi

PASS_=""
if [ -f "$TUNNEL_PASSWORD_FILE" ]; then
    PASS_=$(cat "$TUNNEL_PASSWORD_FILE")
fi

if [ "${TUNNEL_REQUIRES_OTP:-}" = "true" ]; then
    log "starting openfortivpn (MFA mode — aguardando OTP via FIFO)"
    # Tira password do arquivo de config — vai pelo stdin
    sed -i '/^[[:space:]]*password[[:space:]]*=/d' "$config_file"

    # Stream: senha (imediato) + OTP (lê do FIFO, bloqueia até o backend
    # mandar o código). O `cat` de FIFO bloqueia abrir até alguém escrever
    # no outro lado, então open(O_RDONLY) só retorna depois do POST /otp.
    ( printf '%s\n' "$PASS_"; cat "$TUNNEL_OTP_PIPE"; ) \
        | openfortivpn -c "$config_file" --persistent=10 --set-routes=0 --set-dns=0 --otp-prompt &
    ofvpn_pid=$!
else
    log "starting openfortivpn (sem MFA)"
    if [ -n "$PASS_" ]; then
        echo "password = $PASS_" >> "$config_file"
    fi
    openfortivpn -c "$config_file" --persistent=10 --set-routes=0 --set-dns=0 &
    ofvpn_pid=$!
fi

echo "$ofvpn_pid" > "$TUNNEL_PID_FILE"

trap 'kill -TERM "$ofvpn_pid" 2>/dev/null || true; exit 0' TERM INT

exec tunnel-controller \
    --control-socket "$TUNNEL_CONTROL_SOCKET" \
    --manager        openfortivpn \
    --pid-file       "$TUNNEL_PID_FILE" \
    --otp-pipe       "$TUNNEL_OTP_PIPE" \
    --log-level      "$TUNNEL_LOG_LEVEL"
