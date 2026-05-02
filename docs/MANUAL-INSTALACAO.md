# Manual de Instalação — VPN Aggregator no Mini PC

Manual passo-a-passo para instalar o VPN Aggregator num mini PC com Ubuntu
Server 24.04 LTS. Cobre desde o boot da ISO até o primeiro consultor
acessando um cliente real.

> **Estado do manual:** os textos de cada passo estão escritos. As capturas
> de tela marcadas com `_(print: …)_` serão geradas automaticamente após o
> Playwright MCP carregar (reiniciar VS Code uma vez para ativar) — basta
> me pedir para "gerar os prints" depois de subir o stack localmente.

---

## 1. Pré-requisitos

### Hardware (mini PC)

| Recurso | Mínimo | Recomendado |
|---|---|---|
| CPU | 2 cores (x86_64) | 4 cores |
| RAM | 4 GB | 8 GB |
| Disco | 30 GB SSD | 100 GB SSD |
| Rede | 100 Mbps cabeada | 1 Gbps cabeada |

Modelos validados: Beelink SER-series (Ryzen 5/7), Minisforum UM-series,
Intel NUC i3/i5 11ª gen ou superior. Qualquer mini PC x86_64 com BIOS UEFI
moderno funciona.

### Software / rede

- Ubuntu Server 24.04 LTS (clean install)
- Acesso SSH como root ou conta sudo
- IPv4 estático na rede da consultoria
- NTP funcional (sem clock drift > 30s)
- Outbound liberado em (SPEC §4.5.2):
  - 443/tcp para `licensing.vagg.io`, `ghcr.io`, `archive.ubuntu.com`
  - 123/udp para `pool.ntp.org`
  - Portas dos servidores VPN dos clientes (varia)

### Coisas que você precisa coletar antes

- License key (`VAGG-XXXX-XXXX-XXXX`) — recebida no email pós-pagamento Stripe
- Domínio `vpn.{sua-consultoria}.com.br` controlado e DNS gerenciável
- Para cada cliente VPN:
  - Tipo (OpenVPN / OpenConnect / FortiVPN / WireGuard / strongSwan)
  - Endpoint (host:porta)
  - Credenciais (usuário/senha ou cert)
  - Subnet real do cliente
  - DNS server interno (se houver)
  - Tipo de MFA

---

## 2. Boot e instalação do Ubuntu Server

### 2.1 Criar pendrive bootável

1. Baixar a ISO oficial em https://ubuntu.com/download/server
2. Gravar com Rufus (Windows) ou `dd` (Linux/macOS):
   ```bash
   sudo dd if=ubuntu-24.04.2-live-server-amd64.iso of=/dev/sdX bs=4M status=progress
   ```

_(print: tela do Rufus selecionando a ISO)_

### 2.2 Instalação guiada

Conectar o mini PC com:
- Pendrive na USB
- Cabo de rede no switch da consultoria
- Monitor + teclado USB para o setup inicial

Boot pelo pendrive (F12/Del/F10 dependendo do mini PC), opção `Try or
install Ubuntu Server`.

_(print: menu inicial do instalador Subiquity)_

Configurações importantes durante o wizard:

| Tela | Valor |
|------|-------|
| Network configuration | IP estático conforme planejamento de rede |
| Storage | Use entire disk + LVM (default OK) |
| Profile | usuário sudo, hostname `vagg-prod` |
| SSH setup | habilitar OpenSSH server |
| Featured Server Snaps | **deixar tudo desmarcado** (Docker virá pelo install.sh) |

_(print: tela de configuração de rede com IP estático preenchido)_

_(print: tela "Install complete" pedindo reboot)_

Após reboot, remova o pendrive. O servidor sobe e fica acessível via SSH.

---

## 3. Preparar a VM

Conecte por SSH:

```bash
ssh seu-usuario@<ip-do-mini-pc>
```

Atualize e fixe timezone:

```bash
sudo apt update && sudo apt upgrade -y
sudo timedatectl set-timezone America/Sao_Paulo
sudo hostnamectl set-hostname vagg-prod
```

Confirme conectividade outbound (SPEC §4.5.2):

```bash
curl -fsS https://licensing.vagg.io/healthz && echo " license-server OK"
curl -fsS https://ghcr.io/v2/ | head -1                      # registry
date  # confira o relógio
```

Se algum desses falhar, **não prossiga** — o instalador vai quebrar
em pontos que parecem aleatórios. Resolva firewall antes.

---

## 4. Rodar o instalador

```bash
curl -fsSL https://install.vagg.io/install.sh -o /tmp/vagg-install.sh
sha256sum /tmp/vagg-install.sh
# Confronte o hash com https://vagg.io/install/checksums.txt

sudo bash /tmp/vagg-install.sh \
    --license-key=VAGG-XXXX-XXXX-XXXX \
    --domain=vpn.suaconsultoria.com.br \
    --admin-email=ti@suaconsultoria.com.br
```

O instalador (5–15 minutos) executa:

