# VPN Aggregator — Makefile raiz
# Targets agregam comandos por componente. Cada componente tem seu próprio
# Makefile/scripts internos; este arquivo orquestra.

.PHONY: help bootstrap lint test clean \
        bootstrap-core bootstrap-ui bootstrap-license-server \
        lint-core lint-ui lint-license-server \
        test-core test-ui test-license-server \
        license-check

# ----- Default -----

help:
	@echo "Targets disponíveis:"
	@echo "  bootstrap       Instala dependências de todos os componentes"
	@echo "  lint            Roda linters em todos os componentes"
	@echo "  test            Roda testes em todos os componentes"
	@echo "  license-check   Verifica licenças de dependências (bloqueia AGPL/GPL-3/SSPL/BSL/FCL)"
	@echo "  clean           Remove artefatos de build, caches e venvs"

# ----- Bootstrap -----

bootstrap: bootstrap-core bootstrap-ui bootstrap-license-server
	@echo "[bootstrap] Concluído"

bootstrap-core:
	@echo "[bootstrap-core] (placeholder — implementado em Fase 2)"

bootstrap-ui:
	@echo "[bootstrap-ui] (placeholder — implementado em Fase 7)"

bootstrap-license-server:
	cd license-server && python -m pip install --upgrade pip && pip install -e ".[dev]"

# ----- Lint -----

lint: lint-core lint-ui lint-license-server
	@echo "[lint] Concluído"

lint-core:
	@echo "[lint-core] (placeholder — ruff check + mypy --strict em Fase 2)"

lint-ui:
	@echo "[lint-ui] (placeholder — eslint + prettier --check em Fase 7)"

lint-license-server:
	cd license-server && ruff check . && ruff format --check . && mypy --strict src

# ----- Test -----

test: test-core test-ui test-license-server
	@echo "[test] Concluído"

test-core:
	@echo "[test-core] (placeholder — pytest em Fase 2)"

test-ui:
	@echo "[test-ui] (placeholder — vitest em Fase 7)"

test-license-server:
	cd license-server && pytest --cov=src --cov-report=term-missing --cov-fail-under=70

# ----- License compliance (SPEC §2.5 / §13.5) -----

license-check: license-check-license-server
	@echo "[license-check] Concluído"

license-check-license-server:
	@echo "[license-check] vagg-license-server"
	@command -v pip-licenses >/dev/null 2>&1 || pip install pip-licenses
	@cd license-server && pip-licenses --format=plain --with-urls \
		--fail-on='AGPL;AGPL-3.0;AGPL-3.0-only;AGPL-3.0-or-later;GPL-3.0;GPL-3.0-only;GPL-3.0-or-later;SSPL;BUSL;BSL;FCL'

# ----- Clean -----

clean:
	@echo "[clean] Removendo caches e artefatos..."
	@find . -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache" -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "node_modules" -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "dist" -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "build" -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".venv" -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "[clean] Concluído"
