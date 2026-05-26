# VAGG SAML Relay — Chrome extension

Captura o callback SAML do gateway VPN (FortiGate) e relaya pro VAGG core
automaticamente. **Obrigatória pra admins** que conectam VPNs com SAML SSO
via VAGG painel — sem esta extensão o redirect de `127.0.0.1:8020/?id=...`
do gateway dá ERR_CONNECTION_REFUSED no PC do admin e exige copy/paste
manual.

## Como funciona

1. Admin clica "Conectar" no painel VAGG → popup Microsoft abre
2. Admin faz login + push approval normalmente
3. Gateway redireciona popup pra `http://127.0.0.1:8020/?id=<SAML_SESSION_ID>`
4. **Esta extensão intercepta** essa request (via `webNavigation.onBeforeNavigate`)
5. Extrai o `?id=`, faz `POST /api/v1/clients/{id}/saml-login/relay` pro VAGG core
6. VAGG core entrega o id pro `openfortivpn --saml-login` do tunnel container
7. Tunnel sobe sozinho

## Instalação (desenvolvimento — load unpacked)

1. Abra `chrome://extensions/` no Chrome/Edge
2. Ative "Modo do desenvolvedor" (toggle no canto superior direito)
3. Click "Carregar sem compactação"
4. Aponte pra esta pasta (`clients/chrome-extension/`)
5. Click no ícone da extensão → configure URL do VAGG + access token
6. Pronto

## Configuração

- **URL do VAGG**: ex. `http://192.168.68.102` ou `https://vagg.minhaempresa.com`
- **Access token**: JWT do admin. Pegue após login no painel:
  ```js
  // DevTools console no painel VAGG:
  localStorage.getItem('vagg.access_token')
  ```

## Distribuição em ambiente corporativo

Pra forçar instalação via política de grupo (GPO Windows / MDM macOS):

1. Empacote como `.crx` ou publique como private extension na Chrome Web Store
2. Configure `ExtensionInstallForcelist` na política do Chrome
3. Configure `vagg_base_url` via `managed_storage` no manifest

Detalhes: <https://chromeenterprise.google/policies/#ExtensionInstallForcelist>

## Permissões usadas

- `webNavigation` — observa navegações pra `127.0.0.1`
- `tabs` — fecha o popup após o relay
- `storage` — guarda URL do VAGG + token (sync, criptografado pelo Chrome)
- `notifications` — feedback ao user (sucesso/erro do relay)
- `host_permissions` — necessário pro fetch ao VAGG core

## Detecção pelo painel

O `content.js` da extensão postou `window.postMessage({source: 'vagg-ext', type: 'installed'})`
no carregamento da página. O painel VAGG escuta isso e:

- Se detectar a extensão → UX 100% automática (sem copy/paste)
- Se NÃO detectar → fallback pra clipboard / paste manual + warning pra instalar

## Build pra produção

```bash
cd clients/chrome-extension
zip -r vagg-saml-relay-v1.0.0.zip . -x "*.md" -x ".git/*"
```

Upload o .zip pra Chrome Web Store ou GPO ExtensionInstallForcelist.
