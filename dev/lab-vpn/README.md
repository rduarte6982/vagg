# dev/lab-vpn — laboratório de VPN para testes ponta a ponta

Sobe num container um **servidor OpenVPN** e um **recurso interno fake**
(nginx) para você poder testar o fluxo completo do vagg-aggregator com uma
VPN real — sem depender de provedor externo nem da rede de um cliente
real.

## Arquitetura

```
                       [192.168.99.0/24] (rede do "cliente fake")
                               │
   ┌───────────────┐      ┌────┴────┐      ┌──────────────┐
   │   vpn-server  │──────┤ docker  ├──────│  lan-asset   │
   │ kylemanna/    │      │ network │      │  nginx       │
   │ openvpn :1194 │      └─────────┘      │  192.168.99.10│
   └───────────────┘                        └──────────────┘
            ▲
            │ udp/1194
            │
   ┌────────┴────────┐
   │  vagg-aggregator │  → cria container vagg-tunnel-*
   │  (host network)  │  → faz NAT 192.168.99.0/24 ↔ 10.200.99.0/24
   └────────┬────────┘
            │
   ┌────────┴────────┐
   │   consultor    │  conecta na VPN corporativa, enxerga
   │   (você)       │  10.200.99.10 → cai no nginx do cliente
   └────────────────┘
```

## Pré-requisitos

- Docker rodando localmente
- `bash` (Linux/macOS/WSL2)
- A pasta `dev/` do vagg ao lado (este lab é independente, mas o passo
  a passo combinado mora em [VPN-LAB.md](../VPN-LAB.md))

## Subindo o lab

```bash
cd dev/lab-vpn/

# 1. Setup inicial (gera PKI, cria certificado do consultor, sobe servidor)
./setup.sh

# Em WSL2 ou se outras máquinas precisam acessar o servidor, especifique
# o IP que será gravado no .ovpn:
./setup.sh --serve-host 192.168.0.50
```

Saída esperada: arquivo `client.ovpn` na pasta atual + 2 containers
rodando (`lab-vpn-server`, `lab-vpn-asset`).

## Validação

Sem o vagg, você pode testar que o servidor está saudável:

```bash
# Direto, com cliente openvpn local (Linux):
sudo openvpn --config client.ovpn

# Em outro terminal, depois que conectar:
curl http://192.168.99.10  # deve devolver a página do nginx
```

## Como usar com o vagg-aggregator

Veja o passo a passo completo em
[`../VPN-LAB.md`](../VPN-LAB.md). Em resumo, no painel admin:

| Campo          | Valor                |
| -------------- | -------------------- |
| ID             | `lab`                |
| Nome           | Cliente Lab          |
| Protocolo      | openvpn              |
| CIDR virtual   | `10.200.99.0/24`     |
| CIDR real      | `192.168.99.0/24`    |
| Configuração do túnel | (cole o `client.ovpn`) |

## Limpar

```bash
docker compose down -v   # remove containers + PKI
rm -f client.ovpn
```

## Notas

- A PKI é criada **sem senha** (`nopass`). É um lab — não use em produção.
- A subnet OpenVPN interna (entre vpn-server e clientes OpenVPN) é
  `10.99.0.0/24`. A subnet "do cliente" (que o consultor quer alcançar
  via NAT do vagg) é `192.168.99.0/24`.
- Se for rodar em WSL2 e quiser conectar de outra máquina da LAN, lembre
  de configurar port forwarding `udp/1194` da WSL pro Windows e abrir o
  firewall.
