# VAGG — VPN Aggregator

Produto **B2B SaaS self-hosted** para consultorias de TI (foco inicial: consultorias
SAP brasileiras) gerenciarem acesso simultâneo a múltiplas VPNs de clientes finais.
A consultoria instala o **Aggregator Gateway** na própria infra, atrás da OpenVPN
corporativa; o gateway mantém túneis persistentes para todos os clientes e o
consultor enxerga as redes permitidas com DNS amigável, sem cliente VPN no notebook.

- **Repositório:** https://github.com/rduarte6982/vagg (público, Apache 2.0)
- **Histórico:** desenvolvido fora do OS (era `C:\Users\rodrigoduarte\vagg` no
  Windows); clonado para cá em **2026-07-15** para retomar a evolução.

## Fonte única da verdade

**`docs/SPEC.md`** (v1.2) — especificação mestre. Regras de uso (Seção 0):
- **Não rediscutir** as decisões fechadas da Seção 2 (stack, libs, padrões).
- Trabalhar **uma fase por vez** (roadmap de 11 fases na Seção 11); ler só a
  seção da fase + referências.
- Não criar arquivos fora da estrutura da Seção 12.
- Testes fazem parte do critério de aceite de cada fase.
- Código/variáveis em inglês; logs e UI em português.

Outros docs: `docs/KICKOFF.md` (como começar), `docs/CONTRIBUTING.md` (fluxo de PR),
`docs/MANUAL-INSTALACAO.md` (instalação p/ IT da consultoria).

## Stack (Seção 2.1 do SPEC — fechada)

| Camada | Tecnologia |
|---|---|
| Aggregator Core (API) | Python 3.12 + FastAPI + SQLite (WAL) + Alembic |
| Containers de túnel | Docker Compose; openvpn, openconnect(+SAML), openfortivpn(+SAML), strongswan, wireguard, saml-portal |
| DNS interno | CoreDNS (split-horizon) |
| Admin UI | React 18 + Vite + TanStack Query + shadcn/ui (`ui/` e `portal/`) |
| License Server | Python 3.12 + FastAPI + Postgres 16 + Stripe + Ed25519 (cloud — `license-server/`, deploy Render) |
| Alvo | Ubuntu 24.04 LTS, single-VM x86_64 com AES-NI (sem Kubernetes) |

## Estrutura

`core/` (API principal), `tunnels/` (imagens Docker por protocolo), `dns/`,
`ui/`, `portal/` (Portal de Transparência — diferencial, Fase 11),
`license-server/`, `installer/`, `deploy/`, `clients/`, `docs/`, `scripts/`.

## Como rodar

`make help` lista tudo. Principais: `make bootstrap` (deps de core+ui+license-server+
tunnels), `make lint`, `make test`, `make tunnels-build` / `make images-build`.
Testes por componente: `make test-core`, `make test-ui`, etc.

## Ambiente de teste real (dev)

- **Gateway de desenvolvimento:** VM **VAGG (ID 101)** no Proxmox — **recriada do
  zero em 2026-07-15** (a anterior, que respondia em `192.168.68.102`, foi apagada).
  - Ubuntu 24.04 LTS (cloud image + cloud-init), 4 vCPU (cpu=host, AES-NI ✓),
    8 GB RAM (balloon 4 GB), disco 60 GB qcow2 no storage `SSD`.
  - **IP estático `192.168.68.103`** (gw 192.168.68.1) — acesso: `ssh -i
    ~/.ssh/id_ed25519_vagg rodrigo@192.168.68.103` (chave da máquina Windows;
    senha de fallback no `.env` deste projeto). QEMU guest agent ativo.
  - Instalado: Docker 29 + compose v5, git, make. Repo clonado em `~/vagg`
    (main). Runtime em `/var/lib/vagg`; secrets/compose em `/etc/vagg`.
  - **Stack no ar** via `sudo bash scripts/test-install.sh` — os 4 containers
    (`vagg-test-vagg-{core,ui,dns,portal}-1`) sobem healthy. Painel admin em
    `http://192.168.68.103:8443` (API) e `http://192.168.68.103:8080` (UI);
    portal em `:8081`; UI HTTPS em `:8543`. Credenciais em
    `/etc/vagg/admin-credentials.txt` (login `admin@vagg.dev`).
  - **Snapshot Proxmox** `vagg-gateway-funcional` (2026-07-15) = baseline
    limpo e funcional (rollback via MCP se algo quebrar).
  - ⚠️ Referências antigas a `192.168.68.102` (ex.: TOMORROW.md) estão obsoletas.
