#!/bin/bash
set -e

TOKEN=$(curl -s -X POST -d 'username=admin&password=admin' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  http://192.168.68.102/api/v1/auth/login | grep -oP '"access_token":"\K[^"]+')

echo "=== /api/v1/clients/brasanitas ==="
curl -s -H "Authorization: Bearer $TOKEN" \
  http://192.168.68.102/api/v1/clients/brasanitas | python3 -m json.tool

echo ""
echo "=== ppp1 interface ==="
ip -br addr show ppp1 || true

echo ""
echo "=== ip route show (filtro brasanitas) ==="
ip route show | grep -E "192.168.40|10.210.5" || echo "(nenhuma rota encontrada)"

echo ""
echo "=== iptables nat -L POSTROUTING (filtro ppp/masq) ==="
sudo -n iptables -t nat -S POSTROUTING 2>/dev/null | grep -iE "ppp|masq" || echo "(precisa sudo)"

echo ""
echo "=== iptables filter -L FORWARD (filtro ppp) ==="
sudo -n iptables -S FORWARD 2>/dev/null | grep -iE "ppp" || echo "(precisa sudo)"

echo ""
echo "=== ping pelos hops ==="
echo "ping 192.168.40.1 (gateway peer):"
ping -c 2 -W 2 192.168.40.1 2>&1 | tail -3
echo ""
echo "ping 10.210.5.1 (gateway suposto):"
ping -c 2 -W 2 10.210.5.1 2>&1 | tail -3
