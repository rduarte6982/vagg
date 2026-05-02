#!/usr/bin/env bash
# install.sh — instalador idempotente do VPN Aggregator (SPEC §9 / Fase 10).
#
# Uso:
#   sudo bash install.sh \
#     --license-key=VAGG-XXXX-XXXX-XXXX \
#     --domain=vpn.consultoria.com.br \
#     --admin-email=ti@consultoria.com.br
#
# Idempotência: re-rodar com os mesmos argumentos é seguro. Re-rodar com
# argumentos diferentes atualiza somente o que mudou.

set -Eeuo pipefail
IFS=$'\n\t'

# ----- Defaults / paths -----

VAGG_HOME="${VAGG_HOME:-/var/lib/vagg}"
VAGG_ETC="${VAGG_ETC:-/etc/vagg}"
VAGG_USER="${VAGG_USER:-vagg}"
VAGG_GROUP="${VAGG_GROUP:-vagg}"
VAGG_VERSION="${VAGG_VERSION:-latest}"
VAGG_REGISTRY="${VAGG_REGISTRY:-ghcr.io/rduarte6982/vagg}"

LICENSE_KEY=""
DOMAIN=""
ADMIN_EMAIL=""
LICENSE_SERVER="${LICENSE_SERVER:-https://licensing.vagg.io}"
SKIP_DOCKER_INSTALL=0

# ----- Utility -----

log() { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

require_root() {
    if [[ $EUID -ne 0 ]]; then
        fail "execute como root (sudo bash install.sh ...)"
    fi
}

usage() {
    sed -n '2,16p' "$0"
    exit 1
}

parse_args() {
    for arg in "$@"; do
        case "$arg" in
            --license-key=*) LICENSE_KEY="${arg#*=}" ;;
            --domain=*) DOMAIN="${arg#*=}" ;;
            --admin-email=*) ADMIN_EMAIL="${arg#*=}" ;;
            --version=*) VAGG_VERSION="${arg#*=}" ;;
            --skip-docker-install) SKIP_DOCKER_INSTALL=1 ;;
            --help|-h) usage ;;
            *) fail "argumento desconhecido: $arg (use --help)" ;;
        esac
    done

    [[ -z "$LICENSE_KEY" ]] && fail "--license-key é obrigatório"
    [[ -z "$DOMAIN" ]] && fail "--domain é obrigatório"
    [[ -z "$ADMIN_EMAIL" ]] && fail "--admin-email é obrigatório"
}

# ----- Steps -----

check_prereqs() {
    log "Verificando pré-requisitos do sistema..."
    [[ "$(uname -s)" == "Linux" ]] || fail "este instalador roda apenas em Linux"
    if ! grep -q '^ID=ubuntu$' /etc/os-release 2>/dev/null; then
        warn "distro != Ubuntu — instalador testado apenas em Ubuntu 24.04"
    fi
    command -v curl >/dev/null || apt-get install -y curl
    command -v openssl >/dev/null || apt-get install -y openssl
}

install_docker() {
    if [[ $SKIP_DOCKER_INSTALL -eq 1 ]] || command -v docker >/dev/null; then
        log "Docker já presente — pulando instalação"
        return 0
    fi
    log "Instalando Docker via repositório oficial..."
    apt-get update -y
    apt-get install -y ca-certificates curl gnupg
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
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
}

create_user_and_dirs() {
    log "Criando usuário e diretórios..."
    if ! id "$VAGG_USER" >/dev/null 2>&1; then
        useradd --system --home-dir "$VAGG_HOME" --shell /usr/sbin/nologin \
            --user-group "$VAGG_USER"
    fi
    install -d -o "$VAGG_USER" -g "$VAGG_GROUP" -m 0755 \
        "$VAGG_HOME" \
        "$VAGG_HOME/clients" \
        "$VAGG_HOME/sockets" \
        "$VAGG_HOME/dns-config" \
        "$VAGG_HOME/db" \
        "$VAGG_HOME/backups"
    install -d -o root -g root -m 0755 "$VAGG_ETC"
    # docker socket needs the vagg-core process to be able to talk to it.
    usermod -aG docker "$VAGG_USER" || true
}

