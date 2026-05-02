# vagg-installer

Instalador idempotente do VPN Aggregator (SPEC §9 / Fase 10).

## Conteúdo

```
installer/
├── install.sh              # bootstrap completo (Ubuntu 24.04)
├── compose/
│   └── docker-compose.yml  # stack vagg-core + vagg-ui + vagg-dns
├── systemd/
│   ├── vagg.service        # supervisor do compose
│   ├── vagg-update.service # roda /usr/local/bin/vagg-update --quiet
│   └── vagg-update.timer   # diário 03:30
└── bin/
    └── vagg-update         # update + rollback automático
```

## Instalar

Em VM Ubuntu 24.04 limpa, com SSH como root/sudoer:

```bash
curl -fsSL https://install.vagg.io/install.sh -o /tmp/vagg-install.sh
sha256sum /tmp/vagg-install.sh        # confronte com checksums.txt publicado

sudo bash /tmp/vagg-install.sh \
    --license-key=VAGG-XXXX-XXXX-XXXX \
    --domain=vpn.consultoria.com.br \
    --admin-email=ti@consultoria.com.br
```

O instalador:
1. Valida pré-requisitos (Ubuntu, root, conectividade).
2. Instala Docker engine + compose plugin.
3. Cria usuário `vagg`, grupo `vagg`, dirs em `/var/lib/vagg` e `/etc/vagg`.
4. Pula imagens Docker do registry GHCR.
5. Gera secrets (JWT secret, senha admin, hash Argon2) — escritos em
   `/etc/vagg/core.env` (mode 0640) e `/etc/vagg/admin-credentials.txt`
   (mode 0600). A senha do admin é exibida uma única vez.
6. Instala compose stack + unidades systemd.
7. Roda `alembic upgrade head` num container temporário.
8. `systemctl enable --now vagg.service`.
9. Aguarda /api/v1/system/health responder (timeout 60s).

## Idempotência

Re-rodar `install.sh` com os mesmos argumentos:
- não re-gera o `core.env` se ele existir
- pula Docker install se já presente
- atualiza só os arquivos cujo conteúdo mudou (compose / systemd)
- `alembic upgrade head` é seguro mesmo em DB já migrado

Re-rodar com `--license-key` diferente: o novo valor sobrescreve só
após você apagar o `core.env` (proteção contra `argv` typos).

## Atualizações

```bash
sudo /usr/local/bin/vagg-update
```

Comportamento:
1. Snapshot de `/var/lib/vagg/db` + `/etc/vagg/core.env` em
   `/var/lib/vagg/backups/<timestamp>/`. Mantém os 14 mais recentes.
2. Lê `https://updates.vagg.io/manifest.json` (`{"latest": "..."}`).
3. Se igual à versão atual: noop.
4. Senão: troca o tag em `core.env`, `docker compose pull`, `up -d`,
   roda alembic upgrade.
5. Health check 30 × 2s. Falhou → restaura snapshot + restart antigo.

A unit `vagg-update.timer` agenda diariamente 03:30 (com jitter ±15min).

## Diretórios criados

| Path | Modo | Conteúdo |
|------|------|----------|
| `/etc/vagg/core.env` | 0640 root:vagg | Secrets do core (JWT, license, hash admin) |
| `/etc/vagg/admin-credentials.txt` | 0600 root:root | Senha temporária inicial — apague após primeiro login |
| `/etc/vagg/docker-compose.yml` | 0644 | Stack |
| `/var/lib/vagg/db/` | 0755 vagg:vagg | SQLite + WAL |
| `/var/lib/vagg/clients/` | 0755 vagg:vagg | Configs por cliente (.ovpn etc.) |
| `/var/lib/vagg/sockets/` | 0755 vagg:vagg | Unix sockets do tunnel-controller |
| `/var/lib/vagg/dns-config/` | 0755 vagg:vagg | Corefile gerado pelo dns_manager |
| `/var/lib/vagg/backups/` | 0755 vagg:vagg | Snapshots de update |

## Critérios de aceite (SPEC §11 Fase 10)

- [x] Instalação clean em VM Ubuntu 24.04 vazia funciona end-to-end
- [x] Re-rodar instalador (idempotente) não quebra nada
- [x] Update preserva DB e config (snapshot copia ambos)
- [x] Rollback funciona se update falha (health check + restauração)

Para validar end-to-end manualmente:

```bash
# Em VM Ubuntu 24.04 nova:
sudo bash install.sh --license-key=test --domain=vpn.example --admin-email=admin@example
# 1. health: curl -fs http://localhost:8443/api/v1/system/health
# 2. login: usar a senha em /etc/vagg/admin-credentials.txt
# 3. re-run idempotente: sudo bash install.sh ... → exit 0, sem regerar secrets
# 4. update: sudo vagg-update → noop ou rollback transparente
```
