# vagg-dns

CoreDNS oficial (`coredns/coredns:1.11.1`) que serve DNS split-horizon para os
consultores conectados ao OpenVPN da consultoria. SPEC §4.4 + §5.3.

A imagem é stock — não há Dockerfile. O Corefile é gerado e mantido pelo
`vagg-core` (`vagg_core.services.dns_manager`) e recarregado via SIGUSR1 a
cada conexão / desconexão de túnel.

## Run

```bash
docker run -d --name vagg-dns \
    -v $(pwd)/dns-config:/etc/coredns:ro \
    -p 53:53/udp -p 53:53/tcp \
    --restart unless-stopped \
    coredns/coredns:1.11.1 -conf /etc/coredns/Corefile
```

Ou via docker-compose (`installer/compose/docker-compose.yml` na Fase 10).

## Reload

`vagg-core` envia SIGUSR1 ao container `vagg-dns` quando regenera o Corefile.
Manual:

```bash
docker kill --signal=SIGUSR1 vagg-dns
```

## Schema do Corefile gerado

```
. {
    forward . 8.8.8.8 8.8.4.4
    cache 30
}

petroleo.vpn.consultoria.com.br:53 {
    forward . 192.168.1.10:53 {
        bind tun-abc123
        force_tcp
        prefer_udp
    }
    rewrite stop {
        answer name regex (.*) {1}
        answer value regex 192\.168\.1\.(\d+) 10.200.1.{1}
    }
    cache 30
    log
}
```

O bloco `rewrite` reescreve as respostas: o IP real do cliente
(`192.168.1.x`) é mapeado para o IP virtual (`10.200.1.x`) usado pelo
consultor. Combinado com NAT (Fase 4), isso elide colisões entre clientes
que usam a mesma faixa interna.

## Limites conhecidos

- Apenas CIDRs `/24` são suportados pela rewrite atual. Subnets mais largas
  exigem outra forma de regex; o renderer rejeita em tempo de geração.
- Cliente sem `dns_server` cadastrado é omitido — queries para
  `<client>.vpn.<dominio>` caem na zona global e retornam NXDOMAIN. Isso
  é correto: split-horizon exige um resolver autoritativo do lado cliente.
- TTL de cache é fixo em 30s (SPEC §4.4 — janela de inconsistência aceita).
