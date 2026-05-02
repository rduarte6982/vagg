#!/usr/bin/env bash
# scripts/test-install.sh — instalação de TESTE no mini PC (ou qualquer VM
# Ubuntu 24.04) sem precisar de domínio próprio, sem licensing.vagg.io,
# sem registry público de imagens.
#
# Diferenças vs installer/install.sh (produção):
#   - Constrói as 8 imagens localmente com `make images-build`
#   - Usa o IP da máquina como "domínio" (sem TLS, http://<ip>:8443)
#   - License key = "test-license" (validado fail-soft pelo core)
#   - vagg-update.timer NÃO é habilitado (não há updates.vagg.io)
#   - Compose roda em modo foreground/background do próprio repo, sem
#     copiar para /etc/vagg — assim você pode iterar e re-testar
#
# Uso (no mini PC, dentro do repo clonado):
#   sudo bash scripts/test-install.sh
#
# Pra resetar e re-testar:
#   sudo bash scripts/test-install.sh --reset

set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VAGG_HOME="${VAGG_HOME:-/var/lib/vagg}"
VAGG_ETC="${VAGG_ETC:-/etc/vagg}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@vagg.test}"
RESET=0

log() { printf '\033[1;34m[test-install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

require_root() {
    [[ $EUID -eq 0 ]] || fail "rode como root: sudo bash scripts/test-install.sh"
}

parse_args() {
    for arg in "$@"; do
        case "$arg" in
            --reset) RESET=1 ;;
            --admin-email=*) ADMIN_EMAIL="${arg#*=}" ;;
            --help|-h)
                grep '^#' "$0" | head -25
                exit 0
                ;;
            *) fail "argumento desconhecido: $arg" ;;
        esac
    done
}

reset_state() {
    log "removendo stack anterior (se houver)..."
    if command -v docker >/dev/null; then
        docker compose -f "$REPO_DIR/installer/compose/docker-compose.test.yml" down -v 2>/dev/null || true
        docker ps -aq --filter "label=vagg.managed=true" | xargs -r docker rm -f 2>/dev/null || true
    fi
    rm -rf "$VAGG_HOME" "$VAGG_ETC"
    log "estado removido."
}

detect_lan_ip() {
    # Pega o primeiro IPv4 não-loopback. Aceita IP inválido com fallback,
    # mas avisa para o usuário poder corrigir.
    local ip
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    if [[ -z "$ip" ]]; then
        warn "não consegui detectar IP da LAN — vou usar 127.0.0.1"
        ip="127.0.0.1"
    fi
    echo "$ip"
}

ensure_docker() {
    if command -v docker >/dev/null; then
        return 0
    fi
    log "Docker não encontrado — instalando..."
    apt-get update -y
    apt-get install -y ca-certificates curl gnupg make
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    . /etc/os-release
    cat >/etc/apt/sources.list.d/docker.list <<EOF
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable
EOF
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
}

build_images() {
    log "construindo as 8 imagens locais (5–10 min na primeira vez)..."
    cd "$REPO_DIR"
    make images-build
}

prepare_dirs() {
    log "preparando dirs em $VAGG_HOME e $VAGG_ETC..."
    install -d -m 0755 \
        "$VAGG_HOME/db" \
        "$VAGG_HOME/clients" \
        "$VAGG_HOME/sockets" \
        "$VAGG_HOME/dns-config" \
        "$VAGG_HOME/backups"
    install -d -m 0755 "$VAGG_ETC"
}

