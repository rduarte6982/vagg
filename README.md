# VPN Aggregator

Produto B2B SaaS self-hosted para consultorias de TI gerenciarem acesso simultâneo a múltiplas VPNs de clientes finais.

A consultoria instala o **Aggregator Gateway** na própria infraestrutura, atrás da OpenVPN corporativa que já existe. O produto mantém túneis persistentes para todos os clientes da consultoria — quando um consultor conecta na OpenVPN da empresa, passa a enxergar as redes dos clientes que tem permissão, com nomes amigáveis via DNS, sem rodar nenhum cliente VPN específico no notebook.

## Documentação

- [Como testar localmente](TESTING.md) — três caminhos: demo só-front, stack Docker, modo híbrido
- [Especificação técnica completa](docs/SPEC.md) — fonte única da verdade
- [Guia de kickoff](docs/KICKOFF.md) — como começar o desenvolvimento
- [Contribuição](docs/CONTRIBUTING.md) — padrões e fluxo de PR

## Status

Em desenvolvimento ativo (pré-MVP). Roadmap em 11 fases na Seção 11 do SPEC.

## Licença

[Apache License 2.0](LICENSE) — ver SPEC Seção 2.5 para racional e compatibilidade com componentes externos.
