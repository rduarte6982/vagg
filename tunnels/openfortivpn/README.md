# vagg-tunnel-openfortivpn

Container que termina túneis Fortinet SSL VPN (FortiClient™ compat) usando o cliente OSS [`openfortivpn`](https://github.com/adrienverge/openfortivpn).

## Build

```bash
docker build -f tunnels/openfortivpn/Dockerfile -t vagg/tunnel-openfortivpn:dev tunnels/
```

## Config

`/config/tunnel.conf` no formato chave-valor padrão do `openfortivpn`:

```
host = vpn.cliente.example.com
port = 10443
trusted-cert = abcd0123...
set-routes = 0
set-dns = 0
```

`username` e `password` são adicionados pelo entrypoint a partir de `TUNNEL_USERNAME` e `TUNNEL_PASSWORD_FILE`. **Não** colocar credenciais no `.conf` em texto plano se for compartilhar entre operadores.

## Restart

`openfortivpn --persistent=10` reconecta sozinho com backoff de 10s. O container ainda assim usa `--restart=unless-stopped` no orchestrator para casos catastróficos.

## OTP

`tunnel-controller` escreve o código no FIFO `TUNNEL_OTP_PIPE`. O `openfortivpn` lê senhas de stdin via prompts; redirecionamento do FIFO para stdin é trabalho de fase posterior (similar ao openconnect).
