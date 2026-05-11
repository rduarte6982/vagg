#!/usr/bin/env bash
# rollback-saml-v1.sh — restaura a stack SAML pro snapshot funcional
# de 2026-05-11 (commit 93a1f91).
#
# Uso (no homelab):
#   sudo bash deploy/snapshots/rollback-saml-v1.sh
#
# Não toca em DB nem clientes — só images + recriação dos containers
# vagg-core e vagg-ui. Tunnel containers existentes morrem na próxima
# desconexão e nascem novos com :test (que aponta pro :stable-saml-v1
# após este script).

set -euo pipefail

SNAPSHOT="stable-saml-v1"
COMPOSE_DIR="/home/rodrigo/projects/vagg/installer/compose"

log() { printf '\033[36m[rollback]\033[0m %s\n' "$*"; }
ok()  { printf '\033[32m  ✓\033[0m %s\n' "$*"; }
err() { printf '\033[31m  ✗\033[0m %s\n' "$*" >&2; }

log "verificando snapshot $SNAPSHOT presente local..."
MISSING=0
for img in \
    vagg/saml-portal \
    vagg/tunnel-openconnect-saml \
    vagg/tunnel-openfortivpn-saml \
    vagg/tunnel-openfortivpn \
    vagg/tunnel-openconnect \
    vagg/tunnel-openvpn \
    ghcr.io/rduarte6982/vagg/core \
    ghcr.io/rduarte6982/vagg/ui ; do
    if docker image inspect "${img}:${SNAPSHOT}" >/dev/null 2>&1; then
        ok "$img:$SNAPSHOT"
    else
        err "$img:$SNAPSHOT NÃO ENCONTRADO"
        MISSING=$((MISSING + 1))
    fi
done
if [ "$MISSING" -gt 0 ]; then
    err "snapshot incompleto ($MISSING imagens faltando). Aborta."
    exit 1
fi

log "retaggeando :stable-saml-v1 → :test (e :latest pro core/ui)"
for img in \
    vagg/saml-portal \
    vagg/tunnel-openconnect-saml \
    vagg/tunnel-openfortivpn-saml \
    vagg/tunnel-openfortivpn \
    vagg/tunnel-openconnect \
    vagg/tunnel-openvpn ; do
    docker tag "${img}:${SNAPSHOT}" "${img}:test"
    ok "$img:test"
done

for img in ghcr.io/rduarte6982/vagg/core ghcr.io/rduarte6982/vagg/ui ; do
    docker tag "${img}:${SNAPSHOT}" "${img}:test"
    docker tag "${img}:${SNAPSHOT}" "${img}:latest"
    ok "$img:test + :latest"
done

log "recriando vagg-core e vagg-ui"
cd "$COMPOSE_DIR"
docker compose up -d --force-recreate vagg-core vagg-ui

log "aguardando healthcheck..."
sleep 8
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Image}}' | grep -E 'vagg-(core|ui)'

log ""
log "rollback completo. Tunnel containers existentes ainda usam imagem antiga"
log "até serem recriados (próxima desconexão/reconexão pela UI)."
log ""
log "Pra forçar recriação dos tunnels ativos:"
log "  docker ps --filter label=vagg.managed=true --format '{{.Names}}' | xargs -r docker rm -f"
log "  → e clicar 'Conectar' de novo na UI."