1. Validação de pré-requisitos (Ubuntu, root, NTP)
2. Docker + compose plugin via repositório oficial
3. Cria usuário `vagg`, dirs `/var/lib/vagg/*` e `/etc/vagg/*`
4. Pull das 8 imagens (core, ui, portal, dns, 5 protocolos)
5. Geração de secrets (JWT 256-bit, senha admin Argon2id)
6. `alembic upgrade head` num container temporário
7. `systemctl enable --now vagg.service` + `vagg-update.timer`
8. Health-check 30 × 2s

Final esperado:

```
[install] ============================================================
[install] Instalação concluída.
[install] Painel:    https://vpn.suaconsultoria.com.br:8443
[install] Login:     ti@suaconsultoria.com.br
[install] Senha:     ver /etc/vagg/admin-credentials.txt
[install] ============================================================
```

A senha temporária está em `/etc/vagg/admin-credentials.txt` (mode 0600).
**Apague o arquivo após o primeiro login.**

---

## 5. Configurar a OpenVPN corporativa

No servidor OpenVPN da consultoria, adicione ao arquivo de config:

```
push "route 10.200.0.0 255.255.0.0"
push "dhcp-option DNS 10.200.0.53"
push "dhcp-option DOMAIN-SEARCH vpn.suaconsultoria.com.br"
```

E adicione rota estática apontando `10.200.0.0/16` para o IP do mini PC.

```bash
sudo systemctl reload openvpn@server     # ou o nome da sua unit
```

Validar (com um consultor conectado na OpenVPN):

```bash
ping 10.200.0.53                                          # gateway DNS
nslookup test.vpn.suaconsultoria.com.br                   # deve resolver
```

---

## 6. Primeiro acesso ao painel

Abra `https://vpn.suaconsultoria.com.br:8443` no navegador.

_(print: tela de login do vagg-ui)_

Logar com email do admin + senha do `admin-credentials.txt`.

Trocar senha imediatamente em **Sistema → Conta**.

_(print: dashboard limpo, todos os contadores em 0)_

Idioma alterna no canto superior direito (PT/EN), tema dark/light no
ícone ☼/☾.

---

## 7. Adicionar o primeiro cliente

Menu **Clientes → + Novo cliente**.

_(print: formulário de novo cliente vazio)_

Preencher:

| Campo | Exemplo |
|-------|---------|
| ID (slug) | `petroleo` |
| Nome | `Petroleo S.A.` |
| Protocolo | `openvpn` |
| Virtual CIDR | `10.200.1.0/24` |
| Real CIDR | `192.168.1.0/24` (descoberta no `.ovpn` do cliente) |
| DNS server | `192.168.1.10` (DNS interno do cliente) |
| Username | (usuário do cliente VPN) |
| Password | (senha do cliente VPN) |
| Configuração do túnel | conteúdo completo do arquivo `.ovpn` |

_(print: formulário preenchido com dados de exemplo)_

Salvar → o vagg-core sobe o container `vagg-tunnel-petroleo`, tenta
estabelecer o túnel, e atualiza o status. Acompanhe na coluna
**Estado do túnel**:

`stopped` → `starting` (≤30s) → `up`

_(print: tabela de clientes mostrando status `up`)_

Se travar em `starting` ou ir pra `errored`, em **Clientes → Petróleo →
Logs** você vê a saída do tunnel-controller — geralmente é credencial
errada ou MFA pendente (ver §9 abaixo).

---

## 8. Adicionar consultores e policies

### 8.1 Consultores

**Consultores → + Novo consultor**:

| Campo | Como preencher |
|-------|-------|
| Email | corporativo |
| Nome | display |
| OpenVPN username | mesmo username do client-config-dir do OpenVPN |
| Static pool IP | IP fixo no pool da OpenVPN (Opção B do SPEC §7.2) |
| Role | `viewer` / `operator` / `admin` |

_(print: formulário de novo consultor)_

### 8.2 Policies

**Policies → + Nova política**:

- Consultor: João Silva
- Cliente: Petróleo
- Escopo: `full` (acesso completo) ou `subnet:10.200.1.128/26` ou `host:10.200.1.50`

_(print: matriz de policies preenchida)_

> Por padrão, **default-deny**: sem policy explícita, o consultor não
> acessa nada. Iptables emite `LOG VAGG_DENY_RBAC ...` em pacotes
> bloqueados — você vê o motivo em **Auditoria** filtrando por
> `tunnel.denied`.

---

## 9. MFA / OTP em túneis que pedem código

Para clientes com OTP/TOTP/SMS-OTP (OpenConnect Cisco AnyConnect com
2FA, FortiVPN com token), o tunnel-controller pausa em "aguardando OTP"
e o status fica `starting`.

Acesse **Clientes → cliente-X → Enviar OTP**, digite o código gerado
pelo app autenticador / SMS, confirme.

_(print: dialog de envio de OTP)_

O tunnel-controller escreve o código no FIFO interno e a conexão
prossegue.

