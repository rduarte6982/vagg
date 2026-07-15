#!/bin/bash
# vagg-aggregator — reconcilia rotas de TODOS os clientes ativos.
# Idempotente, silencioso quando não há nada a fazer.
set -eu

LOG_TAG="vagg-routes"
log() { logger -t "$LOG_TAG" "$*"; }

API="${VAGG_API:-http://127.0.0.1:8443/api/v1}"
USER_="${VAGG_USER:-admin}"
PASS_="${VAGG_PASS:-admin}"

# 0) sysctls
sysctl -q -w net.ipv4.ip_forward=1 || true
sysctl -q -w net.ipv4.conf.all.rp_filter=2 || true

# 1) iptables globais (ppp+ e tun+)
for IFACE_GLOB in "ppp+" "tun+"; do
    iptables -C FORWARD -o "$IFACE_GLOB" -j ACCEPT 2>/dev/null \
        || iptables -I FORWARD -o "$IFACE_GLOB" -j ACCEPT
    iptables -C FORWARD -i "$IFACE_GLOB" -j ACCEPT 2>/dev/null \
        || iptables -I FORWARD -i "$IFACE_GLOB" -j ACCEPT
    iptables -t nat -C POSTROUTING -o "$IFACE_GLOB" -j MASQUERADE 2>/dev/null \
        || iptables -t nat -A POSTROUTING -o "$IFACE_GLOB" -j MASQUERADE
    iptables -t mangle -C FORWARD -o "$IFACE_GLOB" -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null \
        || iptables -t mangle -A FORWARD -o "$IFACE_GLOB" -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
done

# 2) Espera aggregator
for i in $(seq 1 30); do
    curl -fsS "$API/system/health" >/dev/null 2>&1 && break
    sleep 2
done

# 3) Login admin
TOKEN=$(curl -fsS -X POST "$API/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=$USER_" --data-urlencode "password=$PASS_" \
  | jq -r .access_token 2>/dev/null || true)

[ -z "$TOKEN" ] || [ "$TOKEN" = "null" ] && { log "login falhou"; exit 0; }

# Helper: dado um real_cidr (ex: 192.168.40.0/24), encontra a iface ppp/tun
# cujo IP atribuído cai dentro desse CIDR.
find_iface_for() {
    local cidr="$1"
    [ -z "$cidr" ] || [ "$cidr" = "0.0.0.0/0" ] && return 1

    # Extrai os 2 primeiros octetos do CIDR base (ex: "192.168.40.0/24" -> "192.168")
    local base prefix2
    base=$(echo "$cidr" | cut -d'/' -f1)
    prefix2=$(echo "$base" | cut -d'.' -f1-2)

    # Lista interfaces ppp/tun ativas e o IP de cada uma
    while read -r I IP; do
        [ -z "$I" ] && continue
        local ip_prefix2
        ip_prefix2=$(echo "$IP" | cut -d'.' -f1-2)
        if [ "$ip_prefix2" = "$prefix2" ]; then
            echo "$I"
            return 0
        fi
    done < <(ip -4 -br addr show 2>/dev/null \
                | awk '$1 ~ /^(ppp[0-9]+|tun[0-9]+)/ {split($3,a,"/"); print $1, a[1]}')
    return 1
}

# 4) Pra cada client up, aplica rotas
CLIENTS_JSON=$(curl -fsS -H "Authorization: Bearer $TOKEN" "$API/clients" 2>/dev/null || echo "[]")

echo "$CLIENTS_JSON" | jq -r '.[] | select(.tunnel_state=="up") | .id' | while read -r CID; do
    [ -z "$CID" ] && continue

    # real_cidr (principal) usado pra detectar a interface
    REAL=$(echo "$CLIENTS_JSON" | jq -r --arg id "$CID" \
        '.[] | select(.id==$id) | .real_cidr // ""')

    if [ -z "$REAL" ] || [ "$REAL" = "null" ] || [ "$REAL" = "0.0.0.0/0" ]; then
        log "client=$CID: real_cidr inválido ($REAL) — pulando"
        continue
    fi

    IFACE=$(find_iface_for "$REAL" || true)
    if [ -z "$IFACE" ]; then
        log "client=$CID: nenhuma interface ppp/tun bate com real_cidr=$REAL"
        continue
    fi

    # CIDRs a aplicar: real_cidr + nat_mappings.real_cidr únicos, sem 0.0.0.0/0
    CIDRS=$(echo "$CLIENTS_JSON" | jq -r --arg id "$CID" '
        .[] | select(.id==$id) |
        ([.real_cidr] + ((.nat_mappings // []) | map(.real_cidr))) |
        unique | .[] |
        select(. != null and . != "" and . != "0.0.0.0/0")
    ')

    echo "$CIDRS" | while read -r CIDR; do
        [ -z "$CIDR" ] && continue
        # Adiciona se ainda não existe rota DESSE cidr POR essa iface
        if ! ip route show "$CIDR" 2>/dev/null | grep -q "dev $IFACE"; then
            if ip route replace "$CIDR" dev "$IFACE" scope link 2>/dev/null; then
                log "client=$CID: ip route replace $CIDR dev $IFACE"
            else
                log "client=$CID: FALHA ip route replace $CIDR dev $IFACE"
            fi
        fi
    done
done

exit 0
