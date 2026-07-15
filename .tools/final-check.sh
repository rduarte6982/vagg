#!/bin/bash
echo "=== UI title ==="
curl -s http://192.168.68.102:443/ | grep -oE '<title>[^<]+</title>'

echo "=== /api/v1/system/health (via UI proxy) ==="
curl -s http://192.168.68.102:443/api/v1/system/health
echo

echo "=== /downloads/ index ==="
curl -s http://192.168.68.102:443/downloads/ | grep -oE 'vagg-client-setup[^"]*\.exe' | head -3

echo "=== vagg-client-setup-0.4.0.exe download ==="
curl -s -o /dev/null -w "HTTP %{http_code} size=%{size_download} bytes\n" http://192.168.68.102:443/downloads/vagg-client-setup-0.4.0.exe

echo "=== rduarte login ==="
curl -s -X POST -d 'username=rduarte&password=123456' -H 'Content-Type: application/x-www-form-urlencoded' http://192.168.68.102:443/api/v1/auth/login -o /tmp/login.json -w 'HTTP %{http_code}\n'
TOKEN=$(grep -oP '"access_token":"\K[^"]+' /tmp/login.json)

echo "=== /me/clients with rduarte token ==="
curl -s -H "Authorization: Bearer $TOKEN" http://192.168.68.102:443/api/v1/me/clients | head -c 300
echo
