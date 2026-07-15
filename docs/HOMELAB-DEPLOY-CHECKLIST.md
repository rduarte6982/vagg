# Homelab deploy — checklist pós-sessão 2026-05-25

Mudanças desta sessão que precisam chegar no homelab pra validação end-to-end.

## 1. Pull do código + rebuild de imagens

```bash
ssh rodrigo@192.168.68.102
cd ~/projects/vagg
git pull                                    # quando os commits estiverem no main

# Imagens que mudaram:
sudo docker build -f tunnels/saml-portal/Dockerfile        -t vagg/saml-portal:test       tunnels/
sudo docker build -f tunnels/openconnect/Dockerfile        -t vagg/tunnel-openconnect:test tunnels/
sudo docker build -f core/Dockerfile                       -t vagg/core:test               core/
sudo docker build -f ui/Dockerfile                         -t vagg/ui:test                 ui/

# (portal, outros tunnels não mudaram nesta sessão)
```

## 2. Adicionar `VAGG_CORE_CRYPTO_KEY` no `.env`

Em produção a Fernet key precisa ser explícita (em dev/test ela é derivada do
jwt_secret via HKDF + warning, mas em `environment=production` falha o boot
do core).

```bash
# Gerar uma chave fresh
NEW_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
echo "VAGG_CORE_CRYPTO_KEY=$NEW_KEY" | sudo tee -a /etc/vagg/dev.env
# (se usar outro path do .env, ajustar)
```

## 3. Aplicar migration 0010_totp_secret

```bash
# Dentro do container vagg-core (que já roda alembic na inicialização normalmente):
sudo docker compose -f installer/compose/docker-compose.yml \
  -f /etc/vagg/docker-compose.override.yml \
  exec vagg-core alembic upgrade head

# Ou só restartar — o entrypoint do core deve rodar migrate automático:
sudo docker compose -f installer/compose/docker-compose.yml \
  -f /etc/vagg/docker-compose.override.yml \
  restart vagg-core

# Verificar:
sudo docker exec vagg-vagg-core-1 alembic current
# esperado: 0010_totp_secret (head)
```

## 4. Validar endpoints novos

```bash
# Login admin
TOKEN=$(curl -sS -X POST http://localhost:8443/api/v1/auth/login \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'username=admin@vagg.example' --data-urlencode 'password=admin' \
  | jq -r .access_token)

# Cadastrar cliente teste (FortiGate + SAML pra validar bypass do 403)
curl -sS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -X POST http://localhost:8443/api/v1/clients -d '{
    "id":"vexia-test","name":"Vexia Test","vpn_type":"openfortivpn",
    "virtual_cidr":"10.200.99.0/24","real_cidr":"10.99.0.0/16",
    "auth_method":"saml",
    "vpn_username":"ST297788234@vexia.com.br",
    "config_text":"host = vpnssl.vexia.com.br\nport = 10443\n",
    "nat_mappings":[]
  }'

# Cadastrar cliente teste (OTP/TOTP)
curl -sS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -X POST http://localhost:8443/api/v1/clients -d '{
    "id":"forti-otp-test","name":"FortiGate OTP","vpn_type":"openfortivpn",
    "virtual_cidr":"10.200.98.0/24","real_cidr":"10.98.0.0/16",
    "auth_method":"otp",
    "vpn_username":"user","vpn_password":"senha",
    "config_text":"host = gw.exemplo.com\nport = 10443\n",
    "nat_mappings":[]
  }'

# Cadastrar seed TOTP no cliente OTP
curl -sS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -X PUT http://localhost:8443/api/v1/clients/forti-otp-test/totp \
  -d '{"secret":"JBSWY3DPEHPK3PXP"}'
# esperado: 200 com {"has_secret": true, "digits": 6, ...}

# Preview do código TOTP gerado
curl -sS -H "Authorization: Bearer $TOKEN" \
  -X POST http://localhost:8443/api/v1/clients/forti-otp-test/totp/preview
# esperado: {"code": "<6 digits>", "seconds_remaining": <0-30>, "period": 30}
```

## 5. Validar o flow SAML real (E2E que ficou pendente)

```bash
# Cliente Vexia: dispara saml-portal
curl -sS -H "Authorization: Bearer $TOKEN" -X POST \
  http://localhost:8443/api/v1/clients/vexia-test/saml/start | jq

# → retorna portal_url ex: http://192.168.68.102:14500/
# Abrir no painel http://192.168.68.102:8080 → Clientes → vexia-test → Conectar
# Vai abrir o iframe com Firefox remoto → completar login Microsoft → aprovar push
# saml_callback.py captura SVPNCOOKIE automaticamente (bypass do 403 hostcheck)
# orchestrator sobe vagg-tunnel-openfortivpn-saml com o cookie
```

## 6. App client Windows — sem mudança de deploy necessária

O `clients/windows/` foi auditado e **não precisa de update pra esta sessão**:

- `MyClientsResponse` Go ↔ `MyClientsResponse` Python: **100% match** (mesmos campos, tipos compatíveis)
- `tokenPair` Go ↔ `TokenPair` Python: match
- Endpoint consumido: `GET /api/v1/me/clients` (shape inalterado)
- Endpoint de login: `POST /api/v1/auth/login` (agora aceita consultor também — backward-compat)
- **5/5 testes de contrato Go verdes** (`go test ./internal/api/`)

Se você reinstalar/rebuildar o client por outro motivo:
```powershell
cd clients\windows
wails build -platform=windows/amd64 -clean
```

## 7. Resumo da matriz de compat (sessão 2026-05-25)

| Componente | Mudou esta sessão? | Breaking pra client? | Ação no homelab |
|---|---|---|---|
| `clients.totp_secret` (migration 0010) | ➕ novo campo | Não | `alembic upgrade head` (auto via restart) |
| `core.crypto` (Fernet wrapper) | ➕ novo módulo | Não | setar `VAGG_CORE_CRYPTO_KEY` no .env |
| `services.totp` (RFC 6238) | ➕ novo módulo | Não | nenhuma |
| Endpoints `/clients/{id}/totp/*` | ➕ novos | Não consumidos pelo client | rebuild vagg-core |
| `auth.py` (login consultor por email/nome) | 🔄 expandido | Não — backward-compat | rebuild vagg-core |
| JWT extra claims (role/consultant_id) | 🔄 expandido | Não — token opaco no client | rebuild vagg-core |
| `tunnel_orchestrator.py` (totp_seed + UA Forti + ?redirect=1) | 🔄 expandido | API interna | rebuild vagg-core |
| `tunnels/openconnect/entrypoint.sh` (FIFO no stdin) | 🐛 fix | API interna | rebuild tunnel-openconnect |
| `tunnels/saml-portal/saml_callback.py` (novo) | ➕ novo | API interna | **rebuild saml-portal** ← crítico pro bypass |
| `ui/src/pages/Clients.tsx` (cards SAML/TOTP) | 🔄 UI | N/A (web only) | rebuild vagg-ui |
| `clients/windows/internal/api/client_test.go` | ➕ teste novo | N/A | só CI |

## 8. Rollback se algo der errado

Tag `:stable-saml-v1` ainda existe nas imagens. Pra voltar:

```bash
sudo bash deploy/snapshots/rollback-saml-v1.sh
```

(retag `:stable-saml-v1` → `:test` em todas as 8 imagens da stack SAML +
recreate via compose.)
