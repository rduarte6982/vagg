#!/bin/bash
# Aplica manualmente as rotas + NAT da brasanitas pra validar o caminho de
# rede. Se o ping daqui funcionar, o problema é do orchestrator (não está
# rodando o ip route add quando o túnel sobe).

set -e

# 1) Rotas
echo "=== adicionando rotas dev ppp1 ==="
ip route add 192.168.40.0/24 dev ppp1 2>&1 || echo "(192.168.40.0/24 já existe ou erro)"
ip route add 10.210.5.0/24 dev ppp1 2>&1 || echo "(10.210.5.0/24 já existe ou erro)"

echo ""
echo "=== rotas agora ==="
ip route show | grep -E "192\.168\.40|10\.210\.5"

# 2) NAT (POSTROUTING MASQUERADE)
echo ""
echo "=== iptables nat POSTROUTING ==="
iptables -t nat -C POSTROUTING -o ppp1 -j MASQUERADE 2>/dev/null || \
  iptables -t nat -A POSTROUTING -o ppp1 -j MASQUERADE
iptables -t nat -S POSTROUTING | grep ppp1

# 3) FORWARD ACCEPT
echo ""
echo "=== iptables FORWARD ==="
iptables -C FORWARD -i ppp1 -j ACCEPT 2>/dev/null || \
  iptables -I FORWARD -i ppp1 -j ACCEPT
iptables -C FORWARD -o ppp1 -j ACCEPT 2>/dev/null || \
  iptables -I FORWARD -o ppp1 -j ACCEPT
iptables -S FORWARD | grep ppp1

# 4) MTU clamp (Fortinet costuma exigir MSS clamping)
echo ""
echo "=== mss clamping ==="
iptables -t mangle -C FORWARD -o ppp1 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || \
  iptables -t mangle -A FORWARD -o ppp1 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

# 5) sysctl
sysctl -q -w net.ipv4.ip_forward=1
sysctl -q -w net.ipv4.conf.all.rp_filter=2
sysctl -q -w net.ipv4.conf.ppp1.rp_filter=2

echo ""
echo "=== teste ping ==="
echo "192.168.40.1:"
ping -c 2 -W 2 -I ppp1 192.168.40.1 2>&1 | tail -3
echo ""
echo "10.210.5.1:"
ping -c 2 -W 2 -I ppp1 10.210.5.1 2>&1 | tail -3
