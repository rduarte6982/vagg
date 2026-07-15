#!/bin/bash
TOKEN=$(curl -s -X POST -d 'username=admin&password=admin' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  http://192.168.68.102/api/v1/auth/login | grep -oP '"access_token":"\K[^"]+')

echo "=== Clientes ==="
curl -s -H "Authorization: Bearer $TOKEN" http://192.168.68.102/api/v1/clients > /tmp/clients.json

python3 <<'PY'
import json
with open("/tmp/clients.json") as f:
    data = json.load(f)
for c in data:
    print(f"  id={c['id']:15} name={c['name']:25} type={c['vpn_type']:14} otp={c['requires_otp']!s:5} state={c['tunnel_state']}")
PY
