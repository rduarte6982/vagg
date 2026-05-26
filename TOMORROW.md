# Estado quando você acordar — 2026-05-26 manhã

## TL;DR
Mudei a abordagem da noite. Em vez de rebuildar a image openconnect-saml (que precisa SSH + ~10min), o **backend agora faz o portal-flow ele mesmo via Python httpx**, extrai `portal-userauthcookie` da XML do `getconfig.esp`, e passa pro openconnect já no formato gateway-válido. Sem rebuild de image.

**Deploy: 1 arquivo, 30 segundos.**

## Causa raiz confirmada (research no openconnect source)

`auth-globalprotect.c::parse_portal_xml` extrai `<portal-userauthcookie>` da resposta do `/global-protect/getconfig.esp`. Esse é o cookie que `/ssl-vpn/login.esp` aceita.

O `prelogin-cookie` que minha extensão capturava do `/SAML20/SP/ACS` é portal-only — gateway rejeita com HTTP 512 ("auth-failed-password-empty" no header `X-Private-Pan-Globalprotect-Extension`).

## O que mudou (commit pendente)

[core/src/vagg_core/api/v1/tunnels.py](core/src/vagg_core/api/v1/tunnels.py) — endpoint `relay_saml_cookie`:
- Se cookie é `prelogin-cookie` E `vpn_type=globalprotect`, faz POST httpx em `/global-protect/getconfig.esp` com `User-Agent: PAN GlobalProtect`
- Parseia XML, extrai `<portal-userauthcookie>` + `<portal-prelogonuserauthcookie>`
- Salva no DB como `portal-userauthcookie=VALUE|portal-prelogonuserauthcookie=VALUE2` (formato combinado)
- Fallback: se getconfig falhar, continua com prelogin-cookie original (gateway flow limitado)

[tunnels/openconnect-saml/entrypoint.sh](tunnels/openconnect-saml/entrypoint.sh):
- Parse do formato combinado `cookie1=A|cookie2=B`
- USERGROUP fica como `portal-userauthcookie` quando esse é o tipo
- Patch openconnect já injeta com VAGG_GP_COOKIE_NAME — agora vai com nome certo

## Deploy (30s)

```powershell
cd C:\Users\rodrigoduarte\vagg
scp core/src/vagg_core/api/v1/tunnels.py rodrigo@192.168.68.102:/tmp/tunnels.py
scp tunnels/openconnect-saml/entrypoint.sh rodrigo@192.168.68.102:/tmp/entrypoint.sh
ssh rodrigo@192.168.68.102 "docker cp /tmp/tunnels.py vagg-vagg-core-1:/usr/local/lib/python3.12/site-packages/vagg_core/api/v1/tunnels.py && CID=`$(docker create vagg/tunnel-openconnect-saml:test) && docker cp /tmp/entrypoint.sh `$CID:/usr/local/bin/entrypoint && docker commit `$CID vagg/tunnel-openconnect-saml:test && docker rm `$CID && docker restart vagg-vagg-core-1 && docker stop vagg-tunnel-mrv 2>/dev/null ; docker rm vagg-tunnel-mrv 2>/dev/null ; echo 'PRONTO'"
```

## Teste (sequência)

1. Espera ~10s pro vagg-core restart completo
2. Painel → Conectar MRV → SSO autopilot deve completar em ~2s
3. Espera 15s pro openconnect estabelecer

## Validação

```powershell
ssh rodrigo@192.168.68.102 "docker logs --tail 30 vagg-vagg-core-1 2>&1 | grep gp_portal_resolve && echo '=== TUNNEL ===' && docker logs --tail 30 vagg-tunnel-mrv 2>&1 && echo '=== PING ===' && ping -c 2 -W 2 10.210.2.44"
```

**Espero ver no log do core:**
```
tunnel.gp_portal_resolve.ok client_id=mrv has_prelogon=false
```

**Espero ver no tunnel:**
```
POST /ssl-vpn/prelogin.esp
VAGG: appended portal-userauthcookie=*** (XX chars)
POST /ssl-vpn/login.esp
... (resposta 200, não 512)
Connected as 192.168.X.X
```

**E ping 10.210.2.44 deve responder.**

## Se ainda falhar

Caso 1: log mostra `gp_portal_resolve.no_userauthcookie` com `tags_seen=[...]` — significa que MRV retornou XML mas sem `<portal-userauthcookie>`. Cola o `tags_seen` que eu vejo qual tag MRV usa (variantes: `<userauthcookie>`, `<auth-cookie>`, `<jnlpcookie>`).

Caso 2: log mostra `gp_portal_resolve.exception` — getconfig.esp call falhou (timeout, cert, etc). Cola o `err` que diagnostico.

Caso 3: openconnect ainda dá 512 em login.esp — MRV exige `portal-prelogonuserauthcookie` também. Precisa rebuild da image pra adicionar segunda injeção. Aí volta a sequência antiga do TOMORROW.md anterior (manter no git history).

## Memória relevante
[reference_paloalto_gp_saml](.claude/projects/.../memory/reference_paloalto_gp_saml.md) — 5 pegadinhas críticas
