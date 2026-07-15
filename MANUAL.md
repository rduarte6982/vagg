# Manual de uso · VPN Aggregator

Guia prático pra **operadores** — quem cadastra clientes, consultores, políticas e fica de olho nos túneis. Para a arquitetura interna ver [docs/SPEC.md](docs/SPEC.md). Pra montar o ambiente do zero ver [TESTING.md](TESTING.md) e [dev/VPN-LAB.md](dev/VPN-LAB.md).

---

## 1. O que cada coisa significa

```
        ┌──────────────────┐
        │   Consultor       │  pessoa que consome a VPN da consultoria
        │   (você)          │
        └────────┬──────────┘
                 │ openvpn cliente conectado na sua VPN corporativa
                 ▼
        ┌──────────────────────────┐
        │   vagg-aggregator         │  esta ferramenta — controla tudo
        │                          │
        │   - clients (clientes)    │  empresas que você atende
        │   - consultants           │  pessoas da sua consultoria
        │   - policies              │  quem acessa o quê
        │   - audit chain           │  log assinado
        └────────┬─────────────────┘
                 │ N túneis persistentes (um por cliente)
        ┌────────┴────────────────────┐
        ▼            ▼                ▼
  ┌──────────┐ ┌──────────┐    ┌──────────┐
  │ Cliente A│ │ Cliente B│ …  │ Cliente N│   redes dos clientes
  │ (Petró-  │ │ (Banco   │    │          │   finais (não compartilhadas
  │  leo SA) │ │  Azul)   │    │          │   entre si)
  └──────────┘ └──────────┘    └──────────┘
```

**Glossário rápido:**
- **Cliente** = empresa cuja rede você precisa alcançar (ex.: "Petróleo SA")
- **Consultor** = pessoa da sua equipe (ex.: "Paulo Silva")
- **CIDR real** = endereçamento que existe na rede do cliente (ex.: `192.168.99.0/24`)
- **CIDR virtual** = endereçamento que o consultor enxerga, atribuído por você (ex.: `10.200.99.0/24`)
- **Política** = autorização "consultor X pode acessar cliente Y, escopo Z"
- **Audit** = trilha hash-chained de eventos (LGPD/SOC2-friendly)

---

## 2. Acessar o painel

| URL | O que é |
|---|---|
| http://192.168.68.102:8080 | **Admin UI** — onde você opera o produto |
| http://192.168.68.102:8081 | **Portal de Transparência** — para o cliente final auditar quem acessou sua rede |
| http://192.168.68.102:8443/docs | API Swagger — pra automação |

Login admin:
```
admin@vagg.example  /  admin
```

---

## 3. Cadastrar um cliente (= empresa)

1. Abra http://192.168.68.102:8080 → faça login → **Clientes** → **Novo cliente**

2. Preencha:

| Campo | O que é | Exemplo |
|---|---|---|
| **ID** | Slug curto, vai aparecer em DNS e logs. 3–32 caracteres, sem espaço. | `petroleo` |
| **Nome** | Nome legível pra UI | `Petróleo SA` |
| **Protocolo** | Tipo de VPN do cliente | `openvpn` (ou `openconnect`, `wireguard`...) |
| **CIDR virtual** | Faixa que **você atribui** dentro de `10.200.0.0/16` — escolha um `/24` único | `10.200.10.0/24` |
| **CIDR real** | Faixa que o cliente realmente usa (descubra com o admin de rede dele) | `192.168.50.0/24` |
| **DNS** | DNS interno do cliente (opcional — habilita resolução de nomes) | `192.168.50.1` |
| **Usuário / senha** | Se a VPN exigir autenticação por user/pass | `vpnuser` / `••••` |
| **Configuração do túnel** | Conteúdo do `.ovpn` / `.conf` / `.wg` que o cliente forneceu | (cole o arquivo inteiro) |

3. Clique **Salvar cliente**. O cliente aparece na lista com LED **cinza** (Parado).

> ⚠️ **CIDR virtual deve ser único** entre todos os clientes. Se você botar dois clientes em `10.200.10.0/24`, o segundo falha com 409 Conflict — protege você.

---

