# VPN Aggregator — Especificação Técnica Mestre

> **Versão:** 1.2
> **Data:** 2026-04-30
> **Audiência primária:** Claude Code (implementação)
> **Audiência secundária:** Equipe de IT da consultoria (instalação), gestor de produto (visão)
> **Idioma das decisões:** Português · **Idioma do código:** Inglês
>
> **Mudanças v1.1 → v1.2:**
> - Adicionada restrição de hardware-target em Seção 2.1 (x86_64 + AES-NI obrigatório)
> - Expandida Seção 5.7 (instalador) para suportar modos `byo` e `appliance`
> - Adicionada Seção 14 (Hardware Targets e Appliance Strategy)
> - Hardware de referência para desenvolvimento: Lenovo ThinkCentre M93p Tiny
>
> **Mudanças v1.0 → v1.1:**
> - Adicionada Seção 1.5 (Modelo de Responsabilidade Compartilhada)
> - Adicionada Seção 1.6 (Posicionamento Estratégico — modelo B2B2B)
> - Adicionada Seção 1.7 (Diferencial Irresistível — Portal de Transparência)
> - Adicionada Seção 2.5 (Licenciamento e Compliance Comercial)
> - Adicionada Seção 5.6 (Portal de Transparência para Cliente Final)
> - Adicionada Fase 11 ao plano de implementação
> - Adicionada Seção 13.5 (Prior Art e Building Blocks Verificados)

---

## Sumário Numerado

```
0.  Instruções de uso para Claude Code
1.  Visão geral do produto
2.  Decisões técnicas fechadas (NÃO rediscutir)
3.  Arquitetura
4.  Networking — NAT, DNS, Roteamento, Firewall
5.  Componentes detalhados
6.  Licenciamento via Stripe
7.  RBAC e Multi-tenancy
8.  Auditoria e Compliance
9.  Instalação (guia para IT da consultoria)
10. Operação contínua
11. Plano de implementação por fases
12. Estrutura do repositório
13. Anexos
14. Hardware Targets e Appliance Strategy
```

---

## 0. Instruções de uso para Claude Code

Este documento é a **fonte única da verdade**. As regras de uso eficiente:

1. **Não rediscutir decisões da Seção 2.** Stack, libraries, padrões — tudo já decidido.
2. **Trabalhar uma fase por vez.** A Seção 11 quebra a implementação em 10 fases sequenciais. Cada fase tem entradas (o que ler), saídas (o que produzir) e critérios de aceite (testes).
3. **Ao receber um pedido tipo "implemente Fase X":** ler **somente** a seção da fase + as seções referenciadas nela. Não carregar o documento inteiro.
4. **Não inventar arquivos fora da estrutura da Seção 12.** Se um arquivo não está no layout, perguntar antes de criar.
5. **Testes são parte da fase, não opcional.** Cada fase precisa terminar verde nos testes definidos no critério de aceite.
6. **Ao mudar contrato de API ou schema de DB:** atualizar este documento na mesma PR.
7. **Idioma:** comentários e nomes de variáveis em inglês; mensagens de log e UI em português.

---

## 1. Visão geral do produto

### 1.1 O que é

VPN Aggregator é um produto B2B SaaS com componente self-hosted para consultorias de TI (foco inicial: consultorias SAP brasileiras). Resolve o problema do consultor que precisa acessar redes de múltiplos clientes simultaneamente — cada uma com sua VPN, suas credenciais, seu MFA, seus IPs sobrepostos.

A consultoria instala o **Aggregator Gateway** dentro da própria infraestrutura, atrás da OpenVPN corporativa que já existe. O Aggregator mantém túneis persistentes para todos os clientes da consultoria. Quando um consultor conecta na OpenVPN da empresa, ele automaticamente passa a enxergar as redes dos clientes que tem permissão, com nomes amigáveis via DNS, sem nunca rodar um cliente VPN específico no notebook.

### 1.2 Quem usa

| Perfil | Uso típico |
|---|---|
| Consultor | Conecta na OpenVPN da empresa (que já usa hoje) e acessa SAP/servidores dos clientes via DNS amigável |
| Admin de TI da consultoria | Configura clientes novos, cria políticas RBAC, monitora túneis, trata incidentes |
| Gestor de projeto | Visualiza painel de utilização, audit logs para compliance |
| Auditoria interna / cliente final | Solicita relatório de quem acessou o quê e quando |

### 1.3 Problema que resolve

| Pain point | Custo atual | Como resolve |
|---|---|---|
| Consultor perde 15-30min/dia entre VPNs | R$ 30-50k/mês em consultoria de 30 pessoas | Uma única VPN; outras VPNs são abstraídas |
| IT instala N clientes VPN em N notebooks | R$ 10k+/mês em chamados | Zero clientes VPN nos notebooks |
| Sem audit trail centralizado | Risco de NDA/LGPD | Toda conexão e acesso fica logado |
| Revogar consultor que saiu | Risco até remover de N VPNs | Revogação central, instantânea |
| MFA repetido em N VPNs | Atrito enorme | MFA da OpenVPN da empresa apenas |
| IPs sobrepostos entre clientes | Bug obscuro de roteamento | NAT remapping centralizado |

### 1.4 Não-objetivos (escopo explícito)

Para evitar scope creep:

- **Não substitui** a OpenVPN corporativa existente; senta atrás dela.
- **Não é** um zero-trust gateway tipo Cloudflare Access ou Tailscale.
- **Não inspeciona** tráfego (sem DPI, sem MITM TLS).
- **Não termina** os túneis de cliente no notebook do consultor — túneis vivem no Aggregator.
- **Não substitui** SIEM/IDS — gera logs estruturados que SIEMs consomem.
- **Não fornece** acesso direto via internet — sempre passa pela OpenVPN corporativa.

### 1.5 Modelo de Responsabilidade Compartilhada

Inspirado no AWS Shared Responsibility Model, esta seção delimita o que cabe a quem. Esse modelo é também material de venda — diretor de TI gosta de fornecedor que sabe o que NÃO faz.

| Camada | Responsabilidade | Exemplo concreto |
|---|---|---|
| Segurança física do datacenter | Consultoria / cloud provider | Acesso ao rack, energia, climatização |
| Segurança de perímetro de rede | Consultoria | Firewall corporativo, IDS/IPS, segmentação, MITM proxy |
| Hardening de SO da VM Aggregator | Consultoria + Produto | Consultoria: patches, antivírus, SIEM. Produto: instalador aplica CIS benchmark |
| Detecção de malware no host | Consultoria | EDR / antivírus corporativo |
| Detecção de port scan, DDoS | Consultoria | SIEM corporativo |
| Autenticação do consultor (1º fator) | Consultoria | OpenVPN existente + LDAP/RADIUS/cert da empresa |
| MFA do consultor (acesso à rede da empresa) | Consultoria | Duo / Microsoft Authenticator no OpenVPN |
| **Identidade do consultor após autenticado** | **Produto** | **vagg-core resolve username via RADIUS lookup** |
| **Autorização (RBAC consultor × cliente)** | **Produto** | **Policies, default-deny, scope granular** |
| **Revogação atômica de acesso** | **Produto** | **API + UI de offboarding em <5s** |
| **Audit trail de acesso a redes de clientes** | **Produto** | **Hash chain, append-only, export estruturado** |
| **Gestão de credenciais de VPNs de clientes** | **Produto** | **Cofre central, rotação, separação por cliente** |
| **Roteamento e NAT entre redes virtuais e reais** | **Produto** | **iptables NETMAP atômico** |
| Segurança da rede do cliente final | Cliente final | Firewall, IDS, AV no servidor SAP, etc — fora do escopo |
| Conformidade contratual da consultoria com cliente final | Consultoria + Produto | Consultoria: contrato, processo. Produto: evidências técnicas (audit, RBAC) |
| Licenciamento Stripe e cobrança | Produto | License server cuida disso |
| Backup operacional do estado do produto | Consultoria | Backup script roda automaticamente; consultoria valida o destino |
| Atualização de versão do produto | Consultoria (decisão) + Produto (mecanismo) | `vagg-update` é fornecido; consultoria escolhe quando aplicar |
| Treinamento do consultor | Consultoria | Doc do produto disponível, mas treino interno é da consultoria |

**Princípio de design:** o produto NÃO tenta fazer o trabalho que o perímetro corporativo já faz. Tudo que é genérico de infra (filtrar tráfego malicioso, detectar anomalia de rede, bloquear malware) fica fora. O produto cobre exclusivamente as camadas de **identidade, autorização, auditoria e gestão de credenciais de terceiros** — exatamente o que o perímetro corporativo NÃO consegue fazer.

Esse modelo deve ser exibido na primeira página do contrato comercial, no onboarding, e no material de venda. Define expectativas, protege juridicamente, e mostra maturidade.

### 1.6 Posicionamento Estratégico — Modelo B2B2B

O produto opera num modelo de três camadas que é raro e por isso valioso. Entender isso é essencial para venda e para arquitetura.

#### As três entidades

```
┌───────────────────────────────────────────────────────────┐
│  Cliente Final (B nº2)                                    │
│  Petrobras, Vale, Itaú, MRV, etc                          │
│  ↑ Contrata serviços de SAP/TI                            │
│                                                           │
│  ┌────────────────────────────────────────────────────┐   │
│  │  Consultoria (B nº1)                               │   │
│  │  Stefanini, TIVIT, BRQ, T-Systems, etc             │   │
│  │  ↑ Compra o VPN Aggregator                         │   │
│  │                                                    │   │
│  │  ┌──────────────────────────────────────────────┐  │   │
│  │  │  Produto (você)                              │  │   │
│  │  │  VPN Aggregator                              │  │   │
│  │  └──────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────┘
```

#### Por que esse nicho está vazio

Mapeamento competitivo: nenhum dos principais produtos open-source ou comerciais atende esse modelo:

| Categoria | Exemplos | O que fazem | Por que NÃO atende |
|---|---|---|---|
| Mesh VPN self-hosted | Tailscale, NetBird, Headscale, ZeroTier | Você constrói SUA mesh | Pressupõe que você é dono da rede |
| Reverse proxy + identity | Pangolin, Cloudflare Access, Twingate | Expõe SEUS recursos com autenticação | Direção oposta — você quer consumir, não expor |
| Concentrador VPN enterprise | Pulse Secure, Palo Alto GP, Fortinet | Termina VPN entrante na SUA rede | Modelo single-tenant |
| Cliente VPN com gerência | Pritunl, OpenVPN AS | Clientes conectam à SUA rede | Idem |
| Multi-VPN client tool | ethack/docker-vpn, scripts caseiros | Roda múltiplas VPNs no notebook do usuário | Sem multi-tenancy, sem RBAC, sem audit |
| Cloud VPN (SASE/SSE) | Zscaler, Netskope, Cloudflare WARP | Tráfego sai pela rede deles | Modelo invertido |

O quadrante "consumir VPNs de terceiros + multi-tenant + audit + revenda corporativa" não tem produto.

#### Implicações estratégicas

1. **Você é o primeiro mover em uma categoria que ainda não tem nome.** Vantagem: mercado virgem. Risco: demanda não-validada — antes de escalar venda, precisa de 2-3 design partners pra validar willingness-to-pay.
2. **Não vale a pena tentar competir como "alternativa do Tailscale".** Tailscale tem $1B em funding. Diferenciação tem que ser pelo nicho, não por features.
3. **Mercado-alvo principal:** consultorias B2B com mais de 20 consultores, mais de 5 clientes simultâneos, presença no Brasil (LGPD). TAM realista: ~500-2000 empresas.
4. **Mercados adjacentes potenciais (pós-MVP):** MSPs (Managed Service Providers), grandes integradoras de tecnologia, escritórios de advocacia com clientes em múltiplas redes, contabilidades que acessam ERPs de clientes.

### 1.7 O Diferencial Irresistível — Portal de Transparência para Cliente Final

Esta é a feature que ganha contrato. Ler com atenção.

#### O problema que resolve

Hoje a relação entre cliente final e consultoria, no aspecto de acesso à rede, é de **confiança cega**. Cliente final precisa confiar:
- Que a consultoria revogou acesso de funcionário desligado
- Que a consultoria audita o que cada consultor faz
- Que credenciais não estão em planilhas no Drive de alguém
- Que se acontecer incidente, há trilha de auditoria

Quando o cliente final pergunta "me mostra o relatório de quem da consultoria acessou minha rede no último trimestre", a resposta da consultoria hoje é uma planilha exportada de algum lugar duvidoso, sem garantia de integridade.

#### A solução

O Aggregator expõe um **portal read-only** dedicado ao cliente final. A consultoria, com um clique, gera credenciais para o cliente final acessar:

```
https://transparency.consultoria.com.br/cliente/petrobras
```

Login do cliente final mostra:

| Visualização | Conteúdo |
|---|---|
| Dashboard | # consultores ativos com acesso à rede do cliente final, # acessos no mês, # policies expiradas |
| Lista de consultores | Nome, função, projeto, data de adição, última conexão |
| Audit timeline | Eventos cronológicos: conexões, acessos a hosts, mudanças de policy |
| Policies ativas | Quem tem acesso a quê, com qual escopo, válida até quando |
| Histórico de revogações | Quem perdeu acesso, quando, por quê (offboarded / project ended / role change) |
| Export | Relatório PDF assinado para auditoria interna do cliente final, mensal ou ad-hoc |

#### Por que isso ganha contrato

**Para o gestor de TI da consultoria (quem compra o produto):**
- Argumento de venda novo no RFP — categoria onde competidores não têm resposta
- Reduz pressão de auditoria do cliente final (auditor consulta direto, sem onerar a consultoria)
- Cria diferenciação visível em demonstrações comerciais
- Facilita renovação contratual ("vocês têm o portal, isso é difícil de tirar")

