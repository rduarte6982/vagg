# KICKOFF — VPN Aggregator com Claude Code

> Companheiro do `SPEC-vpn-aggregator-v1.2.md`. Ler **depois** do SPEC.
> Este arquivo é a porta de entrada do desenvolvimento.

---

## 1. Preparação do hardware de desenvolvimento (M93p)

Antes de chamar Claude Code, executar isso na sua bancada:

### Verificações rápidas (15 minutos)

```bash
# CPU e AES-NI
cat /proc/cpuinfo | grep -E "model name|aes" | head -4

# RAM
free -h

# SSD wear
sudo smartctl -a /dev/sda | grep -E "Wearout|Wear_Leveling|Power_On_Hours"

# Versão do BIOS (anota — vale atualizar se >2 anos atrás)
sudo dmidecode -s bios-version
```

Decisões com base no resultado:
- Se RAM = 1×8GB → considerar comprar +1 pente DDR3 SODIMM 8GB usado (~R$80-150) para 16GB dual-channel
- Se SSD wear > 80% → trocar por SSD novo 256GB (~R$150-200)
- Se BIOS antigo → atualizar via Lenovo Vantage ou ISO bootável

### Instalação do SO base (45 minutos)

```bash
# 1. Baixar Ubuntu Server 24.04 LTS minimal ISO
# 2. Gravar em pendrive (Rufus / dd / balenaEtcher)
# 3. Boot da pendrive no M93p (F12 no boot)
# 4. Instalar:
#    - Username: rodrigo
#    - Hostname: vagg-dev
#    - Disk: usar disco inteiro com LVM
#    - SSH server: habilitado durante install
#    - Pacotes adicionais: nenhum (tudo via Ansible/script depois)
# 5. Após reboot, configurar IP estático na sua LAN
```

Pós-instalação:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git build-essential python3.12-venv

# Setup chave SSH (do seu notebook de dev)
ssh-copy-id rodrigo@<ip-do-m93p>

# Desabilitar login com senha (segurança)
sudo sed -i 's/^#PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart sshd
```

Pronto. M93p está virgem, esperando o vagg-installer da Fase 10.

---

## 2. Bootstrap do projeto (no seu notebook de dev)

```bash
mkdir -p ~/projetos/vagg
cd ~/projetos/vagg
git init -b main

# Copia os documentos
mkdir -p docs
cp ~/Downloads/SPEC-vpn-aggregator-v1.2.md docs/SPEC.md
cp ~/Downloads/KICKOFF-CLAUDE-CODE.md docs/KICKOFF.md

# Primeiro commit
git add .
git commit -m "docs: spec inicial v1.2 + kickoff"

# Criar repo no GitHub e subir
gh repo create rduarte6982/vagg --private --source=. --push
```

---

## 3. Primeiro chamado ao Claude Code

Depois de ter Claude Code instalado (via `npm install -g @anthropic-ai/claude-code`), abrir terminal no diretório do projeto e rodar `claude`. Cole **exatamente** o prompt abaixo:

```
Vamos construir o VPN Aggregator — produto B2B SaaS para consultorias 
gerenciarem acesso a múltiplas VPNs de clientes.

REGRAS DE TRABALHO:
1. Leia docs/SPEC.md seções 0, 1.1, 2 (inteira), 12, 13.5 e 14 antes 
   de qualquer ação. Esses são contexto + decisões fechadas.
2. NÃO leia o resto do SPEC ainda. Cada fase tem seções específicas que 
   serão indicadas no momento certo, isso minimiza tokens.
3. Não rediscuta decisões que estão na Seção 2. Stack, libs, padrões, 
   licença — tudo decidido.
4. Toda nova dependência precisa passar pelo check de licença da 
   Seção 2.5 antes de adicionar. Sem AGPL, sem GPL-3.

TAREFA AGORA:
Bootstrap do monorepo conforme Seção 12. Quero que você crie:
- README.md raiz com visão geral curta + link para docs/SPEC.md
- LICENSE (Apache 2.0)
- .gitignore robusto (Python, Node, Docker, IDEs, OS)
- .editorconfig (linha 100, LF, UTF-8)
- Estrutura de pastas vazias com .gitkeep conforme Seção 12
- .github/workflows/ com 3 workflows stub:
  - core-ci.yml (Python lint + test, ainda sem código)
  - ui-ci.yml (Node lint + test, ainda sem código)
  - release.yml (semantic release com placeholder)
- docs/ com CONTRIBUTING.md mínimo
- Makefile raiz com targets: bootstrap, lint, test, clean