## 4. Cadastrar um consultor

**Consultores** → **Novo consultor**

| Campo | Detalhe |
|---|---|
| **E-mail** | Identificador. Use o e-mail corporativo dele. |
| **Nome** | "Paulo Silva" |
| **Usuário OpenVPN** | (opcional) o nome que ele usa pra entrar na sua VPN corporativa — usado pelo RBAC |
| **IP estático no pool** | (opcional) IP fixo que você atribui a ele dentro do pool 10.8.0.0/24 da OpenVPN — facilita rastreamento por IP |
| **Papel** | `viewer` (só lê), `operator` (cria/edita políticas), `admin` (tudo) |

---

## 5. Criar uma política — **quem acessa o quê**

Esse é o coração do RBAC. **Sem política, o consultor não enxerga nada.**

**Políticas** → **Nova política**

| Campo | O que faz |
|---|---|
| **Consultor** | Quem ganha acesso |
| **Cliente** | Qual empresa ele pode alcançar |
| **Tipo de escopo** | `Acesso total` (toda a CIDR do cliente), `Sub-rede` (uma fatia), `Host único` |
| **Valor do escopo** | Se sub-rede: `10.10.5.0/24`. Se host: `192.168.50.42`. Se "Acesso total" deixe em branco. |
| **Expira em** | (opcional) data/hora — útil pra acessos temporários (consultor de fora do projeto) |

**Exemplos práticos:**

- _"Paulo trabalha em todo o cliente Petróleo"_ → consultor: Paulo, cliente: petroleo, escopo: `Acesso total`
- _"Beatriz só acessa o servidor SAP do Banco Azul, IP 192.168.50.42"_ → consultor: Beatriz, cliente: banco-azul, escopo: `Host único`, valor: `192.168.50.42`
- _"André tem acesso temporário até 30/dez à VLAN de RH do Cliente C"_ → escopo: `Sub-rede`, valor: `10.10.5.0/24`, expira em: `2026-12-30`

---

## 6. Conectar / desconectar um túnel

Na lista de **Clientes**:

- Ícone ⏻ (cinza/vermelho) → **Conectar** — sobe o container do túnel, faz handshake com o servidor VPN do cliente
- Ícone ⏼ (verde) → **Desconectar** — derruba o container, remove rotas/iptables daquele cliente

Estados do LED na linha do cliente:

| LED | Estado | O que significa |
|---|---|---|
| 🟢 verde pulsante | `up` | Túnel conectado, NAT ativo, consultores podem alcançar a rede |
| 🟡 âmbar | `starting` | Subindo o túnel; handshake em curso |
| 🟡 âmbar | `down` | Conectou e caiu — pode ter sido instabilidade do servidor remoto |
| 🔴 vermelho | `errored` | Falhou — clique nos logs pra ver (credencial errada, certificado expirado, host inacessível) |
| ⚪ cinza | `stopped` | Você desconectou manualmente |

> ℹ️ Em produção, você normalmente **deixa o túnel sempre conectado** (`up`) — o aggregator existe pra ser permanente. Desconectar é incomum, só usado em janelas de manutenção.

---

## 7. Auditoria

**Auditoria** → mostra a cadeia hash-chained de eventos. Cada linha tem:

- **Quando** — timestamp ISO
- **Tipo de evento** — `tunnel.connect`, `policy.create`, `auth.login.success`, `tunnel.error`, …
- **Ator** — qual consultor (ou "sistema" se foi o agregador)
- **Detalhes** — payload JSON

**Filtrar:** digite parte do nome do evento. Ex: `tunnel.` mostra só eventos de túnel.

**Exportar:** clique **CSV** ou **JSON** pra baixar o filtrado.

> O log é **append-only** com hash encadeado — você não consegue editar nem apagar. Use isso em auditoria LGPD: prove que ninguém adulterou o histórico.

---

## 8. Painel Sistema

Mostra: versão, saúde, status da licença e botão pra **regenerar Corefile DNS** (força o CoreDNS a recarregar a zona após mudanças manuais — raramente necessário).

---

## 9. O Portal de Transparência

URL: http://192.168.68.102:8081

