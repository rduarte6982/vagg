# VPN-LAB — testando o vagg ponta a ponta com uma VPN real

Este guia te leva do zero a "consultor consegue acessar a rede de um cliente
através do agregador" usando um laboratório self-contained — sem precisar de
mini PC, hardware extra ou cliente real.

---

## 1. Por que não dá pra fazer 100% no Windows nativo

O coração do vagg é o NAT remapping em iptables + policy routing no kernel
Linux do host (SPEC §4.2 / §4.3). Em produção, o `vagg-core` roda com
`network_mode: host` e capacidade `NET_ADMIN` para criar regras `iptables` e
tabelas `ip rule` que mapeiam `10.200.x.0/24` (virtual) ↔ subnet real do
cliente, e direcionam pacotes ao tun-* certo.

No **Docker Desktop para Windows**, `network_mode: host` se refere à VM
Linux interna do Docker, não ao Windows. O túnel até sobe lá dentro, mas
nem o Windows nem outros containers do mesmo daemon enxergam a interface
tun-*. Então o tráfego do consultor não chega. **É limitação fundamental,
não tem patch que resolva.**

→ A solução simples é **rodar o aggregator dentro de WSL2**. Ali Docker
Engine e iptables são nativos, e tudo funciona como num servidor Linux de
verdade. Linux/macOS nativos também servem; só Windows nativo não.

---

## 2. Arquitetura do teste

```
┌──────────────────────────────────────────────────────────────────┐
│  WSL2 Ubuntu 24.04 (ou Linux nativo)                             │
│                                                                  │
│  ┌─────────────────────┐         ┌──────────────────────────┐    │
│  │  vagg-aggregator   │         │  lab-vpn (cliente fake)  │    │
│  │  (network_mode:    │         │                          │    │
│  │   host, NET_ADMIN) │         │  ┌────────────────────┐  │    │
│  │                    │         │  │ vpn-server :1194  │  │    │
│  │  - vagg-core       │◄────────┤  │ kylemanna/openvpn │  │    │
│  │  - vagg-ui :8080   │  ovpn   │  └────────────────────┘  │    │
│  │  - vagg-portal     │         │                          │    │
│  │  - vagg-tunnel-lab │         │  ┌────────────────────┐  │    │
│  │    (criado pelo    │         │  │ lan-asset (nginx) │  │    │
│  │     core via API)  │         │  │ 192.168.99.10     │  │    │
│  │                    │         │  └────────────────────┘  │    │
│  │  iptables NETMAP:  │         │  rede: 192.168.99.0/24   │    │
│  │  10.200.99.0/24    │         └──────────────────────────┘    │
│  │  ↔ 192.168.99.0/24 │                                          │
│  └────────────────────┘                                          │
│           ▲                                                      │
└───────────┼──────────────────────────────────────────────────────┘
            │ http
            │
   ┌────────┴────────┐
   │  Você (browser) │  vai chamar http://10.200.99.10 e cair no
   │                 │  nginx via NAT do aggregator
   └─────────────────┘
```

**Quem é quem:**
- `lab-vpn` é o "cliente final" — uma rede pequena (192.168.99.0/24) que
  hospeda um servidor OpenVPN e um nginx interno.
- `vagg-aggregator` é a sua infra — roda dentro da WSL2, mantém um túnel
  permanente para o lab-vpn e expõe o nginx via 10.200.99.10 para os
  consultores.
- O "consultor" vai ser você mesmo, fazendo `curl http://10.200.99.10`
  direto da WSL2 ou de qualquer host alcançável (Windows, browser, etc.).

---

## 3. Passo a passo

### 3.1 Habilitar WSL2 + Ubuntu 24.04 (se ainda não tem)

No PowerShell **como administrador**:

```powershell
wsl --install -d Ubuntu-24.04
# reinicie se for primeira vez
```

Depois, abra o Ubuntu pelo menu Iniciar e crie um usuário Linux normal.

### 3.2 Instalar Docker Engine na WSL

> ⚠️ Não use Docker Desktop com integração WSL aqui — o Docker Desktop
> rotea os containers pela VM dele e a flag `host` não nos serve. Instale
> o Docker Engine **dentro** da WSL.

```bash
# dentro do Ubuntu da WSL
sudo apt update
sudo apt install -y curl ca-certificates
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# saia e entre de novo na WSL para o grupo aplicar:
exit
# (no PowerShell) wsl
docker run --rm hello-world  # tem que funcionar sem sudo
```