NÃO CRIAR ainda:
- Código real de qualquer componente
- Dockerfiles
- Configs de license server, core, etc.

Após criar, mostre `tree -L 3` da estrutura final e me peça revisão antes 
de prosseguir para Fase 1.
```

---

## 4. Workflow recomendado para as próximas fases

Depois que o bootstrap estiver de pé, o padrão para cada fase fica assim:

```
"Implementa Fase N do SPEC. Lê docs/SPEC.md seção 11 (apenas a fase 
referenciada) e as seções específicas que ela menciona. Não lê outras 
seções. Quando terminar, roda os testes e me mostra o output."
```

Substituir `N` pela fase. Ordem das fases (Seção 11):

| Fase | O que faz | Tempo estimado | Bloqueia o quê |
|---|---|---|---|
| 1 | License Server (cloud) | 2-3 dias | Validação de licença em todas as outras |
| 2 | Aggregator Core esqueleto | 2-3 dias | Quase tudo |
| 3 | Tunnel Orchestrator + container OpenVPN | 3-5 dias | Fases 4-5 |
| 4 | NAT remapping e roteamento | 2-3 dias | Tráfego real funcionar |
| 5 | Containers de outros protocolos VPN | 4-5 dias | Suporte a clientes diversos |
| 6 | DNS layer (CoreDNS) | 1-2 dias | UX final |
| 7 | Admin UI (React) | 5-7 dias | Operação |
| 8 | RBAC integrado com OpenVPN | 2-3 dias | Multi-tenant funcional |
| 9 | Audit pipeline | 2-3 dias | Compliance |
| 10 | Installer + packaging | 3-4 dias | Demos comerciais |
| 11 | Portal de Transparência (diferencial) | 4-6 dias | Vendas |

Total realista: 30-45 dias úteis com Claude Code trabalhando em paralelo com você revisando.

---

## 5. Quando interromper o Claude Code

Algumas situações exigem que você pause e reavalie:

- Claude Code sugere instalar uma lib que NÃO está na Seção 2.1 → recusar, sugerir alternativa
- Claude Code sugere mudar uma decisão da Seção 2 → recusar, lembrar que está fechada
- Claude Code começa a "consertar" código de fase anterior sem ter sido pedido → revisar mudanças com cuidado
- Claude Code passa de 1.5x do tempo estimado da fase → parar, revisar, possivelmente quebrar a fase em sub-tarefas

---

## 6. Checkpoints obrigatórios entre fases

Antes de marcar uma fase como done, validar **manualmente**:

1. Critérios de aceite da Seção 11 daquela fase passam
2. CI verde
3. `mypy --strict` (Python) e `eslint` (JS) sem warnings
4. Testes >70% coverage no novo código
5. Doc atualizada se mudou contrato de API ou schema

Só depois rodar `git tag fase-N-completa` e seguir.

---

## 7. Validação de licença em cada PR

Claude Code é ágil em adicionar libs. Para evitar contaminação por AGPL:

```bash
# No CI (já vai estar configurado pela Seção 13.5):
make license-check

# Bloqueia merge se aparecer:
# - AGPL-1.0, AGPL-3.0
# - GPL-3.0
# - SSPL
# - BSL
# - Custom commercial licenses
```

Se aparecer no relatório, alterar a dependência ou pedir aprovação manual sua antes de prosseguir.

---

## 8. Ritmo sustentável

Sugestão de cadência saudável (você + Claude Code juntos):

- **Manhã (2h):** Claude Code implementa a fase em background; você revisa o que ele entregou ontem
- **Tarde (2h):** Você roda os testes localmente, abre PR, faz comentários
- **Final do dia:** Claude Code aplica revisões; merge

Não tente fazer 3 fases num dia. Vai gerar dívida técnica que custa mais tempo depois.

---

## 9. Quando começar a vender

Não esperar todas as fases. Cronograma de venda paralela ao desenvolvimento:

| Marco | Quando | Ação comercial |
|---|---|---|
| Fase 5 completa | ~D+15 | Conversas exploratórias com 3-5 consultorias amigas, sem cobrar |
| Fase 8 completa | ~D+25 | Demo agendada com 2 prospects, ainda sem cobrar |
| Fase 11 completa | ~D+45 | Primeiro contrato pago (recomenda 50% off como design partner) |
| 3 design partners ativos | ~D+90 | Pricing oficial, lista de espera |

Não tente vender sem ter Fase 11 funcionando. O Portal é o diferencial — vender sem ele é vender commodity.

---

**Bora.**
