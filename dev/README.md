# vagg · ambiente de teste local

Esta pasta contém scripts e um docker-compose simplificado para subir o
**vagg-core**, **Admin UI** e **Portal de Transparência** numa máquina de
desenvolvimento (Linux / macOS / Windows) sem precisar reconfigurar
iptables, DNS ou TLS. SQLite em volume, autenticação real, dados
populados via seed.

> ⚠️ **Não usar em produção.** Este compose desabilita o `network_mode:
> host`, o `network_apply_enabled` e o DNS layer. Veja
> `installer/compose/docker-compose.yml` para a stack real.

## Pré-requisitos

- **Docker Desktop** ≥ 4.30 (ou Docker Engine 24+ e Compose v2)
- macOS / Linux: `bash`, `openssl`, `jq`, `curl`
- Windows: PowerShell 7 (recomendado) — use os scripts `*.ps1`

## Passo a passo

### 1. Bootstrap (gera senhas / segredos)

**bash / WSL / macOS:**
```bash
cd dev/
./bootstrap.sh                       # senha "admin", e-mail admin@vagg.local
./bootstrap.sh --password Tr0c@gora  # custom
```

**Windows (PowerShell):**
```powershell
cd dev\
.\bootstrap.ps1                                  # senha "admin"
.\bootstrap.ps1 -Password 'Tr0c@gora'            # custom
```

Isso cria `dev.env` (não commitado) com:
- `VAGG_ADMIN_EMAIL`
- `VAGG_ADMIN_PASSWORD_HASH` (argon2 — gerado dentro do container vagg-core)
- `VAGG_JWT_SECRET` (48 bytes random)

### 2. Subir a stack

```bash
docker compose --env-file dev.env up -d --build
```

Espere ~30 s no primeiro boot enquanto as imagens são construídas e o
core roda as migrations Alembic. Acompanhe com `docker compose logs -f`.

### 3. Popular dados de exemplo (opcional)

**bash:**
```bash
./seed.sh
```

**PowerShell:**
```powershell
.\seed.ps1
```

O seed cria 3 clientes (Petróleo / Lojas Urano / Banco Azul), 3
consultores e 3 políticas. É idempotente — pode rodar de novo sem
duplicar.

### 4. Acessar

| Serviço         | URL                              | Credenciais                  |
| --------------- | -------------------------------- | ---------------------------- |
| Admin UI        | http://localhost:8080            | admin@vagg.local / admin     |
| Portal          | http://localhost:8081            | (magic link via email)       |
| API (Swagger)   | http://localhost:8443/docs       | Bearer JWT da Admin UI       |

## Limpar

```bash
docker compose down -v   # apaga o volume com SQLite
rm -f dev.env
```

## Rodar SEM Docker — modo demonstração

Se você só quer **ver a UI** (sem backend, sem dados reais), use o
modo demo embutido — ele desvia todas as chamadas pra um banco em
memória. Ótimo pra apresentação ou screenshots:

```bash
cd ui/
npm install
npm run dev
# abra http://localhost:5173/?demo=1
```

O banner amarelo no topo indica que o modo demo está ativo. Para sair:
adicione `?demo=0` na URL ou abra a página **Sistema** e clique em
"Sair do modo demo".

Idem para o portal:
```bash
cd portal/
npm install
npm run dev    # http://localhost:5174/?demo=1
```

## Modo híbrido (hot-reload + backend real)

Para iterar no front-end com hot-reload mas falando com um vagg-core de
verdade:

```bash
# Terminal 1 — só o core via compose
cd dev/
docker compose --env-file dev.env up -d --build vagg-core
./seed.sh

# Terminal 2 — UI dev server (proxy /api → 8443 via vite.config)
cd ui/
npm run dev      # http://localhost:5173

# Terminal 3 — Portal dev server
cd portal/
npm run dev      # http://localhost:5174
```

Os dois `vite.config.ts` já fazem o proxy correto para `localhost:8443`.

## Troubleshooting

**`bootstrap.sh` falha com "openssl: command not found"**  
Windows nativo: prefira `bootstrap.ps1`. Linux/macOS: `apt install
openssl` ou `brew install openssl`.

**`docker compose up` mostra `unhealthy` no vagg-core**  
Veja `docker compose logs vagg-core`. As migrations rodam no boot — se a
imagem é nova, isso pode demorar até 30s. O healthcheck retenta por 30
ciclos.

**Login dá 401 mesmo com a senha certa**  
Verifique se o `VAGG_ADMIN_PASSWORD_HASH` no `dev.env` foi gerado pelo
mesmo build do core. Se você reconstruiu a imagem com mudanças no
argon2, regenere com `./bootstrap.sh --force`.

**Quero reset total**  
```bash
docker compose down -v
./bootstrap.sh --force
docker compose --env-file dev.env up -d --build
./seed.sh
```
