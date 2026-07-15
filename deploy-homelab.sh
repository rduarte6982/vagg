#!/usr/bin/env bash
# deploy-homelab.sh — atualiza o vagg-server homelab numa tacada só.
#
# Roda DENTRO do homelab (192.168.68.102), no diretório do repo clonado.
# Faz: git pull, rebuild dos containers, aplica migrations, força refresh do
# UI cache, copia o último .exe pra pasta de downloads se ele existir local.
#
# Uso:
#   bash deploy-homelab.sh
#   bash deploy-homelab.sh /caminho/pro/vagg-client-setup-X.Y.Z.exe
#
# Exit codes:
#   0  tudo certo
#   1  pré-condição falhou (não é git, sem docker, etc)
#   2  build falhou
#   3  migration falhou

set -euo pipefail

# ----- helpers -----

c_red()    { printf '\033[31m%s\033[0m' "$1"; }
c_green()  { printf '\033[32m%s\033[0m' "$1"; }
c_blue()   { printf '\033[34m%s\033[0m' "$1"; }
c_yellow() { printf '\033[33m%s\033[0m' "$1"; }

step() {
    printf '\n%s %s\n' "$(c_blue '==>')" "$(c_blue "$1")"
}

ok()   { printf '   %s %s\n' "$(c_green '✓')" "$1"; }
warn() { printf '   %s %s\n' "$(c_yellow '⚠')" "$1"; }
fail() { printf '   %s %s\n' "$(c_red '✗')" "$1"; }

# ----- pré-condições -----

step "Verificando ambiente"

if ! command -v docker >/dev/null 2>&1; then
    fail "docker não encontrado no PATH"; exit 1
fi
ok "docker $(docker --version | cut -d' ' -f3 | tr -d ',')"

if ! docker compose version >/dev/null 2>&1; then
    fail "docker compose v2 ausente (instale o plugin docker-compose-plugin)"; exit 1
fi
ok "docker compose disponível"

# detecta o repo (CWD precisa ser raiz)
if [[ ! -f "core/pyproject.toml" || ! -d "installer/compose" ]]; then
    fail "este script precisa rodar na raiz do repo vagg (com core/ e installer/)"
    fail "cwd atual: $(pwd)"
    exit 1
fi
ok "repo detectado em $(pwd)"

# detecta o compose ativo
COMPOSE_FILE="installer/compose/docker-compose.yml"
ENV_FILE="/etc/vagg/core.env"
if [[ ! -f "$ENV_FILE" ]]; then
    warn "$ENV_FILE não existe — talvez o stack esteja em outro lugar"
fi
ok "usando compose: $COMPOSE_FILE"

# ----- 1) git pull -----

step "1/6 Atualizando código (git pull)"
git fetch --all --quiet
LOCAL=$(git rev-parse HEAD)
git pull --ff-only
NEW=$(git rev-parse HEAD)
if [[ "$LOCAL" == "$NEW" ]]; then
    warn "já estava no HEAD ($LOCAL) — nenhum commit novo"
else
    ok "atualizado: ${LOCAL:0:8} → ${NEW:0:8}"
fi

# ----- 2) Build da imagem do core (mudou auth/deps/me/consultants) -----

step "2/6 Buildando vagg-core"
if docker compose -f "$COMPOSE_FILE" build vagg-core >/tmp/vagg-build-core.log 2>&1; then
    ok "vagg-core buildou"
else
    fail "build do core falhou — log em /tmp/vagg-build-core.log"
    tail -20 /tmp/vagg-build-core.log
    exit 2
fi

# ----- 3) Build da imagem do UI (mudou Consultants.tsx, System.tsx, nginx.conf, i18n) -----

step "3/6 Buildando vagg-ui"
# --no-cache pra garantir que o nginx.conf novo entra (Dockerfile pode estar
# cacheando a etapa COPY)
if docker compose -f "$COMPOSE_FILE" build --no-cache vagg-ui >/tmp/vagg-build-ui.log 2>&1; then
    ok "vagg-ui buildou"
else
    fail "build do UI falhou — log em /tmp/vagg-build-ui.log"
    tail -20 /tmp/vagg-build-ui.log
    exit 2
fi

# ----- 4) Sobe os containers atualizados -----

step "4/6 Subindo containers"
docker compose -f "$COMPOSE_FILE" up -d vagg-core vagg-ui
sleep 3
ok "containers up"

# ----- 5) Aplica migrations Alembic (cria password_hash + seed rduarte) -----

step "5/6 Aplicando migrations"
if docker compose -f "$COMPOSE_FILE" exec -T vagg-core alembic upgrade head >/tmp/vagg-migrate.log 2>&1; then
    ok "migrations aplicadas"
    grep -E "running upgrade|0004|0005" /tmp/vagg-migrate.log | sed 's/^/   /' || true
else
    fail "migration falhou — log em /tmp/vagg-migrate.log"
    tail -20 /tmp/vagg-migrate.log
    exit 3
fi

# ----- 6) Garante a pasta de downloads e copia o exe se passado -----

step "6/6 Pasta de downloads"
sudo mkdir -p /var/lib/vagg/downloads
sudo chown -R "$USER":"$USER" /var/lib/vagg/downloads
ok "/var/lib/vagg/downloads pronta"

if [[ "${1:-}" != "" ]]; then
    if [[ -f "$1" ]]; then
        cp "$1" /var/lib/vagg/downloads/
        ok "copiado: $(basename "$1") → /var/lib/vagg/downloads/"
    else
        warn "argumento '$1' não é um arquivo — pulando cópia"
    fi
fi

ls -la /var/lib/vagg/downloads/ | grep -v "^total" | sed 's/^/   /'

# ----- summary -----

step "Pronto"
ok "vagg-server atualizado"
ok "abra a UI: https://192.168.68.102 (ou http no caso do dev)"
ok "FORCE-RELOAD do browser: Ctrl+Shift+R / Cmd+Shift+R — o nginx serve index.html com no-store mas o browser pode estar com bundle JS antigo cacheado"
echo
echo "Pra verificar saúde dos containers:"
echo "   docker compose -f $COMPOSE_FILE ps"
echo "   docker compose -f $COMPOSE_FILE logs --tail=30 vagg-core"
