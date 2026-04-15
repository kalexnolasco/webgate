# webgate

[![PyPI](https://img.shields.io/pypi/v/webgate?style=flat-square)](https://pypi.org/project/webgate/)
[![Python](https://img.shields.io/pypi/pyversions/webgate?style=flat-square)](https://pypi.org/project/webgate/)
[![License](https://img.shields.io/pypi/l/webgate?style=flat-square)](https://github.com/kalexnolasco/webgate/blob/main/LICENSE)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](Dockerfile)
[![Status](https://img.shields.io/badge/status-beta-orange?style=flat-square)](https://pypi.org/project/webgate/)
[![Tests](https://img.shields.io/badge/tests-34%20passed-brightgreen?style=flat-square)](https://github.com/kalexnolasco/webgate/actions)
[![Docs](https://img.shields.io/badge/docs-kalexnolasco.github.io-blue?style=flat-square)](https://kalexnolasco.github.io/webgate/)

Self-hosted web application for remote server management via **SSH terminal** and **SFTP file browser**. A modern Python replacement combining the best of [webssh](https://github.com/huashengdun/webssh) and [filebrowser](https://github.com/filebrowser/filebrowser) into a single unified tool with a FileZilla-inspired interface.

> **Documentation: [kalexnolasco.github.io/webgate](https://kalexnolasco.github.io/webgate/)**
>
> **🎮 Live demo: [webgate-demo.fly.dev](https://webgate-demo.fly.dev/)** — login `demo` / `demo` (read-only, resets hourly)

---

## Why webgate?

Managing remote servers often means juggling SSH clients, SFTP tools, credentials, and VPN configs across your team. In many real-world scenarios, **direct SSH access to every server isn't possible** -- you only have HTTP/HTTPS access to a single entry point.

### The problem

A typical client infrastructure looks like this: a network of internal servers (databases, application servers, workers, etc.) behind a firewall, with only **one server exposed via HTTP**. Your team needs to manage all of them, but each engineer would need VPN access, local SSH clients, and credential management.

```mermaid
flowchart TB
    subgraph internet ["Internet"]
        YOU["Your Team"]
    end

    subgraph firewall ["Client Firewall"]
        GW["Gateway Server
        (HTTP only)"]

        subgraph internal ["Internal Network"]
            DB1[(PostgreSQL
            10.0.1.10)]
            DB2[(MySQL
            10.0.1.11)]
            APP1["App Server
            10.0.1.20"]
            APP2["App Server
            10.0.1.21"]
            WORKER["Worker
            10.0.1.30"]
            REDIS["Redis
            10.0.1.40"]
        end
    end

    YOU -- "HTTPS :443" --> GW
    GW -. "SSH :22" .-> DB1
    GW -. "SSH :22" .-> DB2
    GW -. "SSH :22" .-> APP1
    GW -. "SSH :22" .-> APP2
    GW -. "SSH :22" .-> WORKER
    GW -. "SSH :22" .-> REDIS

    style internet fill:#e8f0fe,stroke:#4a90d9
    style firewall fill:#fff3e0,stroke:#ff9800
    style internal fill:#f0f9e8,stroke:#5cb85c
    style GW fill:#ffcc02,stroke:#e6a800,color:#333
    style YOU fill:#4a90d9,stroke:#2a6cb5,color:#fff
```

### The solution

Deploy **webgate** on the gateway server. Your entire team gets browser-based SSH and SFTP access to every internal server -- no VPN, no local SSH clients, no credential files scattered across laptops.

```mermaid
flowchart TB
    subgraph internet ["Internet"]
        ENG1["Engineer 1
        (Browser)"]
        ENG2["Engineer 2
        (Browser)"]
        ENG3["Engineer 3
        (Browser)"]
    end

    subgraph firewall ["Client Firewall"]
        WG["webgate
        Gateway Server
        :443"]

        subgraph internal ["Internal Network"]
            DB1[(PostgreSQL
            10.0.1.10)]
            DB2[(MySQL
            10.0.1.11)]
            APP1["App Server
            10.0.1.20"]
            APP2["App Server
            10.0.1.21"]
            WORKER["Worker
            10.0.1.30"]
            REDIS["Redis
            10.0.1.40"]
        end
    end

    ENG1 -- "HTTPS" --> WG
    ENG2 -- "HTTPS" --> WG
    ENG3 -- "HTTPS" --> WG
    WG -- "SSH" --> DB1
    WG -- "SSH" --> DB2
    WG -- "SSH" --> APP1
    WG -- "SSH" --> APP2
    WG -- "SSH" --> WORKER
    WG -- "SSH" --> REDIS

    style internet fill:#e8f0fe,stroke:#4a90d9
    style firewall fill:#fff3e0,stroke:#ff9800
    style internal fill:#f0f9e8,stroke:#5cb85c
    style WG fill:#5cb85c,stroke:#449d44,color:#fff
    style ENG1 fill:#4a90d9,stroke:#2a6cb5,color:#fff
    style ENG2 fill:#4a90d9,stroke:#2a6cb5,color:#fff
    style ENG3 fill:#4a90d9,stroke:#2a6cb5,color:#fff
```

### Use cases

| Scenario | How webgate helps |
|----------|-------------------|
| **Client with restricted access** | Deploy on the only HTTP-accessible server, reach all internal machines via SSH/SFTP |
| **On-call / incident response** | Open a browser from any device, connect instantly -- no laptop with SSH keys needed |
| **Team onboarding** | Admin creates a user, assigns groups -- new engineer has access in seconds |
| **Audit & compliance** | Centralized access point, all connections go through one managed gateway |
| **Air-gapped environments** | Only needs outbound HTTP from the gateway, no inbound ports on internal servers |
| **Multi-client management** | Run separate webgate instances per client, each with its own server registry |

---

## Features

| Category | Capabilities |
|----------|-------------|
| **SSH Web Terminal** | Browser-based terminal via xterm.js + asyncssh, resize handling, copy/paste, multi-tab sessions |
| **SFTP File Browser** | Directory listing, upload/download, drag & drop, rename, delete, mkdir, chmod, breadcrumb navigation |
| **File Editor** | In-browser text editor powered by CodeMirror 6 with syntax highlighting (oneDark theme) |
| **File Preview** | PDF viewer, image preview (PNG, JPG, GIF, SVG, WebP) directly in the browser |
| **Server Registry** | Add/edit/delete servers, groups, tags, password & key auth, test connectivity, import/export, per-server SSH/SFTP toggles |
| **Quick Connect** | One-off SSH/SFTP connections without saving server config (FileZilla-style toolbar) |
| **Access Control** | Admin creates users, assigns server groups, enables/disables SSH or SFTP per server, restricts SFTP to specific paths, read-only SFTP mode |
| **Server Monitoring** | Background SSH connectivity checks every 60s, green/red status dot on server dashboard |
| **Dark/Light Theme** | Toggle between dark and light themes, saved in localStorage, terminal adapts |
| **Credential Security** | SSH passwords and private keys encrypted at rest with Fernet (derived from app secret) |
| **Connection Pool** | SFTP connections are reused per server (5 min TTL), not opened/closed on every request |
| **Upload Progress** | Visual progress bar with percentage during file uploads |
| **ZIP Download** | Download entire directories as ZIP archives from the SFTP browser |
| **Keyboard Shortcuts** | Escape closes modals, Ctrl+1 Site Manager, Ctrl+N New Server |
| **Docker Ready** | Multi-stage Dockerfile, single-command deployment, health checks, persistent volumes |
| **Responsive** | Adapts to tablet and mobile screen sizes |
| **Zero Frontend Build** | Vanilla JS + Alpine.js, no npm/node required, all assets from CDN |

## Screenshots

### Login
![Login](docs/screenshots/login.png)

### Site Manager
![Site Manager](docs/screenshots/site-manager.png)

### SSH Terminal
![SSH Terminal](docs/screenshots/terminal.png)

### SFTP File Browser
![SFTP Browser](docs/screenshots/sftp.png)

### File Editor (CodeMirror 6)
![Editor](docs/screenshots/editor.png)

### Split View (Terminal + SFTP)
![Split View](docs/screenshots/split-view.png)

### Access Control (per-server SSH/SFTP toggles + path restrictions)
![Access Control](docs/screenshots/access-control.png)

### SSH Disabled (button greyed out)
![SSH Disabled](docs/screenshots/ssh-disabled.png)

### SFTP Path Restriction in Action
![SFTP Restricted](docs/screenshots/sftp-restricted.png)

### User Management
![Users](docs/screenshots/users.png)

### Audit Log
![Audit](docs/screenshots/audit.png)

### Light Theme
![Light Theme](docs/screenshots/light-theme.png)

### v0.4.1 — SSH Session Recording

Set `WEBGATE_RECORD_SESSIONS=true` and every SSH session is captured to an asciinema cast v2 file. Replay in the browser with the embedded asciinema player, or download the `.cast` and `asciinema play` it locally.

```bash
docker run -e WEBGATE_RECORD_SESSIONS=true \
  -e WEBGATE_RECORDINGS_DIR=/data/recordings \
  -v webgate-data:/data \
  kalexnolasco/webgate:0.4.1
```

| Recordings list | Replay in browser |
| --- | --- |
| ![Recordings](docs/screenshots/v0.4/04-recordings-modal.png) | ![Replay](docs/screenshots/v0.4/03-recording-replay.png) |

Non-admins see only their own recordings; admins see everyone's. Each recording row has **▶ Play** (browser), **DL** (download `.cast`), and **Del**.

### v0.4.0 — Shared Terminal Sessions

Pair-debugging or onboarding from anywhere: the owner clicks **🔗 Share** in the terminal toolbar, copies the URL, and any colleague who opens it joins the same live session. Output is broadcast to every participant; any RW participant can type.

| Owner | Joiner |
| --- | --- |
| ![Owner view](docs/screenshots/v0.4/01-shared-terminal-owner.png) | ![Joiner view](docs/screenshots/v0.4/02-shared-terminal-joiner.png) |

The `?join=<token>` URL parameter is recognized after login -- a joiner can be sent the URL directly even if they aren't logged in yet.

### v0.3.x — Operations Pack

These screenshots come from the live demo at https://webgate-demo.fly.dev (login `demo` / `demo`).

#### Demo banner on login
![Demo banner](docs/screenshots/v0.3/01-login-demo-banner.png)

#### Site Manager with jump-host indicator
The `↺` next to `internal-app` means it tunnels through `bastion`.

![Dashboard with jump host](docs/screenshots/v0.3/02-dashboard-jump-host.png)

#### Terminal with snippets toolbar
Click a snippet button to send `command + Enter` to the active session. Right-click to delete, `+` to create.

![Terminal snippets](docs/screenshots/v0.3/03-terminal-snippets-jump.png)

#### Snippet executed
Clicking `ls -lah` sent the command and the output appears in the terminal.

![Snippet executed](docs/screenshots/v0.3/04-snippet-executed.png)

#### SFTP via jump host
Browsing the `internal-app` filesystem — the SFTP connection is also tunneled through the bastion.

![SFTP via jump](docs/screenshots/v0.3/05-sftp-via-jump.png)

#### Webhooks management (admin)
Per-event subscription, optional HMAC signing, last delivery status.

![Webhooks modal](docs/screenshots/v0.3/06-webhooks-modal.png)

#### Add Server form with Jump Via dropdown
Pick any other registered server as the bastion.

![Add Server with Jump Via](docs/screenshots/v0.3/08-add-server-jump-via.png)

## Quick Start

### Docker (recommended)

```bash
# Clone and run
git clone https://gitlab.wdna.com/wdna/webgate.git
cd webgate
docker compose up -d

# Open http://localhost:8443
# Login with admin / admin (you'll be asked to change the password)
```

> **Important:** On first launch, webgate creates a default `admin` / `admin` account. You will be forced to change the password on first login. Set a strong secret key in production:

```bash
WEBGATE_SECRET_KEY=$(openssl rand -hex 32) docker compose up -d
```

### Development with SSH demo server

A `compose.dev.yml` is included with a demo SSH container for testing:

```bash
docker compose -f compose.dev.yml up -d
# webgate at :8443 + SSH demo server (user: demo, password: demo)
```

### Local Development

```bash
# Install dependencies
uv sync

# Run dev server with auto-reload
uv run uvicorn webgate.app:create_app --factory --reload --host 0.0.0.0 --port 8443

# Or simply
uv run python -m webgate
```

## User Management

webgate uses a **role-based access model** with two roles: **admin** and **user**.

### How it works

```mermaid
flowchart LR
    ADMIN["Admin"] -->|creates| SERVERS["Servers
    (grouped)"]
    ADMIN -->|creates| USERS["Users"]
    ADMIN -->|assigns groups to| USERS

    USERS -->|can access| ALLOWED["Servers in
    allowed groups"]

    style ADMIN fill:#5cb85c,stroke:#449d44,color:#fff
    style SERVERS fill:#e8f0fe,stroke:#4a90d9
    style USERS fill:#fff3e0,stroke:#ff9800
    style ALLOWED fill:#f0f9e8,stroke:#5cb85c
```

| | Admin | User |
|---|---|---|
| Add/edit/delete servers | Yes | No |
| Enable/disable SSH or SFTP per server | Yes | No |
| Restrict SFTP to specific paths | Yes | No |
| Create/delete users | Yes | No |
| Assign groups to users | Yes | No |
| See all servers | Yes | Only servers in assigned groups |
| SSH terminal (if enabled on server) | Yes | Yes (allowed servers only) |
| SFTP file browser (if enabled, within allowed paths) | Yes | Yes (allowed servers only) |
| Quick Connect | Yes | Yes |

### Example workflow

1. **Admin** logs in (default `admin`/`admin`, forced to change password)
2. **Admin** adds servers and organizes them into groups (`production`, `staging`, `dev`)
3. **Admin** creates users and assigns groups:
   - `alice` -> `production`, `staging` (senior engineer)
   - `bob` -> `staging`, `dev` (junior, no prod access)
   - `charlie` -> `production` (read-only ops, only prod)
4. Each user logs in and sees **only** the servers in their assigned groups

## Architecture

```
webgate/
├── src/webgate/
│   ├── __main__.py          # Entry point: uvicorn launcher
│   ├── app.py               # FastAPI app factory, lifespan, middleware
│   ├── config.py            # Pydantic Settings (env vars, defaults)
│   ├── auth/                # JWT auth, user management, admin routes
│   │   ├── models.py        # User model + Pydantic schemas
│   │   ├── service.py       # Password hashing, JWT, seed_admin, CRUD
│   │   └── routes.py        # Login, change-password, admin user CRUD
│   ├── servers/             # Server registry CRUD, connectivity test
│   │   ├── models.py        # Server model + schemas
│   │   ├── service.py       # CRUD with group-based filtering
│   │   └── crypto.py        # Fernet encrypt/decrypt for credentials
│   ├── terminal/            # WebSocket SSH bridge (xterm.js <-> asyncssh)
│   ├── files/               # SFTP operations with connection pooling
│   │   ├── sftp_service.py  # SFTP client wrapper
│   │   ├── pool.py          # Connection pool (reuse per server, 5min TTL)
│   │   └── routes.py        # REST API: ls, read, write, upload, download, chmod
│   ├── db/                  # SQLAlchemy async engine + session factory
│   └── static/              # Frontend (single index.html, FileZilla-style UI)
├── tests/
├── Dockerfile               # Multi-stage build (python:3.13-slim)
├── Dockerfile.ssh-demo      # Demo SSH container for development
├── compose.yml              # Production deployment
├── compose.dev.yml          # Development with SSH demo server
└── pyproject.toml
```

```mermaid
flowchart LR
    subgraph Browser
        XT[xterm.js] --> WS[WebSocket]
        UI[Alpine.js UI] --> REST[REST API]
        CM[CodeMirror] --> REST
    end

    subgraph webgate ["webgate (FastAPI)"]
        WS --> SSH[asyncssh Session]
        REST --> POOL[SFTP Pool]
        POOL --> SFTP[asyncssh SFTP]
        REST --> DB[(SQLite)]
        REST --> AUTH[JWT Auth]
    end

    SSH --> RS[Remote Server]
    SFTP --> RS

    style Browser fill:#e8f0fe,stroke:#4a90d9
    style webgate fill:#f0f9e8,stroke:#5cb85c
    style RS fill:#fff3e0,stroke:#ff9800
```

## API Reference

### Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/login` | Login, returns JWT token |
| `GET` | `/api/auth/me` | Current user info (includes `must_change_password`) |
| `POST` | `/api/auth/change-password` | Change own password |
| `GET` | `/api/auth/users` | List all users (admin only) |
| `POST` | `/api/auth/users` | Create user with allowed groups (admin only) |
| `PUT` | `/api/auth/users/{id}/groups` | Update user's allowed groups (admin only) |
| `PUT` | `/api/auth/users/{id}/password` | Reset user's password (admin only) |
| `DELETE` | `/api/auth/users/{id}` | Delete user (admin only) |
| `GET` | `/api/auth/audit` | Audit log with filters (admin only) |

### Server Registry

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/servers` | List servers (filtered by user's allowed groups) |
| `POST` | `/api/servers` | Create server (admin only) |
| `GET` | `/api/servers/{id}` | Server details |
| `PUT` | `/api/servers/{id}` | Update server (admin only) |
| `DELETE` | `/api/servers/{id}` | Delete server (admin only) |
| `POST` | `/api/servers/{id}/test` | Test SSH connectivity |
| `GET` | `/api/servers/groups` | List groups (filtered by user's access) |
| `POST` | `/api/servers/import` | Bulk import (admin only) |
| `GET` | `/api/servers/export` | Export all servers (admin only) |

### Terminal (WebSocket)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `WS` | `/api/ws/terminal/{server_id}` | SSH terminal to saved server |
| `WS` | `/api/ws/terminal/quick` | Quick connect with inline credentials |

### SFTP File Manager

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/files/{id}/ls?path=` | Directory listing |
| `GET` | `/api/files/{id}/read?path=` | Read text file |
| `GET` | `/api/files/{id}/download?path=` | Download file |
| `POST` | `/api/files/{id}/upload?path=` | Upload files (multipart) |
| `PUT` | `/api/files/{id}/write` | Save text file |
| `POST` | `/api/files/{id}/mkdir` | Create directory |
| `POST` | `/api/files/{id}/rename` | Rename/move |
| `DELETE` | `/api/files/{id}/delete?path=` | Delete file/directory |
| `POST` | `/api/files/{id}/chmod` | Change permissions |
| `GET` | `/api/files/{id}/stat?path=` | File metadata |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check (`{"status": "ok"}`) |

## Configuration

All settings are configurable via environment variables with the `WEBGATE_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `WEBGATE_HOST` | `0.0.0.0` | Server bind address |
| `WEBGATE_PORT` | `8443` | Server port |
| `WEBGATE_SECRET_KEY` | `change-me-in-production` | JWT signing + Fernet encryption key |
| `WEBGATE_DB_URL` | `sqlite+aiosqlite:///./webgate.db` | Database URL |
| `WEBGATE_ALLOWED_ORIGINS` | `*` | CORS origins (comma-separated) |
| `WEBGATE_ROOT_PATH` | `` (empty) | URL prefix when served behind a reverse proxy at a sub-path (e.g. `/webgate`) |
| `WEBGATE_DEMO_MODE` | `false` | Read-only public demo: blocks all writes, seeds a `demo`/`demo` user and shows a banner |

### PostgreSQL

SQLite is the default. To use PostgreSQL, just point `WEBGATE_DB_URL` at it (the `asyncpg` driver is bundled as of v0.3.1):

```bash
export WEBGATE_DB_URL='postgresql+asyncpg://user:pass@host:5432/webgate'
```

Lightweight migrations are dialect-aware. Schema is created automatically on first start.

### Jump host / bastion

When adding a server, pick another server from the **Jump Via** dropdown to tunnel the SSH and SFTP connections through it. Useful when the target server is only reachable from a specific bastion. Stored as `jump_via_id` (FK to another `Server` row); `asyncssh`'s native `tunnel=` parameter does the actual chaining.

### SSH command snippets

Each user has a personal library of named commands. They appear as buttons in the terminal toolbar -- click to send `command + Enter`. Right-click to delete, `+` to create. Stored in the `snippets` table.

### Webhooks

Admins can register HTTPS endpoints that receive a JSON POST when events fire (`user_login`, `ssh_connect`, `server_added`, etc). Each webhook can subscribe to all events (`*`) or a specific subset.

```json
POST https://your-receiver.example.com/wh
Content-Type: application/json
X-Webgate-Signature: sha256=<hmac of body using your webhook's secret>

{"event": "ssh_connect", "timestamp": "2026-04-15T18:03:18Z",
 "data": {"user": "alice", "server": "prod-web-01", "host": "10.0.1.50:22"}}
```

Manage from the **Webhooks** button in the top toolbar (admin only). Last delivery status is shown next to each row.
| `WEBGATE_LOG_LEVEL` | `info` | Log level |
| `WEBGATE_SESSION_TIMEOUT` | `3600` | SSH session timeout (seconds) |
| `WEBGATE_MAX_UPLOAD_SIZE` | `104857600` | Max upload size (100 MB) |
| `WEBGATE_JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `WEBGATE_JWT_EXPIRE_MINUTES` | `1440` | Token expiry (24 hours) |
| `WEBGATE_MONITOR_INTERVAL` | `60` | Server status check interval (seconds) |
| `WEBGATE_MONITOR_TIMEOUT` | `5` | SSH connect timeout for checks (seconds) |
| `WEBGATE_MONITOR_CONCURRENCY` | `10` | Max parallel status checks |

## Docker

### Build and Run

```bash
docker compose up -d
# Login at http://localhost:8443 with admin / admin
```

### Production with TLS (Caddy reverse proxy)

```yaml
# compose.yml
services:
  webgate:
    build: .
    container_name: webgate
    restart: unless-stopped
    ports:
      - "8443:8443"
    volumes:
      - webgate-data:/data
    environment:
      WEBGATE_SECRET_KEY: "${WEBGATE_SECRET_KEY}"

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy-data:/data

volumes:
  webgate-data:
  caddy-data:
```

```
# Caddyfile
webgate.example.com {
    reverse_proxy webgate:8443
}
```

### Reverse proxy at a sub-path (e.g. `https://example.com/webgate/`)

When webgate is exposed behind an existing site under a URL prefix, set `WEBGATE_ROOT_PATH` so FastAPI and the frontend both build URLs with the prefix. The frontend derives the prefix automatically from `window.location.pathname`, but `WEBGATE_ROOT_PATH` is still needed on the backend for OpenAPI URLs.

**Docker Compose:**

```yaml
services:
  webgate:
    image: kalexnolasco/webgate:latest
    environment:
      WEBGATE_SECRET_KEY: "${WEBGATE_SECRET_KEY}"
      WEBGATE_ROOT_PATH: "/webgate"
```

> **Important:** the reverse proxy must **forward the prefix unchanged** (not strip it). Webgate receives requests as `/webgate/api/...` and handles them natively — do not rewrite them to `/api/...`.

#### nginx

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;

    ssl_certificate     /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;

    # WebSocket (xterm.js terminal) -- must come before the generic location
    location /webgate/api/ws/ {
        proxy_pass http://127.0.0.1:8443;
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host       $host;
        proxy_read_timeout 86400s;   # keep long-lived SSH sessions alive
        proxy_send_timeout 86400s;
    }

    location /webgate/ {
        proxy_pass http://127.0.0.1:8443;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Prefix /webgate;
        client_max_body_size 100m;       # match WEBGATE_MAX_UPLOAD_SIZE
    }
}
```

#### Apache 2.4

```apache
# Required modules: proxy proxy_http proxy_wstunnel headers rewrite ssl
# sudo a2enmod proxy proxy_http proxy_wstunnel headers rewrite

<VirtualHost *:443>
    ServerName example.com

    SSLEngine on
    SSLCertificateFile    /etc/ssl/certs/example.com.crt
    SSLCertificateKeyFile /etc/ssl/private/example.com.key

    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto  "https"
    RequestHeader set X-Forwarded-Prefix "/webgate"

    # Redirect /webgate -> /webgate/ (trailing slash)
    RewriteEngine On
    RewriteRule ^/webgate$ /webgate/ [R=301,L]

    # WebSocket (xterm.js terminal) -- MUST come before the HTTP ProxyPass
    ProxyPass        /webgate/api/ws/  ws://127.0.0.1:8443/webgate/api/ws/
    ProxyPassReverse /webgate/api/ws/  ws://127.0.0.1:8443/webgate/api/ws/

    # HTTP
    ProxyPass        /webgate/  http://127.0.0.1:8443/webgate/
    ProxyPassReverse /webgate/  http://127.0.0.1:8443/webgate/
</VirtualHost>
```

#### Traefik (labels)

```yaml
services:
  webgate:
    image: kalexnolasco/webgate:latest
    environment:
      WEBGATE_ROOT_PATH: "/webgate"
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.webgate.rule=Host(`example.com`) && PathPrefix(`/webgate`)"
      - "traefik.http.routers.webgate.entrypoints=websecure"
      - "traefik.http.routers.webgate.tls=true"
      - "traefik.http.services.webgate.loadbalancer.server.port=8443"
```

Traefik forwards the full path by default, so no extra middleware is needed. Long WebSocket timeouts can be tuned via `forwardingTimeouts` in the Traefik static config.

### Useful Commands

```bash
docker compose logs -f webgate    # View logs
docker compose down               # Stop (data preserved)
docker compose down -v            # Stop + delete data (fresh start)
docker compose build --no-cache   # Rebuild from scratch
```

## Development

```bash
# Install with dev dependencies
uv sync

# Run with auto-reload
uv run uvicorn webgate.app:create_app --factory --reload --host 0.0.0.0 --port 8443

# Run with demo SSH server
docker compose -f compose.dev.yml up -d

# Lint & format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Type check
uv run pyright src/

# Test
uv run pytest tests/ -v

# Test with coverage
uv run coverage run -m pytest tests/ -v && uv run coverage report
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11+, FastAPI, uvicorn, asyncssh, SQLAlchemy, aiosqlite, Pydantic v2 |
| **Auth** | JWT (python-jose), bcrypt, Fernet (cryptography), slowapi (rate limiting) |
| **Frontend** | Vanilla JS, Alpine.js, xterm.js, CodeMirror 6 |
| **Database** | SQLite (default), any SQLAlchemy-supported DB |
| **Container** | Docker, multi-stage build, python:3.13-slim |

## Security

- **Default admin password forced change** -- `admin`/`admin` is temporary, must be changed on first login
- **SSH credentials encrypted at rest** with Fernet (key derived from `WEBGATE_SECRET_KEY`)
- **JWT authentication** with configurable expiry
- **Group-based access control** -- users only see servers in their assigned groups
- **Per-server feature control** -- admin can disable SSH or SFTP independently per server
- **SFTP path restrictions** -- admin can lock SFTP to specific directories per server
- **SFTP read-only mode** -- admin can set per-server read-only flag, blocking all write operations
- **SFTP path traversal protection** (server-side normalization and validation)
- **CORS configurable** per deployment
- **No plaintext password storage** (user passwords hashed with bcrypt)
- **Admin-only server management** -- regular users cannot add, edit, or delete servers

## Roadmap

### Completed (v0.1.x)

- [x] SSH web terminal (xterm.js + asyncssh)
- [x] SFTP file browser with full CRUD
- [x] Server registry with groups and tags
- [x] In-browser text editor (CodeMirror 6)
- [x] PDF and image preview
- [x] Quick connect toolbar
- [x] Docker deployment
- [x] JWT authentication with forced password change
- [x] Fernet credential encryption
- [x] Admin user management with group-based access
- [x] SFTP connection pool (reuse connections, 5 min TTL)
- [x] Multi-tab split pane (terminal + files side by side)
- [x] SSH key management (per-server key upload with visual indicator)
- [x] File search / filter within SFTP listings
- [x] Server import/export from UI (JSON)
- [x] Session persistence across page reloads
- [x] Rate limiting on auth endpoints (slowapi)
- [x] Audit log (admin-viewable action history)
- [x] Per-server SSH/SFTP toggles (admin can enable/disable each feature)
- [x] SFTP path restrictions (admin can limit access to specific directories)

### Completed (v0.2.x)

- [x] SFTP read-only mode per server (browse and download only)
- [x] Server status monitoring (background SSH checks, green/red dot)
- [x] Dark/light theme toggle with localStorage persistence
- [x] Responsive tablet/mobile layout
- [x] Keyboard shortcuts (Escape, Ctrl+1, Ctrl+N)
- [x] Upload progress bar with percentage
- [x] Folder download as ZIP

### Planned (v0.3.x -- Collaboration & Ops)

- [ ] Shared terminal sessions (multiple users watching the same session)
- [ ] Session recording and playback (audit/training)
- [ ] SSH command snippets/macros (saved per server or global)
- [ ] Webhook/notifications on connection events
- [ ] Two-factor authentication (TOTP)
- [ ] LDAP/Active Directory integration
- [ ] API key authentication (for automation/scripts)

### Planned (v0.4.x -- Enterprise)

- [ ] PostgreSQL support (tested and documented)
- [ ] Multi-instance deployment with shared DB
- [ ] SSH jump host / bastion support (ProxyCommand equivalent)
- [ ] Custom branding (logo, colors, company name)
- [ ] Backup/restore UI for server registry
- [ ] Internationalization (i18n)

## Requirements

- Python 3.11+
- Linux, macOS, or WSL (asyncssh requires Unix-like OS)
- Target servers must have SSH enabled

## License

MIT

---

**webgate** -- Remote server management, simplified.
