# vagg-tunnel-openvpn

Imagem do container que termina o túnel OpenVPN para um cliente da consultoria (SPEC §5.2). Implementada na **Fase 3**; outras VPNs (`openconnect`, `openfortivpn`, `wireguard`, `strongswan`) chegam na Fase 5.

## Build

O contexto é a pasta `tunnels/`, não `tunnels/openvpn/`, porque copiamos o `shared/tunnel_controller.py`.

```bash
docker build -f tunnels/openvpn/Dockerfile -t vagg/tunnel-openvpn:dev tunnels/
```

## Como o orchestrator (vagg-core) sobe esta imagem

```bash
docker run -d \
    --name vagg-tunnel-petroleo \
    --cap-add NET_ADMIN \
    --device /dev/net/tun \
    --security-opt no-new-privileges:true \
    --restart unless-stopped \
    --network vagg-net-tenants \
    -v /var/lib/vagg/clients/petroleo:/config:ro \
    -v /var/run/vagg/petroleo:/var/run/vagg \
    -e TUNNEL_USERNAME=consultor1 \
    vagg/tunnel-openvpn:dev
```

`/config/tunnel.conf` é o `.ovpn` montado em read-only. `/config/password` (modo 600) traz a senha quando `auth-user-pass` é necessário.

## Contrato (SPEC §5.2)

| Env var | Default | Função |
|---|---|---|
| `TUNNEL_CONFIG_PATH` | `/config/tunnel.conf` | Caminho do `.ovpn` |
| `TUNNEL_USERNAME` | (vazio) | Usuário; junto com `TUNNEL_PASSWORD_FILE` produz `--auth-user-pass` |
| `TUNNEL_PASSWORD_FILE` | `/config/password` | Caminho de arquivo com a senha (modo 600) |
| `TUNNEL_CONTROL_SOCKET` | `/var/run/vagg/control.sock` | Socket pro `tunnel-controller` (escutado pelo vagg-core) |
| `TUNNEL_OPENVPN_MGMT_SOCKET` | `/var/run/openvpn-mgmt.sock` | Mgmt do OpenVPN, interno ao container |
| `TUNNEL_LOG_LEVEL` | `INFO` | Log do controller |

## Observabilidade

- stdout do container: log do OpenVPN em `--verb 3` (texto) + linhas JSON do `entrypoint`/`tunnel-controller`.
- vagg-core lê stdout via `docker logs` (endpoint `/api/v1/clients/{id}/logs`).
- Status detalhado via socket: `echo '{"cmd":"status"}' | socat - UNIX-CONNECT:/var/run/vagg/<client>/control.sock`.

## SegurançA

- User não-root (`vagg`).
- `--cap-add NET_ADMIN` é o mínimo necessário pro `tun` device.
- `--security-opt no-new-privileges` impede escalada via setuid.
- Config e senha ficam em `/config` (read-only mount). Senha nunca aparece em env var (passada como arquivo).
