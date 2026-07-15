#!/bin/bash
echo "=== rotas dev ppp+/tun+ ==="
ip route show | grep -E "dev (ppp|tun)" | sort

echo ""
echo "=== ping 192.168.40.1 (Brasanitas principal) ==="
ping -c 2 -W 2 192.168.40.1 2>&1 | tail -3

echo ""
echo "=== ping 10.210.5.1 (Brasanitas extra/SAP) ==="
ping -c 2 -W 2 10.210.5.1 2>&1 | tail -3

echo ""
echo "=== ping 10.80.0.1 (LongPing) ==="
ping -c 2 -W 2 10.80.0.1 2>&1 | tail -3

echo ""
echo "=== ping 10.0.0.1 (Roit) ==="
ping -c 2 -W 2 10.0.0.1 2>&1 | tail -3

echo ""
echo "=== timer status ==="
systemctl is-enabled vagg-routes.timer
systemctl is-active vagg-routes.timer

echo ""
echo "=== teste de auto-recovery: deletar rota 10.210.5.0/24 e aguardar 65s ==="
sudo -n ip route del 10.210.5.0/24 dev ppp1 2>/dev/null && echo "deletado"
echo "antes do timer:"
ip route show 10.210.5.0/24 || echo "  (rota ausente)"
echo "rodando service manualmente pra simular o timer..."
sudo -n systemctl start vagg-routes.service
sleep 2
echo "depois:"
ip route show 10.210.5.0/24
echo ""
echo "ping 10.210.5.1:"
ping -c 2 -W 2 10.210.5.1 2>&1 | tail -3
