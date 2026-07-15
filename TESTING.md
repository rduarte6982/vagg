# TESTING — como testar o vagg

Existem **quatro** caminhos pra colocar a aplicação na sua frente, do
mais rápido pro mais completo. Escolha o que se encaixa no que você
quer verificar.

| Caminho | Onde | O que valida | Tempo |
|---|---|---|---|
| 1. Demo standalone | qualquer SO | Visual / UX | 1 min |
| 2. Stack Docker (sem VPN real) | qualquer SO | API + UI integradas | 5 min |
| 3. Híbrido | qualquer SO | DX (hot reload) | 5 min |
| **4. Lab VPN ponta-a-ponta** | **WSL2 ou Linux** | **NAT, túnel, NETMAP** | **20 min** — ver [`dev/VPN-LAB.md`](dev/VPN-LAB.md) |

---

## 1. Modo demonstração — só Front-End, sem backend (1 minuto)

Use se você quer **ver o visual**, navegar pelas telas, criar/excluir
clientes fake, sem subir Docker. Os dados ficam no `sessionStorage` do
navegador e somem ao fechar a aba.

```bash
cd ui/
npm install
npm run dev
```

Abra **http://localhost:5173/?demo=1** — o banner amarelo no topo
confirma que o modo demo está ativo.

- Login: qualquer e-mail e senha funcionam (auto-preenchidos).
- Dashboards, listagens, criação e exclusão funcionam normalmente.
- A página **Sistema** tem um botão "Recriar dados de exemplo" e um
  "Sair do modo demo".

Para o portal de transparência:

```bash
cd portal/
npm install
npm run dev      # http://localhost:5174/?demo=1
```

---

## 2. Stack completa via Docker Compose (5 minutos)

Use se você quer **testar de verdade**: API real, banco SQLite, JWT,
audit chain, criação de clientes via UI etc. — tudo num único host, sem
mexer em iptables ou DNS.

### 2.1. Pré-requisitos

- Docker Desktop ≥ 4.30 (Windows/macOS) ou Docker Engine 24+ no Linux
- 2 GB de RAM livres, 1 GB de disco
- Linux/macOS/WSL: `bash`, `openssl`, `jq`, `curl`
- Windows nativo: PowerShell 7 e os scripts `.ps1`

### 2.2. Bootstrap

Gera `dev/dev.env` com hash argon2 da senha admin e segredo JWT
aleatório. Idempotente.

```bash
cd dev/
./bootstrap.sh                     # senha "admin"
# ou: ./bootstrap.sh --password "Tr0c@gora" --email "admin@empresa.com"
```

Windows:
```powershell
cd dev\
.\bootstrap.ps1
```

### 2.3. Subir tudo

```bash
docker compose --env-file dev.env up -d --build
```

Primeira vez: ~2-3 min de build (core, ui, portal). Depois: <30 s.
Acompanhe com `docker compose logs -f`.

### 2.4. Popular dados (opcional, recomendado)

```bash
./seed.sh        # bash
.\seed.ps1       # PowerShell
```

Cria 3 clientes (Petróleo / Lojas Urano / Banco Azul), 3 consultores
e 3 políticas. Idempotente.

### 2.5. Acessar

| Serviço         | URL                              | Credenciais                  |
| --------------- | -------------------------------- | ---------------------------- |
| **Admin UI**    | http://localhost:8080            | admin@vagg.local / admin     |
| **Portal**      | http://localhost:8081            | magic link via e-mail        |
| API (Swagger)   | http://localhost:8443/docs       | Bearer JWT da Admin UI       |

> ⚠️ Os túneis VPN reais **não conectam** neste compose (`network_mode:
> host` está desligado para não tocar no iptables do seu Windows). A UI
> mostra os clientes corretamente, criação/leitura/exclusão funciona, e
> o botão Conectar dispara a chamada à API mas a tentativa de subir o
> container do túnel falha sem o host networking. Isso é intencional —
> em produção, o `installer/install.sh` configura o ambiente correto.

### 2.6. Limpar

```bash
docker compose down -v        # apaga o volume SQLite
rm -f dev.env                 # opcional
```

---

## 3. Modo híbrido — front com hot-reload + backend real (avançado)

Útil se você está iterando em CSS/UX e quer ver as mudanças
instantaneamente, mas conectado num core de verdade.

```bash
# Terminal 1 — só o core
cd dev/
./bootstrap.sh
docker compose --env-file dev.env up -d --build vagg-core
./seed.sh

# Terminal 2 — UI com hot reload (proxy /api → 8443)
cd ui/
npm install && npm run dev   # http://localhost:5173

# Terminal 3 — Portal com hot reload
cd portal/
npm install && npm run dev   # http://localhost:5174
```

Os dois `vite.config.ts` já fazem proxy de `/api` e `/portal` para
`localhost:8443`.

---

## Smoke test rápido (5 cliques)

Depois que a stack subir, valide que está tudo OK:

1. Abra http://localhost:8080 → faça login (`admin@vagg.local` / `admin`)
2. **Dashboard** deve mostrar mapa de topologia + 4 stat tiles +
   atividade recente
3. **Clientes** deve listar 3 itens (se rodou seed) com LEDs verde/amarelo
4. Clique **Novo cliente** → modal abre, preencha qualquer coisa, salve
5. **Auditoria** deve mostrar uma linha `client.create` recém-adicionada

Se tudo funcionou, o agregador está funcional.

---

## Rodando os testes automatizados

```bash
# Front (vitest + jsdom + testing-library)
cd ui     && npm install && npm test
cd portal && npm install && npm test

# Backend (pytest async + sqlite ephemeral)
cd core/
python -m pip install -e .[dev]
pytest -ra
```

---

## Problemas comuns

- **Login retorna 401 mesmo com senha correta** → o `VAGG_ADMIN_PASSWORD_HASH`
  pode estar de uma versão anterior do core. Rode
  `./bootstrap.sh --force` e suba de novo.
- **Porta 8080/8081/8443 já em uso** → edite o `ports:` em
  `dev/docker-compose.yml`.
- **Erro "vagg-core: name resolution"** dentro da UI/Portal → verifique
  que `vagg-core` está com `condition: service_healthy`. Aguarde alguns
  segundos extras.
- **Tudo o mais** → `docker compose logs -f vagg-core`.