É um **outro produto**, voltado pro cliente final (não pra você). Resumindo: o cliente recebe um magic link no e-mail, abre o portal, e vê **quem da consultoria acessou a rede dele, quando e o que foi alcançado**. Ele baixa um PDF assinado para auditoria interna.

Você não precisa fazer nada lá — é o cliente que entra. Você só configura o e-mail dele em **External Viewers** (futuro — esse fluxo está na API mas não tem UI ainda).

---

## 10. Atalhos via API (pra automação)

Tudo da UI é só fachada de uma API REST documentada em http://192.168.68.102:8443/docs. Atalhos comuns:

```bash
# Login (pega token)
TOKEN=$(curl -sS -X POST http://192.168.68.102:8443/api/v1/auth/login \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'username=admin@vagg.example' \
  --data-urlencode 'password=admin' | jq -r .access_token)

# Listar clientes
curl -sS -H "Authorization: Bearer $TOKEN" \
  http://192.168.68.102:8443/api/v1/clients | jq

# Conectar um túnel
curl -sS -H "Authorization: Bearer $TOKEN" -X POST \
  http://192.168.68.102:8443/api/v1/clients/petroleo/connect

# Status do túnel
curl -sS -H "Authorization: Bearer $TOKEN" \
  http://192.168.68.102:8443/api/v1/clients/petroleo/status | jq

# Cadastrar cliente novo
curl -sS -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -X POST \
  http://192.168.68.102:8443/api/v1/clients \
  -d '{"id":"acme","name":"ACME","vpn_type":"openvpn",
       "virtual_cidr":"10.200.20.0/24","real_cidr":"172.16.0.0/24",
       "config_text":"<ovpn aqui>","nat_mappings":[]}'
```

---

# 11. Posso testar com VPNs reais?

**Sim**, é exatamente pra isso que ele existe. Algumas regras pra não sofrer:

## 11.1 Protocolos suportados

Cada cliente cadastrado escolhe um `vpn_type`:

| Protocolo | Caso típico | Imagem do túnel | OTP suportado |
|---|---|---|---|
| `openvpn` | OpenVPN community / Access Server | `vagg/tunnel-openvpn` | ✅ via management socket |
| `openconnect` | Cisco AnyConnect, Palo Alto GlobalProtect | `vagg/tunnel-openconnect` | ✅ via FIFO |
| `openfortivpn` | Fortinet SSL-VPN | `vagg/tunnel-openfortivpn` | ✅ via FIFO |
| `wireguard` | WireGuard | `vagg/tunnel-wireguard` | ❌ (WG não tem MFA) |
| `strongswan` | IPSec IKEv2 (corporativo) | `vagg/tunnel-strongswan` | ✅ via FIFO |

### 11.1.1 MFA / 2FA — TOTP e SAML (complementares)

O VAGG suporta dois caminhos pra autenticação multi-fator. **Os dois coexistem** — você escolhe por cliente via campo `auth_method`:

| `auth_method` | Quando usar | Como funciona |
|---|---|---|
| **`otp`** (TOTP RFC 6238) | VPN exige código de 6 dígitos de um app autenticador (Microsoft Authenticator, Google Authenticator, FortiToken, 1Password, Authy) | Admin cadastra o **seed TOTP** no VAGG (cifrado at-rest com Fernet). Aggregator gera o código fresh a cada connect/reconnect e empurra automaticamente — zero-touch, túnel fica `up` mesmo após reconexões. Se o seed não for cadastrado, cai pro modo manual (UI pede 6 dígitos no Conectar). |
| **`saml`** (SSO via browser) | VPN exige login SSO Azure AD / Okta / Google com **push notification** ou **biometria** — Microsoft Authenticator com "Aprovar/Rejeitar", FIDO, Conditional Access | VAGG abre um **browser remoto** (container Firefox + mitmproxy) num iframe. Usuário faz login normal lá; o cookie SSO é capturado e injetado no túnel. Suporta Palo Alto GlobalProtect e FortiGate com Azure AD. |
| **`none`** | VPN só com usuário + senha | Sem 2FA. |

