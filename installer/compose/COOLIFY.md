# Deploy via Coolify

Deploy do painel admin + portal de transparência usando Coolify. Para o
caminho completo (com túneis VPN reais) use [`scripts/test-install.sh`](../../scripts/test-install.sh).

## Pré-requisitos

1. Coolify funcionando com Traefik
2. Push em `main` já rodou o workflow `publish-images` ao menos uma vez
3. Pacotes ghcr.io marcados como **public** em
   https://github.com/users/rduarte6982/packages → cada um (`vagg/core`,
   `vagg/ui`, `vagg/portal`) → Settings → Change visibility → Public

## Passos no Coolify

### 1. Gerar o hash da senha admin

Em qualquer máquina com Python 3.12:

```bash
python -m pip install argon2-cffi
python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('TROQUE_ESTA_SENHA'))"
```

Copie a saída inteira (começa com `$argon2id$v=19$...`).

### 2. Criar o resource

Em **+ New Resource → Docker Compose Empty**, cole o conteúdo de
[`docker-compose.coolify.yml`](docker-compose.coolify.yml).

### 3. Variáveis de ambiente

Em **Environment Variables**:

| Nome | Valor |
|------|-------|
| `VAGG_ADMIN_EMAIL` | seu email (ex: `ti@suaconsultoria.com.br`) |
| `VAGG_ADMIN_PASSWORD_HASH` | hash gerado no passo 1 |
| `VAGG_LICENSE_KEY` | qualquer string em modo teste (ex: `test-license`) |

As demais (`SERVICE_FQDN_*`, `SERVICE_PASSWORD_*`) Coolify gera sozinho.

### 4. Deploy

Click **Deploy**. Coolify pulla as 3 imagens, cria a rede, sobe os 4
serviços, Traefik resolve os 3 FQDNs com Let's Encrypt.

### 5. Acessar

Os 3 endpoints aparecem na aba **Domains** do resource:

| Serviço | URL exemplo |
|---------|-------------|
| API admin | `https://api-xxx.duarteapps.cloud` |
| Painel admin | `https://ui-xxx.duarteapps.cloud` |
| Portal transparência | `https://portal-xxx.duarteapps.cloud` |

Logue no painel admin com o email + senha que você escolheu.

## Limitações vs install no mini PC

| Recurso | Coolify | Mini PC (`scripts/test-install.sh`) |
|---------|---------|-------------------------------------|
| Painel admin / portal | ✅ | ✅ |
| RBAC + Auditoria | ✅ | ✅ |
| Magic link / TOTP / PDF assinado | ✅ | ✅ |
| TLS Let's Encrypt automático | ✅ | ❌ (HTTP puro) |
| Túneis VPN reais | ❌ | ⚠️ (requer `network_apply_enabled=true`) |
| iptables NETMAP / RBAC chain ativo | ❌ | ⚠️ |
| Deploy / atualização automatizados | ✅ | ✅ via `vagg-update` |

Para uma demo pública (mostrar UI, fluxo de auditoria, portal funcionando
com dados sintéticos) → **Coolify é o caminho certo**.

Para validar túneis ligando a clientes reais → **mini PC com test-install**.

## Atualizar

Cada push em `main` que mexa em `core/`, `ui/`, ou `portal/` dispara o
workflow `publish-images`. Para puxar a nova versão no Coolify:

1. Aba **Deployments** → **Redeploy** (Coolify pulla `:latest` de novo)

Ou habilite **Auto-deploy on push** apontando para o webhook do GitHub.

## Troubleshooting

### "No image to be pulled" + path not found

Você criou como Service sem git source mas usou um compose com `build:`.
Use [`docker-compose.coolify.yml`](docker-compose.coolify.yml) que usa
`image:` (precompiladas).

### "manifest unknown" ao pullar

Pacote ainda não foi publicado. Verifique:

```bash
gh api /users/rduarte6982/packages?package_type=container
```

Se vazio, force o workflow: aba Actions → publish-images → Run workflow.

### "denied: requested access to the resource is denied"

Pacote está privado. Ative o public em
https://github.com/users/rduarte6982/packages → cada `vagg/*`.

### vagg-core em loop de restart

Ver logs: Coolify → vagg-core → Logs. Causa mais comum: variáveis
`VAGG_ADMIN_PASSWORD_HASH` ausente ou malformada (precisa começar com
`$argon2id$v=19$`).