### 3.3 Clonar o repositório dentro da WSL

> Importante: clone **dentro** do filesystem Linux da WSL (`~/projects`),
> NÃO em `/mnt/c/...`. Performance é 10× melhor e evita problemas de
> permissão com o Docker.

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/rduarte6982/vagg.git
cd vagg
```

### 3.4 Subir o **lab-vpn** (cliente fake)

```bash
cd dev/lab-vpn
./setup.sh
```

Isso:
- Inicializa a PKI do OpenVPN (sem senha — é lab)
- Gera o certificado do "consultor"
- Sobe o servidor OpenVPN em `udp://<ip-da-wsl>:1194`
- Sobe o nginx interno em `192.168.99.10`
- Salva `dev/lab-vpn/client.ovpn` — esse arquivo vai pro painel admin

Confirme que rodou:
```bash
docker compose ps
# vê dois containers: lab-vpn-server e lab-vpn-asset
cat client.ovpn | head -20
# vê algo tipo "client / dev tun / proto udp / remote 172.x.x.x 1194 / ..."
```

### 3.5 Subir o **vagg-aggregator** com networking real

> ⚠️ NÃO use o `dev/docker-compose.yml` para esta etapa — ele desabilita
> network_apply (era pro modo de teste de UI no Windows). Use o compose
> de produção que está em `installer/compose/docker-compose.yml`.

Dois caminhos: o **rápido** (script test-install) ou o **manual**.

#### 3.5.a Rápido — `scripts/test-install.sh`

```bash
cd ~/projects/vagg
sudo bash scripts/test-install.sh
```

Esse script faz:
1. Constrói as 8 imagens locais (5–10 min na primeira vez)
2. Gera senhas e segredos em `/etc/vagg/core.env`
3. Sobe o compose em modo teste-com-network-real
4. Imprime URL + senha admin no final

> O `docker-compose.test.yml` que ele usa NÃO usa `network_mode: host`
> por padrão (era pra rodar no Windows). Para validar VPN real, edite
> `/etc/vagg/docker-compose.yml` e troque o serviço `vagg-core`:
> remova `ports:` e adicione `network_mode: host` + `cap_add:
> [NET_ADMIN, NET_RAW]`. Depois suba a env com
> `VAGG_CORE_NETWORK_APPLY_ENABLED=true` em `/etc/vagg/core.env`.

#### 3.5.b Manual — usando o compose de produção

```bash
cd ~/projects/vagg
sudo mkdir -p /etc/vagg /var/lib/vagg/{db,clients,sockets,dns-config}

# Construa as imagens localmente
make images-build   # tagueia ghcr.io/rduarte6982/vagg/<comp>:test

# Gera o core.env com hash da senha "admin"
HASH=$(docker run --rm ghcr.io/rduarte6982/vagg/core:test \
  python -m vagg_core.scripts.hash_password admin)
JWT=$(openssl rand -base64 48)

sudo tee /etc/vagg/core.env >/dev/null <<EOF
VAGG_CORE_ENVIRONMENT=test
VAGG_CORE_DOMAIN=vpn.lab.local
VAGG_CORE_DATABASE_URL=sqlite+aiosqlite:////var/lib/vagg/db/vagg-core.db
VAGG_CORE_JWT_SECRET=$JWT
VAGG_CORE_ADMIN_EMAIL=admin@vagg.local
VAGG_CORE_ADMIN_PASSWORD_HASH=$HASH
VAGG_CORE_LICENSE_KEY=test-license
VAGG_CORE_LICENSE_SERVER=http://127.0.0.1:9999
VAGG_CORE_NETWORK_APPLY_ENABLED=true
VAGG_CORE_DNS_ENABLED=true
VAGG_CORE_DNS_CONFIG_PATH=/var/lib/vagg/dns-config/Corefile
VAGG_CORE_TUNNELS_CONFIG_DIR=/var/lib/vagg/clients
VAGG_CORE_TUNNELS_SOCKETS_DIR=/var/lib/vagg/sockets
VAGG_CORE_TUNNELS_IMAGE_TAG=test
VAGG_REGISTRY=ghcr.io/rduarte6982/vagg
VAGG_VERSION=test
EOF

sudo docker compose \
  -f installer/compose/docker-compose.yml \
  --env-file /etc/vagg/core.env \
  up -d
```

Verifique:
```bash
curl -s http://127.0.0.1:8443/api/v1/system/health
# {"status":"ok"}
```

