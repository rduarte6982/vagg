# vagg-core

Cérebro do VPN Aggregator. API REST FastAPI com SQLite (WAL) que faz CRUD de clientes, consultores, policies, mapeamentos NAT, orquestra túneis (Fase 3+), gera regras iptables (Fase 4+), e expõe audit log (Fase 9+).

Implementa a **Fase 2** do plano: esqueleto com auth + CRUD funcional dos 3 recursos principais (clients, consultants, policies). Tunnel actions (`/connect`, `/disconnect`, `/otp`, `/logs`) ficam stubadas com 202/501 até a Fase 3.

Especificação na Seção 5.1 do [SPEC](../docs/SPEC.md).

## Endpoints

| Método | Caminho | Função | Status |
|---|---|---|---|
| POST | `/api/v1/auth/login` | OAuth2 password flow → access + refresh JWT | ✅ |
| POST | `/api/v1/auth/refresh` | Renova access via refresh token | ✅ |
| GET / POST / PATCH / DELETE | `/api/v1/clients[/{id}]` | CRUD de tenants | ✅ |
| GET / POST / PATCH / DELETE | `/api/v1/consultants[/{id}]` | CRUD de consultores | ✅ |
| GET / POST / DELETE | `/api/v1/policies[/{id}]` | CRUD de policies (RBAC) | ✅ |
| POST | `/api/v1/clients/{id}/connect` | Sobe túnel | 🟡 stub (202) |
| POST | `/api/v1/clients/{id}/disconnect` | Derruba túnel | 🟡 stub (202) |
| POST | `/api/v1/clients/{id}/otp` | Envia OTP ao container | 🟡 stub (501) |
| GET | `/api/v1/clients/{id}/status` | Estado do túnel | ✅ (lê DB) |
| GET | `/api/v1/clients/{id}/logs` | Tail dos logs | 🟡 stub |
| GET | `/api/v1/audit` | Lista eventos | ✅ |
| GET | `/api/v1/system/{health,version,license,metrics}` | Operacional | ✅ (license e metrics são stub) |

OpenAPI navegável em `/docs`.

## Decisões técnicas

- **DB:** SQLite WAL (SPEC §2.1), driver `aiosqlite` (Apache 2.0). Pragmas `foreign_keys=ON` e `journal_mode=WAL` aplicados em cada conexão.
- **Auth:** OAuth2 password flow + JWT HS256 (SPEC §2.2). Hash de senha com argon2-cffi.
- **Admin único bootstrap:** vem de env vars (`VAGG_CORE_ADMIN_EMAIL`, `VAGG_CORE_ADMIN_PASSWORD_HASH`). Multi-admin é feature de fase posterior.
- **Sem `app = create_app()` no module-load:** uvicorn usa factory mode (`--factory`), evitando avaliar Settings no import.

## Setup local

```bash
# Hash da senha bootstrap
python -m vagg_core.scripts.hash_password 'sua-senha-strong'
# (cole o output no .env como VAGG_CORE_ADMIN_PASSWORD_HASH)

# JWT secret
openssl rand -hex 32  # cole como VAGG_CORE_JWT_SECRET no .env

# Subir
cp .env.example .env  # edite com os valores acima
pip install -e ".[dev]"
alembic upgrade head
uvicorn --factory vagg_core.main:create_app --reload --port 8443
```

Acessa `http://localhost:8443/docs` e clica em **Authorize** para autenticar.

## Desenvolvimento

```bash
ruff check .                         # lint
ruff format --check .                # format
mypy --strict src                    # types
pytest                                # full suite (sem Docker — usa SQLite tempfile)
pytest -m "not integration"          # só unit
```

## Migrations

```bash
alembic revision --autogenerate -m "descricao_curta"
alembic upgrade head
alembic downgrade -1
```

## Compliance

Todas as deps validadas contra SPEC §2.5: MIT, BSD, Apache 2.0, MPL 2.0. Driver Postgres não se aplica aqui (SQLite); o `aiosqlite` é Apache 2.0. Hash com `argon2-cffi` (MIT).