- **Clientes reais usados nos testes:** MRV (GlobalProtect + SAML/Microsoft SSO —
  fluxo mais difícil) e Vexia.
- **Proxmox via MCP:** `https://proxmox-mcp.duarteapps.cloud/mcp` (streamable HTTP,
  sem auth do lado do cliente) — gerencia a VM (start/stop, exec via guest agent,
  snapshots, comandos `qm`/`pvesh` no host).
- `.mcp.json` do projeto: Playwright (validar SSO/portal) + Coolify DuarteApps.

## Estado (2026-07-15 — gateway reprovisionado e FUNCIONAL)

Gateway recriado do zero e validado ponta a ponta na VM nova. O que foi feito:

- **Control plane 100% funcional:** stack healthy, login admin OK, API/CRUD de
  clientes OK, DNS (CoreDNS) gerando Corefile, TLS self-signed, UI e Portal
  renderizando (login "vagg. by ROIT" + dashboard com topologia da rede).
- **Data plane (orquestração) validado:** ao dar `connect`, o core cria e sobe o
  container `vagg-tunnel-<cliente>` via docker.sock e o `tunnel-controller` binda
  o control socket — **exatamente a máquina que estava quebrada no TOMORROW.md**.
- **Clientes cadastrados** (prontos p/ conectar): `vexia-test` (openfortivpn+SAML)
  e `forti-otp-test` (openfortivpn+TOTP, demo).
- **8 imagens de túnel + 3 SAML** buildadas com o nome correto (`vagg/tunnel-*:test`).

Durante o reprovisionamento foram descobertos e corrigidos **8 bugs de
fresh-install** (nenhum aparecia na VM antiga, que tinha estado herdado) —
ver commit `3544c91` e os `fix(installer)` anteriores. Todos já commitados no
repo local da VM; **push ao GitHub pendente de aprovação do Rodrigo**.

### Data path LIGADO (2026-07-15) — clientes FortiClient reais

- Cadastrados e **conectados de verdade** (openfortivpn, sem MFA): **LongPing**
  (`vpn.lpht.com.br`, real_cidr `10.80.0.0/16`) e **Brasanitas**
  (`vpn.grupobrasanitas.com.br`, real_cidr `10.210.0.0/16`). Túneis autenticam
  e o gateway alcança os SAP: LongPing `10.80.90.124/26/91.151:3200`,
  Brasanitas `10.210.5.x:32NN` — todos OPEN.
- **Encaminhamento habilitado** no gateway via `vagg-forward.service` (systemd,
  enabled): `ip_forward=1` + `iptables -t nat -A POSTROUTING -o ppp+ -j
  MASQUERADE` + FORWARD ACCEPT nas ppp. Provado com container bridge alcançando
  os SAP. (Em produção quem gerencia isso é o core com `NETWORK_APPLY_ENABLED=1`.)
- **Consultor de teste:** `consultor.demo@vagg.dev` / `demo1234`, com policies
  `full` p/ LongPing e Brasanitas → `/me/routes` devolve `10.80.0.0/16` e
  `10.210.0.0/16`.
- **Acesso do consultor:** a máquina dele precisa rotear essas faixas p/ o
  gateway `192.168.68.103`. O **VAGG Client** faz isso sozinho (next-hop =
  host do serverURL); manualmente no Windows (admin):
  `route -p add 10.80.0.0 mask 255.255.0.0 192.168.68.103` e
  `route -p add 10.210.0.0 mask 255.255.0.0 192.168.68.103`. Depois o SAP GUI
  conecta nos IPs reais.