**Para o cliente final (Petrobras, Vale, Itaú):**
- Visibilidade em tempo real sem depender de relatórios produzidos sob demanda
- Evidência forense pré-fabricada para incident response
- Atende requisitos contratuais e regulatórios (LGPD Art. 37, SOX Section 404, BACEN 4.658, etc.)
- Reduz dependência de confiança subjetiva — "trust through transparency"

#### Por que é defensável

- **Tecnicamente requer arquitetura centralizada.** Consultoria que tenta replicar com scripts não consegue — não tem audit log centralizado por construção
- **Cria efeito de rede inverso.** Quanto mais clientes finais usarem o portal, mais a consultoria fica presa ao produto (switching cost alto)
- **Onboarding viral interno.** Auditor de Cliente A vê o portal, comenta com auditor de Cliente B em outra empresa, vira pressão pra outras consultorias adotarem
- **Difícil de copiar superficialmente.** Não basta criar uma tela read-only — precisa do hash chain de auditoria, do RBAC granular, da revogação atômica, tudo o que está nas Seções 7 e 8

#### Modelo de cobrança

Portal de transparência é incluso no plano **Professional** e **Enterprise**, NÃO no Starter. Isso cria um upgrade path natural — consultoria começa no Starter, fecha primeiro contrato grande com cliente final exigente, naturalmente vai pro Professional.

Cliente final não paga nada — quem paga é a consultoria. Mas o cliente final pode pedir o portal contratualmente, o que vira argumento da consultoria pra justificar o upgrade.

#### Diferenciais Tier 2 (importantes, não irresistíveis)

Estes ficam no roadmap pós-MVP, todos viáveis com a arquitetura existente:

| Feature | Valor | Esforço |
|---|---|---|
| Just-in-time access via Slack | Consultor pede, gerente aprova com 1 clique, expira ao fim do dia | Médio (integração Slack OAuth) |
| Time-bounded policies por padrão | Toda policy nasce com expiração de 30 dias; renovação exige justificativa | Baixo (já no schema) |
| One-click LGPD report | PDF estruturado conforme ANPD | Baixo |
| Onboarding zero-touch | IT faz upload do .ovpn, sistema tenta conectar e sugere mapeamentos | Médio |
| Mobile companion app (consultor) | OTP, status, requests JIT | Alto (app nativo) |
| Anomaly detection | Flag "Consultor X nunca acessou Cliente Y antes" | Médio (regras simples; ML é overkill) |
| SAP-specific integrations | Integração com SM01/SM50/SU01 logs | Alto (e nichado) |

---

## 2. Decisões técnicas fechadas (NÃO rediscutir)

Listar tudo que já está decidido evita rounds de discussão e reduz consumo de tokens. Mudanças aqui exigem justificativa técnica explícita.

### 2.1 Stack

| Camada | Tecnologia | Por quê |
|---|---|---|
| Aggregator Core (API) | Python 3.12 + FastAPI + uvicorn | Familiar, ecosystem maduro, async nativo |
| Aggregator persistence | SQLite (WAL mode) | Single-node, simples, suficiente |
| VPN client containers | Docker + Docker Compose | Isolamento, padrão da indústria |
| DNS server interno | CoreDNS | Plugins flexíveis, split-horizon nativo |
| Admin UI | React 18 + Vite + TanStack Query + shadcn/ui | Padrão moderno, bem suportado |
| License Server | Python 3.12 + FastAPI | Consistência com Aggregator |
| License Server DB | Postgres 16 | Hospedado em Cloud Run/Render/Fly |
| License signing | Ed25519 (PyNaCl) | Mais rápido que RSA, chaves menores |
| Pagamento | Stripe Subscriptions API | Mercado padrão, suporta BRL |
| Audit log shipping | Vector (vector.dev) | Lightweight, configurável |
| Métricas | Prometheus + Grafana (opcional) | Padrão de indústria |
| Container orchestration no host | docker-compose v2 | Sem Kubernetes — single-VM |
| OS alvo | Ubuntu 24.04 LTS | LTS, kernel recente, bem suportado |
| TLS interno | Let's Encrypt via DNS-01 challenge | Funciona em IPs internos |

#### Restrições de hardware-target (CRÍTICO — não violar)

O produto será distribuído em duas formas: software-only (BYO hardware) e appliance pré-configurado. Para manter ambos viáveis, **todo código precisa rodar com:**

- Arquitetura `x86_64` apenas (sem ARM no MVP — Pi/Apple Silicon ficam para roadmap pós-MVP)
- Mínimo: 2 cores com AES-NI, 4 GB RAM, 30 GB SSD, 1× Gigabit Ethernet
- Recomendado: 4 cores com AES-NI, 8 GB RAM, 128 GB SSD
- Sem dependências de GPU, hardware aceleradores específicos, ou serviços cloud-only
- Sem dependências que precisem mais de 4 GB de RAM em runtime
- Tudo deve funcionar offline após instalação inicial (exceto refresh diário de licença)

Hardware de referência para desenvolvimento e demos: **Lenovo ThinkCentre M93p Tiny** (i5-4570T, 8GB DDR3, 128GB SSD, 1× Gigabit). Detalhes na Seção 14.

Ao implementar qualquer fase, validar regularmente com `docker stats` que cada container consome menos que seu orçamento alocado. Stack inteiro com 5 clientes simulados deve consumir <2GB RAM e <30% CPU em hardware tier mínimo.

### 2.2 Padrões de código

| Padrão | Regra |
|---|---|
| Formatação Python | `ruff format` (linha 100) |
| Linter Python | `ruff check` com config rigorosa |
| Type checking | `mypy --strict` em todo código de produção |
| Test runner | `pytest` + `pytest-asyncio` |
| Frontend lint | `eslint` + `prettier` |
| Commits | Conventional Commits (feat/fix/chore/docs) |
| Branching | trunk-based, feature branches curtas |
| API style | REST + JSON; OpenAPI gerado pelo FastAPI |
| Auth de API | OAuth2 password flow + JWT (HS256 para sessão admin) |
| Erros | Sempre HTTP semântico + body `{detail, code, trace_id}` |
| Logs | Structured JSON, campo `trace_id` em tudo |
| Timezone | UTC internamente, conversão na UI |

### 2.3 Convenções de naming

```
Componentes:     kebab-case            (vpn-aggregator-core)
Pacotes Python:  snake_case            (vpn_aggregator)
Containers:      vagg-{component}      (vagg-core, vagg-dns, vagg-tunnel-petroleo)
Networks Docker: vagg-net-{purpose}    (vagg-net-mgmt, vagg-net-tenants)
Database tables: snake_case            (clients, tunnels, consultants, audit_events)
API routes:      /api/v1/{resource}    (/api/v1/clients)
Env vars:        VAGG_{COMPONENT}_{KEY} (VAGG_CORE_DB_PATH)
```

### 2.4 Versionamento

- **Produto:** SemVer 1.0.0+
- **API:** prefixo `/api/v1`; breaking change → `/api/v2`
- **License JWT:** campo `lv` (license_version) começa em 1

### 2.5 Licenciamento do código e compliance comercial

#### Licença do nosso código

Decidido: **Apache License 2.0** para todo o código próprio (vagg-core, vagg-ui, vagg-license-server, vagg-installer, vagg-tunnel-* Dockerfiles).

Razões:
- Permissiva (permite uso comercial, redistribuição, sublicenciamento)
- Cláusula de patentes protege contra litígio retaliatório
- Compatível com todos os componentes externos que usamos
- Não força AGPL-style "share-alike" — nosso modelo de receita não depende de "fechar" o código

A monetização vem de: licença de uso (chave Stripe), serviços de implantação, suporte, customização para cliente final exigente. Não vem de manter código fechado. Mesma estratégia da Anthropic com vários componentes.

Se mais tarde aparecer concorrente que faça fork e venda contra você sem agregar valor, considerar mover para licença source-available tipo BSL (Business Source License) ou Elastic License v2 — mas só se isso virar problema real, não preventivamente.

#### Análise de cada componente externo

| Componente | Licença | Uso permitido | Cuidado |
|---|---|---|---|
| `openconnect` (binário) | LGPL-2.1 | Rodar em container como processo separado | Não modificar e re-distribuir sem source disclosure |
| `openfortivpn` (binário) | GPL-3.0 | Rodar em container | Idem |
| `OpenVPN` (binário) | GPL-2.0 | Rodar em container | Idem; "OpenVPN" é trademark — não usar no nome do produto |
| `WireGuard` (binário/kernel) | GPL-2.0 | Rodar em container | "WireGuard®" é trademark de Jason Donenfeld; usar com asterisco |
| `strongSwan` (binário) | GPL-2.0 | Rodar em container | Idem |
| `CoreDNS` | Apache 2.0 | Uso livre | Nenhum |
| `Vector` (vector.dev) | MPL 2.0 | Uso livre | Modificações no Vector requerem disclosure (mas usamos sem modificar) |
| `Docker` | Apache 2.0 | Uso livre | Trademark "Docker" não usar no nome |
| Imagens base (Ubuntu, Alpine) | Várias OSS | Uso livre | Nenhum |
| Bibliotecas Python (FastAPI, SQLAlchemy, etc.) | MIT/BSD/Apache | Uso livre | Verificar `pip-licenses` no CI |
| Bibliotecas JS (React, Vite, shadcn, TanStack) | MIT | Uso livre | Verificar `license-checker` no CI |
| `aw1cks/openconnect` Dockerfile (referência) | MIT (verificar) | Forkar e adaptar | Atribuição no NOTICE |

#### Componentes que NÃO podemos forkar comercialmente (armadilha AGPL)

Verificado em pesquisa de 2026-04-30:

| Projeto | Status | Por que não dá |
|---|---|---|
| **NetBird** (`management/`, `signal/`, `relay/`) | AGPLv3 desde v0.53.0 (Aug/2025) | Oferecer como serviço comercial obriga release das modificações sob AGPL |
| **Pangolin** (server) | AGPLv3 + Fossorial Commercial License | FCL **proíbe explicitamente** revenda como SaaS competidor |
| **Pritunl** | AGPLv3 | Idem AGPL |
| **NetBird clients** | BSD-3 | Forkável, mas é só o cliente — não o que precisamos |

Regra prática: **antes de incluir qualquer dependência nova, verificar `LICENSE` no repo.** Se for AGPL ou contém "FCL/Commercial License" mais restritiva, não usar. Se permissiva (MIT/BSD/Apache 2.0/MPL 2.0), OK.

#### Componentes que podemos estudar livremente (sem forkar)

| Projeto | Licença | O que estudar |
|---|---|---|
| **Headscale** | BSD-3 | API design, identidade, ACL flatfile, multi-tenant patterns |
| **Octelium** | Apache 2.0 | Policy engine, infraestrutura Kubernetes-native (mesmo que não usemos K8s) |
| **Firezone** | Apache 2.0 | UI/UX de zero-trust gateway |
| **Pritunl** (mesmo AGPL) | AGPL | UI patterns, modelo enterprise (estudar visualmente, não copiar código) |

Regra: estudar UX/arquitetura é livre. Copiar código de projeto AGPL para nosso repo é contaminação.

#### Trademarks a respeitar

Nunca usar no nome do produto, logo, ou marketing principal:
- **OpenVPN** (registered trademark da OpenVPN Inc.) → "compatível com OpenVPN protocol"
- **WireGuard®** (registered trademark de Jason A. Donenfeld) → "compatível com WireGuard®"
- **Cisco AnyConnect™** → "compatível com Cisco AnyConnect VPN"
- **FortiClient™** → "compatível com Fortinet SSL VPN"
- **GlobalProtect™** → "compatível com Palo Alto GlobalProtect"
- **Pulse Secure™** / **Ivanti Connect Secure™** → idem

Padrão de copy seguro: *"VPN Aggregator suporta os protocolos compatíveis com OpenVPN, WireGuard®, Cisco AnyConnect, Fortinet SSL VPN, Palo Alto GlobalProtect e IPsec."*

#### Patentes — riscos e mitigações

| Risco | Mitigação |
|---|---|
| Cisco patentes em torno do AnyConnect | `openconnect` é OSS clean-room implementation com 15+ anos sem litígio. Risco residual baixo |
| Patentes do WireGuard | Jason Donenfeld licenciou amplamente; baixo risco |
| Patente de NAT specific (Symantec, Juniper) | Implementação via iptables NETMAP é técnica padrão e antiga; baixo risco |

Não fazer **patent search** preventivo no MVP. Se chegar a 100+ clientes pagantes, contratar advogado de IP pra fazer FTO (freedom-to-operate) review. Antes disso é over-engineering legal.

#### Compliance regulatório brasileiro

| Requisito | Como atender |
|---|---|
| LGPD — base legal de tratamento | Contrato com a consultoria define controlador (consultoria) e operador (produto). Cláusulas no ToS |
| LGPD — Art. 37 (registro de operações) | Audit log já cumpre, com retenção configurável |
| LGPD — direitos do titular (acesso, eliminação) | Audit log do consultor é dado pessoal dele; portal admin permite export e delete (com efeito quebrando hash chain — documentar) |
| Marco Civil da Internet — Art. 13 a 15 | Audit logs (retenção mínima 6 meses para conexão, 1 ano padrão); IPs de origem registrados |
| ISS sobre subscription SaaS | Item de contabilidade — recomendar enquadramento como "licenciamento de software" (alíquota varia 2-5% conforme município) |
| Stripe BRL | Stripe opera no Brasil, suporta BRL, CNPJ (não CPF do titular) na conta |
| Nota fiscal | Stripe não emite NF-e brasileira — integrar com gateway de NF (Omie, Conta Azul, etc.) ou emitir manualmente após payment_succeeded |

#### Cláusulas a incluir no contrato com a consultoria

(Material para advogado redigir, não jurídico definitivo)

