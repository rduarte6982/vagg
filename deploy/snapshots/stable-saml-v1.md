# Snapshot `stable-saml-v1` — 2026-05-11

Snapshot imutável da stack SAML em estado **funcional conhecido**. Inclui:
captura de cookie GP/Azure AD via mitmproxy + openconnect-saml com 2 patches,
captura de SVPNCOOKIE FortiGate via mesma stack + openfortivpn-saml com
`--cookie-on-stdin` no Debian trixie (openfortivpn 1.23.1).

## Git anchor

Commit: `93a1f91 feat(saml): stack completo de captura de cookie SAML (GP + FortiGate)`

```bash
git checkout 93a1f91 -- tunnels/saml-portal tunnels/openconnect-saml tunnels/openfortivpn-saml
```

## Image digests (homelab — locais)

```
ghcr.io/rduarte6982/vagg/core:stable-saml-v1            sha256:e56af7cadd3d
ghcr.io/rduarte6982/vagg/ui:stable-saml-v1              sha256:6f0e9625e40d
vagg/saml-portal:stable-saml-v1                         sha256:97a081589f16
vagg/tunnel-openconnect-saml:stable-saml-v1             sha256:a56c14ae83b1
vagg/tunnel-openconnect:stable-saml-v1                  sha256:ff6bfa0f2f64
vagg/tunnel-openfortivpn-saml:stable-saml-v1            sha256:6ed2657f6d8d
vagg/tunnel-openfortivpn:stable-saml-v1                 sha256:f620dfe5425a
vagg/tunnel-openvpn:stable-saml-v1                      sha256:801a8061156f
```

## Características funcionais nesta versão

- `vagg-tunnel-openconnect-saml`: openconnect from-source com patches host-id +
  VAGG_GP_COOKIE env. Roda Azure AD-federated GP (gateways tipo MRV).
- `vagg-tunnel-openfortivpn-saml`: openfortivpn 1.23.1 Debian trixie + TOFU
  cert + `--cookie-on-stdin`. Roda FortiGate Azure AD via SVPNCOOKIE captured.
- `vagg-saml-portal`: Firefox + xpra-html5 (porta 14500) + mitmproxy (porta 8080)
  com `cookie_addon.py` em 2 modes (`kind=gp` / `kind=forti`).
- Mount `/dev/ppp` + `/dev/net/tun` no orchestrator pra openfortivpn-saml.
- `set-dns=1` no entrypoint pra capture de DNS interno.
- Snapshot de ifaces pré-existentes pra filtrar tun0 de outros tunnels.

## Procedimento de rollback

### Opção A — Apenas voltar imagens no compose

```bash
# Para cada serviço, fixar tag stable-saml-v1
cd /home/rodrigo/projects/vagg/installer/compose

# Editar docker-compose.yml temporariamente OU exportar VAGG_VERSION
VAGG_VERSION=stable-saml-v1 sudo docker compose up -d \
    --force-recreate vagg-core vagg-ui

# Tunnel containers são criados dinamicamente pelo orchestrator usando
# o tag default (vagg/tunnel-*:test). Pra forçar o stable, retag local:
docker tag vagg/saml-portal:stable-saml-v1               vagg/saml-portal:test
docker tag vagg/tunnel-openconnect-saml:stable-saml-v1   vagg/tunnel-openconnect-saml:test
docker tag vagg/tunnel-openfortivpn-saml:stable-saml-v1  vagg/tunnel-openfortivpn-saml:test
docker tag vagg/tunnel-openfortivpn:stable-saml-v1       vagg/tunnel-openfortivpn:test
docker tag vagg/tunnel-openconnect:stable-saml-v1        vagg/tunnel-openconnect:test
docker tag vagg/tunnel-openvpn:stable-saml-v1            vagg/tunnel-openvpn:test
```

### Opção B — Voltar código + rebuild

```bash
# 1. Reverter código pra o commit do snapshot
git checkout 93a1f91 -- \
    tunnels/saml-portal \
    tunnels/openconnect-saml \
    tunnels/openfortivpn-saml \
    tunnels/openconnect \
    core/src/vagg_core/services/tunnel_orchestrator.py \
    core/src/vagg_core/api/v1/clients.py

# 2. Rebuild todas as imagens da stack SAML
cd /home/rodrigo/projects/vagg
for prot in saml-portal openconnect-saml openfortivpn-saml; do
    docker build --no-cache -f tunnels/$prot/Dockerfile \
        -t vagg/${prot/saml-portal/saml-portal}:test tunnels/
done
docker build --no-cache -f core/Dockerfile \
    -t ghcr.io/rduarte6982/vagg/core:test core/

# 3. Recriar containers
cd installer/compose
sudo docker compose up -d --force-recreate vagg-core
```

## Cuidado

- **Não deletar** as tags `:stable-saml-v1` dos images mesmo após rebuild de
  `:test` ou `:latest`. Docker mantém o image content desde que haja alguma
  tag pointing pra ele.
- `docker image prune -a` removeria as stable-saml-v1 também. Sempre usar
  `prune -a --filter "label!=vagg.snapshot=stable-saml-v1"` (a label não
  existe ainda — TODO: adicionar nos Dockerfiles antes do próximo rebuild).
- DB schema do snapshot inclui migration `0010_auto_discovery`. Rollback de
  schema NÃO está no escopo desse snapshot — apenas imagens + código.
