#!/bin/bash
TOKEN=$(curl -s -X POST -d 'username=admin&password=admin' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  http://192.168.68.102/api/v1/auth/login | grep -oP '"access_token":"\K[^"]+')

echo "=== POST /clients/mrv/saml/start ==="
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"gateway_url":"https://gp.mrv.com.br"}' \
  http://192.168.68.102/api/v1/clients/mrv/saml/start | python3 -m json.tool

echo "=== docker ps (saml) — depois de 3s ==="
sleep 3
docker ps --filter 'name=saml' --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

echo "=== ss listening ==="
ss -tlnp 2>/dev/null | grep -E ':145[0-9][0-9]' | head -5

echo "=== curl portal_url ==="
PORT=$(docker ps --filter 'name=saml' --format '{{.Ports}}' | head -1 | grep -oE '0\.0\.0\.0:[0-9]+' | head -1 | cut -d: -f2)
echo "porta detectada: $PORT"
[ -n "$PORT" ] && curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://192.168.68.102:$PORT/ --max-time 8