1. **Aceitação dos termos das VPNs dos clientes finais** — consultoria declara que tem autorização contratual de cada cliente final para usar clientes VPN open-source (`openconnect`, `openfortivpn`, etc.) ao invés do cliente oficial. Em caso de violação contratual com cliente final, responsabilidade é da consultoria.
2. **Limitação de responsabilidade** — produto é fornecido "as-is" com cap de responsabilidade no valor de 12 meses de subscription.
3. **Auditoria** — consultoria pode auditar logs do produto a qualquer momento; produto pode usar telemetria anonimizada para melhoria (opt-out disponível).
4. **Compliance de dados** — consultoria é controladora dos dados pessoais; produto é operador. DPA (Data Processing Agreement) anexo.
5. **Ownership de logs** — logs gerados pertencem à consultoria; produto não tem direito de uso comercial deles.
6. **Off-boarding** — em caso de cancelamento, consultoria tem 90 dias para exportar dados; após isso, deletados.

---

## 3. Arquitetura

### 3.1 Diagrama lógico

```
┌──────────────────────────────────────────────────────────────────────┐
│                       NOTEBOOKS DOS CONSULTORES                      │
│  [João — SAP]   [Maria — Basis]   [Pedro — MM]   [...N consultores]  │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ Cliente OpenVPN (que já existe)
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│         OPENVPN SERVER DA CONSULTORIA (já existe, não muda)          │
│  - Autentica usuário (LDAP/RADIUS/cert)                              │
│  - Atribui IP do pool 10.8.0.0/24                                    │
│  - Push routes apontando para Aggregator                             │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
                                   ▼ subnet corporativa interna
┌──────────────────────────────────────────────────────────────────────┐
│                      VM AGGREGATOR (o produto)                       │
│  Ubuntu 24.04 LTS · 4 vCPU · 8GB RAM · 50GB SSD                      │
│                                                                      │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────────┐    │
│  │ vagg-core  │  │ vagg-dns   │  │ vagg-ui    │  │ vagg-router  │    │
│  │ (FastAPI)  │  │ (CoreDNS)  │  │ (React)    │  │ (iptables)   │    │
│  └────────────┘  └────────────┘  └────────────┘  └──────────────┘    │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │              POOL DE TÚNEIS (1 container por cliente)        │    │
│  │  vagg-tunnel-petroleo  vagg-tunnel-varejo  vagg-tunnel-N…    │    │
│  │  (openconnect)         (openfortivpn)      (openvpn)         │    │
│  └──────────────────────────────────────────────────────────────┘    │
└─────────┬─────────────────────────────────────────────────────┬──────┘
          │                                                     │
          │ HTTPS daily                                         │ Túneis VPN
          ▼                                                     ▼
┌──────────────────────────┐                ┌──────────────────────────┐
│   LICENSE SERVER (cloud) │                │   REDES DOS CLIENTES     │
│   FastAPI + Stripe       │                │   Petróleo · Varejo · …  │
└──────────────────────────┘                └──────────────────────────┘
```

### 3.2 Fluxo de pacote (consultor → cliente)

Trace de um `ssh consultor@prd-sap.petroleo.vpn.consultoria.com.br`:

1. **Notebook do consultor** resolve o hostname via DNS pushed pela OpenVPN → DNS server = Aggregator (10.8.0.1).
2. **Aggregator DNS** (CoreDNS) recebe query `prd-sap.petroleo.vpn.consultoria.com.br`. Match na zona `petroleo.vpn.consultoria.com.br`. Forward para o resolver do túnel do Petróleo.
3. **CoreDNS** retorna IP virtual `10.200.1.50` (mapeamento NAT do IP real `192.168.1.50` do cliente).
4. **Notebook** envia pacote SSH para `10.200.1.50` via OpenVPN.
5. **OpenVPN server** roteia pacote para Aggregator (rota estática para `10.200.0.0/16`).
6. **Aggregator (vagg-router)** recebe pacote, consulta tabela RBAC: usuário `joao` tem permissão para `petroleo`? Sim. Consulta tabela NAT: `10.200.1.50` → cliente `petroleo`, IP real `192.168.1.50`.
7. **iptables DNAT** reescreve destino para `192.168.1.50`, marca pacote para sair pela interface do túnel `petroleo`.
8. **Pacote sai** pelo container `vagg-tunnel-petroleo` (interface `tun-petroleo`).
9. **Servidor de SAP do cliente** recebe pacote como vindo do IP do cliente VPN da consultoria.
10. **Resposta** volta pelo caminho inverso, com SNAT.

Tempo total esperado: <5ms de overhead vs conexão direta.

### 3.3 Componentes principais (resumo)

| Componente | Linguagem | Responsabilidade |
|---|---|---|
| `vagg-core` | Python | API REST, orquestração de túneis, NAT rules, RBAC, audit |
| `vagg-dns` | CoreDNS | DNS split-horizon |
| `vagg-ui` | React | Painel admin |
| `vagg-router` | n/a | Conjunto de regras iptables/nftables gerenciadas pelo core |
| `vagg-tunnel-{client}` | varia | Container por cliente, roda o cliente VPN específico |
| `vagg-license-server` | Python | Cloud-hosted, valida assinaturas Stripe |
| `vagg-installer` | Bash | Script único de instalação |

### 3.4 Stack runtime (na VM aggregator)

```
[Ubuntu 24.04 LTS host]
├─ systemd unit: vagg-core.service   → roda o FastAPI core
├─ systemd unit: vagg-router.service → aplica regras iptables na inicialização
├─ docker compose stack:
│   ├─ vagg-ui          (porta 8443, HTTPS)
│   ├─ vagg-dns         (porta 53 UDP/TCP)
│   ├─ vagg-tunnel-*    (vários, dinamicamente gerenciados pelo core)
│   └─ vagg-vector      (shipping de logs)
```

`vagg-core` roda **fora** do Docker, direto no host, porque precisa manipular `iptables`, `ip route`, `ip rule`. Mexer em rede do host de dentro de container é receita de bug.

---

## 4. Networking — NAT, DNS, Roteamento, Firewall

Esta é a seção crítica. Todo o produto se sustenta nas decisões de rede.

### 4.1 Modelo de rede em camadas

| Camada | Range | Propósito |
|---|---|---|
| Internet | público | Não tocada |
| OpenVPN corporativa | 10.8.0.0/24 | Pool de IPs dos consultores (já existe) |
| Subnet corporativa | varia | Onde a VM aggregator vive |
| Aggregator mgmt net | 172.20.0.0/24 | Rede Docker para core ↔ DNS ↔ UI |
| **Aggregator virtual space** | **10.200.0.0/16** | **Range virtual onde clientes são apresentados** |
| Aggregator tenants net | 172.30.0.0/24 | Rede Docker para containers de túnel |
| Túneis para clientes | varia | Cada cliente tem sua subnet real |

O range `10.200.0.0/16` é reservado para o produto. Cada cliente recebe um `/24` dentro dele:

```
10.200.1.0/24 → Cliente Petróleo (real: 192.168.1.0/24)
10.200.2.0/24 → Cliente Varejo   (real: 192.168.1.0/24)  ← mesmo range real
10.200.3.0/24 → Cliente Indústria (real: 10.10.0.0/16)   ← /16 mapeado em /24 sumarizado
10.200.4.0/24 → Cliente Banco
…
10.200.255.0/24 → reservado
```

Capacidade: 254 clientes por instalação (suficiente para qualquer consultoria realista).

### 4.2 NAT remapping detalhado

#### Por que precisa

Sem NAT remapping, IPs sobrepostos quebram tudo. Cliente A e Cliente B usando ambos `192.168.1.0/24` é o caso comum (não excepcional) — qualquer consultoria com >5 clientes encontra isso.

#### Como funciona

Para cada cliente, o aggregator mantém:

1. **Subnet real** do cliente (descoberta via push do servidor VPN dele)
2. **Subnet virtual** atribuída pelo admin no onboarding (ex.: `10.200.1.0/24`)
3. **Mapeamento 1:1** entre IPs reais e virtuais

Implementação via `iptables NETMAP` (mapeia ranges inteiros, sem precisar de regra por host):

```bash
# Tráfego SAINDO do consultor (DNAT — virtual → real)
iptables -t nat -A PREROUTING -d 10.200.1.0/24 -j NETMAP --to 192.168.1.0/24

# Tráfego VOLTANDO do cliente (SNAT — real → virtual)
iptables -t nat -A POSTROUTING -s 192.168.1.0/24 -o tun-petroleo -j NETMAP --to 10.200.1.0/24
```

Se a subnet real é maior que /24 (ex.: cliente usa /16), três opções:

| Tamanho real | Estratégia |
|---|---|
| /24 ou menor | Mapeamento 1:1 simples |
| /16 a /20 | Subdividir em múltiplos /24 virtuais (ex.: cliente Banco com /16 → recebe `10.200.50.0/24` para sub-rede de SAP, `10.200.51.0/24` para sub-rede de RH) — admin define no onboarding |
| /8 (raríssimo) | Forçar admin a sumarizar; provavelmente o cliente não precisa de tudo |

#### Tabela NAT em runtime (no SQLite)

```sql
CREATE TABLE nat_mappings (
  id              INTEGER PRIMARY KEY,
  client_id       TEXT NOT NULL REFERENCES clients(id),
  virtual_cidr    TEXT NOT NULL,    -- ex.: "10.200.1.0/24"
  real_cidr       TEXT NOT NULL,    -- ex.: "192.168.1.0/24"
  description     TEXT,             -- ex.: "Sub-rede SAP do cliente"
  created_at      DATETIME NOT NULL
);
```

O `vagg-core` recompila as regras iptables sempre que `nat_mappings` muda. Implementação atômica via `iptables-restore` (não regra-por-regra).

### 4.3 Roteamento

#### No OpenVPN server da consultoria

Adicionar à config do servidor OpenVPN:

```
push "route 10.200.0.0 255.255.0.0"    # Todo o range virtual via aggregator
push "dhcp-option DNS 10.200.0.53"     # Aggregator DNS (IP fixo dentro do mgmt net)
push "dhcp-option DOMAIN-SEARCH vpn.consultoria.com.br"
```

E rota estática no servidor OpenVPN (ou no firewall da consultoria) apontando `10.200.0.0/16` para o IP do aggregator na subnet corporativa.

#### Na VM aggregator

```bash
# IP forwarding habilitado
sysctl -w net.ipv4.ip_forward=1

# Policy routing: cada cliente tem sua tabela
echo "100 vagg-petroleo" >> /etc/iproute2/rt_tables
echo "101 vagg-varejo"   >> /etc/iproute2/rt_tables
…

# Default route por tabela aponta para a interface do túnel daquele cliente
ip route add default dev tun-petroleo table vagg-petroleo

# Regras de policy: pacote marcado por iptables vai pra tabela correta
ip rule add fwmark 0x1 table vagg-petroleo
ip rule add fwmark 0x2 table vagg-varejo
…

# Marca pacotes com base no destino virtual
iptables -t mangle -A PREROUTING -d 10.200.1.0/24 -j MARK --set-mark 0x1
iptables -t mangle -A PREROUTING -d 10.200.2.0/24 -j MARK --set-mark 0x2
…
```

#### No notebook do consultor

Nada. O consultor instala só o cliente OpenVPN da consultoria como sempre. Tudo é transparente.

### 4.4 DNS split-horizon

#### Esquema de naming (CRÍTICO — substitui o `.local`)

> **Regra:** Nunca usar `.local`. Conflita com mDNS (RFC 6762) e causa atrasos no macOS.

Padrão recomendado: subdomínio próprio da consultoria.

```
{host}.{client-slug}-{env}.vpn.{consultoria}.com.br

Exemplos:
prd-sap-01.petroleo-prd.vpn.consultoria.com.br
qas-sap-01.petroleo-qas.vpn.consultoria.com.br
prd-sap-01.varejo-prd.vpn.consultoria.com.br
prd-erp-01.industria-prd.vpn.consultoria.com.br
```

Vantagens:
- Funciona em todos os SOs sem hack
- Permite emitir certificados Let's Encrypt via wildcard DNS-01 challenge → HTTPS interno funcionando
- Não conflita com nada na internet (a consultoria controla `vpn.consultoria.com.br`)
- Permite sub-zonas por ambiente

Alternativa (menos boa, mas aceitável se não tem domínio): `.internal`. Não usa mDNS, mas alguns SOs têm comportamento estranho. Evitar se possível.

#### Configuração CoreDNS

Cada cliente vira uma zona. CoreDNS faz forward para o DNS do cliente através do túnel:

```
# /etc/coredns/Corefile (gerado pelo vagg-core)

. {
    forward . 8.8.8.8 8.8.4.4
    cache 30
}

petroleo-prd.vpn.consultoria.com.br:53 {
    forward . 192.168.1.10:53 {
        force_tcp
        prefer_udp
    }
    rewrite stop {
        # Reescreve respostas: real (192.168.x.x) → virtual (10.200.1.x)
        answer name regex (.*) {1}
        answer value regex 192\.168\.1\.(\d+) 10.200.1.{1}
    }
    cache 30
    log
}

varejo-prd.vpn.consultoria.com.br:53 {
    forward . 192.168.1.10:53 {
        force_tcp
        bind tun-varejo  # interface do túnel do varejo
    }
    rewrite stop {
        answer value regex 192\.168\.1\.(\d+) 10.200.2.{1}
    }
    cache 30
    log
}
```

> Detalhe importante: o `bind` força a query a sair pela interface do túnel correto, mesmo que dois clientes usem o mesmo IP de DNS.

#### Cache DNS no notebook

Notebooks fazem cache. O TTL de 30s acima minimiza problemas, mas se o cliente reconfigurar IPs, ainda há janela de inconsistência. Aceitar essa janela como custo do produto e documentar para o consultor.

### 4.5 Firewall corporativo — pontos de atenção

Esta é a seção que IT da consultoria precisa fechar antes da instalação.

