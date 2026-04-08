# --- Stage 1: build ---
FROM python:3.13-slim AS builder

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-editable

COPY src/ src/

# --- Stage 2: runtime ---
FROM python:3.13-slim

RUN groupadd -r webgate && useradd -r -g webgate -m webgate

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Data directory for SQLite DB + uploaded SSH keys
RUN mkdir -p /data && chown webgate:webgate /data
VOLUME /data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    WEBGATE_HOST=0.0.0.0 \
    WEBGATE_PORT=8443 \
    WEBGATE_DB_URL=sqlite+aiosqlite:////data/webgate.db \
    WEBGATE_LOG_LEVEL=info

EXPOSE 8443

USER webgate

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8443/api/health')"

CMD ["python", "-m", "webgate"]
