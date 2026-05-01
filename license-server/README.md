# vagg-license-server

Servidor de licenciamento do VPN Aggregator. Emite e renova licenças JWT assinadas com Ed25519, validadas localmente pelo `vagg-core` em cada instalação. Integra com Stripe Subscriptions via webhooks.

Implementa a Fase 1 do plano de [implementação](../docs/SPEC.md). Especificação completa nas Seções 2 e 6 do SPEC.

## Endpoints

| Método | Caminho | Função |
|---|---|---|
| POST | `/api/v1/activate` | Primeira ativação. Vincula `instance_id` + `fingerprint`. Retorna JWT. |
| POST | `/api/v1/refresh` | Renovação diária. Retorna JWT novo (TTL 7 dias). |
| POST | `/webhooks/stripe` | Webhook Stripe (signature-verified). |
| GET | `/health` | Liveness check. |
| GET | `/version` | Versão do servidor. |
| GET | `/docs` | OpenAPI/Swagger UI. |

## Decisões técnicas

- **Algoritmo de assinatura:** Ed25519 (EdDSA no JWT). Mais rápido que RSA, chaves pequenas. Chave pública embarcada em `vagg-core` (SPEC §6.6).
- **Driver Postgres:** `asyncpg` (Apache 2.0). Não usar `psycopg` (LGPL).
- **TTL do JWT:** 7 dias. Refresh acontece diariamente; grace period de 14 dias é decisão do `vagg-core` (SPEC §6.4), não do servidor.
- **Idempotência de webhook:** cada `event.id` é processado no máximo uma vez (`stripe_webhook_deliveries`).
- **Anti-tampering:** instance_id + fingerprint_hash são vinculados na primeira ativação. Mismatch retorna 409. Migração entre hosts exige reativação manual via suporte (SPEC §6.6).

## Setup local

```bash
# 1. Gerar par Ed25519 (uma vez por ambiente)
python -m vagg_license.scripts.generate_keypair --out-dir .secrets

# 2. Copiar template e preencher .env
cp .env.example .env
# edite .env com:
#   - VAGG_LICENSE_JWT_PRIVATE_KEY_PEM=$(cat .secrets/private.pem)
#   - VAGG_LICENSE_JWT_PUBLIC_KEY_PEM=$(cat .secrets/public.pem)
#   - VAGG_LICENSE_STRIPE_API_KEY=sk_test_...
#   - VAGG_LICENSE_STRIPE_WEBHOOK_SECRET=whsec_... (do Stripe CLI ou dashboard)
#   - VAGG_LICENSE_STRIPE_PRICE_ID_* com seus price IDs Stripe Test Mode

# 3. Subir Postgres + servidor
docker compose up -d
docker compose logs -f license-server
```

Rodar migrations manualmente (já roda no `CMD` do Dockerfile):

```bash
docker compose exec license-server alembic upgrade head
```

## Desenvolvimento

```bash
# Instalar deps + extras de dev
pip install -e ".[dev]"

# Lint + format check
ruff check .
ruff format --check .

# Type check
mypy --strict src

# Testes
pytest                      # com testcontainers (precisa Docker)
pytest -m "not integration" # só unitários (sem Docker)

# Subir servidor em dev
uvicorn vagg_license.main:app --reload --port 8080
```

### Testando webhooks com Stripe CLI

```bash
# Encaminha eventos do Stripe Test Mode para o servidor local
stripe listen --forward-to localhost:8080/webhooks/stripe

# A CLI imprime "whsec_..." — use esse valor em VAGG_LICENSE_STRIPE_WEBHOOK_SECRET

# Em outro terminal: dispara um evento de teste
stripe trigger customer.subscription.created
```

## Deploy

### Render (recomendado para começar)

```bash
# 1. Renderizar render.yaml (na raiz do monorepo, mas referencia rootDir: license-server)
render blueprint apply

# 2. No painel Render, preencher os secrets que ficaram com sync: false:
#    VAGG_LICENSE_JWT_PRIVATE_KEY_PEM, VAGG_LICENSE_JWT_PUBLIC_KEY_PEM
#    VAGG_LICENSE_STRIPE_API_KEY, VAGG_LICENSE_STRIPE_WEBHOOK_SECRET
#    VAGG_LICENSE_STRIPE_PRICE_ID_*

# 3. Configurar webhook endpoint no Stripe Dashboard:
#    URL: https://vagg-license-server.onrender.com/webhooks/stripe
#    Eventos:
#      - customer.subscription.created
#      - customer.subscription.updated
#      - customer.subscription.deleted
#      - customer.subscription.paused
#      - invoice.payment_failed
#      - invoice.payment_succeeded
```

### Cloud Run / Fly.io

O `Dockerfile` é portável. Para Cloud Run, fazer push para Artifact Registry e `gcloud run deploy`. Para Fly.io, `fly launch` e configurar secrets via `fly secrets set`.

## Migrations

```bash
# Gerar migration nova (a partir de mudanças nos models)
alembic revision --autogenerate -m "descricao_curta"

# Aplicar
alembic upgrade head

# Reverter (cuidado em produção)
alembic downgrade -1
```

## Compliance de licenças

Todas as deps validadas contra SPEC §2.5 (sem AGPL, GPL-3, SSPL, BSL, FCL). Rodar `make license-check` da raiz do monorepo para revalidar.