#### 4.5.1 Inbound para a VM aggregator

| Origem | Porta | Protocolo | Por quê |
|---|---|---|---|
| Subnet OpenVPN (10.8.0.0/24) | 53 | UDP/TCP | DNS dos consultores |
| Subnet OpenVPN | 8443 | TCP | Painel admin (apenas admins) |
| Rede de management interna | 22 | TCP | SSH do time de IT |
| Rede de management | 9090 | TCP | Métricas Prometheus (opcional) |

Tudo o resto bloqueado. Especialmente: **nada da internet pública chega na VM aggregator**.

#### 4.5.2 Outbound da VM aggregator (CRÍTICO)

Esta é a parte que mais quebra em ambientes corporativos restritivos. Lista exaustiva:

| Destino | Porta | Protocolo | Necessidade |
|---|---|---|---|
| Servidores VPN dos clientes | varia | varia | Estabelecer túneis (lista completa por cliente, ver tabela 4.5.3) |
| api.stripe.com | 443 | TCP | (Apenas license server, não aggregator) |
| `licensing.vagg.io` (license server público) | 443 | TCP | Validação diária da licença |
| pool.ntp.org | 123 | UDP | NTP — JWT validation depende de clock correto |
| Distros Ubuntu (archive.ubuntu.com, security.ubuntu.com) | 80, 443 | TCP | Atualizações |
| ghcr.io, docker.io, registry-1.docker.io | 443 | TCP | Pull de imagens Docker |
| DNS público (8.8.8.8, 1.1.1.1) | 53 | UDP | Resolver hostnames externos |

Se o ambiente tem proxy mandatório, todo o tráfego acima precisa passar pelo proxy com NO_PROXY para os IPs dos servidores VPN dos clientes.

#### 4.5.3 Portas dos servidores VPN dos clientes

Cada protocolo tem suas portas. IT precisa garantir saída para cada um:

| Protocolo | Portas padrão | Notas |
|---|---|---|
| OpenVPN | UDP 1194 (ou customizada) | Verificar no .ovpn fornecido pelo cliente |
| Cisco AnyConnect | TCP 443 | Pode usar TCP/UDP em portas custom |
| GlobalProtect | TCP 443, UDP 4501 | UDP melhora performance |
| FortiClient SSL VPN | TCP 443, TCP 10443 | Verificar com o cliente |
| IPsec (strongSwan) | UDP 500 (IKE), UDP 4500 (NAT-T), ESP (proto 50) | ESP raw protocol pode ser bloqueado |
| WireGuard | UDP 51820 (ou customizada) | Mais leve |

**Pegadinha comum:** firewall da consultoria bloqueando UDP por padrão. WireGuard e OpenVPN sobre UDP simplesmente não conectam. Precisa whitelistar.

#### 4.5.4 TLS Inspection (MITM proxy)

Algumas consultorias usam Zscaler, Forcepoint, Palo Alto Decryption. Se sim:

- **License server validation:** Funciona se a CA do proxy estiver no truststore da VM. Precisa adicionar antes de instalar.
- **Pull de imagens Docker:** Idem.
- **Túneis VPN dos clientes:** **NÃO** podem ser inspecionados. TLS Inspection quebra todos os SSL VPNs (AnyConnect, GP, Forti). IT precisa criar exceção para os IPs dos servidores VPN dos clientes.

Documentar essa exceção como requisito obrigatório no checklist de instalação.

#### 4.5.5 Conntrack e tamanho de tabela

Aggregator vai ter centenas a milhares de conexões simultâneas. Conntrack table padrão (262144) é suficiente, mas vale aumentar:

```bash
# /etc/sysctl.d/99-vagg.conf
net.netfilter.nf_conntrack_max = 524288
net.netfilter.nf_conntrack_tcp_timeout_established = 7200
net.ipv4.ip_forward = 1
```

#### 4.5.6 MTU

Túneis sobrepostos causam fragmentação. Configurar MTU 1380 nos túneis VPN (margem para overhead duplo). Validar com `ping -M do -s 1352 host.cliente.vpn.consultoria.com.br`.

### 4.6 IP space planning

Subnets reservadas pelo produto:

| CIDR | Uso | Imutável? |
|---|---|---|
| 10.200.0.0/16 | Espaço virtual de clientes | Sim — não usar para outras coisas |
| 172.20.0.0/24 | Docker mgmt network | Configurável via env |
| 172.30.0.0/24 | Docker tenants network | Configurável via env |
| 169.254.0.0/16 | Link-local (não usado) | n/a |

A consultoria precisa garantir que `10.200.0.0/16` está livre na rede dela. Se já usa parte desse range, configurar variável `VAGG_VIRTUAL_RANGE` para outro `/16` no instalador.

---

## 5. Componentes detalhados

### 5.1 vagg-core

#### Responsabilidade

Cérebro do sistema. API REST que:
- CRUD de clientes, consultores, políticas RBAC, mapeamentos NAT
- Orquestra ciclo de vida dos containers de túnel (start/stop/health)
- Gera e aplica regras iptables via `iptables-restore` atômico
- Gera config do CoreDNS e dispara reload
- Recebe e armazena audit events
- Conversa com license server diariamente
- Expõe métricas Prometheus

#### Estrutura interna

```
vagg-core/
├── pyproject.toml
├── src/vagg_core/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app
│   ├── config.py                  # Settings via pydantic-settings
│   ├── db/
│   │   ├── models.py              # SQLAlchemy models
│   │   ├── migrations/            # alembic
│   │   └── session.py
│   ├── api/
│   │   ├── v1/
│   │   │   ├── clients.py
│   │   │   ├── consultants.py
│   │   │   ├── tunnels.py
│   │   │   ├── policies.py
│   │   │   ├── audit.py
│   │   │   └── system.py          # /health, /version
│   │   └── deps.py                # auth, db session, etc
│   ├── services/
│   │   ├── tunnel_orchestrator.py # docker SDK
│   │   ├── nat_manager.py         # iptables generation
│   │   ├── dns_manager.py         # CoreDNS config gen
│   │   ├── rbac.py                # policy evaluation
│   │   ├── audit.py               # event sink
│   │   ├── license_client.py      # phone home
│   │   └── radius_client.py       # consulta OpenVPN auth
│   ├── workers/
│   │   ├── license_check.py       # daily cron
│   │   ├── tunnel_health.py       # checa túneis a cada 30s
│   │   └── audit_shipper.py       # vector handoff
│   └── core/
│       ├── security.py            # JWT, password hashing
│       └── errors.py              # exceções custom
└── tests/
    ├── unit/
    └── integration/
```

#### Endpoints principais (resumo)

```
POST   /api/v1/auth/login                   # admin login
POST   /api/v1/auth/refresh

GET    /api/v1/clients                      # lista clientes
POST   /api/v1/clients                      # cria cliente (cria container)
GET    /api/v1/clients/{id}
PATCH  /api/v1/clients/{id}
DELETE /api/v1/clients/{id}                 # destrói container, remove regras
POST   /api/v1/clients/{id}/connect         # sobe o túnel
POST   /api/v1/clients/{id}/disconnect
POST   /api/v1/clients/{id}/otp             # passa OTP pro container
GET    /api/v1/clients/{id}/status          # status real-time
GET    /api/v1/clients/{id}/logs            # tail dos logs

GET    /api/v1/consultants                  # lista consultores
POST   /api/v1/consultants                  # cria
PATCH  /api/v1/consultants/{id}             # mexe em RBAC
DELETE /api/v1/consultants/{id}

GET    /api/v1/policies                     # quem acessa o quê
POST   /api/v1/policies
DELETE /api/v1/policies/{id}

GET    /api/v1/audit                        # busca audit events
GET    /api/v1/audit/export                 # CSV/JSON

GET    /api/v1/system/health
GET    /api/v1/system/version
GET    /api/v1/system/license               # status licença
GET    /api/v1/system/metrics               # /metrics prometheus
```

#### Autenticação

- **Admin UI → core:** OAuth2 password flow + JWT (access 15min, refresh 7d)
- **Workers internos → core:** Não falam HTTP; usam DB/queue compartilhada
- **Consultor → core:** Não falam direto. Identidade vem da OpenVPN via RADIUS lookup.

### 5.2 vagg-tunnel-{client}

Container Docker, um por cliente. Imagem específica por protocolo:

```
vagg/tunnel-openvpn:latest      → roda openvpn
vagg/tunnel-openconnect:latest  → roda openconnect (Cisco/GP)
vagg/tunnel-openfortivpn:latest → roda openfortivpn
vagg/tunnel-wireguard:latest    → roda wg-quick
vagg/tunnel-strongswan:latest   → roda swanctl
```

#### Padrão comum

Cada imagem tem o mesmo contrato:

```
ENV VARS de input:
  TUNNEL_CONFIG_PATH=/config/tunnel.conf  # config específica do protocolo
  TUNNEL_USERNAME=...                     # se aplicável
  TUNNEL_PASSWORD_FILE=/run/secrets/pwd
  TUNNEL_OTP_PIPE=/run/otp.pipe           # named pipe pra OTP

CAPABILITIES:
  cap_add: [NET_ADMIN]
  devices: [/dev/net/tun]
  security_opt: [no-new-privileges:true]

NETWORKS:
  vagg-net-tenants (com IP fixo)

INTERFACE EXPOSTA:
  /var/run/vagg/tunnel-{client}.sock      # unix socket de controle
                                           # comandos: status, restart, otp <code>

LOGS:
  stdout em JSON
```

O `vagg-core` se comunica com cada container via unix socket montado na rede de mgmt. Isso permite:
- Passar OTP em runtime
- Pedir status detalhado
- Forçar restart
- Sem expor portas TCP

### 5.3 vagg-dns

CoreDNS rodando em container. Config gerada por `vagg-core` no path montado `/etc/coredns/Corefile`. Reload via signal `SIGUSR1`.

```yaml
# docker-compose.yml fragment
vagg-dns:
  image: coredns/coredns:1.11.1
  command: ["-conf", "/etc/coredns/Corefile"]
  volumes:
    - ./dns-config:/etc/coredns:ro
  networks:
    vagg-net-mgmt:
      ipv4_address: 172.20.0.53
  restart: unless-stopped
```

### 5.4 vagg-ui

React + Vite SPA, servida por nginx em container. Comunica com `vagg-core` via REST.

#### Telas principais

| Tela | Rota | Função |
|---|---|---|
| Dashboard | / | Status geral, # consultores ativos, clientes online |
| Clientes | /clients | Lista, CRUD, status |
| Cliente detalhe | /clients/:id | Config, NAT mappings, logs em tempo real |
| Consultores | /consultants | Lista, RBAC |
| Policies | /policies | Matriz consultor × cliente |
| Audit | /audit | Filtro, busca, export |
| Sistema | /system | Status, licença, versão, backup/restore |

Tema dark/light. Internacionalização pt-BR + en.

### 5.5 vagg-license-server

Hospedado em cloud (Cloud Run / Render / Fly.io). NÃO faz parte do install do cliente.

```
vagg-license-server/
├── pyproject.toml
├── src/vagg_license/
│   ├── main.py
│   ├── api/
│   │   ├── activate.py            # primeira ativação com chave
│   │   ├── refresh.py             # refresh diário
│   │   └── webhook_stripe.py      # eventos Stripe
│   ├── services/
│   │   ├── stripe_client.py
│   │   ├── jwt_signer.py          # Ed25519
│   │   └── license_store.py
│   └── db/
│       └── models.py              # licenses, customers
└── tests/
```

Endpoints:

```
POST /api/v1/activate    body: {license_key, instance_id, fingerprint}
                         resp: {jwt, expires_at, plan}

POST /api/v1/refresh     body: {license_key, instance_id, fingerprint}
                         resp: {jwt, expires_at}

POST /webhooks/stripe    Stripe webhook (assinado)
                         atualiza estado das licenças
```

Detalhes na Seção 6.

### 5.6 vagg-portal — Portal de Transparência para Cliente Final

Este componente implementa o diferencial irresistível descrito na Seção 1.7. Disponível nos planos Professional e Enterprise.

#### Arquitetura

```
┌──────────────────────────────────────────────────────────┐
│  vagg-portal (componente novo)                           │
│  - SPA React separada do vagg-ui (admin)                 │
│  - Backend FastAPI separado (vagg-portal-api)            │
│  - Hospedado em subdomínio dedicado                      │
│    ex: transparency.consultoria.com.br                   │
│  - HTTPS público (Let's Encrypt HTTP-01 ou DNS-01)       │
│  - Auth: magic link via email + opcional MFA             │
│  - DB: read-only views do SQLite do vagg-core            │
└──────────────────────────────────────────────────────────┘
```

Decisão de design: **portal vive em subdomínio dedicado e expõe apenas read-only**. Justificativa:
- Isolamento de segurança — invasão do portal não compromete o admin
- Permite que cliente final acesse via internet pública (não precisa estar na VPN da consultoria)
- Read-only por construção evita risco de ação destrutiva

#### Modelo de identidade

| Entidade | Como autentica | O que vê |
|---|---|---|
| Auditor do cliente final | Email + magic link + opcional TOTP | Dados do SEU cliente apenas |
| Convidado externo (auditor 3º) | Token de uso único com expiração curta | View específica + watermark |

**Importante:** o cliente final NÃO tem usuários no `consultants` table. Eles são "external_viewers" numa tabela separada. Zero overlap com o sistema RBAC interno.

#### Schema