> **Dica:** Microsoft Authenticator suporta os dois modos. Se você não consegue extrair o seed TOTP (algumas orgs bloqueiam), use SAML.

#### Como cadastrar o seed TOTP (auto-OTP)

1. No app autenticador do user da VPN, **mostre o secret** (Microsoft Authenticator → ⋮ → "Mostrar secret" / "Export"; Google Authenticator → "Edit" → "Show QR")
2. Copie o **base32** (ex: `JBSWY3DPEHPK3PXP`) **ou** a URI `otpauth://totp/...?secret=...`
3. No VAGG: **Clientes → ⋮ → Editar** → ative `auth_method = otp` → cole no campo "Seed TOTP" → **Salvar seed**
4. Botão **Testar agora** mostra o código corrente — bate com o app? OK, salvo e cifrado at-rest.
5. Lista de Clientes mostra badge **🔐 Auto-OTP** verde — Conectar não pede mais código.

API equivalente:

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  http://192.168.68.102:8443/api/v1/clients/petroleo/totp \
  -d '{"secret": "JBSWY3DPEHPK3PXP"}'
```

Configuração obrigatória de produção: defina `VAGG_CORE_CRYPTO_KEY` (32 bytes urlsafe-base64) no `.env`. Sem isso, em `environment=production` a aplicação se recusa a cifrar/decifrar. Em dev/test, a chave é derivada do `JWT_SECRET` (HKDF) — não use isso em prod.

Geração da chave:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## 11.2 Pegando o arquivo de config

Cada protocolo tem um formato:

- **OpenVPN** → `.ovpn` completo (com certificados inline) — esse é o caso do cliente típico de OpenVPN
- **OpenConnect / OpenFortiVPN** → você não tem arquivo; cadastra `host`, `usuário`, `senha`, e o `vpn_type`
- **WireGuard** → arquivo `.conf` com `[Interface]` e `[Peer]`
- **strongSwan** → arquivo `swanctl.conf` ou `ipsec.conf`

Cole o conteúdo no campo **Configuração do túnel**. Senha/usuário, quando aplicável, vão nos campos próprios.

## 11.3 O que perguntar pro IT do cliente

Antes de cadastrar, pegue do contato técnico do cliente:

1. **Qual protocolo** a VPN deles usa
2. **Endereço de host** + **porta**
3. **Credencial** (certificado, user+senha, e/ou TOTP)
4. **CIDR real** da LAN deles (qual range existe atrás da VPN — ex.: `10.20.0.0/16`)
5. **DNS interno** (opcional mas útil — habilita resolução de nomes tipo `sap.cliente.local`)
6. **Limite de conexões simultâneas** — algumas VPNs SSL têm limite por usuário; criar **um usuário dedicado pro aggregator** evita conflito com colegas que querem conectar manualmente.

## 11.4 Limitações que vimos no nosso lab

No lab que rodamos juntos, tudo (servidor OpenVPN do "cliente fake" + aggregator + cliente curl) ficou **na mesma máquina**. Isso causa overlap de rotas:

- A bridge Docker do `lab-vpn` tem `192.168.99.0/24` direto na máquina
- O `tun0` do aggregator queria a mesma rota
- Resultado: tráfego pelo curl sai pela bridge (não pelo túnel)

**Em produção essa situação não acontece** porque o servidor VPN do cliente está em outro lugar (datacenter dele, AWS, etc.). Mas se você quiser repetir o lab certinho:

- Suba o `lab-vpn/docker-compose.yml` numa **outra VM** ou no Proxmox em VLAN separada
- Ajuste `client.ovpn` (`./setup.sh --serve-host <ip-da-vm-do-lab>`)
- O aggregator passa a ver o servidor OpenVPN como uma rede externa, e a rota pelo `tun0` fica única

## 11.5 Patches que ainda precisam ir pro main

Se você for testar VPNs reais agora no homelab, **algumas correções** que fiz manualmente durante o setup ainda não foram para o GitHub. Estão aplicadas no servidor `192.168.68.102` mas no repo público continua o código antigo. Lista do que precisa ser commit:

1. `tunnels/openvpn/Dockerfile` — UID 1000, mgmt socket em `/var/run/vagg/`, atualmente roda como root (em produção deveria ser `setcap` + user-ns mapping; para já, root é o caminho)
2. `tunnels/openvpn/entrypoint.sh` — remover `--management-hold` (controller não emite "hold release")
3. **Os outros 4 Dockerfiles** (`openconnect`, `openfortivpn`, `wireguard`, `strongswan`) **provavelmente têm os mesmos bugs** — vou descobrir quando você cadastrar o primeiro cliente desses protocolos. Precisa fazer um patch equivalente em cada.
4. `core/Dockerfile` — adicionar `iproute2 iptables procps` (faltavam, sem isso o `network_manager` não roda)
5. `core/src/vagg_core/services/tunnel_orchestrator.py` — `SecurityOpt: ["apparmor=unconfined"]`, sem `no-new-privileges:true`
6. `core/src/vagg_core/services/network_applier.py` — falha em `sysctl net.netfilter.nf_conntrack_max` mesmo com privileged. Provavelmente precisa um fallback "se não der pra setar, log warning e continua".
7. `installer/compose/docker-compose.yml` — adicionar `extra_hosts: vagg-core:host-gateway` em ui/portal, e `privileged: true` + `group_add` no core
8. `ui/src/lib/api.ts` — endpoints estão em `/clients/{id}/connect|disconnect|status|otp|logs`, mas a UI chama `/tunnels/{id}/...` — vai dar 404 ao tentar conectar/desconectar pela UI (no nosso lab usei API direta via curl).

Posso fazer um PR com tudo isso de uma vez quando você quiser.

---

# 12. Onboarding novo cliente — checklist rápido

Quando um cliente novo chega:

- [ ] Pedir ao IT do cliente: protocolo, host, credenciais, CIDR real, DNS interno (Seção 11.3)
- [ ] Atribuir um **CIDR virtual livre** dentro de `10.200.0.0/16` (ver lista atual em **Clientes**)
- [ ] **Clientes → Novo cliente** com tudo acima
- [ ] **Conectar** → aguardar LED ficar verde
- [ ] Validar com `curl http://<ip-virtual>` (se tem um web service interno) ou `ping`
- [ ] Para cada consultor que vai trabalhar lá: **Políticas → Nova política**
- [ ] Entregar pro consultor o **mapa virtual** (CIDR virtual atribuído + DNS sufixo)

