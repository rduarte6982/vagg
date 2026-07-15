#!/bin/bash
TOKEN=$(curl -s -X POST -d 'username=admin&password=admin' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  http://192.168.68.102/api/v1/auth/login | grep -oP '"access_token":"\K[^"]+')

echo "=== POST /clients/minerva/otp (sem token vai ser 401, com token vai ser 4xx ou 200) ==="
curl -s -o /dev/null -w 'HTTP %{http_code}\n' -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{"code":"123456"}' \
    http://192.168.68.102/api/v1/clients/minerva/otp

echo "=== POST /clients/minerva/connect ==="
curl -s -o /dev/null -w 'HTTP %{http_code}\n' -X POST \
    -H "Authorization: Bearer $TOKEN" \
    http://192.168.68.102/api/v1/clients/minerva/connect