```sql
CREATE TABLE external_viewers (
  id              INTEGER PRIMARY KEY,
  client_id       TEXT NOT NULL REFERENCES clients(id),
  email           TEXT NOT NULL,
  display_name    TEXT NOT NULL,
  role            TEXT NOT NULL CHECK(role IN ('auditor', 'manager', 'compliance')),
  totp_enabled    BOOLEAN NOT NULL DEFAULT 0,
  totp_secret     TEXT,
  invited_by      INTEGER NOT NULL REFERENCES consultants(id),
  invited_at      DATETIME NOT NULL,
  last_login_at   DATETIME,
  active          BOOLEAN NOT NULL DEFAULT 1,
  UNIQUE(client_id, email)
);

CREATE TABLE external_viewer_sessions (
  id              INTEGER PRIMARY KEY,
  viewer_id       INTEGER NOT NULL REFERENCES external_viewers(id),
  jwt_id          TEXT NOT NULL UNIQUE,
  ip_address      TEXT NOT NULL,
  user_agent      TEXT,
  created_at      DATETIME NOT NULL,
  expires_at      DATETIME NOT NULL,
  revoked_at      DATETIME
);

CREATE TABLE portal_access_log (
  id              INTEGER PRIMARY KEY,
  viewer_id       INTEGER NOT NULL,
  client_id       TEXT NOT NULL,
  endpoint        TEXT NOT NULL,
  ip_address      TEXT NOT NULL,
  occurred_at     DATETIME NOT NULL
);
```

#### Endpoints (vagg-portal-api)

```
POST   /portal/auth/request_magic_link    body: {email}
GET    /portal/auth/consume                ?token=...
POST   /portal/auth/totp                   body: {totp_code}
POST   /portal/auth/refresh

GET    /portal/dashboard                   summary: # consultants, # accesses last 30d, etc
GET    /portal/consultants                 lista de quem tem acesso ao SEU cliente
GET    /portal/consultants/{id}            detalhe (sem dados pessoais sensíveis)
GET    /portal/timeline                    audit cronológico (paginated)
GET    /portal/policies                    quem acessa o quê
GET    /portal/revocations                 histórico de offboarding
POST   /portal/reports/lgpd                gera PDF assinado (rate-limited 1/dia)
POST   /portal/reports/quarterly           idem trimestral
```

#### Telas

| Tela | Conteúdo |
|---|---|
| `/dashboard` | Cards: # consultores ativos, # acessos no mês, # policies expiradas, último incidente |
| `/consultants` | Tabela: nome, função (mas NÃO email/telefone), data de adição, última conexão |
| `/timeline` | Eventos cronológicos com filtro por consultor/data; cada evento mostra: timestamp, consultor, host destino virtual, protocolo. NÃO mostra payload nem IPs reais (preserva segurança da consultoria) |
| `/policies` | Quem tem acesso a quê, com qual escopo, válido até quando |
| `/revocations` | Audit de offboarding: quem perdeu acesso, quando, motivo |
| `/reports` | Geração de PDF com hash de integridade (verificável independentemente) |

#### Restrições de exposição

Cliente final **NÃO** vê:
- Email, telefone, ou outros dados pessoais sensíveis dos consultores
- IPs reais da rede da consultoria
- Outros clientes da consultoria (multi-tenant isolation por construção)
- Configurações técnicas internas
- Logs de admin (mudanças de policy aparecem no timeline mas sem nome do admin)

#### Onboarding do cliente final

Fluxo, do ponto de vista do admin da consultoria:

```
1. UI Admin → Cliente Petrobras → aba "Transparência"
2. "Adicionar auditor": email + nome + role
3. Sistema envia email com magic link
4. Auditor clica, define TOTP (recomendado), entra
5. Vê dashboard limpo, pré-filtrado para cliente Petrobras
```

Tempo total: 2 minutos.

#### PDF de relatório — formato

Estrutura padrão:

```
[Logo da consultoria]    [Logo VPN Aggregator]
Relatório de Acesso à Rede — Cliente: Petrobras
Período: 01/04/2026 a 30/04/2026
Gerado em: 30/04/2026 14:32 UTC
Hash de integridade: sha256:abc123...

Sumário Executivo
- 14 consultores com acesso ativo
- 1.247 conexões registradas
- 0 acessos negados (default-deny funcionando)
- 2 offboardings no período

Consultores Ativos
[tabela]

Top 10 Hosts Mais Acessados
[tabela]

Eventos Notáveis
[lista de eventos importantes]

Policies em Vigor
[tabela]

Verificação de Integridade
Este relatório foi gerado a partir de audit log com hash chain integrity-protected.
Para verificar: vagg-cli verify-report <arquivo.pdf>

Assinatura digital: [Ed25519 signature]
```

PDF é assinado com Ed25519 (mesma key infrastructure da licença). Cliente final pode verificar autenticidade com a chave pública.

#### Considerações de segurança específicas

| Risco | Mitigação |
|---|---|
| Cliente final vaza credenciais | Magic link tem TTL curto; recomenda TOTP; auditoria de login |
| Cliente final tira screenshot e divulga publicamente | Watermark com email do viewer em cada página |
| Cliente final tenta acessar dados de outro cliente | Constraint no DB e middleware de isolamento — impossível por design |
| Phishing fingindo ser portal | Domínio dedicado com EV cert; cliente final é instruído a salvar URL |
| DDoS no portal | Cloudflare na frente (recomendação operacional, não no produto) |

### 5.7 vagg-installer

Script bash único, idempotente, com **dois modos** de instalação:

#### Modo `byo` (Bring Your Own hardware)

Para clientes que vão instalar em VM própria (Proxmox, VMware, Hyper-V, cloud).

```bash
curl -fsSL https://install.vagg.io/install.sh | sudo bash -s -- \
  --mode=byo \
  --license-key=VAGG-XXXX-XXXX-XXXX \
  --domain=vpn.consultoria.com.br
```

Comportamento: assume Ubuntu 24.04 limpo, instala dependências, configura tudo, ativa licença, sobe stack. Detalhes na Seção 9.

#### Modo `appliance`

Para appliances pré-configurados (Tier "Appliance" do plano de venda). A imagem é gerada por nós em build time e gravada no disco antes de enviar o hardware. Cliente recebe a caixa, conecta cabos, e completa configuração via wizard web.

Build pipeline (executa no nosso CI):

```bash
# Gera imagem .img bootável
sudo bash build-appliance-image.sh \
  --base=ubuntu-24.04-server-minimal \
  --target-disk=128G \
  --hostname-template=vagg-{serial}

# Saída: vagg-appliance-{version}-{date}.img.zst
```

A imagem inclui:
- Ubuntu 24.04 LTS minimal pré-configurado
- Docker e dependências instaladas
- Imagens dos containers já carregadas (vagg-core, vagg-ui, vagg-dns, todos os tunnel-*)
- systemd units habilitados
- `cloud-init` configurado para first-boot wizard
- SSH key padrão de fábrica (forçada a trocar no primeiro login)
- Hostname temporário, regenerado no first-boot

First-boot do cliente (na caixa física):

```
1. Conecta cabo de rede e cabo de energia
2. Aguarda 2-3 minutos (boot + DHCP + auto-discovery)
3. Acessa http://vagg-setup.local OU o IP atribuído por DHCP
4. Wizard solicita:
   - License key
   - Domínio do produto (ex: vpn.consultoria.com.br)
   - Email do admin inicial
   - Configuração de rede (DHCP ou IP estático)
   - Timezone
5. Wizard valida licença, configura tudo, gera senha do admin
6. Reboot
7. Pronto. Tempo total: 5-10 minutos
```

#### Modo `dev` (apenas desenvolvimento interno)

```bash
sudo bash install.sh --mode=dev --skip-license
```

Pula validação de licença, usa license key de desenvolvimento, monta volumes do código local. Para Claude Code rodar testes na máquina de desenvolvimento sem precisar de license server real.

---

## 6. Licenciamento via Stripe

### 6.1 Modelo de billing

| Plano | Preço (BRL/mês) | Limites |
|---|---|---|
| Starter | R$ 1.499 | 5 clientes, 15 consultores, audit básico |
| Professional | R$ 3.999 | 20 clientes, 60 consultores, audit + export |
| Enterprise | R$ 8.999 | Ilimitado, SSO, audit estruturado, SLA |

Cobrança mensal recorrente via Stripe Subscriptions. BRL nativo (Stripe suporta).

Add-ons opcionais:
- Cliente VPN extra (acima do plano): R$ 199/cliente/mês
- Implementação assistida one-time: R$ 12.000

### 6.2 Fluxo de ativação inicial

```
1. Customer compra via /pricing → Stripe Checkout
2. Stripe webhook customer.subscription.created → license-server
3. License-server gera license_key (UUIDv7) + envia email com chave + link doc
4. IT da consultoria roda installer com --license-key=XXX
5. Installer chama POST /api/v1/activate
   body: {license_key, instance_id (gerado), fingerprint (CPU+MAC hash)}
6. License-server valida com Stripe, retorna JWT (Ed25519 signed)
   payload: {sub, plan, limits, exp, iat, license_key, instance_id, fingerprint_hash}
   exp: now + 7 dias
7. Aggregator armazena JWT em /var/lib/vagg/license.jwt
8. Aggregator valida JWT em cada operação relevante (assinatura local, sem chamar servidor)
```

### 6.3 Fluxo de refresh diário

```
1. Cron interno do vagg-core dispara às 03:00 (timezone do servidor)
2. POST /api/v1/refresh com license_key + instance_id + fingerprint atual
3. License-server consulta cache (Postgres) do estado da assinatura Stripe
4. Se assinatura ATIVA: retorna novo JWT (exp = now + 7d)
5. Se PAST_DUE (atraso de pagamento): retorna JWT com flag warning=true (continua funcionando)
6. Se CANCELED: retorna 402 Payment Required
7. Aggregator persiste novo JWT
```

### 6.4 Grace period e degraded mode

```
JWT válido (não expirou):
  → operação normal

JWT expirou + última refresh < 7 dias atrás + falha de rede:
  → modo normal (assume rede temporária)

JWT expirou + última refresh entre 7 e 14 dias atrás:
  → DEGRADED MODE
    - Banner vermelho na UI: "Licença não validada há X dias. Verifique conectividade ou pagamento."
    - APIs read-only funcionam
    - APIs write (criar cliente, mudar policy) bloqueadas
    - Túneis existentes continuam funcionando

JWT expirou há > 14 dias OU resposta CANCELED do server:
  → DISABLED MODE
    - Banner: "Licença expirada. Sistema desabilitado."
    - Túneis derrubados
    - APIs retornam 402
    - SSH ainda funciona (admin precisa de jeito de recuperar)
```

Razões para grace period generoso: ambiente corporativo brasileiro tem instabilidade de internet, pagamentos atrasam, IT às vezes troca proxy. 14 dias dá tempo de resolver sem trauma.

### 6.5 Schema do JWT

```json
{
  "iss": "vagg-license-server",
  "sub": "license-key-uuid",
  "iat": 1714512000,
  "exp": 1715116800,
  "lv": 1,
  "plan": "professional",
  "limits": {
    "max_clients": 20,
    "max_consultants": 60,
    "audit_export": true,
    "sso": false
  },
  "license_key": "VAGG-XXXX-XXXX-XXXX",
  "instance_id": "instance-uuid",
  "fingerprint_hash": "sha256...",
  "warning": null
}
```

Assinatura Ed25519. Public key embedada no binário do aggregator (constante em `vagg_core.security.LICENSE_PUBLIC_KEY`).

### 6.6 Anti-tampering

Princípio: tornar o bypass mais caro que pagar a licença.

| Técnica | Implementação |
|---|---|
| Chave pública embedada | Hardcoded em código compilado, não em arquivo |
| Validação inline | License check é parte do path crítico (não função isolada que daria pra patchar) |
| Fingerprint vinculado | Mover instalação pra outro hardware exige re-ativação manual |
| Múltiplos checks | UI, core, e workers cada um valida independentemente |
| Telemetria de violação | Tentativa de uso com JWT inválido reporta para license-server (se rede) |

Não vai impedir um atacante motivado, mas eleva muito o custo. O mercado-alvo (consultoria SAP) não tem incentivo para piratear porque a economia de produtividade já justifica o preço.

### 6.7 Eventos Stripe tratados

```
customer.subscription.created          → cria license_key
customer.subscription.updated          → atualiza plan, limits
customer.subscription.deleted          → marca CANCELED
customer.subscription.paused           → marca PAUSED (degraded mode)
invoice.payment_failed                 → flag warning, mas mantém ativo
invoice.payment_succeeded              → confirma renew
```

### 6.8 Tabela license_server.licenses

```sql
CREATE TABLE licenses (
  id                    UUID PRIMARY KEY,
  license_key           TEXT UNIQUE NOT NULL,        -- "VAGG-XXXX-XXXX-XXXX"
  stripe_customer_id    TEXT NOT NULL,
  stripe_subscription_id TEXT NOT NULL,
  plan                  TEXT NOT NULL,
  status                TEXT NOT NULL,               -- active, past_due, canceled, paused
  email                 TEXT NOT NULL,
  company_name          TEXT NOT NULL,
  cnpj                  TEXT,
  instance_id           TEXT,
  fingerprint_hash      TEXT,
  activated_at          TIMESTAMPTZ,
  last_refresh_at       TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL,
  updated_at            TIMESTAMPTZ NOT NULL
);

CREATE TABLE license_events (
  id                    UUID PRIMARY KEY,
  license_id            UUID REFERENCES licenses(id),
  event_type            TEXT NOT NULL,
  payload               JSONB,
  occurred_at           TIMESTAMPTZ NOT NULL
);
```

---

## 7. RBAC e Multi-tenancy

### 7.1 Modelo

```
Consultant ─┬─ has many ─→ Policy ─→ has one ─→ Client
            │
            └─ has one role: viewer | operator | admin
```

`Policy` é granular:

```sql
CREATE TABLE policies (
  id              INTEGER PRIMARY KEY,
  consultant_id   INTEGER NOT NULL REFERENCES consultants(id),
  client_id       TEXT NOT NULL REFERENCES clients(id),
  scope           TEXT NOT NULL,    -- 'full', 'subnet:10.200.1.0/26', 'host:10.200.1.50'
  expires_at      DATETIME,         -- opcional, para acesso temporário
  created_by      INTEGER REFERENCES consultants(id),
  created_at      DATETIME NOT NULL
);
```