E acesse o painel: a UI roda no `:443` em produção, mas como aqui está
sem TLS você pode bater direto no `vagg-core` em `:8443/docs` (Swagger)
ou usar a UI dev em outro terminal:

```bash
# em outro terminal da WSL:
cd ui && npm install && npm run dev
# e abra http://localhost:5173 (sem ?demo=1) — vai falar com :8443
```

### 3.6 Cadastrar o cliente "lab" no painel

No browser (`http://localhost:5173`), faça login com `admin@vagg.local`
/ `admin` e abra **Clientes → Novo cliente**:

| Campo                | Valor                                |
| -------------------- | ------------------------------------ |
| ID                   | `lab`                                |
| Nome                 | Cliente Lab                          |
| Protocolo            | openvpn                              |
| CIDR virtual         | `10.200.99.0/24`                     |
| CIDR real            | `192.168.99.0/24`                    |
| DNS                  | (deixe em branco)                    |
| Usuário / senha      | (deixe em branco)                    |
| **Configuração do túnel** | cole o conteúdo de `dev/lab-vpn/client.ovpn` |

Para colar o `.ovpn`:
```bash
cat dev/lab-vpn/client.ovpn   # copie o output inteiro pro campo do form
```

Salve. O cliente aparece na lista com LED **cinza** (Parado).

### 3.7 Conectar o túnel

Clique no ícone ⏻ na linha do cliente. O LED vai pra **âmbar**
(Iniciando) e em alguns segundos pra **verde** (Online).

Verifique com `docker ps`:
```bash
docker ps | grep vagg-tunnel
# deve aparecer um container vagg-tunnel-lab rodando
```

E que a interface tun foi criada no host:
```bash
ip link show | grep tun-
# tun-lab ou tun-lab-XXXX (o exato depende do iface_name())
```

E que as regras NAT estão ativas:
```bash
sudo iptables -t nat -L PREROUTING -n | grep 10.200.99
# deve aparecer: NETMAP all 0.0.0.0/0 10.200.99.0/24 to:192.168.99.0/24
```

### 3.8 O teste do consultor — acessar o recurso interno

Da própria WSL2 (você é o "consultor"):

```bash
curl -v http://10.200.99.10
# deve devolver o HTML da página "🔒 Recurso interno do cliente"
```

🎉 Se essa requisição retornou 200 com a página teal, o agregador está
fazendo NAT corretamente:
1. Você bateu em `10.200.99.10`
2. iptables NETMAP traduziu para `192.168.99.10` no caminho de saída
3. ip rule mandou pelo `tun-lab-*`
4. Pacotes saíram pelo OpenVPN, chegaram no `lan-asset` (192.168.99.10)
5. Resposta voltou via SNAT (192.168.99.10 → 10.200.99.10)

### 3.9 Auditoria

No painel **Auditoria** você vai ver:
- `client.create` — quando você cadastrou
- `tunnel.connect` — quando clicou em conectar
- (eventos do health worker, hash-chained)

E no painel **Sistema**, em DNS, o botão "Regenerar Corefile" agora
inclui o cliente lab no zone.

---

## 4. Cenários de erro pra praticar

Depois que o feliz funcionou, vale exercitar os caminhos ruins:

### Túnel que erra o handshake
- Edite o `dev/lab-vpn/client.ovpn` e troque o `remote` para um IP
  errado. Cadastre como cliente novo. Estado deve ir pra **Com erro**
  e a auditoria registra `tunnel.error`.

### Subnet duplicada
- Crie um segundo cliente com `virtual_cidr=10.200.99.0/24` (o mesmo
  do "lab"). O core deve recusar com 409 Conflict.

### Desconectar
- Clique ⏻ na linha do cliente em estado Online. Container some
  (`docker ps`), regras iptables somem, audit registra
  `tunnel.disconnect`.

### Reset total
```bash
sudo docker compose -f installer/compose/docker-compose.yml down -v
cd dev/lab-vpn && docker compose down -v && rm -f client.ovpn
sudo rm -rf /etc/vagg /var/lib/vagg
```

---

## 5. Quando rodar isso é exagero

Se você só quer demonstrar a UI (apresentação, vídeo, screenshots), use
o **modo demo** descrito em [TESTING.md](../TESTING.md) — é instantâneo
e não exige WSL nem Docker rodando. O lab-vpn aqui é pra você validar
funcionalmente que o produto faz o que promete.