---

# 13. Quando algo falha

| Sintoma | Onde olhar |
|---|---|
| LED âmbar há mais de 30 s | Logs do container — UI futuro: `Clientes → ⋯ → Logs`. Por API: `GET /clients/{id}/logs?lines=100` |
| LED vermelho | Idem. Causas comuns: `auth fail` (credencial), `tls error` (cert errado), `route add failed` (overlap de CIDR) |
| Túnel sobe mas consultor não alcança nada | Falta política. Vai em **Políticas** e cria uma com escopo correto. |
| Login retorna 401 | Senha errada ou cookie velho — abrir incógnito |
| API retorna 502 timeout no `/status` | Container do túnel travou — `Desconectar` e `Conectar` de novo |
| `network_manager` falhou no log do core | Tema sysctl/iptables — ver Seção 11.5 patches 4–6 |

Para trazer logs do core inteiro:

```bash
ssh rodrigo@192.168.68.102 'sudo docker logs vagg-vagg-core-1 --tail 100'
```

Para logs do túnel de um cliente específico:

```bash
ssh rodrigo@192.168.68.102 'sudo docker logs vagg-tunnel-petroleo --tail 100'
```

---

# 14. Para encerrar a sessão

```bash
# parar tudo
ssh rodrigo@192.168.68.102 'sudo docker compose -f /home/rodrigo/projects/vagg/installer/compose/docker-compose.yml -f /etc/vagg/docker-compose.override.yml down'

# parar e apagar todo o estado
ssh rodrigo@192.168.68.102 'sudo docker compose -f /home/rodrigo/projects/vagg/installer/compose/docker-compose.yml -f /etc/vagg/docker-compose.override.yml down -v && sudo rm -rf /etc/vagg /var/lib/vagg'
```
