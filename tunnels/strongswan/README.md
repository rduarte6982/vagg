# vagg-tunnel-strongswan

Container que termina túneis IPsec usando [strongSwan](https://strongswan.org/) com a interface `swanctl` moderna (não o CLI legacy `ipsec`).

## Build

```bash
docker build -f tunnels/strongswan/Dockerfile -t vagg/tunnel-strongswan:dev tunnels/
```

## Config

`/config/swanctl.conf` no formato `swanctl`:

```
connections {
    vagg-conn {
        version = 2
        proposals = aes256-sha256-modp2048
        local_addrs  = %any
        remote_addrs = vpn.cliente.example.com
        local {
            auth = psk
            id = consultor1@aggregator.local
        }
        remote {
            auth = psk
            id = vpn.cliente.example.com
        }
        children {
            vagg-conn {
                local_ts = 0.0.0.0/0
                remote_ts = 192.168.1.0/24
                start_action = trap
                esp_proposals = aes256-sha256
            }
        }
    }
}

secrets {
    ike-cliente {
        secret = "psk-shared-com-cliente"
    }
}
```

O nome do `child` que será iniciado é `vagg-conn` por convenção; pode ser sobrescrito via `TUNNEL_STRONGSWAN_CHILD`.

## OTP / XAUTH

Para conexões que usam XAUTH/EAP-MSCHAPv2 com OTP, `tunnel-controller` escreve o código no FIFO `TUNNEL_OTP_PIPE`. A integração desse FIFO com o canal de credenciais do `charon` (via plugin `eap-mschapv2-passwd-stdin` ou similar) é trabalho de fase posterior — nesta fase, IPsec assume PSK ou cert estático.

## Restart

`tunnel-controller --manager strongswan` interpreta `restart` como no-op (charon não responde a SIGUSR1 do mesmo jeito que openvpn). Para reciclar a SA, faça `swanctl --terminate --child vagg-conn && swanctl --initiate --child vagg-conn` manualmente, ou recicle o container.