generate_secrets() {
    local env_file="$VAGG_ETC/core.env"
    if [[ -f "$env_file" ]]; then
        log "Reaproveitando $env_file existente (idempotente)"
        return 0
    fi
    log "Gerando secrets em $env_file..."
    local jwt_secret
    jwt_secret="$(openssl rand -hex 32)"
    local admin_password
    admin_password="$(openssl rand -base64 18 | tr -d '/+=')"
    # Argon2 hash via container temporário do vagg-core.
    local admin_hash
    admin_hash="$(docker run --rm "${VAGG_REGISTRY}/core:${VAGG_VERSION}" \
        python -m vagg_core.scripts.hash_password "$admin_password")"
    umask 077
    cat >"$env_file" <<EOF
VAGG_CORE_ENVIRONMENT=production
VAGG_CORE_LOG_LEVEL=INFO
VAGG_CORE_DOMAIN=${DOMAIN}
VAGG_CORE_DATABASE_URL=sqlite+aiosqlite:////var/lib/vagg/db/vagg-core.db
VAGG_CORE_JWT_SECRET=${jwt_secret}
VAGG_CORE_ADMIN_EMAIL=${ADMIN_EMAIL}
VAGG_CORE_ADMIN_PASSWORD_HASH=${admin_hash}
VAGG_CORE_LICENSE_KEY=${LICENSE_KEY}
VAGG_CORE_LICENSE_SERVER=${LICENSE_SERVER}
VAGG_CORE_NETWORK_APPLY_ENABLED=true
VAGG_CORE_DNS_ENABLED=true
VAGG_CORE_DNS_CONFIG_PATH=/var/lib/vagg/dns-config/Corefile
VAGG_CORE_DNS_CONTAINER_NAME=vagg-dns
VAGG_CORE_TUNNELS_CONFIG_DIR=/var/lib/vagg/clients
VAGG_CORE_TUNNELS_SOCKETS_DIR=/var/lib/vagg/sockets
VAGG_CORE_TUNNELS_IMAGE_TAG=${VAGG_VERSION}
EOF
    chmod 0640 "$env_file"
    chown root:"$VAGG_GROUP" "$env_file"

    cat >"$VAGG_ETC/admin-credentials.txt" <<EOF
========================================================================
VPN AGGREGATOR — credenciais iniciais do admin
========================================================================
URL    : https://${DOMAIN}:8443
Login  : ${ADMIN_EMAIL}
Senha  : ${admin_password}
========================================================================
TROQUE A SENHA NO PRIMEIRO LOGIN e remova este arquivo:
  rm /etc/vagg/admin-credentials.txt
========================================================================
EOF
    chmod 0600 "$VAGG_ETC/admin-credentials.txt"
    log "Senha temporária do admin escrita em $VAGG_ETC/admin-credentials.txt"
}

install_compose() {
    log "Instalando docker-compose stack em $VAGG_ETC/docker-compose.yml..."
    install -m 0644 -o root -g root \
        "$(dirname "$0")/compose/docker-compose.yml" \
        "$VAGG_ETC/docker-compose.yml"
}

install_systemd() {
    log "Instalando unidades systemd..."
    install -m 0644 -o root -g root \
        "$(dirname "$0")/systemd/vagg.service" \
        /etc/systemd/system/vagg.service
    install -m 0644 -o root -g root \
        "$(dirname "$0")/systemd/vagg-update.service" \
        /etc/systemd/system/vagg-update.service
    install -m 0644 -o root -g root \
        "$(dirname "$0")/systemd/vagg-update.timer" \
        /etc/systemd/system/vagg-update.timer
    install -m 0755 -o root -g root \
        "$(dirname "$0")/bin/vagg-update" \
        /usr/local/bin/vagg-update
    systemctl daemon-reload
    systemctl enable --now vagg.service
    systemctl enable --now vagg-update.timer
}

pull_images() {
    log "Baixando imagens Docker..."
    local tag="$VAGG_VERSION"
    docker pull "${VAGG_REGISTRY}/core:${tag}"      || warn "imagem core:${tag} ausente"
    docker pull "${VAGG_REGISTRY}/ui:${tag}"        || warn "imagem ui:${tag} ausente"
    for proto in openvpn openconnect openfortivpn wireguard strongswan; do
        docker pull "${VAGG_REGISTRY}/tunnel-${proto}:${tag}" \
            || warn "imagem tunnel-${proto}:${tag} ausente — habilite o cliente correspondente após o pull manual"
    done
    docker pull coredns/coredns:1.11.1 || warn "imagem coredns ausente"
}

run_migrations() {
    log "Rodando migrations alembic..."
    docker run --rm \
        --env-file "$VAGG_ETC/core.env" \
        -v "$VAGG_HOME/db:/var/lib/vagg/db" \
        "${VAGG_REGISTRY}/core:${VAGG_VERSION}" \
        alembic upgrade head
}

start_stack() {
    log "Subindo stack via systemd (vagg.service)..."
    systemctl restart vagg.service
}

health_check() {
    log "Aguardando vagg-core responder..."
    local i
    for i in {1..30}; do
        if curl -fs --max-time 2 http://127.0.0.1:8443/api/v1/system/health >/dev/null; then
            log "vagg-core respondendo OK"
            return 0
        fi
        sleep 2
    done
    fail "vagg-core não respondeu após 60s — verifique 'journalctl -u vagg.service'"
}

print_summary() {
    log ""
    log "============================================================"
    log "Instalação concluída."
    log ""
    log "Painel:    https://${DOMAIN}:8443"
    log "Login:     ${ADMIN_EMAIL}"
    log "Senha:     ver $VAGG_ETC/admin-credentials.txt"
    log ""
    log "Logs:      journalctl -u vagg.service -f"
    log "Atualizar: sudo vagg-update"
    log "============================================================"
}

# ----- Main -----

main() {
    require_root
    parse_args "$@"
    check_prereqs
    install_docker
    create_user_and_dirs
    pull_images
    generate_secrets
    install_compose
    install_systemd
    run_migrations
    start_stack
    health_check
    print_summary
}

main "$@"
