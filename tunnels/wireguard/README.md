# vagg-tunnel-wireguard

Container que termina túneis [WireGuard®](https://www.wireguard.com/). Usa o módulo do kernel via `wg-quick` (Alpine 3.20+ + kernel ≥ 5.6).

## Build

```bash
docker build -f tunnels/wireguard/Dockerfile -t vagg/tunnel-wireguard:dev tunnels/
```

## Config

`/config/tunnel.conf` no formato padrão WireGuard®:

```ini
[Interface]
PrivateKey = ...
Address = 10.200.99.2/24
DNS = 10.200.99.1

[Peer]
PublicKey = ...
Endpoint = vpn.cliente.example.com:51820
AllowedIPs = 192.168.1.0/24
PersistentKeepalive = 25
```

`TUNNEL_DEV` (definido pelo orchestrator) é usado como nome da interface — `wg-quick` exige que seja a chave do arquivo em `/etc/wireguard/<name>.conf`. O entrypoint cria o symlink.

## Restart / OTP

- **Restart:** WireGuard® não responde a SIGUSR1; `tunnel-controller` reporta sucesso silencioso. Em queda real (handshake stale > 3 min), o `--restart=unless-stopped` do orchestrator recicla o container.
- **OTP:** **não suportado** — WireGuard® é puramente criptográfico, sem segundo fator no protocolo. `submit_otp` retorna `{"ok": false, "error": "OTP not supported by WireGuard"}`.

## Notas

- Roda como **root** no container (necessário para `wg-quick`/`ip-link`/`ip-addr`). Cap NET_ADMIN é a única adicional.
- Trademark: WireGuard® é marca registrada de Jason A. Donenfeld.
