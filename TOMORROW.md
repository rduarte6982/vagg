# Estado MRV — 2026-05-26 manhã (após sessão Playwright autônoma)

## Resumo do que validei via Playwright (autonomamente, sem mexer com você)

1. **Backend funciona perfeitamente** — POST `/saml-login/start` retorna 202 ✓
2. **Microsoft SSO autopilot completa em ~2s** (sessão MS ativa do seu browser)
3. **`/SAML20/SP/ACS` retorna headers corretos:**
   - `prelogin-cookie: <72 chars>` — capturável via `webRequest.onHeadersReceived`
   - `saml-auth-status: 1` (success)
   - `saml-username: rodrigo.duarte@parceiro.mrv.com.br`
4. **Relay-cookie endpoint funciona** — POST manual com cookie retorna `state=starting`
5. **Vexia continua up há ~9h** (não quebrei nada)

## O que está quebrado em MRV agora

Container `vagg-tunnel-mrv` sobe mas tunnel-controller não consegue bind socket:
```
{"detail": "timeout/erro ao conectar no control socket: [Errno 111] Connection refused",
 "context": {"socket": "/var/lib/vagg/sockets/mrv/control.sock"}}
```

**Causa raiz:** o entrypoint que está dentro da image `vagg/tunnel-openconnect-saml:test` foi alterado SEM `--background --syslog` (eu testei essa hipótese). Sem `--background`, openconnect ocupa o shell em foreground, `exec tunnel-controller` nunca roda → socket nunca bind.

## Portal pre-resolver NÃO funciona pra MRV

Testei manualmente via curl:
```
POST /global-protect/getconfig.esp
  user=rodrigo.duarte@...
  passwd=<cookie>           ← gateway prelogin-cookie
→ HTTP 512 (auth-failed)
```

MRV exige um cookie portal-flavored DIFERENTE. Pra obter teria que disparar SAML SAML via `/global-protect/prelogin.esp` (não `/ssl-vpn/prelogin.esp`). São SAMLRequests diferentes — testei e confirmado.

**Decisão:** mantenho gateway flow no backend (working) + HIP report no openconnect (pendente teste). Portal flow não vale o esforço pra MRV.

## Fix necessário (você executa quando voltar)

1. **Re-deploy entrypoint** com `--background --syslog` restaurado:

```powershell
cd C:\Users\rodrigoduarte\vagg
git pull origin main
scp tunnels/openconnect-saml/entrypoint.sh rodrigo@192.168.68.102:/tmp/entrypoint.sh
ssh rodrigo@192.168.68.102 "docker run --rm -d --entrypoint sleep --name vagg_fix vagg/tunnel-openconnect-saml:test 60 && docker cp /tmp/entrypoint.sh vagg_fix:/usr/local/bin/entrypoint && docker exec vagg_fix chmod +x /usr/local/bin/entrypoint && docker commit vagg_fix vagg/tunnel-openconnect-saml:test && docker stop vagg_fix ; docker stop vagg-tunnel-mrv 2>/dev/null ; docker rm vagg-tunnel-mrv 2>/dev/null ; echo PRONTO"
```

2. **Painel → Disconnect MRV → aguarda 15s → Conectar MRV**

3. **Aguardar 30s** pro HIP report submission.

4. **Validar:**
```powershell
ssh rodrigo@192.168.68.102 "ip route | grep ppp0 | head -25 ; echo --- ; ping -c 2 -W 2 10.210.2.44"
```

## Hipóteses pro resultado

- **Cenário A:** HIP aceito → routes ampliadas → ping responde. Sucesso total.
- **Cenário B:** HIP aceito mas mesmas routes (10.210.5.0/24 + catchall) → MRV firewall por usuário (não HIP). Falar com TI deles.
- **Cenário C:** HIP rejeitado → ajustar XML do hip-report.sh (mais categorias).

Pra saber QUAL cenário, precisa de `tcpdump` ou `strace` dentro do container — sem `--syslog` os logs sumiriam pós-daemon e perderíamos visibilidade. Por isso mantive `--syslog`.

## Workaround pra ver logs pós-daemon

Se precisar diagnosticar, dentro do container:
```bash
docker exec vagg-tunnel-mrv ls -la /tmp /var/log
docker exec vagg-tunnel-mrv cat /tmp/openconnect.log 2>/dev/null
docker exec vagg-tunnel-mrv ps aux
```

## Commits desde noite passada
- `bb5ac59` — SAML stack v8 + portal-flow groundwork (commit anterior)
- `65ba4a5` — backend portal pre-resolver
- (próximo) — HIP report + entrypoint restore
