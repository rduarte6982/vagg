#!/usr/bin/env bash
# seed.sh — popula o vagg-core de teste com 3 clientes, 3 consultores e
# algumas políticas, para que a UI tenha conteúdo de demonstração.
#
# Pré-requisitos:
#   - dev.env já criado (./bootstrap.sh)
#   - stack rodando (docker compose --env-file dev.env up -d)
#   - jq + curl (universal em Linux/Mac/WSL)

set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f dev.env ]]; then
  echo "erro: dev.env não encontrado. rode ./bootstrap.sh primeiro." >&2
  exit 2
fi
# shellcheck disable=SC1091
source dev.env

API="http://localhost:8443/api/v1"
EMAIL="${VAGG_ADMIN_EMAIL:-admin@vagg.local}"
PASSWORD="${SEED_PASSWORD:-admin}"

echo "-> aguardando vagg-core em $API"
for _ in $(seq 1 60); do
  if curl -fsS "$API/system/health" >/dev/null 2>&1; then break; fi
  sleep 1
done

echo "-> autenticando como $EMAIL"
TOKEN=$(curl -fsS -X POST "$API/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=$EMAIL" \
  --data-urlencode "password=$PASSWORD" | jq -r .access_token)

if [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
  echo "erro: login falhou (verifique a senha em SEED_PASSWORD; default=admin)" >&2
  exit 3
fi

H=("-H" "Authorization: Bearer $TOKEN" "-H" "Content-Type: application/json")

echo "-> criando clientes (idempotente)"
create_client() {
  local id="$1" name="$2" vpn="$3" virtual="$4" real="$5" dns="${6:-}"
  local body
  if [[ -n "$dns" ]]; then
    body=$(jq -n \
      --arg id "$id" --arg name "$name" --arg vpn "$vpn" \
      --arg virtual "$virtual" --arg real "$real" --arg dns "$dns" \
      '{id:$id,name:$name,vpn_type:$vpn,virtual_cidr:$virtual,real_cidr:$real,dns_server:$dns,nat_mappings:[]}')
  else
    body=$(jq -n \
      --arg id "$id" --arg name "$name" --arg vpn "$vpn" \
      --arg virtual "$virtual" --arg real "$real" \
      '{id:$id,name:$name,vpn_type:$vpn,virtual_cidr:$virtual,real_cidr:$real,nat_mappings:[]}')
  fi
  curl -fsS "${H[@]}" -X POST "$API/clients" -d "$body" >/dev/null \
    || echo "   ! cliente $id já existe — ignorando"
}

create_client petroleo  "Petróleo SA"        openvpn       10.200.10.0/24 172.16.0.0/24  172.16.0.10
create_client lojas-ur  "Lojas Urano"        openconnect   10.200.20.0/24 10.10.0.0/16   10.10.0.5
create_client banco     "Banco Azul"         openfortivpn  10.200.30.0/24 192.168.50.0/24

echo "-> criando consultores"
create_consultant() {
  local email="$1" name="$2" role="$3" pool_ip="${4:-}"
  local body
  if [[ -n "$pool_ip" ]]; then
    body=$(jq -n --arg email "$email" --arg name "$name" --arg role "$role" --arg ip "$pool_ip" \
      '{email:$email,name:$name,role:$role,static_pool_ip:$ip}')
  else
    body=$(jq -n --arg email "$email" --arg name "$name" --arg role "$role" \
      '{email:$email,name:$name,role:$role}')
  fi
  curl -fsS "${H[@]}" -X POST "$API/consultants" -d "$body" >/dev/null \
    || echo "   ! consultor $email já existe — ignorando"
}

create_consultant paulo.silva@consultoria.com "Paulo Silva"     operator 10.8.0.5
create_consultant beatriz.lima@consultoria.com "Beatriz Lima"   viewer
create_consultant andre.romero@consultoria.com "André Romero"   admin

echo "-> criando políticas"
# Pega IDs gerados
CONSULTANTS=$(curl -fsS "${H[@]}" "$API/consultants")
get_id() { echo "$CONSULTANTS" | jq -r ".[] | select(.email==\"$1\") | .id"; }
PAULO_ID=$(get_id paulo.silva@consultoria.com)
BEA_ID=$(get_id beatriz.lima@consultoria.com)

create_policy() {
  local consultant_id="$1" client_id="$2" scope_kind="$3" scope_value="${4:-}"
  local body
  if [[ -n "$scope_value" ]]; then
    body=$(jq -n --argjson cid "$consultant_id" --arg client "$client_id" --arg kind "$scope_kind" --arg value "$scope_value" \
      '{consultant_id:$cid,client_id:$client,scope_kind:$kind,scope_value:$value}')
  else
    body=$(jq -n --argjson cid "$consultant_id" --arg client "$client_id" --arg kind "$scope_kind" \
      '{consultant_id:$cid,client_id:$client,scope_kind:$kind}')
  fi
  curl -fsS "${H[@]}" -X POST "$API/policies" -d "$body" >/dev/null || true
}

create_policy "$PAULO_ID" petroleo full
create_policy "$PAULO_ID" lojas-ur subnet 10.10.5.0/24
create_policy "$BEA_ID"   banco    host   192.168.50.10

echo "-> pronto"
echo
echo "Acesse:"
echo "  http://localhost:8080  → Admin UI"
echo "  http://localhost:8081  → Portal"
echo "  http://localhost:8443/docs"
