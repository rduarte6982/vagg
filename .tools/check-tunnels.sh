#!/bin/bash
TOKEN=$(curl -s -X POST -d 'username=admin&password=admin' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  http://192.168.68.102/api/v1/auth/login | grep -oP '"access_token":"\K[^"]+')

echo "=== /api/v1/clients ==="
curl -s -H "Authorization: Bearer $TOKEN" http://192.168.68.102/api/v1/clients | python3 -c "
import json, sys
data = json.load(sys.stdin)
for c in data:
    state = c.get('tunnel_state','?')
    err = c.get('tunnel_last_error','')
    err_short = (err[:60] + '...') if err and len(err) > 60 else (err or '')
    print(f\"{c['id']:15} state={state:10} err={err_short}\")
"
