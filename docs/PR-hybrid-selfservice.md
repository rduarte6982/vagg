# PR: feat/hybrid-selfservice → main

**Branch:** `feat/hybrid-selfservice` (commits `a14c43a`, `13d64bb`) · já pushed
**Abrir em:** https://github.com/rduarte6982/vagg/pull/new/feat/hybrid-selfservice

## Resumo
Modelo híbrido de conexão VPN: o **admin** sobe o túnel; o **consultor** pode
**reconectar e reautenticar OTP** (via VAGG Client) para clientes que tem por Policy.
Inclui 4 bugfixes e a reconciliação de 1 patch §11.5 do homelab.

## Mudanças
### Server (core)
- `/me/clients` enriquecido: `auth_method`, `requires_otp`, `has_saml_cookie`, `saml_cookie_valid`
- `POST /api/v1/me/clients/{id}/reconnect` e `/otp` — escopados por Policy ativa
  (404 se não-autorizado, operator/admin only). `perform_connect()` compartilhado.
- Pré-check de cookie SAML expirado no connect (erro claro, não falha silenciosa)
- Fix `ck_client_vpn_type`: inclui `globalprotect` (ORM estava dessincronizado da migration 0006)
- Fix `saml_callback.py`: `_ERROR_HTML_TPL` indefinido → `_render_error_html` (NameError latente)
- `core/Dockerfile`: `iproute2 iptables procps` no runtime (patch §11.5 reconciliado)

### Client (Windows, v0.7.0)
- Persiste access+refresh token (sobrevive restart); corrige descarte do client logado no Login
- `Reconnect`/`SubmitOTP` (retry de refresh em 401) + UI de Reconectar/OTP + avisos SAML

## Testes
211 passando (era 202: +6 self-service, +2 SAML expiry, +1 globalprotect). `go build`+`vet`+`tsc` limpos.

## Validação E2E (homelab)
- `/me` enriquecido correto (mrv=saml/cookie, equatorial=otp…)
- reconnect: sem-auth→401, não-autorizado→404, autorizado→202 (cria container)
- otp: auth+policy OK, roteamento correto ao orchestrator

## ⚠️ Nota de deploy (breaking)
O código valida `admin_email` como EmailStr. O homelab tinha `VAGG_CORE_ADMIN_EMAIL=admin`
→ corrigido para `admin@vagg.example`. **Login admin agora é `admin@vagg.example` / `admin`.**
O `group_add: ["988"]` deve ficar no override `/etc/vagg` (o base não tem mais).

## Checklist pré-merge
- [ ] Revisar o diff (57 arquivos, core + client)
- [ ] Confirmar a mudança de login admin (documentar/avisar)
- [ ] Após merge: servidor voltar a trackear `main` (hoje está na branch)
- [ ] CI publicar `core:test`/`ui:test` no ghcr (ou manter build local)

## NÃO incluso neste PR (follow-ups separados)
- UI redesign (páginas React) — grande, não revisado
- Validação MRV/Vexia ACL (precisa SAML fresco com MFA)
- Fixes de tunnels não-ativos (strongswan incompleto, wireguard restart no-op — ver audit)
