#!/bin/sh
# Entrypoint do vagg-tunnel-openfortivpn-saml — caminho FortiGate SSL VPN
# com SAML SSO (Azure AD + Microsoft Authenticator MFA).
#
# Pré-requisitos via env:
#   TUNNEL_CONFIG_PATH       — config com host=<gateway>, port=<port>, etc
#   TUNNEL_SAML_COOKIE_PATH  — caminho pro cookie capturado pelo saml-portal
#                              (default /share/cookie, formato JSON)
#
# Espera ATIVA pelo cookie em /share/cookie (timeout 20min). Quando chega,
# extrai SVPNCOOKIE=<value> e roda openfortivpn --cookie-on-stdin.

set -eu

log() { echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"src\":\"entrypoint\",\"msg\":\"$*\"}"; }

[ -e /dev/net/tun ] || { log "FATAL /dev/net/tun missing"; exit 1; }
[ -e /dev/ppp ]    || { log "FATAL /dev/ppp missing — host needs ppp_generic kernel module"; exit 1; }
[ -f "$TUNNEL_CONFIG_PATH" ] || { log "FATAL TUNNEL_CONFIG_PATH=$TUNNEL_CONFIG_PATH not found"; exit 1; }

# Snapshot das tunnel ifaces pré-existentes (network_mode=host expõe ifaces
# de outros tunnels — auto-discovery precisa filtrar).
ip -j link show 2>/dev/null > /run/tunnel-iface-snapshot.json || echo '[]' > /run/tunnel-iface-snapshot.json

mkdir -p "$(dirname "$TUNNEL_CONTROL_SOCKET")"
[ -p "$TUNNEL_OTP_PIPE" ] || mkfifo "$TUNNEL_OTP_PIPE"

config_file=/tmp/openfortivpn.conf
umask 077
cp "$TUNNEL_CONFIG_PATH" "$config_file"

# set-dns = 1 → pppd reescreve /etc/resolv.conf com DNS pushed pelo gateway.
if ! grep -qE '^[[:space:]]*set-dns[[:space:]]*=' "$config_file"; then
    echo "set-dns = 1" >> "$config_file"
fi

# Auto-trust do cert (TOFU) — mesmo tratamento da imagem non-SAML.
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
        fi
    fi
fi

# Remove qualquer linha username/password que tenha vindo do config —
# auth é via SAML cookie, não credenciais.
sed -i -E '/^[[:space:]]*(username|password)[[:space:]]*=/d' "$config_file"

# Resolução do SVPNCOOKIE em 3 fontes, em ordem de prioridade:
#  1. TUNNEL_SAML_COOKIE env — passado pelo orchestrator quando o usuário
#     completou SAML e a API persistiu o cookie no DB. Caso normal.
#  2. /share/cookie file — fallback se rodar sem orchestrator (dev/debug).
#     Útil em testes locais onde o saml-portal escreve direto.
#  3. Falha rápido se nenhum dos dois disponível (sem polling longo —
#     orchestrator garantia que TUNNEL_SAML_COOKIE chega no env do connect).
COOKIE_VAL=""
if [ -n "${TUNNEL_SAML_COOKIE:-}" ]; then
    # Aceita formato "SVPNCOOKIE=valor" OU só o valor raw.
    case "$TUNNEL_SAML_COOKIE" in
        "SVPNCOOKIE="*) COOKIE_VAL="${TUNNEL_SAML_COOKIE#SVPNCOOKIE=}" ;;
        *)              COOKIE_VAL="$TUNNEL_SAML_COOKIE" ;;
    esac
    log "got SVPNCOOKIE from env (${#COOKIE_VAL} chars)"
elif [ -f "${TUNNEL_SAML_COOKIE_PATH:-/share/cookie}" ]; then
    COOKIE_PATH="${TUNNEL_SAML_COOKIE_PATH:-/share/cookie}"
    COOKIE_RAW=$(jq -r '.cookie // empty' "$COOKIE_PATH" 2>/dev/null || cat "$COOKIE_PATH")
    case "$COOKIE_RAW" in
        "SVPNCOOKIE="*)
            COOKIE_VAL="${COOKIE_RAW#SVPNCOOKIE=}"
            log "got SVPNCOOKIE from $COOKIE_PATH (${#COOKIE_VAL} chars)"
            ;;
        *)
            log "FATAL cookie file unexpected format: $(echo "$COOKIE_RAW" | head -c 60)"
            exit 1
            ;;
    esac
fi

if [ -z "$COOKIE_VAL" ]; then
    log "FATAL no SVPNCOOKIE available — orchestrator should pass via TUNNEL_SAML_COOKIE env"
    log "       OR saml-portal should have written /share/cookie before this container starts"
    exit 1
fi

log "starting openfortivpn (SAML cookie injected via stdin)"

# openfortivpn --cookie-on-stdin recebe o SVPNCOOKIE inteiro (raw value)
# pelo stdin. Persistente=10 reconecta se cair.
echo "$COOKIE_VAL" \
    | openfortivpn -c "$config_file" --cookie-on-stdin --persistent=10 &
ofvpn_pid=$!

echo "$ofvpn_pid" > "$TUNNEL_PID_FILE"

trap 'kill -TERM "$ofvpn_pid" 2>/dev/null || true; exit 0' TERM INT

exec tunnel-controller \
    --control-socket "$TUNNEL_CONTROL_SOCKET" \
    --manager        openfortivpn \
    --pid-file       "$TUNNEL_PID_FILE" \
    --otp-pipe       "$TUNNEL_OTP_PIPE" \
    --log-level      "$TUNNEL_LOG_LEVEL"