---

## 10. Validar end-to-end

Conecte um consultor de teste na OpenVPN da consultoria. No notebook
dele:

```bash
ping 10.200.1.1                                       # gateway virtual
nslookup prd-sap.petroleo.vpn.suaconsultoria.com.br   # DNS split-horizon
ssh user@prd-sap.petroleo.vpn.suaconsultoria.com.br   # SSH real
```

Os três precisam funcionar. Em **Auditoria** você vê o evento
`tunnel.access` registrado com timestamp + consultor + host destino.

_(print: timeline de auditoria mostrando o tunnel.access)_

---

## 11. Portal de Transparência (opcional, planos Pro/Enterprise)

Adicionar auditor do cliente final via API admin:

```bash
curl -fsSL -X POST https://vpn.suaconsultoria.com.br:8443/api/v1/external-viewers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "client_id": "petroleo",
        "email": "auditor@petroleo.com.br",
        "display_name": "Maria Compliance",
        "role": "compliance",
        "enable_totp": true
      }'
```

A resposta inclui `totp_uri` — encaminhe para o auditor configurar
Google/Microsoft Authenticator.

_(print: portal de transparência — tela de login pedindo magic link)_

_(print: dashboard do portal com counters e botão "Baixar relatório")_

O PDF gerado tem assinatura Ed25519 verificável offline com:

```bash
python -m vagg_core.scripts.verify_portal_report \
  --canonical canonical.json \
  --signature signature.b64 \
  --public-key pubkey.b64
```

(Os três arquivos são extraídos do rodapé do PDF — o auditor pode usar
qualquer ferramenta que extraia texto).

---

## 12. Manutenção

### Atualizações automáticas

`vagg-update.timer` roda diariamente às 03:30 com jitter ±15min.
Verifica `https://updates.vagg.io/manifest.json`, snapshot de DB+config
em `/var/lib/vagg/backups/`, aplica, health-check, rollback se falhar.

Forçar manualmente:

```bash
sudo /usr/local/bin/vagg-update
```

### Backup manual antes de mudanças críticas

```bash
sudo systemctl stop vagg.service
sudo tar czf /tmp/vagg-snapshot-$(date +%F).tgz \
    /var/lib/vagg/db /etc/vagg/core.env
sudo systemctl start vagg.service
```

### Logs

```bash
journalctl -u vagg.service -f         # supervisor
docker logs -f vagg-core              # API
docker logs -f vagg-tunnel-petroleo   # túnel específico
```

### Alertas comuns

| Sintoma | Causa | Resolução |
|---------|-------|-----------|
| `install.sh` falha em "Validating license" | License-server inalcançável | Liberar 443 outbound |
| `vagg-tunnel-X` em CrashLoopBackOff | Credencial errada | `docker logs vagg-tunnel-X` |
| Túnel up mas DNS não resolve | DNS do cliente inacessível pelo tun | `docker exec vagg-tunnel-X dig @<dns> <host>` |
| Consultor pinga gw mas não pinga host | NAT errado ou policy bloqueando | Auditoria → filtrar consultor → razão do drop |
| Painel inacessível | nginx do ui down | `docker compose -f /etc/vagg/docker-compose.yml up -d vagg-ui` |

---

## 13. Desinstalar (se preciso)

```bash
sudo systemctl disable --now vagg.service vagg-update.timer
sudo docker compose -f /etc/vagg/docker-compose.yml down -v
sudo rm -rf /var/lib/vagg /etc/vagg
sudo rm /etc/systemd/system/vagg*.service /etc/systemd/system/vagg-update.timer
sudo rm /usr/local/bin/vagg-update
sudo systemctl daemon-reload
sudo userdel -r vagg 2>/dev/null
```

---

## Apêndice — Diagrama de rede

```
┌─────────────────────────────────────────────────────────────┐
│ Notebook do consultor                                       │
│   ↓ OpenVPN                                                 │
│ Pool 10.8.0.0/24                                            │
└──────────┬──────────────────────────────────────────────────┘
           │
           ↓ rota: 10.200.0.0/16 → Mini PC
┌──────────┴──────────────────────────────────────────────────┐
│ Mini PC (vagg-prod)                                         │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ vagg-core (FastAPI)  vagg-ui (nginx)  vagg-portal (n) │ │
│  │ vagg-dns (CoreDNS, 10.200.0.53)                       │ │
│  │ iptables: NETMAP virtual ↔ real, RBAC chains          │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ tun-petroleo  → 192.168.1.0/24 (real)                 │ │
│  │ tun-varejo    → 192.168.1.0/24 (real, mesmo CIDR!)    │ │
│  │ tun-industria → 10.50.0.0/16   (real)                 │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
           │
           ↓ outbound: cada túnel sai pelo seu protocolo
        Servidores VPN dos clientes
```

NAT torna 192.168.1.50 do Petróleo → `10.200.1.50` no consultor, e
192.168.1.50 do Varejo → `10.200.2.50`, sem colisão.
