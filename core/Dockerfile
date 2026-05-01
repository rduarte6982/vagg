# syntax=docker/dockerfile:1.7
# Imagem do vagg-core. Em produção roda no host (não em container) por causa do
# acesso a iptables/ip rule (SPEC §3.4). Esta imagem existe para dev e para a
# integração com docker-compose nos testes finais (Fase 10).

FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --upgrade pip wheel && pip wheel --wheel-dir /wheels .

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system --gid 1000 vagg \
    && useradd --system --uid 1000 --gid vagg --create-home vagg \
    && mkdir -p /var/lib/vagg \
    && chown -R vagg:vagg /var/lib/vagg

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels vagg-core \
    && rm -rf /wheels

COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

USER vagg
EXPOSE 8443
VOLUME ["/var/lib/vagg"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://localhost:8443/api/v1/system/health',timeout=3).status==200 else 1)" \
    || exit 1

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn --factory vagg_core.main:create_app --host 0.0.0.0 --port 8443"]
