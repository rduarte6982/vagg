#!/usr/bin/env bash
# bootstrap.sh — gera dev.env com argon2 hash da senha e JWT secret aleatório.
# Idempotente: se dev.env já existir, não sobrescreve (a menos que --force).
#
# Uso:
#   ./bootstrap.sh                 # senha "admin" / e-mail admin@vagg.local
#   ./bootstrap.sh --force         # sobrescreve dev.env
#   ./bootstrap.sh --password X    # usa senha "X"
#   ./bootstrap.sh --email a@b.c   # usa e-mail "a@b.c"

set -euo pipefail

cd "$(dirname "$0")"

PASSWORD="admin"
EMAIL="admin@vagg.local"
FORCE=0
ENV_FILE="dev.env"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --password) PASSWORD="$2"; shift 2 ;;
    --email)    EMAIL="$2";    shift 2 ;;
    --force)    FORCE=1;       shift ;;
    *) echo "argumento desconhecido: $1" >&2; exit 2 ;;
  esac
done

if [[ -f "$ENV_FILE" && $FORCE -eq 0 ]]; then
  echo "✓ $ENV_FILE já existe (use --force para sobrescrever)"
  exit 0
fi

echo "→ gerando $ENV_FILE"
echo "  e-mail:  $EMAIL"
echo "  senha:   $PASSWORD"

# Gera hash argon2 usando o próprio core dentro de um container efêmero.
# Não exige Python no host.
echo "  build da imagem vagg/core:dev (uma vez) ..."
docker compose build vagg-core >/dev/null 2>&1 || \
  docker build -t vagg/core:dev ../core >/dev/null

HASH=$(docker run --rm -i vagg/core:dev python -m vagg_core.scripts.hash_password "$PASSWORD")

# JWT secret: 48 bytes random base64. openssl é universal.
JWT=$(openssl rand -base64 48 | tr -d '\n')

cat > "$ENV_FILE" <<EOF
# Gerado por bootstrap.sh em $(date -Iseconds)
# Não comitar este arquivo — contém senhas hash e segredo JWT.

VAGG_ADMIN_EMAIL=$EMAIL
VAGG_ADMIN_PASSWORD_HASH=$HASH
VAGG_JWT_SECRET=$JWT
EOF

echo
echo "✓ $ENV_FILE pronto."
echo
echo "Próximos passos:"
echo "  docker compose --env-file $ENV_FILE up -d --build"
echo "  ./seed.sh        # popular clientes/consultores de exemplo"
echo
echo "Acesso:"
echo "  http://localhost:8080  → Admin UI ($EMAIL / $PASSWORD)"
echo "  http://localhost:8081  → Portal de Transparência"
echo "  http://localhost:8443/docs  → Swagger da API"
