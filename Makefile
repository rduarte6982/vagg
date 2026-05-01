# VPN Aggregator — Makefile raiz
# Targets agregam comandos por componente. Cada componente tem seu próprio
# Makefile/scripts internos; este arquivo orquestra.

.PHONY: help bootstrap lint test clean \
        bootstrap-core bootstrap-ui bootstrap-license-server bootstrap-tunnels \
        lint-core lint-ui lint-license-server lint-tunnels \
        test-core test-ui test-license-server test-tunnels \
        tunnels-build \
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

bootstrap: bootstrap-core bootstrap-ui bootstrap-license-server bootstrap-tunnels
	@echo "[bootstrap] Concluído"

bootstrap-core:
	cd core && python -m pip install --upgrade pip && pip install -e ".[dev]"

bootstrap-ui:
	@echo "[bootstrap-ui] (placeholder — implementado em Fase 7)"

bootstrap-license-server:
	cd license-server && python -m pip install --upgrade pip && pip install -e ".[dev]"

bootstrap-tunnels:
	cd tunnels/shared && python -m pip install --upgrade pip && pip install -e ".[dev]"

# ----- Lint -----

lint: lint-core lint-ui lint-license-server lint-tunnels
	@echo "[lint] Concluído"

lint-core:
	cd core && ruff check . && ruff format --check . && mypy --strict src

lint-ui:
	@echo "[lint-ui] (placeholder — eslint + prettier --check em Fase 7)"

lint-license-server:
	cd license-server && ruff check . && ruff format --check . && mypy --strict src

lint-tunnels:
	cd tunnels/shared && ruff check . && ruff format --check . && mypy --strict tunnel_controller.py tests

# ----- Test -----

test: test-core test-ui test-license-server test-tunnels
	@echo "[test] Concluído"

test-core:
	cd core && pytest --cov=src --cov-report=term-missing --cov-fail-under=70

test-ui:
	@echo "[test-ui] (placeholder — vitest em Fase 7)"

test-license-server:
	cd license-server && pytest --cov=src --cov-report=term-missing --cov-fail-under=70

test-tunnels:
	cd tunnels/shared && pytest -q

# Build local de imagem do tunnel-openvpn (sem push). Requer Docker.
tunnels-build:
	docker build -f tunnels/openvpn/Dockerfile -t vagg/tunnel-openvpn:dev tunnels/

# ----- License compliance (SPEC §2.5 / §13.5) -----

license-check: license-check-license-server license-check-core
	@echo "[license-check] Concluído"

license-check-license-server:
	@echo "[license-check] vagg-license-server"
	@command -v pip-licenses >/dev/null 2>&1 || pip install pip-licenses
	@cd license-server && pip-licenses --format=plain --with-urls \
		--fail-on='AGPL;AGPL-3.0;AGPL-3.0-only;AGPL-3.0-or-later;GPL-3.0;GPL-3.0-only;GPL-3.0-or-later;SSPL;BUSL;BSL;FCL'

license-check-core:
	@echo "[license-check] vagg-core"
	@command -v pip-licenses >/dev/null 2>&1 || pip install pip-licenses
	@cd core && pip-licenses --format=plain --with-urls \
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
