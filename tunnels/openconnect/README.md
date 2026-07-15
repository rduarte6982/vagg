# vagg-tunnel-openconnect

Container que termina túneis de protocolos compatíveis com OpenConnect:

- Cisco AnyConnect™
- Palo Alto GlobalProtect™
- Pulse Secure™ (parcialmente)

Implementa o contrato comum descrito em [`tunnels/shared/README.md`](../shared/README.md). Adicionado na **Fase 5**.

## Build

```bash
docker build -f tunnels/openconnect/Dockerfile -t vagg/tunnel-openconnect:dev tunnels/
```

## Config

`/config/tunnel.conf` aceita duas formas:

1. Linha única com o endpoint: `vpn.cliente.example.com`
2. Formato `server <host>:<porta>` (mesma sintaxe do `.ovpn`):
   ```
   server vpn.cliente.example.com:443
   ```

Credenciais: `/config/password` (mode 600). Username vai em `TUNNEL_USERNAME`.

## OTP / MFA

Quando `TUNNEL_REQUIRES_OTP=true`, o entrypoint pipa o FIFO `TUNNEL_OTP_PIPE` no stdin do openconnect (depois da senha). O `tunnel-controller` recebe `{"cmd":"otp","code":"123456"}` via socket de controle e escreve no FIFO — bloqueante: a primeira tentativa de auth fica parada até o orchestrator empurrar o código.

Dois modos suportados pelo aggregator:

- **Auto-TOTP (recomendado, zero-touch):** o admin cadastra o seed RFC 6238 do user da VPN em `PUT /api/v1/clients/{id}/totp` (cifrado at-rest com Fernet). O orchestrator gera código fresh a cada connect/reconnect e empurra no FIFO automaticamente. Compatível com Microsoft Authenticator, Google Authenticator, FortiToken, 1Password, etc.
- **Manual:** sem seed cadastrado, o orchestrator espera `POST /api/v1/clients/{id}/otp` com o código digitado pelo admin na UI. Necessário pra Duo Push / SMS / outros canais que não cabem em TOTP RFC 6238.

Pra SAML/SSO (Azure AD com Microsoft Authenticator push), usar o fluxo paralelo de captura de cookie em `tunnels/saml-portal/` + `tunnels/openconnect-saml/` (browser remoto + mitmproxy).

## Limitações conhecidas

- Sem suporte a `dual-stack` (IPv6) testado.
- `--syslog` envia logs ao stderr (capturado por `docker logs`); `--verbose` pode ser ligado via env.
- Reconexão é responsabilidade do `--restart=unless-stopped` do Docker (mesmo padrão do tunnel-openvpn).
