# Contribuindo com o VPN Aggregator

Este documento define o fluxo mínimo de contribuição. Decisões técnicas detalhadas estão em [SPEC.md](SPEC.md) — esta é a fonte única da verdade.

## Antes de começar

1. Leia a [Seção 0 do SPEC](SPEC.md) (Instruções de uso) e a [Seção 2](SPEC.md) (Decisões fechadas — não rediscutir).
2. Confirme em qual fase do plano de implementação ([Seção 11](SPEC.md)) seu trabalho se encaixa.
3. Entenda o modelo de responsabilidade compartilhada ([Seção 1.5](SPEC.md)) antes de propor qualquer feature de segurança.

## Idioma

- **Código** (identificadores, nomes de função, classes, variáveis, comentários): **inglês**.
- **Mensagens de log, UI, documentação, commits, PRs, issues**: **português brasileiro**.

## Padrões de código

| Linguagem | Formatador | Linter | Type checker |
|---|---|---|---|
| Python 3.12 | `ruff format` (linha 100) | `ruff check` | `mypy --strict` |
| TypeScript / JS | `prettier` | `eslint` | `tsc --noEmit` |

CI bloqueia merge se algum desses falhar.

## Commits

Conventional Commits. Exemplos:

```
feat(core): adiciona endpoint de listagem de tunnels
fix(ui): corrige overflow do dashboard em mobile
chore(deps): atualiza fastapi para 0.115
docs(spec): atualiza Seção 4.2 com exemplo de NETMAP
```

Tipos válidos: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`, `build`, `perf`.

## Branches

- `main` é protegido. PRs precisam de CI verde + 1 review.
- Feature branches: `feat/<descricao-curta>` ou `fix/<descricao-curta>`.
- Branches de fase: `phase/<numero>-<nome>` (ex.: `phase/1-license-server`).
- Mantenha branches curtas — rebase frequente em `main`.

## Dependências e licenças

**Antes de adicionar qualquer dependência nova** (Python, Node, ou imagem Docker):

1. Confirme a licença no `LICENSE` do projeto upstream.
2. Verifique contra a lista de bloqueio da [Seção 2.5 do SPEC](SPEC.md):
   - **Bloqueado:** AGPL (qualquer versão), GPL-3.0, SSPL, BSL, FCL, licenças comerciais customizadas.
   - **Permitido:** MIT, BSD (2/3), Apache 2.0, MPL 2.0, ISC, Python Software Foundation License.
   - **Permitido para binário rodando como processo separado em container:** LGPL, GPL-2.0 (sem linkar estaticamente).
3. Se houver dúvida, abra uma issue antes do PR.

CI executa `make license-check` automaticamente.

## Critérios de aceite por fase

Toda fase do plano em [Seção 11 do SPEC](SPEC.md) tem critérios de aceite explícitos. PR de uma fase só faz merge quando:

- Todos os critérios de aceite da fase estão marcados
- CI verde (lint, type check, testes)
- Cobertura de testes > 70% no código novo
- Documentação atualizada se mudou contrato de API ou schema de DB

## Reportando bugs e segurança

- Bugs operacionais: abra issue no repositório.
- Vulnerabilidades de segurança: **não** abra issue pública. Envie um e-mail para o mantenedor (definido em `SECURITY.md` quando publicado).
