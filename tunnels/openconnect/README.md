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

`tunnel-controller` envia o OTP para `TUNNEL_OTP_PIPE`. Para Phase 5 o `entrypoint.sh` cria o FIFO mas **não** o redireciona para o stdin do openconnect — autenticação além de senha estática requer trabalho de plumbing adicional (Duo push via `--script`, TOTP via `--token-mode`, etc). Trabalho previsto em fase posterior.

## Limitações conhecidas

- Sem suporte a `dual-stack` (IPv6) testado.
- `--syslog` envia logs ao stderr (capturado por `docker logs`); `--verbose` pode ser ligado via env.
- Reconexão é responsabilidade do `--restart=unless-stopped` do Docker (mesmo padrão do tunnel-openvpn).