- **VAGG Client:** serverURL = `http://192.168.68.103:8443`, login como
  consultor. Re-sincroniza sozinho (~30s) ou botão "Sincronizar agora".

### Estado (2026-07-29) — login admin consertado + client 0.7.1 publicado

- **Login do admin NUNCA tinha funcionado** nesta instalação: o parser dotenv
  do docker compose v5 interpola `$var` em valores sem aspas do env_file, e o
  hash argon2 (`$argon2id$v=19$...`) chegava mutilado ao container → 401 para
  qualquer senha. **Fix aplicado na VM:** hash entre **aspas simples** no
  `/etc/vagg/core.env` + recreate do `vagg-core`. Login atual: `admin@vagg.dev`
  (senha: ver `/etc/vagg/admin-credentials.txt` na VM — redefinida 2026-07-29).
  Consultor: `consultor.demo@vagg.dev` / `demo1234`. **Patch pendente no repo:**
  `scripts/test-install.sh` ainda grava o hash SEM aspas (instalação nova nasce
  quebrada) e o hint "admin / admin" da tela de login da UI só vale no modo
  demo (`?demo=1`) — enganoso contra gateway real.
- **VAGG Client 0.7.1 (Windows)** buildado e publicado em
  `http://192.168.68.103:8080/downloads/` (autoindex on). Fonte **só existe em
  `C:\Users\rodrigoduarte\vagg\clients\windows`** (branch
  `feat/hybrid-selfservice` do repo; não está no clone do Y:). Wails Go+React;
  toolchain completo na máquina ROIT (ISCC em
  `%LOCALAPPDATA%\Programs\Inno Setup 6`). Exes na VM em
  `/var/lib/vagg/downloads`, montado `→ /var/www/downloads:ro` no `vagg-ui`
  (a imagem da UI já serve `location /downloads/` desse alias).
- **Compose da VM (`/etc/vagg/docker-compose.yml`) tem drift vs repo**:
  `vagg-ui` com porta 8543:443 + volume TLS + extra_hosts, `vagg-core` com
  `group_add: "988"` (GID docker). Nunca editar às cegas com sed/awk — puxar,
  editar, validar com `docker compose config -q`, devolver.
- Erro clássico no client Windows: badge "service offline" + "pipe: CreateFile
  pipe: Acesso negado" = service instalado antigo (sem o fix de SDDL do pipe).
  Cura: reinstalar setup ≥0.7.1. Workaround: `route -p add <real_cidr> ...`
  apontando pro gateway (sem rota o SAP GUI dá WSAEWOULDBLOCK).

### O que falta para "produção real" (precisa do Rodrigo)

1. **Conectar um cliente REAL (MRV/Vexia):** o fluxo SAML/GlobalProtect exige
   login Microsoft + **aprovação de MFA no celular do Rodrigo** — não dá para
   automatizar. Com a stack no ar, é abrir a UI → Clientes → Conectar e aprovar
   o push. Só aí o túnel passa tráfego de verdade.
2. **NAT real:** o `test-install` sobe o core SEM `network_mode: host` (o
   compose de teste é control-plane). Para NAT/rotas de verdade usar o
   `installer/compose/docker-compose.yml` de produção (host net + NET_ADMIN +
   `VAGG_CORE_NETWORK_APPLY_ENABLED=true` + crypto key) via `installer/install.sh`.
3. Escolher a próxima fase do roadmap (Seção 11 do SPEC).
3. License Server: conferir estado do deploy (Render) e integração Stripe
   (conta Stripe ainda com setup incompleto — ver backlog do OS).
4. Criar o symlink `AGENTS.md → CLAUDE.md` (convenção do OS) — precisa ser feito
   no Mac (`ln -s CLAUDE.md AGENTS.md` nesta pasta); o Windows não tem permissão
   de criar symlink no share.
