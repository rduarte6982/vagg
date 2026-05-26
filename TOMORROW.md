# Estado em 2026-05-26 02:00 — sequência pra você de manhã

## Estado funcional ATUAL (no homelab agora)
- Backend tunnels.py: rodando com `/ssl-vpn/prelogin.esp` (GATEWAY flow)
- Entrypoint container: usa `/ssl-vpn:prelogin-cookie` + `--authgroup`
- Image vagg/tunnel-openconnect-saml: SEM patch condicional (versão antiga)
- Extension instalada: v7 ou v8 (sem diferença pro gateway flow)

→ MRV conecta, mas só vê routes que o gateway flow empurra: `10.210.5.0/24`, `10.249.11.0/24`, `192.168.0.0/16`, default. Outros 10.210.x.x NÃO acessíveis.

## O que tem PRONTO no working tree (ainda não deployed)
1. Dockerfile com **patch condicional** (cookie inject só na 1ª request) — em `tunnels/openconnect-saml/Dockerfile`
2. Backend tunnels.py — atualmente `/ssl-vpn`, mas COMENTÁRIO TODO marca onde trocar
3. Entrypoint com flag `TUNNEL_GP_INTERFACE` — default `ssl-vpn`
4. Extension v8 com diagnostic logging — `clients/chrome-extension/vagg-saml-relay-v8.zip`

## Sequência manhã (estimativa: 15min)

### Passo 1 — Rebuild da image openconnect-saml (5-10min)
```powershell
cd C:\Users\rodrigoduarte\vagg
scp -r tunnels rodrigo@192.168.68.102:/tmp/vagg-tunnels-new/
ssh rodrigo@192.168.68.102 "cd /tmp/vagg-tunnels-new && docker build -f openconnect-saml/Dockerfile -t vagg/tunnel-openconnect-saml:test . && docker images vagg/tunnel-openconnect-saml:test"
```

### Passo 2 — Trocar backend pra portal flow
Edite `core/src/vagg_core/api/v1/tunnels.py` linha ~330:
```python
prelogin_url = f"{gateway_url}/global-protect/prelogin.esp"
```

Deploy:
```powershell
scp core/src/vagg_core/api/v1/tunnels.py rodrigo@192.168.68.102:/tmp/tunnels.py
ssh rodrigo@192.168.68.102 "docker cp /tmp/tunnels.py vagg-vagg-core-1:/usr/local/lib/python3.12/site-packages/vagg_core/api/v1/tunnels.py && docker restart vagg-vagg-core-1"
```

### Passo 3 — Subir container MRV com portal flow
No painel: para MRV → aguarda 20s → adiciona env var `TUNNEL_GP_INTERFACE=global-protect` ao client config (ou patch direto no orchestrator passar isso pro container) → Conectar.

OU rapido via docker:
```powershell
ssh rodrigo@192.168.68.102 "docker stop vagg-tunnel-mrv 2>/dev/null ; docker rm vagg-tunnel-mrv 2>/dev/null ; echo 'pronto, agora conectar via UI'"
```

### Passo 4 — Validar
```powershell
ssh rodrigo@192.168.68.102 "docker logs --tail 30 vagg-tunnel-mrv && echo '---' && ip route | grep ppp0"
```

Espera log mostrar:
```
VAGG: appended prelogin-cookie=*** [first request only]
VAGG: skipping cookie injection on subsequent request
... eventually: Connected as X.X.X.X
```

E `ip route | grep ppp0` deve mostrar MUITO mais subnets (não só 10.210.5.0/24).

Aí testa `ping 10.210.2.44` — agora deve responder.

## Se passo 1 (build) demorar demais
Pode rodar em background:
```powershell
ssh rodrigo@192.168.68.102 "cd /tmp/vagg-tunnels-new && nohup docker build -f openconnect-saml/Dockerfile -t vagg/tunnel-openconnect-saml:test . > /tmp/build.log 2>&1 &"
```
Verifica depois com `tail /tmp/build.log` e `docker images vagg/tunnel-openconnect-saml:test`.

## Plan B se portal flow falhar de novo
- Reverte os 2 arquivos (`tunnels.py` e `entrypoint.sh`) — git checkout vai voltar pro gateway-flow funcional
- Investigar via DevTools no popup: F12 → Network → /SAML20/SP/ACS → Response Headers (manda os headers que aparecem aí)

Memória relevante: `~/.claude/projects/.../memory/reference_paloalto_gp_saml.md`