### 7.2 Como a identidade chega ao Aggregator

Não dá pra confiar só em IP de origem (consultor pode ter IP rotativo no pool OpenVPN). Opções, em ordem de robustez:

#### Opção A — RADIUS lookup (recomendado)

OpenVPN autentica via RADIUS. Aggregator também consulta RADIUS para mapear IP-do-pool → username:

```
1. Pacote chega de 10.8.0.42
2. Aggregator consulta cache local: 10.8.0.42 → quem é?
3. Se cache miss: consulta RADIUS Accounting (que sabe quem está conectado)
4. Cache result por 60s
5. Aplica política do username
```

#### Opção B — Static mapping

Cada consultor tem IP fixo no pool OpenVPN (configurado via client-config-dir do OpenVPN). Aggregator tem mapping estático:

```
10.8.0.10 → joao.silva
10.8.0.11 → maria.santos
…
```

Mais simples mas menos flexível.

#### Opção C — Certificate-based + script de auth

OpenVPN com `--auth-user-pass-verify` chama script que escreve `/var/run/vagg/sessions/{ip} = {username}`. Aggregator lê.

**Default da implementação:** Opção B, com Opção A como upgrade configurável. Maioria das consultorias começa com mapping estático.

### 7.3 Default-deny

Sem policy explícita, consultor não acessa nada. Pacote sem match em policy é dropado e gera audit event.

```python
def evaluate_packet(src_ip: IPv4Address, dst_ip: IPv4Address) -> Decision:
    user = resolve_user(src_ip)
    if not user:
        return Decision.DROP("no_user_for_source_ip")

    target_client = resolve_client(dst_ip)  # via virtual range lookup
    if not target_client:
        return Decision.DROP("no_client_for_destination")

    policy = find_policy(user.id, target_client.id)
    if not policy:
        return Decision.DROP("no_policy")

    if policy.expires_at and policy.expires_at < now():
        return Decision.DROP("policy_expired")

    if not scope_matches(policy.scope, dst_ip):
        return Decision.DROP("scope_mismatch")

    return Decision.ALLOW
```

Implementação real é via iptables (não Python por pacote), mas a lógica acima descreve o modelo.

---

## 8. Auditoria e Compliance

### 8.1 Eventos rastreados

| Evento | Quando | Campos críticos |
|---|---|---|
| `consultant.connect` | Consultor conecta no OpenVPN | username, src_ip, openvpn_session_id |
| `consultant.disconnect` | Consultor desconecta | username, duração |
| `tunnel.access` | Pacote atravessa para um cliente | username, client_id, dst_virtual, dst_real, protocol, port |
| `tunnel.denied` | Política bloqueou | username, client_id, motivo |
| `policy.created/updated/deleted` | Admin muda RBAC | admin_user, target_consultant, target_client, scope |
| `client.added/removed` | Admin onboard/offboard cliente | admin_user, client_id |
| `tunnel.up/down` | Túnel sobe/cai | client_id, motivo |
| `auth.login` / `auth.failed` | Login admin | username, success |
| `license.refreshed` / `license.warning` | Licença | status |

### 8.2 Storage e retenção

| Camada | Onde | Retenção |
|---|---|---|
| Quente | SQLite na VM | 30 dias |
| Frio | Arquivo NDJSON, comprimido (zstd) | 1 ano |
| Export externo | Loki/Splunk/ELK via Vector | Conforme cliente |

Audit log é **append-only** no DB (sem UPDATE, sem DELETE).

### 8.3 Resistência a tampering

- Hash em cadeia: cada evento tem `prev_hash` que referencia o anterior. Quebrar a cadeia exige recalcular tudo.
- Cópia diária shipped externa (S3 com object-lock, ou Loki com retention policy).
- Admin não tem permissão de delete em audit logs (apenas export e archive).

### 8.4 Export

- Formato: JSON Lines, CSV
- Filtros: período, cliente, consultor, evento
- Disponível via UI e API
- Para auditoria do cliente final: relatório PDF assinado contendo apenas eventos relacionados àquele cliente

---

## 9. Instalação (guia para IT da consultoria)

### 9.1 Pré-requisitos da infraestrutura

#### Hardware/VM mínimo

| Recurso | Mínimo | Recomendado |
|---|---|---|
| vCPU | 2 | 4 |
| RAM | 4 GB | 8 GB |
| Disco | 30 GB SSD | 100 GB SSD |
| Rede | 100 Mbps | 1 Gbps |

#### Software

- Ubuntu Server 24.04 LTS (clean install)
- Acesso SSH como root ou sudoer
- IPv4 estático na rede corporativa
- Sincronização de tempo via NTP funcional

#### Network

| Item | Status esperado |
|---|---|
| OpenVPN corporativa funcional | ✓ |
| Subnet do pool OpenVPN documentada | ✓ |
| Acesso outbound conforme Seção 4.5.2 | ✓ |
| Range `10.200.0.0/16` livre na rede | ✓ |
| Domínio `vpn.{consultoria}.com.br` controlado e DNS gerenciável | ✓ |
| Lista de servidores VPN dos clientes (IP/hostname + porta) | ✓ |

### 9.2 Checklist pré-instalação

```
[ ] VM Ubuntu 24.04 provisionada com specs acima
[ ] Acesso SSH testado
[ ] DNS reverso configurado (boa prática)
[ ] Firewall corporativo: regras outbound conforme 4.5.2 abertas
[ ] Firewall corporativo: TLS Inspection com bypass para IPs dos servidores VPN dos clientes
[ ] Subdomínio vpn.{consultoria}.com.br configurado (NS apontando para o aggregator OU registro A direto)
[ ] License key recebida por email após pagamento Stripe
[ ] Configurações de cada cliente VPN coletadas:
    [ ] Tipo (OpenVPN/AnyConnect/Forti/GP/IPsec/WG)
    [ ] Endpoint (host:porta)
    [ ] Credenciais (user/pass/cert)
    [ ] Subnet real do cliente
    [ ] DNS server interno do cliente (se houver)
    [ ] Tipo de MFA
[ ] Plano de IPs virtuais montado (qual cliente vira qual /24 dentro do 10.200.0.0/16)
[ ] Lista de consultores com email e (se Opção B) IP fixo desejado
[ ] Backup destination configurado (S3 ou volume montado)
```

### 9.3 Procedimento de instalação

#### Passo 1 — Preparar a VM

```bash
sudo apt update && sudo apt upgrade -y
sudo timedatectl set-timezone America/Sao_Paulo
sudo hostnamectl set-hostname vagg-prod
```

#### Passo 2 — Rodar o instalador

```bash
curl -fsSL https://install.vagg.io/install.sh -o /tmp/vagg-install.sh
sha256sum /tmp/vagg-install.sh
# verificar contra hash publicado em https://vagg.io/install/checksums.txt

sudo bash /tmp/vagg-install.sh \
  --license-key=VAGG-XXXX-XXXX-XXXX \
  --domain=vpn.consultoria.com.br \
  --admin-email=ti@consultoria.com.br
```