generate_env() {
    local env_file="$VAGG_ETC/core.env"
    if [[ -f "$env_file" ]] && [[ $RESET -eq 0 ]]; then
        log "core.env já existe — reaproveitando (use --reset para refazer)"
        return 0
    fi
    log "gerando secrets de TESTE em $env_file..."
    local jwt_secret
    jwt_secret="$(openssl rand -hex 32)"
    local admin_password
    admin_password="$(openssl rand -base64 18 | tr -d '/+=')"
    local admin_hash
    admin_hash="$(docker run --rm ghcr.io/rduarte6982/vagg/core:test \
        python -m vagg_core.scripts.hash_password "$admin_password")"
    local lan_ip
    lan_ip="$(detect_lan_ip)"

    umask 077
    cat >"$env_file" <<EOF
VAGG_CORE_ENVIRONMENT=test
VAGG_CORE_LOG_LEVEL=INFO
VAGG_CORE_DOMAIN=$lan_ip
VAGG_CORE_DATABASE_URL=sqlite+aiosqlite:////var/lib/vagg/db/vagg-core.db
VAGG_CORE_JWT_SECRET=$jwt_secret
VAGG_CORE_ADMIN_EMAIL=$ADMIN_EMAIL
VAGG_CORE_ADMIN_PASSWORD_HASH=$admin_hash
VAGG_CORE_LICENSE_KEY=test-license-no-validation
VAGG_CORE_LICENSE_SERVER=http://127.0.0.1:9999
VAGG_CORE_NETWORK_APPLY_ENABLED=false
VAGG_CORE_DNS_ENABLED=true
VAGG_CORE_DNS_CONFIG_PATH=/var/lib/vagg/dns-config/Corefile
VAGG_CORE_DNS_CONTAINER_NAME=vagg-dns
VAGG_CORE_TUNNELS_CONFIG_DIR=/var/lib/vagg/clients
VAGG_CORE_TUNNELS_SOCKETS_DIR=/var/lib/vagg/sockets
VAGG_CORE_TUNNELS_IMAGE_TAG=test
VAGG_REGISTRY=ghcr.io/rduarte6982/vagg
VAGG_VERSION=test
EOF
    chmod 0640 "$env_file"

    cat >"$VAGG_ETC/admin-credentials.txt" <<EOF
========================================================================
INSTALAÇÃO DE TESTE — credenciais iniciais
========================================================================
URL    : http://${lan_ip}:8443
Login  : ${ADMIN_EMAIL}
Senha  : ${admin_password}
========================================================================
ATENÇÃO: este é um ambiente de TESTE (sem TLS, sem licença real).
NÃO use para acessar redes de clientes em produção.
========================================================================
EOF
    chmod 0600 "$VAGG_ETC/admin-credentials.txt"
    log "senha temporária em $VAGG_ETC/admin-credentials.txt"
}

deploy_compose() {
    log "subindo stack via docker compose..."
    install -m 0644 \
        "$REPO_DIR/installer/compose/docker-compose.test.yml" \
        "$VAGG_ETC/docker-compose.yml"
    docker compose -f "$VAGG_ETC/docker-compose.yml" --env-file "$VAGG_ETC/core.env" \
        up -d --remove-orphans
}

run_migrations() {
    log "rodando alembic upgrade head..."
    docker run --rm \
        --env-file "$VAGG_ETC/core.env" \
        -v "$VAGG_HOME/db:/var/lib/vagg/db" \
        ghcr.io/rduarte6982/vagg/core:test \
        alembic upgrade head
}

health_check() {
    log "aguardando vagg-core responder..."
    local i
    for i in {1..30}; do
        if curl -fs --max-time 2 http://127.0.0.1:8443/api/v1/system/health >/dev/null; then
            log "OK"
            return 0
        fi
        sleep 2
    done
    fail "vagg-core não respondeu em 60s — 'docker compose -f $VAGG_ETC/docker-compose.yml logs vagg-core'"
}

print_summary() {
    local lan_ip
    lan_ip="$(detect_lan_ip)"
    log ""
    log "============================================================"
    log "Instalação de TESTE concluída."
    log ""
    log "Painel admin    : http://${lan_ip}:8443"
    log "Portal auditor  : http://${lan_ip}:8444"
    log "Login           : ${ADMIN_EMAIL}"
    log "Senha           : cat $VAGG_ETC/admin-credentials.txt"
    log ""
    log "Comandos úteis:"
    log "  Logs    : docker compose -f $VAGG_ETC/docker-compose.yml logs -f"
    log "  Stop    : docker compose -f $VAGG_ETC/docker-compose.yml down"
    log "  Reset   : sudo bash scripts/test-install.sh --reset"
    log "============================================================"
}

main() {
    require_root
    parse_args "$@"
    [[ $RESET -eq 1 ]] && reset_state
    ensure_docker
    build_images
    prepare_dirs
    run_migrations
    generate_env
    deploy_compose
    health_check
    print_summary
}

main "$@"
