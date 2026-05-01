# syntax=docker/dockerfile:1.7
# Imagem para deploy em Cloud Run / Render / Fly.io.

# ----- Builder -----
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

# ----- Runtime -----
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Non-root user (CIS Docker benchmark 4.1).
RUN groupadd --system --gid 1000 vagg \
    && useradd --system --uid 1000 --gid vagg --create-home vagg

WORKDIR /app

# Install from prebuilt wheels — no compiler needed in runtime image.
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels vagg-license-server \
    && rm -rf /wheels

COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

USER vagg
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health',timeout=3).status==200 else 1)" \
    || exit 1

# Run migrations then start uvicorn. Migration is idempotent (alembic upgrade head).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn vagg_license.main:app --host 0.0.0.0 --port 8080"]