O instalador:
1. Valida pré-requisitos (kernel, distro, conectividade)
2. Instala Docker, dependências do sistema
3. Cria usuário e diretórios em `/var/lib/vagg`, `/etc/vagg`
4. Baixa imagens Docker
5. Gera certificados internos (Let's Encrypt DNS-01)
6. Inicializa SQLite com migrations
7. Ativa licença com license-server
8. Sobe stack via systemd
9. Cria usuário admin inicial e printa senha temporária
10. Roda health checks finais

Tempo total: 5-15 minutos dependendo da rede.

#### Passo 3 — Acessar o painel

```
URL: https://vpn.consultoria.com.br:8443
Usuário: admin
Senha: (printada pelo instalador, trocar no primeiro login)
```

#### Passo 4 — Configurar OpenVPN corporativa

Adicionar à config do servidor OpenVPN:

```
push "route 10.200.0.0 255.255.0.0"
push "dhcp-option DNS 10.200.0.53"
push "dhcp-option DOMAIN-SEARCH vpn.consultoria.com.br"
```

E rota estática no servidor OpenVPN apontando `10.200.0.0/16` para o IP da VM aggregator.

Reload do OpenVPN. Testar com um consultor: `ping 10.200.0.53` e `nslookup test.vpn.consultoria.com.br`.

#### Passo 5 — Adicionar primeiro cliente

Pelo painel:

1. Clientes → Adicionar
2. Preencher: nome (`Petróleo`), slug (`petroleo`), tipo de VPN (OpenVPN), upload do `.ovpn`, credenciais
3. Definir subnet virtual (sugestão automática: `10.200.1.0/24`)
4. Definir subnet real (descoberta automática do `.ovpn` ou manual)
5. Mapear NAT rules
6. Definir DNS interno do cliente
7. Salvar → container sobe → túnel conecta → audit event

#### Passo 6 — Adicionar consultores e policies

1. Consultores → Importar CSV (ou um a um)
2. Policies → criar matriz consultor × cliente

#### Passo 7 — Validar

Conectar OpenVPN com um consultor de teste:

```bash
# No notebook do consultor
ping 10.200.1.1                                         # gateway virtual do petróleo
nslookup prd-sap.petroleo-prd.vpn.consultoria.com.br    # resolve para 10.200.1.x
ssh user@prd-sap.petroleo-prd.vpn.consultoria.com.br    # conecta de fato
```

### 9.4 Troubleshooting de instalação

| Sintoma | Causa provável | Como corrigir |
|---|---|---|
| `install.sh` falha em "Validating license" | License-server inalcançável | Verificar firewall outbound 443 |
| Container `vagg-tunnel-X` em CrashLoopBackOff | Credenciais erradas | Logs: `docker logs vagg-tunnel-X` |
| Túnel sobe mas DNS não resolve | DNS do cliente não acessível pelo túnel | Validar dentro do container: `docker exec vagg-tunnel-X dig @<dns-cliente> <host>` |
| Consultor pinga 10.200.1.1 mas não pinga 10.200.1.50 | NAT rule errada ou policy bloqueando | UI → Audit → filtrar por consultor → ver razão do drop |
| MFA pede código mas túnel não sobe | OTP não chegou no container | UI → Cliente → Logs → procurar prompt |
| Painel inacessível | nginx no container UI down | `systemctl status vagg.service` |

### 9.5 Atualizações

```bash
sudo /usr/local/bin/vagg-update
```

O updater:
1. Snapshot do estado atual (DB + config)
2. Pull das novas imagens
3. Migra DB (alembic)
4. Restart do stack
5. Health check; se falhar, rollback automático

Updates são publicados em `https://updates.vagg.io/manifest.json` com signature Ed25519.

---

## 10. Operação contínua

### 10.1 Onboarding de novo cliente (rotina)

Tempo médio esperado: 15-30 min.

1. IT recebe do gestor: tipo VPN, credenciais, lista de subnets, IP do DNS interno
2. UI → Clientes → Adicionar
3. Validar conexão (botão "Test connection")
4. Mapear NAT
5. Configurar DNS forward
6. Atribuir consultores via Policies
7. Notificar consultores: "Acesso ao Cliente X liberado, host base é `<host>.x-prd.vpn.consultoria.com.br`"

### 10.2 Onboarding de consultor

1. IT cria usuário no OpenVPN como já faz hoje
2. UI do Aggregator → Consultores → Adicionar (mapear username OpenVPN → identidade no aggregator)
3. Atribuir policies para os clientes do projeto
4. Email automático para o consultor com instruções

### 10.3 Offboarding de consultor (CRÍTICO)

1. UI → Consultores → Desativar
2. Aggregator imediatamente revoga todas as policies
3. Tunnel sessions ativos do consultor são derrubados
4. Audit event registra
5. IT remove do OpenVPN

Tempo do clique até revogação completa: < 5 segundos.

### 10.4 Backup

Diário, automático:

```
/var/lib/vagg/backups/YYYY-MM-DD/
├── db.sqlite                  # snapshot do SQLite
├── config.tar.gz              # /etc/vagg/*
├── audit-archive.ndjson.zst   # audit do dia
└── manifest.json              # metadata + checksums
```

Shipping para S3 / wasabi / NAS via rclone configurado.

Retenção:
- Local: 7 dias
- Remoto: 90 dias (configurável)

### 10.5 Monitoramento

Métricas Prometheus expostas em `/metrics`:

```
vagg_tunnels_total{client="petroleo",status="up"} 1
vagg_consultants_active 12
vagg_packets_routed_total{client="petroleo"} 145789
vagg_dns_queries_total{zone="petroleo-prd"} 4521
vagg_license_valid 1
vagg_license_days_until_expiry 6
vagg_audit_events_total{event_type="tunnel.access"} 89234
```

Alertas sugeridos (Grafana / Alertmanager):
- Túnel down > 5min
- License expiry < 3 dias
- Audit shipping atrasado > 1h
- CPU > 80% por 10min

---

## 11. Plano de implementação por fases

Cada fase é uma PR (ou série coordenada). Critério de aceite é objetivo: testes passam OU validação manual com prints.

### Fase 1 — License Server (cloud)

**Por quê primeiro:** sem license server, nada do resto faz sentido testar.

**Entradas:** Seções 2, 6.

**Saídas:**
- Repo `vagg-license-server` criado
- Endpoints `/api/v1/activate`, `/api/v1/refresh`, `/webhooks/stripe`
- Postgres schema + migrations
- Stripe Test Mode integrado
- Deploy automatizado (Cloud Run ou Render)
- Public/private Ed25519 key gerada, pública commitada como constante
- Documentação no `README.md` do repo

**Critérios de aceite:**
- [ ] Subscription test no Stripe Test Mode dispara webhook que cria license_key
- [ ] `POST /activate` com license_key válida retorna JWT que valida com a public key
- [ ] `POST /refresh` retorna JWT novo
- [ ] Cancelar subscription faz próximo refresh retornar 402
- [ ] Tests de integração rodam em CI (pytest + stripe-mock)

### Fase 2 — Aggregator Core (esqueleto)

**Entradas:** Seções 2, 5.1.

**Saídas:**
- Repo `vagg-core`
- FastAPI app rodando em uvicorn
- SQLite + alembic configurados
- Todos os endpoints da Seção 5.1 stubados (retornam mock)
- OpenAPI docs em `/docs`
- Auth básica (admin login com JWT)
- pytest + ruff + mypy passando
- Dockerfile

**Critérios de aceite:**
- [ ] `POST /auth/login` autentica com admin/senha em env var
- [ ] CRUD de clients funciona (sem ainda criar containers)
- [ ] CRUD de consultants funciona
- [ ] CRUD de policies funciona
- [ ] `mypy --strict` passa
- [ ] Testes unitários cobrem >70% dos handlers

### Fase 3 — Tunnel Orchestrator + container OpenVPN

**Entradas:** Seções 5.2, 4.2 (NAT — apenas a parte que envolve containers).

**Saídas:**
- Imagem `vagg/tunnel-openvpn:latest` (Dockerfile + entrypoint)
- Service `tunnel_orchestrator.py` no core que faz docker SDK calls
- Endpoint `POST /clients/{id}/connect` agora cria container real
- Endpoint `DELETE /clients/{id}` destrói container
- Health check de túnel (a cada 30s)
- Unix socket de controle no container

**Critérios de aceite:**
- [ ] Cliente cadastrado com `.ovpn` válido sobe túnel real
- [ ] Container reinicia automaticamente se cair
- [ ] Logs do container vão para JSON estruturado e são lidos pelo core
- [ ] Test de integração: subir túnel mockado, validar que `tunX` interface aparece

### Fase 4 — NAT remapping e roteamento

**Entradas:** Seções 4.2, 4.3.

**Saídas:**
- `nat_manager.py` que gera regras `iptables-restore`
- `router.py` que aplica via shellout (com lock)
- Validação que regras estão consistentes com DB
- Service que regenera regras quando DB muda
- Testes que validam regras geradas (snapshot tests)

**Critérios de aceite:**
- [ ] Cliente com NAT mapping virtual→real recebe regras `NETMAP` corretas
- [ ] Adicionar/remover cliente rebuilda regras atomicamente (sem janela de drop)
- [ ] Pacotes do range virtual chegam no túnel certo (validar com `tcpdump -i tun-X`)
- [ ] Drop default funciona — pacote sem mapping é dropado e logged

### Fase 5 — Containers de outros protocolos VPN

**Entradas:** Seção 5.2.

**Saídas:**
- `vagg/tunnel-openconnect:latest` (Cisco AnyConnect, GlobalProtect)
- `vagg/tunnel-openfortivpn:latest` (FortiClient SSL)
- `vagg/tunnel-wireguard:latest`
- `vagg/tunnel-strongswan:latest` (IPsec)
- Cada um com mesmo contrato (env vars, socket, JSON logs)
- Suporte a OTP via socket

**Critérios de aceite:**
- [ ] Cada protocolo testado com servidor de teste real (lab)
- [ ] OTP funciona: comando via socket faz a VPN aceitar o código
- [ ] Reconexão automática em caso de queda

### Fase 6 — DNS layer

**Entradas:** Seção 4.4.

**Saídas:**
- Container `vagg-dns` (CoreDNS) configurado
- `dns_manager.py` no core gera Corefile
- Reload via SIGUSR1 quando clientes mudam
- DNS rewriting (real → virtual) funcional

**Critérios de aceite:**
- [ ] Query a `host.cliente-prd.vpn.consultoria.com.br` resolve para IP virtual
- [ ] DNS de cliente novo aparece em ≤5s após cadastro
- [ ] Forwarding correto via interface de túnel (validar com `dig +trace`)

### Fase 7 — Admin UI (React)

**Entradas:** Seção 5.4.

**Saídas:**
- Repo `vagg-ui` (React + Vite + shadcn/ui)
- Telas de Dashboard, Clients, Consultants, Policies, Audit, System
- i18n pt-BR + en
- Dark mode
- Container `vagg/ui:latest` (nginx serving build)

**Critérios de aceite:**
- [ ] Todas as ações da Seção 5.1 acessíveis via UI
- [ ] Realtime updates de status (websocket ou polling)
- [ ] Export CSV/JSON de audit
- [ ] Validação visual em mobile (read-only)

### Fase 8 — RBAC integrado com OpenVPN

**Entradas:** Seção 7.

**Saídas:**
- `rbac.py` faz lookup de identidade
- Suporte a Opção A (RADIUS) e Opção B (static mapping)
- Tabela conntrack respeitada (não dropa flow estabelecido)
- Audit event para cada decisão

**Critérios de aceite:**
- [ ] Consultor sem policy não acessa nada
- [ ] Adicionar policy libera acesso em < 5s
- [ ] Remover policy revoga sessões em < 5s
- [ ] Audit log completo

### Fase 9 — Audit pipeline

**Entradas:** Seção 8.

**Saídas:**
- Tabela `audit_events` com hash chain
- Vector configurado para shipping
- Endpoint de export
- Relatório PDF por cliente (jinja2 + weasyprint)

**Critérios de aceite:**
- [ ] Hash chain validável (script de verificação)
- [ ] Export performático com 1M eventos
- [ ] Filtros funcionam corretamente

### Fase 10 — Installer e packaging

**Entradas:** Seção 9.

**Saídas:**
- `install.sh` idempotente
- Script publicado em `https://install.vagg.io/install.sh` com checksum
- systemd units
- Documentação completa de instalação
- `vagg-update` script

**Critérios de aceite:**
- [ ] Instalação clean em VM Ubuntu 24.04 vazia funciona end-to-end
- [ ] Re-rodar instalador (idempotente) não quebra nada
- [ ] Update preserva DB e config
- [ ] Rollback funciona se update falha

### Fase 11 — Portal de Transparência (Diferencial Irresistível)

**Por quê:** É a feature que ganha contrato. Implementar antes de campanha comercial.

**Entradas:** Seção 1.7, Seção 5.6, Seção 8.

**Saídas:**
- Repo `vagg-portal` (frontend React + Vite separado de vagg-ui)
- Repo `vagg-portal-api` (FastAPI separado, read-only)
- Docker compose stack atualizado para incluir os dois novos serviços
- Subdomínio dedicado configurado via instalador (`transparency.{domain}`)
- Magic link auth + TOTP opcional
- 6 telas funcionais (dashboard, consultants, timeline, policies, revocations, reports)
- PDF report generator (jinja2 + weasyprint) com Ed25519 signature
- CLI `vagg-cli verify-report` para validar PDFs externamente
- Watermark com email do viewer
- Rate limiting nos endpoints sensíveis

**Critérios de aceite:**
- [ ] Auditor de Cliente A não consegue ver dados de Cliente B (test forçado)
- [ ] Magic link expira em 15 minutos
- [ ] TOTP funciona com Google Authenticator e Microsoft Authenticator
- [ ] PDF gerado tem assinatura verificável
- [ ] Watermark presente em todas as páginas
- [ ] Lighthouse score > 90 (acessibilidade matters em portal compliance)
- [ ] i18n funciona pt-BR + en
- [ ] Tests de integração cobrem isolamento multi-tenant

### Fase pós-MVP (opcional)

- SSO (OIDC, SAML)
- Cliente VPN próprio para o consultor (alternativa ao OpenVPN existente)
- Mobile app (iOS/Android) para gerenciar OTP
- Multi-region failover do license-server
- Integração com Vault para secrets

---

## 12. Estrutura do repositório

Monorepo recomendado para reduzir overhead de coordenação. Layout:

```
vagg/
├── README.md
├── SPEC.md                          ← este documento
├── LICENSE
├── .github/
│   └── workflows/
│       ├── core-ci.yml
│       ├── ui-ci.yml
│       ├── tunnels-ci.yml
│       └── release.yml
├── core/                            ← vagg-core
│   ├── pyproject.toml
│   ├── src/vagg_core/
│   ├── tests/
│   └── Dockerfile (não usado em prod, só dev)
├── ui/                              ← vagg-ui
│   ├── package.json
│   ├── src/
│   ├── tests/
│   └── Dockerfile
├── tunnels/                         ← imagens dos containers de VPN
│   ├── openvpn/
│   │   ├── Dockerfile
│   │   ├── entrypoint.sh
│   │   └── README.md
│   ├── openconnect/
│   ├── openfortivpn/
│   ├── wireguard/
│   ├── strongswan/
│   └── shared/
│       └── tunnel-controller.py    ← implementa o socket de controle
├── dns/                             ← config CoreDNS
│   └── templates/
├── installer/
│   ├── install.sh
│   ├── update.sh
│   ├── lib/
│   │   ├── checks.sh
│   │   ├── docker-setup.sh
│   │   └── systemd-units/
│   └── tests/
├── license-server/                  ← repo separado idealmente, mas pode ficar no monorepo
│   ├── pyproject.toml
│   ├── src/vagg_license/
│   └── tests/
├── docs/
│   ├── installation.md              ← compilado a partir da Seção 9
│   ├── operations.md
│   ├── api.md                       ← gerado do OpenAPI
│   ├── architecture.md
│   └── troubleshooting.md
├── examples/
│   ├── openvpn-server-config/       ← config exemplo do OpenVPN corporativo
│   └── client-onboarding/           ← templates de .ovpn, etc
└── scripts/
    ├── dev-bootstrap.sh             ← sobe ambiente local de dev
    └── release.sh
```

### 12.1 Convenções de Git

- Branch principal: `main` (proteção: PRs com CI verde)
- Branches de feature: `feat/short-name`
- Tags de release: `vMAJOR.MINOR.PATCH`
- Cada componente tem seu CHANGELOG ou usa Changesets

### 12.2 CI/CD

- PR → roda lint + test + build em todos os componentes afetados
- Merge para main → publica imagens com tag `:edge`
- Tag `vX.Y.Z` → publica imagens com tag versionada + `:latest` + atualiza `manifest.json` do updater

---

## 13. Anexos

### 13.1 Variáveis de ambiente do core

```
VAGG_CORE_DB_PATH=/var/lib/vagg/db.sqlite
VAGG_CORE_BIND=0.0.0.0:8443
VAGG_CORE_LOG_LEVEL=INFO
VAGG_CORE_ADMIN_EMAIL=...
VAGG_CORE_ADMIN_PASSWORD_HASH=... (argon2)
VAGG_CORE_JWT_SECRET=... (gerado no install)
VAGG_CORE_DOMAIN=vpn.consultoria.com.br
VAGG_CORE_VIRTUAL_RANGE=10.200.0.0/16
VAGG_CORE_LICENSE_KEY=VAGG-XXXX-...
VAGG_CORE_LICENSE_SERVER=https://licensing.vagg.io
VAGG_CORE_OPENVPN_AUTH_MODE=static  # or 'radius'
VAGG_CORE_RADIUS_HOST=...
VAGG_CORE_RADIUS_SECRET=...
VAGG_CORE_AUDIT_RETENTION_DAYS=365
```

### 13.2 Comandos úteis

```bash
# Estado do stack
sudo systemctl status vagg
sudo docker compose -f /etc/vagg/compose.yml ps

# Logs do core
sudo journalctl -u vagg-core -f

# Logs de um túnel
sudo docker logs -f vagg-tunnel-petroleo

# Forçar refresh de licença
sudo vagg license refresh

# Backup manual
sudo vagg backup now

# Validar audit log integrity
sudo vagg audit verify

# Testar conectividade com cliente
sudo vagg client test petroleo
```

### 13.3 Modelo de mensagem de erro (consistência)

```json
{
  "detail": "Mensagem em português para humano",
  "code": "POLICY_NOT_FOUND",
  "trace_id": "uuid",
  "context": { "consultant_id": 42, "client_id": "petroleo" }
}
```

### 13.4 Referências externas

- RFC 6762 (mDNS, justifica não usar `.local`)
- RFC 5737 (TEST-NET ranges, evitar)
- Stripe Subscriptions docs
- CoreDNS docs
- OpenVPN auth-user-pass-verify docs
- iptables NETMAP target docs

### 13.5 Prior Art e Building Blocks Verificados

Resultado da auditoria de prior art realizada em 2026-04-30. Esta seção orienta o que usar como building block, o que estudar como inspiração, e o que NÃO tocar.

#### Building blocks para usar diretamente (sem modificar)

| Componente | Versão alvo | Licença | Onde |
|---|---|---|---|
| `openconnect` (binário) | 9.x | LGPL-2.1 | Container vagg-tunnel-openconnect |
| `openfortivpn` (binário) | 1.23+ (suporte SAML) | GPL-3.0 | Container vagg-tunnel-openfortivpn |
| `OpenVPN` Community Edition | 2.6.x | GPL-2.0 | Container vagg-tunnel-openvpn |
| `WireGuard` | Kernel 5.6+ | GPL-2.0 | Container vagg-tunnel-wireguard |
| `strongSwan` | 5.9.x | GPL-2.0 | Container vagg-tunnel-strongswan |
| `CoreDNS` | 1.11+ | Apache 2.0 | Container vagg-dns |
| `Vector` | 0.40+ | MPL 2.0 | Audit log shipping |
| `Nginx` | 1.24+ | BSD-2 | Reverse proxy interno |

#### Dockerfiles para forkar como ponto de partida

| Repo | Licença | Uso recomendado |
|---|---|---|
| `aw1cks/openconnect` | (verificar — provavelmente MIT) | Base para vagg-tunnel-openconnect; tem suporte a OTP via env var e helper scripts |
| `jesusdf/openconnect` | (idem) | Variante com TUN device naming customizado |
| `makinacorpus/docker-openconnect` | (verificar) | Inclui scripts pra Juniper e openfortivpn |

**Antes de forkar qualquer um, abrir o LICENSE no repo e confirmar permissivo.** Se o repo não tiver LICENSE, NÃO usar — código sem licença explícita é all-rights-reserved por default.

#### Projetos para ESTUDAR (não copiar código, não forkar)

| Projeto | Licença | O que estudar | O que NÃO copiar |
|---|---|---|---|
| **Headscale** (`juanfont/headscale`) | BSD-3 | API design REST, multi-tenancy patterns, ACL flatfile (huJSON) | Código direto pra evitar dependência de updates upstream |
| **Octelium** (`octelium/octelium`) | Apache 2.0 | Policy engine, identity-aware design, Kubernetes-native infra | Forkar nada — escopo deles é amplo demais |
| **Firezone** | Apache 2.0 | UI/UX patterns para zero-trust dashboard | Mesmo motivo |
| **Pritunl** | AGPLv3 | Modelo enterprise visual, paywalls, pricing | NÃO copiar código (AGPL contamina) |
| **NetBird dashboard** (UI) | BSD-3 | Padrões de UI multi-tenant, table designs | Backend é AGPL — só estudar frontend |

#### Projetos que NÃO podemos forkar comercialmente

Pesquisa confirmou que estes têm licenças incompatíveis com o nosso modelo de revenda comercial:

- **NetBird** management/signal/relay/combined → AGPLv3 desde Aug/2025
- **Pangolin** server → AGPLv3 + Fossorial Commercial License (FCL proíbe revenda)
- **Pritunl** → AGPLv3
- **OpenVPN Access Server** → proprietário comercial

Tentar forkar estes = produto morto comercialmente.

#### Por que não há "projeto base" único

Confirmado por pesquisa: nenhum projeto open-source resolve o problema "VPN aggregator multi-tenant para consultorias acessarem redes de terceiros". Os projetos similares resolvem problemas adjacentes (mesh VPN próprio, reverse proxy, concentrador enterprise) e tentar adaptá-los seria mais caro do que construir do zero. O nicho está estruturalmente vazio.

#### Estratégia de inspiração ética

Para cada componente do produto, o processo é:

1. Identificar 2-3 projetos open-source que resolvem problemas adjacentes
2. Rodar localmente, anotar UX patterns que funcionam
3. Ler arquitetura no repo (sem copiar código)
4. Implementar do zero no nosso stack, com nossas decisões
5. Atribuir inspiração no README quando claro

Exemplo: para a UI de Policies, instalar Headscale e NetBird local, brincar 2-3 horas, anotar 10 padrões úteis, implementar do zero. Tempo investido: 1-2 dias. Ganho: design 10x melhor do que inventar do zero, sem risco legal.

#### Auditoria contínua de licenças

Ferramentas a integrar no CI:

```
# Python
pip-licenses --format=json --output-file=licenses-py.json
license-check-fail --fail-on AGPL --fail-on GPL-3.0

# JavaScript
npx license-checker --production --json --out licenses-js.json
npx license-checker --production --failOn 'AGPL;GPL-3.0;BSL'

# Container layers
syft <image> -o spdx-json | grep -i license
```

Configurar como parte do CI bloqueando merge se aparecer licença incompatível em nova dependência. Isso evita armadilha futura.

### 13.6 Glossário

| Termo | Definição |
|---|---|
| Aggregator | A VM que roda o produto na infra do cliente |
| License Server | Serviço cloud que valida assinaturas |
| Cliente (do cliente) | Empresa final cujos servidores o consultor acessa |
| Consultoria | Empresa que compra o VPN Aggregator |
| Consultor | Funcionário da consultoria que acessa servidores de clientes |
| Tenant | Sinônimo de "cliente do cliente" no contexto multi-tenant |
| Virtual range | `10.200.0.0/16` reservado para mapeamento NAT |
| Real range | Subnet real de cada cliente final |
| Policy | Regra "consultor X pode acessar cliente Y com escopo Z" |
| OpenVPN corporativa | A VPN que a consultoria já tinha antes do produto |

---

## 14. Hardware Targets e Appliance Strategy

Esta seção define os tiers de hardware suportados pelo produto e a estratégia de embalagem como appliance físico.

### 14.1 Modelo de distribuição

O produto é vendido em três tiers de delivery, com a mesma stack de software:

| Tier | Hardware | Pricing target (BRL) | Mercado-alvo |
|---|---|---|---|
| **Software-only (BYO)** | Cliente provisiona VM | R$ 1.499 a R$ 3.999/mês (sem hardware) | Consultorias com TI maduro, infra própria |
| **Appliance** | Mini PC fanless, pré-configurado | R$ 4.500 setup + R$ 2.499/mês | Sweet spot — 80% dos casos esperados |
| **Appliance HA** | 2 unidades com failover automático | R$ 9.500 setup + R$ 4.999/mês | Consultorias grandes, contratos com SLA |

A versão appliance vira o canal de venda principal porque elimina a maior objeção comercial ("não temos infra pra hospedar isso"). Margem em hardware: 30-50% sobre custo de aquisição.

### 14.2 Tiers de hardware suportado

O produto roda em qualquer hardware x86_64 que atenda o mínimo, mas oficialmente são suportados quatro tiers:

#### Tier 0 — Development & Demo Reference

**Lenovo ThinkCentre M93p Tiny** (ou equivalente Haswell-era refurbished)

| Spec | Valor |
|---|---|
| CPU | Intel Core i5-4570T (4 cores, AES-NI, 35W TDP) |
| RAM | 8 GB DDR3 (atualizável para 16 GB) |
| Storage | SSD 128 GB SATA |
| NIC | 1× Gigabit Intel I217-LM |
| Capacidade | Até 25 consultores, 15 clientes |
| Custo de aquisição (refurb BR) | R$ 800-1.500 |

**Uso:** desenvolvimento, demos comerciais, primeiros 1-3 clientes pagantes pequenos. **Não** distribuir comercialmente como appliance — geração 2014, fim de vida útil de placa-mãe próximo.

#### Tier 1 — Appliance Padrão (oficial para venda)

**Mini PC industrial fanless** (Protectli, Topton, CWWK ou similar)

| Spec recomendada | Valor |
|---|---|
| CPU | Intel N100, N200, ou Core i3-N305 (4-8 cores, AES-NI, 6-15W TDP) |
| RAM | 8-16 GB DDR4/DDR5 |
| Storage | NVMe 256 GB |
| NIC | 2× ou 4× Gigabit Intel I225/I226 |
| Capacidade | Até 50 consultores, 30 clientes |
| Custo de aquisição | R$ 1.500-3.000 (importado) ou R$ 2.500-4.500 (distribuidor BR) |
| Fanless | Obrigatório (sem partes móveis) |

**Modelos validados** (a confirmar em testes de campo):
- Protectli VP2410, VP2420 — referência da categoria
- Topton N100 4-port — custo benefício importação
- CWWK Magic Computer N5105/N100 — alternativa AliExpress
- HP T740 / Dell Wyse 5070 (refurb) — opção econômica nacional

#### Tier 2 — Enterprise (HA, alto volume)

| Spec | Valor |
|---|---|
| CPU | Xeon E-2300 ou Core i5-13xxxT (8+ cores) |
| RAM | 32 GB DDR4 ECC |
| Storage | 2× NVMe 512 GB em RAID-1 |
| NIC | 2× SFP+ 10 Gigabit + 2× Gigabit |
| Redundância | Dual PSU, ECC RAM |
| Capacidade | 200+ consultores, 100+ clientes |
| Custo | R$ 6.000-12.000 |

**Uso:** consultorias grandes (50+ consultores) ou contratos com SLA 99.9%. Vendido aos pares para failover ativo-passivo.

#### Tier 3 — Cloud / VM grande (BYO)

Hardware virtualizado, sem appliance físico. Usado quando consultoria já tem ambiente VMware/Proxmox maduro e prefere VM. Sem limites técnicos além do que a VM provê.

### 14.3 Build pipeline da imagem appliance

A imagem distribuída no Tier 1 e Tier 2 é gerada por nós em CI:

```
build-pipeline/
├── packer/
│   ├── ubuntu-minimal-base.pkr.hcl     # Packer template
│   └── provision-appliance.sh          # Script de provisionamento
├── cloud-init/
│   ├── user-data                        # Configuração first-boot
│   └── meta-data
├── containers/
│   └── preload-images.sh                # Pré-carrega Docker images
└── Makefile
```

Comando de build:
```bash
make appliance-image VERSION=1.0.0 TARGET_DISK=128G
# Saída: vagg-appliance-1.0.0-amd64.img.zst (~3-4 GB compactado)
```

Imagem é assinada com Ed25519 e tem hash publicado em `https://releases.vagg.io/appliance/{version}/checksums.txt`.

### 14.4 Logística de venda do appliance

Aspectos operacionais que precisam ser endereçados (não no MVP, mas planejados):

| Aspecto | Estratégia inicial |
|---|---|
| Aquisição em volume | Compra direta importada (Aliexpress B2B, Alibaba) com lote de 5-10 unidades; conforme cresce, distribuidor brasileiro |
| Imagem nas unidades | Você grava a imagem manualmente nos primeiros 20-30; depois automatizar via stick USB clonador ou serviço de gravação contratado |
| Embalagem e envio | Caixa branca com manual impresso; envio SEDEX ou similar; nota fiscal de venda de hardware (CFOP 5102 dentro do estado, 6102 fora) |
| Garantia de hardware | Repasse da garantia do fabricante; produto cobre apenas o software via subscription |
| RMA | Substituição em caso de defeito; cliente envia, você manda outro; tempo médio 5-7 dias úteis |
| Estoque | Manter 2-3 unidades em estoque para reposição rápida |
| Importação | Importação direta requer atenção ao DI, ICMS, II — considerar nominee importer no início |

### 14.5 First-boot wizard do appliance

Tela web servida pelo `vagg-installer` em modo `appliance` durante primeiro boot.

```
┌─────────────────────────────────────────────────────────┐
│  VPN Aggregator — Configuração Inicial                  │
│                                                         │
│  Bem-vindo. Esta caixa será configurada em 5 minutos.   │
│                                                         │
│  Passo 1 de 5 — Licença                                 │
│  ┌─────────────────────────────────────────────┐        │
│  │ License key: VAGG-_____-_____-_____         │        │
│  └─────────────────────────────────────────────┘        │
│                                                         │
│  [ Continuar → ]                                        │
└─────────────────────────────────────────────────────────┘
```

Passos:
1. License key (validação online com license-server)
2. Domínio do produto (sugere `vpn.{detectado-via-dns-reverso}` se possível)
3. Configuração de rede (DHCP detectado / IP estático manual)
4. Email do admin inicial + senha (forçada strong)
5. Timezone (default America/Sao_Paulo, detectado via geo-IP)

Após confirmação: auto-configura tudo, sobe stack, gera certificados, valida health checks, mostra "Pronto. Acesse https://{domain}". Reinicia automaticamente.

### 14.6 Monitoramento remoto opcional ("phone home" diagnóstico)

Para appliances vendidos, oferecer **opt-in** de telemetria mínima que ajuda no suporte:

| Métrica | Periodicidade | Justificativa |
|---|---|---|
| Versão instalada | Diário (junto com refresh de licença) | Identificar instalações desatualizadas para alertas de segurança |
| Status geral (up/down/degraded) | Diário | Antecipar incidente antes do cliente reportar |
| # clientes configurados, # consultores ativos | Diário | Métrica de uso para product management |
| Health dos containers | Diário | Detectar containers travados |
| Erros não-recuperáveis dos últimos 7 dias | Diário | Triagem proativa |

**O que NÃO é coletado:**
- Conteúdo de logs de auditoria
- Identidade de consultores ou clientes
- Tráfego, payloads, dados pessoais
- Configurações de VPN dos clientes
- Credenciais de qualquer tipo

Implementação: o license refresh diário já vai pra `licensing.vagg.io`. A telemetria piggybacks no mesmo POST. Cliente desabilita via flag em `/etc/vagg/config.yml` (`telemetry: disabled`).

Esta funcionalidade é **opt-out**, não opt-in. Default ligado para tier Appliance, default desligado para BYO. Documentado em destaque no contrato e no first-boot wizard.

### 14.7 Critérios de seleção definitiva do hardware Tier 1

Antes de comprar lote inicial para venda, validar candidatos com testes de carga:

```
Test rig: 1 unidade do candidato + ferramenta de carga
Load: simular 30 consultores fazendo SSH + RDP em 10 clientes
Duração: 72 horas contínuas
Métricas:
  - CPU sustained < 60% médio, < 85% pico
  - RAM sustained < 50% (incluindo containers)
  - Temperatura interna < 70°C com ambiente a 30°C
  - Sem packet drops na NIC (validar com counters)
  - Sem reboots ou kernel panics
  - Throughput agregado > 500 Mbps
```

Hardware que passa nos critérios entra na lista oficial. Hardware que não passa fica fora — produto é responsável pela qualidade do appliance.

### 14.8 Roadmap de hardware (não-MVP)

| Fase | Quando | Hardware adicionado |
|---|---|---|
| Pós-Fase 11 (MVP completo) | Após 3+ clientes BYO ativos | Tier 1 oficial: 1 modelo principal |
| 6-12 meses pós-launch | Após 10+ clientes Tier 1 | Tier 2 HA disponível |
| 12-18 meses | Após validação comercial | ARM64 (Pi 5 ou equivalente) como tier "Edge Connector" para cliente final paranóico |
| 18+ meses | Demanda de cliente final | Cluster on-prem de múltiplas unidades com sync ativo-ativo |

---

**FIM DO DOCUMENTO**

Última seção propositalmente vazia para marcar o fim. Qualquer adição vai antes desta linha.
