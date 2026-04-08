# Installation

## Docker (recommended)

```bash
git clone https://github.com/kalexnolasco/webgate.git
cd webgate
docker compose up -d
```

Open `http://localhost:8443` in your browser.

!!! tip "Production"
    Set a strong secret key:
    ```bash
    WEBGATE_SECRET_KEY=$(openssl rand -hex 32) docker compose up -d
    ```

### With TLS (Caddy)

```yaml
# compose.yml
services:
  webgate:
    build: .
    restart: unless-stopped
    ports:
      - "8443:8443"
    volumes:
      - webgate-data:/data
    environment:
      WEBGATE_SECRET_KEY: "${WEBGATE_SECRET_KEY}"

  caddy:
    image: caddy:2-alpine
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile

volumes:
  webgate-data:
```

```title="Caddyfile"
webgate.example.com {
    reverse_proxy webgate:8443
}
```

## Local Development

```bash
# Requirements: Python 3.11+, uv
uv sync
uv run python -m webgate
```

### With demo SSH server

```bash
docker compose -f compose.dev.yml up -d
# webgate at :8443 + SSH demo (user: demo, password: demo)
```

## Configuration

All settings use environment variables with the `WEBGATE_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `WEBGATE_HOST` | `0.0.0.0` | Bind address |
| `WEBGATE_PORT` | `8443` | Server port |
| `WEBGATE_SECRET_KEY` | `change-me-in-production` | JWT + encryption key |
| `WEBGATE_DB_URL` | `sqlite+aiosqlite:///./webgate.db` | Database URL |
| `WEBGATE_ALLOWED_ORIGINS` | `*` | CORS origins |
| `WEBGATE_LOG_LEVEL` | `info` | Log level |
| `WEBGATE_SESSION_TIMEOUT` | `3600` | SSH timeout (seconds) |
| `WEBGATE_MAX_UPLOAD_SIZE` | `104857600` | Max upload (100MB) |
| `WEBGATE_JWT_EXPIRE_MINUTES` | `1440` | Token expiry (24h) |
