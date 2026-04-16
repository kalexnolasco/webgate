# webgate

[![PyPI](https://img.shields.io/pypi/v/webgate?style=flat-square)](https://pypi.org/project/webgate/)
[![Python](https://img.shields.io/pypi/pyversions/webgate?style=flat-square)](https://pypi.org/project/webgate/)
[![License](https://img.shields.io/pypi/l/webgate?style=flat-square)](https://github.com/kalexnolasco/webgate/blob/main/LICENSE)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://hub.docker.com/r/kalexnolasco/webgate)
[![Status](https://img.shields.io/badge/status-beta-orange?style=flat-square)](https://pypi.org/project/webgate/)
[![Docs](https://img.shields.io/badge/docs-kalexnolasco.github.io-blue?style=flat-square)](https://kalexnolasco.github.io/webgate/)

Self-hosted web app for remote server management — **SSH terminal**, **SFTP file browser**, **server registry**, all in your browser. A modern Python replacement that combines the best of [webssh](https://github.com/huashengdun/webssh) and [filebrowser](https://github.com/filebrowser/filebrowser) into a single tool with a FileZilla-inspired interface.

> 🎮 **Try it live: [webgate-demo.fly.dev](https://webgate-demo.fly.dev/)** — login `demo` / `demo` (read-only sandbox, resets hourly)
>
> 📖 **Docs: [kalexnolasco.github.io/webgate](https://kalexnolasco.github.io/webgate/)**

---

## Quick start

```bash
export WEBGATE_SECRET_KEY=$(openssl rand -hex 32)
docker compose up -d
# open http://localhost:8443/ — login: admin / admin
```

That's it. The first login forces a password change. Add servers from the **Site Manager**, click **SSH** or **SFTP** to connect.

For a richer dev environment with a sandboxed SSH target pre-baked: `docker compose -f compose.dev.yml up --build`.

> 🧪 **Want to try every feature end-to-end?** A ready-to-run playground brings up webgate **plus** an LDAP server, a public SSH host, a private SSH host only reachable via a bastion, and an HTTP echo for webhooks:
>
> ```bash
> docker compose -f compose.playground.yml up -d --build
> ```
>
> Full walkthrough with screenshots: [docs/LOCAL_TESTING.md](docs/LOCAL_TESTING.md).

---

## Why webgate?

Managing remote servers means juggling SSH clients, SFTP tools, credentials and VPN configs across your team. In many real-world setups **direct SSH access to every server isn't possible** — only HTTP(S) reaches the gateway.

### The problem

```mermaid
flowchart TB
    subgraph internet ["Internet"]
        YOU["Your Team"]
    end
    subgraph firewall ["Client Firewall"]
        GW["Gateway Server<br/>(HTTP only)"]
        subgraph internal ["Internal Network"]
            DB1[(PostgreSQL<br/>10.0.1.10)]
            DB2[(MySQL<br/>10.0.1.11)]
            APP1["App Server<br/>10.0.1.20"]
            APP2["App Server<br/>10.0.1.21"]
            WORKER["Worker<br/>10.0.1.30"]
            REDIS["Redis<br/>10.0.1.40"]
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

Deploy webgate on the gateway. Everyone gets browser-based SSH and SFTP to every internal server — no VPN, no scattered SSH keys, full audit trail.

```mermaid
flowchart TB
    subgraph internet ["Internet"]
        ENG1["Engineer 1<br/>(Browser)"]
        ENG2["Engineer 2<br/>(Browser)"]
        ENG3["Engineer 3<br/>(Browser)"]
    end
    subgraph firewall ["Client Firewall"]
        WG["webgate<br/>Gateway Server :443"]
        subgraph internal ["Internal Network"]
            DB1[(PostgreSQL)]
            APP1["App Server"]
            WORKER["Worker"]
            REDIS["Redis"]
        end
    end
    ENG1 -- "HTTPS" --> WG
    ENG2 -- "HTTPS" --> WG
    ENG3 -- "HTTPS" --> WG
    WG -- "SSH/SFTP" --> DB1
    WG -- "SSH/SFTP" --> APP1
    WG -- "SSH/SFTP" --> WORKER
    WG -- "SSH/SFTP" --> REDIS
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
|---|---|
| **Restricted client networks** | Only the gateway is HTTP-reachable; webgate proxies SSH/SFTP from there |
| **On-call / incident response** | Open a browser anywhere, no laptop with keys needed; share the live session for pair-debugging |
| **Team onboarding** | Admin creates a user, assigns groups; new engineer has access in seconds |
| **Audit & compliance** | Centralized access point, structured audit log, optional asciinema session recording |
| **Multi-client / agency** | One webgate per client, isolated server registries; run lots of them cheaply |

---

## Features

| Category | Capabilities |
|---|---|
| **Terminal** | xterm.js + asyncssh, multi-tab, resize, copy/paste, **shared sessions** with one-click URL, **command snippets** library |
| **SFTP** | Full file ops + drag & drop upload, ZIP folder download, in-browser editor (CodeMirror 6), PDF/image preview |
| **Server Registry** | Groups, tags, password/key auth, encrypted at rest (Fernet), import/export JSON, **jump host / bastion** chaining |
| **Access Control** | Admin/user roles, per-server SSH/SFTP toggles, SFTP path restrictions, read-only SFTP mode, group-based visibility |
| **Auth** | JWT + bcrypt locally, **2FA TOTP**, **API keys** for automation, **LDAP / Active Directory** with group→role mapping |
| **Compliance** | **Session recording** to asciinema cast files with browser replay, structured **audit log**, **webhooks** (HMAC-signed) on key events |
| **Monitoring** | Background SSH connectivity probes, online/offline indicator |
| **Deployment** | Multi-stage Docker image, SQLite default or PostgreSQL, runs behind any reverse proxy at any sub-path, **demo mode** for public read-only deployments |
| **UX** | Dark/light theme, responsive, keyboard shortcuts, vanilla JS + Alpine.js (no npm needed), session persistence across reloads |

---

## Screenshots

### Core (Site Manager, terminal, SFTP, editor)

| | |
|---|---|
| ![Login](docs/screenshots/login.png) | ![Site Manager](docs/screenshots/site-manager.png) |
| ![SSH Terminal](docs/screenshots/terminal.png) | ![SFTP Browser](docs/screenshots/sftp.png) |
| ![Editor](docs/screenshots/editor.png) | ![Split View](docs/screenshots/split-view.png) |

### Access control & admin

| | |
|---|---|
| ![Access Control](docs/screenshots/access-control.png) | ![Users](docs/screenshots/users.png) |
| ![Audit](docs/screenshots/audit.png) | ![Light Theme](docs/screenshots/light-theme.png) |

### Jump host, snippets, webhooks

| | |
|---|---|
| ![Dashboard with jump host](docs/screenshots/v0.3/02-dashboard-jump-host.png) | ![Add Server with Jump Via](docs/screenshots/v0.3/08-add-server-jump-via.png) |
| ![Terminal snippets](docs/screenshots/v0.3/03-terminal-snippets-jump.png) | ![Snippet executed](docs/screenshots/v0.3/04-snippet-executed.png) |
| ![SFTP via jump](docs/screenshots/v0.3/05-sftp-via-jump.png) | ![Webhooks modal](docs/screenshots/v0.3/06-webhooks-modal.png) |

### Shared terminal sessions

Click **🔗 Share** in the terminal toolbar to get a URL; anyone who opens it joins the same live SSH session (broadcast output, multiplexed input).

| Owner | Joiner |
|---|---|
| ![Shared owner](docs/screenshots/v0.4/01-shared-terminal-owner.png) | ![Shared joiner](docs/screenshots/v0.4/02-shared-terminal-joiner.png) |

### Session recording

Enable `WEBGATE_RECORD_SESSIONS=true` and every SSH session is captured to an asciinema cast file with built-in browser replay.

| Recordings list | Browser replay |
|---|---|
| ![Recordings](docs/screenshots/v0.4/04-recordings-modal.png) | ![Replay](docs/screenshots/v0.4/03-recording-replay.png) |

### Public read-only demo mode

`WEBGATE_DEMO_MODE=true` turns the app into a sandbox: banner, seeded `demo`/`demo` user, all writes blocked. Used by the live demo at [webgate-demo.fly.dev](https://webgate-demo.fly.dev/).

![Demo banner](docs/screenshots/v0.3/01-login-demo-banner.png)

---

## Architecture

### Project layout

```
src/webgate/
├── __main__.py          uvicorn launcher
├── app.py               FastAPI factory, lifespan, middleware
├── config.py            Pydantic Settings
├── auth/                JWT + bcrypt, 2FA TOTP, API keys, LDAP, user mgmt
├── audit/               Immutable action log
├── servers/             Registry CRUD, jump-host resolution, Fernet crypto
├── terminal/
│   ├── ssh_session.py   asyncssh wrapper (with optional jump tunnel)
│   ├── shared.py        SharedSession registry: 1 PTY ↔ N WebSockets
│   ├── ws_handler.py    WS bridge: input multiplex / output broadcast
│   └── routes.py        WS endpoints + share-token mint/revoke
├── files/               SFTP service + connection pool (5 min TTL)
├── snippets/            Per-user command library
├── webhooks/            HMAC-signed event dispatcher
├── recordings/          asciinema cast v2 writer + browser replay
├── db/                  SQLAlchemy async engine + dialect-aware migrations
└── static/index.html    Single-file frontend (Alpine.js + xterm.js + CodeMirror)
```

### Request lifecycle

```mermaid
flowchart LR
    Browser["Browser<br/>(Alpine + xterm.js + CodeMirror)"]
    subgraph webgate ["webgate (FastAPI)"]
        AUTH["JWT / API key / LDAP"]
        REST["REST routes"]
        WS["WebSocket handler"]
        POOL["SFTP pool<br/>(5 min TTL)"]
        SHARED["SharedSession<br/>registry"]
        REC["CastRecorder"]
        DB[("DB<br/>SQLite / PostgreSQL")]
    end
    SSH(["asyncssh"])
    REMOTE["Remote server"]

    Browser <-- "HTTPS / WSS" --> AUTH
    AUTH --> REST
    AUTH --> WS
    REST --> POOL
    REST --> DB
    WS --> SHARED
    SHARED -. write .-> REC
    SHARED --> SSH
    POOL --> SSH
    SSH --> REMOTE

    style Browser fill:#e8f0fe,stroke:#4a90d9
    style webgate fill:#f0f9e8,stroke:#5cb85c
    style REMOTE fill:#fff3e0,stroke:#ff9800
```

### Jump host (bastion) chaining

When a server has `jump_via_id` set, webgate opens the SSH connection to the bastion first and tunnels the target connection through it. Same chain is used for the SFTP browser. No VPN required, only outbound SSH from the gateway to the bastion.

```mermaid
flowchart LR
    B["Browser"]
    WG["webgate"]
    BAST["bastion<br/>10.0.0.1"]
    INT["internal-app<br/>10.0.1.50"]
    B -- "HTTPS / WSS" --> WG
    WG -- "SSH" --> BAST
    BAST -- "SSH (tunneled)" --> INT
    style B fill:#4a90d9,stroke:#2a6cb5,color:#fff
    style WG fill:#5cb85c,stroke:#449d44,color:#fff
    style BAST fill:#ffcc02,stroke:#e6a800,color:#333
    style INT fill:#fff3e0,stroke:#ff9800
```

### Shared terminal session

The owner's terminal is registered with a `SharedSession`. When the owner clicks **🔗 Share**, a token is minted and any joiner with the URL attaches a second WebSocket. There's still **one** SSH PTY — output is broadcast to all clients, input from any RW client is multiplexed into the same `stdin`.

```mermaid
flowchart LR
    O["Owner WS"]
    J1["Joiner WS (rw)"]
    J2["Joiner WS (ro)"]
    SS["SharedSession"]
    PTY["asyncssh PTY"]
    REMOTE["Remote SSH server"]
    REC["CastRecorder<br/>(if recording on)"]

    O -- "input" --> SS
    J1 -- "input" --> SS
    J2 -. "no input" .-> SS
    SS -- "write stdin" --> PTY
    PTY -- "stdout" --> SS
    SS -- "broadcast" --> O
    SS -- "broadcast" --> J1
    SS -- "broadcast" --> J2
    SS -. "tee" .-> REC
    PTY <--> REMOTE

    style SS fill:#5cb85c,stroke:#449d44,color:#fff
    style PTY fill:#ffcc02,stroke:#e6a800,color:#333
    style REC fill:#a78bfa,stroke:#7c3aed,color:#fff
```

### Access model — groups, tags, LDAP

Three concepts, easy to mix up. Here's how they fit together:

| Concept | Type | Defined by | What it does |
|---|---|---|---|
| `Server.group` | single string per server (e.g. `production`) | admin, in the Add Server form | gates **visibility**: a non-admin user only sees servers whose `group` is in their `allowed_groups` |
| `Server.tags` | list of strings (e.g. `["nginx","eu-west-1"]`) | admin, in the Add Server form | **cosmetic / search only** — does **not** affect access |
| `User.allowed_groups` | list of strings | admin (Users panel) **or** LDAP mapping | the set of `Server.group` values a non-admin user is allowed to see |
| `User.is_admin` | bool | admin (Users panel) **or** LDAP `WEBGATE_LDAP_ADMIN_GROUPS` | admins see everything regardless of `allowed_groups` |

**With LDAP**, the admin still controls **which group names exist** by typing them when registering each server. LDAP only populates the user side of the equation:

```mermaid
flowchart LR
    subgraph LDAP
        L1["alice ∈ cn=devs"]
        L2["alice ∈ cn=admins"]
    end
    subgraph "WEBGATE_LDAP_GROUP_MAP<br/>(env var)"
        M["{<br/>  &quot;devs&quot;: &quot;production&quot;,<br/>  &quot;sre&quot;: &quot;all&quot;<br/>}"]
    end
    subgraph User
        U["alice.allowed_groups<br/>= [&quot;production&quot;]"]
    end
    subgraph Servers
        S1["app-1<br/>group=production ✅"]
        S2["app-2<br/>group=staging ❌"]
        S3["db-1<br/>group=production ✅"]
    end
    L1 -- mapped --> M
    L2 -. ignored<br/>(not in map) .-> M
    M --> U
    U --> S1
    U --> S3
```

Key rules:

- LDAP **does not create** groups on the webgate side. The right-hand value of `WEBGATE_LDAP_GROUP_MAP` must match exactly what you typed in `Server.group`.
- An LDAP group that isn't in the map is silently ignored.
- `WEBGATE_LDAP_ADMIN_GROUPS` is independent of the map: any membership in those groups grants admin (and admins see all servers).
- **Tags** are never used for access control, only for filtering / search in the UI.

### LDAP authentication

Search-then-bind: webgate binds as the service account, finds the user DN, re-binds as the user with their password to verify credentials, then enumerates LDAP groups and maps them to webgate groups (and admin status).

```mermaid
sequenceDiagram
    participant Browser
    participant webgate
    participant LDAP

    Browser->>webgate: POST /api/auth/login (alice, ****)
    webgate->>webgate: try local password (miss)
    webgate->>LDAP: bind(svc-DN, svc-password)
    LDAP-->>webgate: ok
    webgate->>LDAP: search(uid=alice) under user_base
    LDAP-->>webgate: dn=uid=alice,ou=people,...
    webgate->>LDAP: re-bind(user-DN, user-password)
    LDAP-->>webgate: ok ✅
    webgate->>LDAP: search(member=user-DN) under group_base
    LDAP-->>webgate: [devs, admins]
    webgate->>webgate: map → allowed_groups, is_admin
    webgate->>webgate: upsert local User row
    webgate-->>Browser: JWT
```

---

## Configuration

All settings are environment variables prefixed with `WEBGATE_`.

### Core

| Variable | Default | Description |
|---|---|---|
| `WEBGATE_SECRET_KEY` | `change-me-in-production` | JWT signing + Fernet credential encryption (set this!) |
| `WEBGATE_HOST` | `0.0.0.0` | Bind address |
| `WEBGATE_PORT` | `8443` | Bind port |
| `WEBGATE_LOG_LEVEL` | `info` | uvicorn log level |
| `WEBGATE_FIRST_RUN` | `true` | Allow first-user auto-creation as admin |

### Database

| Variable | Default | Description |
|---|---|---|
| `WEBGATE_DB_URL` | `sqlite+aiosqlite:///./webgate.db` | SQLAlchemy async URL. Use `postgresql+asyncpg://user:pass@host:5432/webgate` for Postgres |

### Sessions, JWT, monitoring

| Variable | Default | Description |
|---|---|---|
| `WEBGATE_SESSION_TIMEOUT` | `3600` | SSH session idle timeout (seconds) |
| `WEBGATE_MAX_UPLOAD_SIZE` | `104857600` | Max upload size (100 MB) |
| `WEBGATE_JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `WEBGATE_JWT_EXPIRE_MINUTES` | `1440` | Token expiry (24 h) |
| `WEBGATE_MONITOR_INTERVAL` | `60` | Server status check interval (s) |
| `WEBGATE_MONITOR_TIMEOUT` | `5` | SSH connect timeout for status checks (s) |
| `WEBGATE_MONITOR_CONCURRENCY` | `10` | Max parallel status checks |
| `WEBGATE_ALLOWED_ORIGINS` | `*` | CORS origins (comma-separated) |

### Reverse proxy & demo mode

| Variable | Default | Description |
|---|---|---|
| `WEBGATE_ROOT_PATH` | `` (empty) | URL prefix when served behind a sub-path (e.g. `/webgate`). The proxy must forward the prefix unchanged |
| `WEBGATE_DEMO_MODE` | `false` | Read-only public demo: blocks writes, hides admin UI, seeds `demo`/`demo` user, shows top banner |

### Session recording (asciinema)

| Variable | Default | Description |
|---|---|---|
| `WEBGATE_RECORD_SESSIONS` | `false` | Capture every terminal session to a cast v2 file |
| `WEBGATE_RECORDINGS_DIR` | `./recordings` | Storage directory for `.cast` files |

### LDAP / Active Directory

| Variable | Default | Description |
|---|---|---|
| `WEBGATE_LDAP_ENABLED` | `false` | Enable LDAP fallback after local credential check |
| `WEBGATE_LDAP_URL` | `` | `ldap://host:389` or `ldaps://host:636` |
| `WEBGATE_LDAP_BIND_DN` | `` | Service account DN, e.g. `cn=admin,dc=example,dc=com` |
| `WEBGATE_LDAP_BIND_PASSWORD` | `` | Service account password |
| `WEBGATE_LDAP_USER_BASE` | `` | e.g. `ou=people,dc=example,dc=com` |
| `WEBGATE_LDAP_USER_FILTER` | `(uid={username})` | AD: `(sAMAccountName={username})` |
| `WEBGATE_LDAP_GROUP_BASE` | `` | e.g. `ou=groups,dc=example,dc=com` (empty = no group lookup) |
| `WEBGATE_LDAP_GROUP_FILTER` | `(member={dn})` | AD nested: `(member:1.2.840.113556.1.4.1941:={dn})` |
| `WEBGATE_LDAP_GROUP_MAP` | `{}` | JSON `{"ldap-cn":"webgate-group"}` |
| `WEBGATE_LDAP_ADMIN_GROUPS` | `[]` | JSON list of LDAP CNs that grant admin |

---

## Deployment

### Production with Docker

```bash
export WEBGATE_SECRET_KEY=$(openssl rand -hex 32)
docker compose up -d
```

The default [`compose.yml`](compose.yml) pulls `kalexnolasco/webgate:latest`, persists state in a named volume, and lists the optional features as commented env vars you can opt into.

### Behind a reverse proxy with TLS

#### Caddy (simplest)

```yaml
# add to compose.yml
caddy:
  image: caddy:2-alpine
  restart: unless-stopped
  ports: ["443:443", "80:80"]
  volumes:
    - ./Caddyfile:/etc/caddy/Caddyfile
    - caddy-data:/data
```
```caddy
# Caddyfile
webgate.example.com {
    reverse_proxy webgate:8443
}
```

#### nginx (sub-path `/webgate/`)

Set `WEBGATE_ROOT_PATH=/webgate` on the container, then:

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;
    ssl_certificate     /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;

    # WebSocket — must come before the generic location
    location /webgate/api/ws/ {
        proxy_pass http://127.0.0.1:8443;
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host       $host;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
    location /webgate/ {
        proxy_pass http://127.0.0.1:8443;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Prefix /webgate;
        client_max_body_size 100m;
    }
}
```

#### Apache 2.4 (sub-path `/webgate/`)

```apache
# Required modules: proxy proxy_http proxy_wstunnel headers rewrite ssl
RewriteEngine On
RewriteRule ^/webgate$ /webgate/ [R=301,L]

ProxyPreserveHost On
RequestHeader set X-Forwarded-Proto  "https"
RequestHeader set X-Forwarded-Prefix "/webgate"

ProxyPass        /webgate/api/ws/  ws://127.0.0.1:8443/webgate/api/ws/
ProxyPassReverse /webgate/api/ws/  ws://127.0.0.1:8443/webgate/api/ws/
ProxyPass        /webgate/  http://127.0.0.1:8443/webgate/
ProxyPassReverse /webgate/  http://127.0.0.1:8443/webgate/
```

> ⚠️ The proxy must **forward the prefix unchanged** — webgate handles `/webgate/api/...` natively, do not strip it.

#### Traefik (Docker labels)

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.webgate.rule=Host(`example.com`) && PathPrefix(`/webgate`)"
  - "traefik.http.routers.webgate.entrypoints=websecure"
  - "traefik.http.routers.webgate.tls=true"
  - "traefik.http.services.webgate.loadbalancer.server.port=8443"
```

### Multi-instance HA (N replicas + PostgreSQL)

Run multiple webgate workers behind a load balancer, all sharing one Postgres database. Only one worker probes server connectivity at a time (leader election via a singleton lease row); the rest handle REST/WS traffic normally.

```mermaid
flowchart LR
    U["Users"]
    LB["Load balancer<br/>(sticky: ip_hash)"]
    W1["webgate #1<br/>(leader)"]
    W2["webgate #2<br/>(follower)"]
    W3["webgate #3<br/>(follower)"]
    PG[(PostgreSQL<br/>shared state)]
    LEASE[["monitor_lease<br/>(singleton row)"]]
    U --> LB
    LB --> W1
    LB --> W2
    LB --> W3
    W1 --> PG
    W2 --> PG
    W3 --> PG
    W1 -- holds --> LEASE
    W2 -. watches .-> LEASE
    W3 -. watches .-> LEASE
    style LB fill:#ffcc02,stroke:#e6a800,color:#333
    style W1 fill:#5cb85c,stroke:#449d44,color:#fff
    style W2 fill:#e8f0fe,stroke:#4a90d9
    style W3 fill:#e8f0fe,stroke:#4a90d9
    style PG fill:#fff3e0,stroke:#ff9800
```

Reference stack:

```bash
export WEBGATE_SECRET_KEY=$(openssl rand -hex 32)
docker compose -f compose.ha.yml up -d
curl -s http://localhost:8443/api/health   # shows instance_id + monitor_role
```

[`compose.ha.yml`](compose.ha.yml) spins up 2 webgate replicas + Postgres + nginx with `ip_hash` sticky sessions. On leader loss, the lease expires within 90 seconds and another replica picks it up automatically.

> **Known limitation**: live shared-terminal sessions still need owner and joiner on the same worker. Sticky sessions mitigate it for same-browser joins; true cross-worker fan-out requires a Redis pub/sub layer (not yet implemented).

### Public read-only demo (Fly.io)

The repo includes [`Dockerfile.demo`](Dockerfile.demo) (webgate + sandboxed sshd via supervisord) and [`fly.toml`](fly.toml). Deploy:

```bash
flyctl launch --no-deploy --copy-config
flyctl secrets set WEBGATE_SECRET_KEY=$(openssl rand -hex 32)
flyctl volumes create webgate_demo_data --size 1 --region cdg
flyctl deploy
```

The demo middleware blocks all writes on `/api/*` (login, terminal share and totp/verify whitelisted), so anyone hitting the URL can browse the seeded `bastion` + `internal-app` pair without poking holes in your infra. The official live demo at https://webgate-demo.fly.dev runs exactly this.

---

## API reference

| Group | Methods (summary) |
|---|---|
| **Auth** | `POST /api/auth/login`, `GET /api/auth/me`, `POST/PUT /api/auth/users/...`, `POST /api/auth/totp/setup`, `GET/POST/DELETE /api/auth/api-keys`, `GET /api/auth/audit` |
| **Servers** | `GET/POST/PUT/DELETE /api/servers`, `POST /api/servers/{id}/test`, `GET /api/servers/groups`, `POST /api/servers/import`, `GET /api/servers/export`, `GET /api/servers/status` |
| **Terminal** | `WS /api/ws/terminal/{server_id}` (owner), `WS /api/ws/terminal/quick` (one-off), `WS /api/ws/terminal/join/{token}?mode=rw\|ro` (joiner), `POST/DELETE /api/terminal/share/{session_id}` |
| **Files (SFTP)** | `GET /ls`, `GET /read`, `GET /download`, `GET /download-zip`, `POST /upload`, `PUT /write`, `POST /mkdir`, `POST /rename`, `DELETE /delete`, `POST /chmod`, `GET /stat` (all under `/api/files/{server_id}/`) |
| **Snippets** | `GET/POST /api/snippets`, `DELETE /api/snippets/{id}` |
| **Webhooks** | `GET/POST /api/webhooks`, `PUT/DELETE /api/webhooks/{id}`, `POST /api/webhooks/{id}/test`, `GET /api/webhooks/events` |
| **Recordings** | `GET /api/recordings`, `GET /api/recordings/{id}/download`, `GET /api/recordings/{id}/play`, `GET /api/recordings/{id}/cast`, `DELETE /api/recordings/{id}` |
| **Health / Config** | `GET /api/health`, `GET /api/config` (public — exposes `demo_mode` to the frontend) |

Full OpenAPI is auto-generated at `/docs` (Swagger UI) and `/redoc`.

---

## Development

```bash
uv sync --all-extras --dev          # install
uv run python -m webgate            # run
uv run uvicorn webgate.app:create_app --factory --reload --host 0.0.0.0 --port 8443

# tests
uv run pytest tests/ -v
uv run pytest tests/ -v --cov=webgate

# lint + types
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run pyright src/

# build wheel
uv build
```

Or use the dev compose with a sandboxed SSH target ready to register:

```bash
docker compose -f compose.dev.yml up --build
# Inside the UI register: hostname=ssh-demo  user=demo  password=demo
```

---

## Tech stack

- **Backend:** Python 3.11+, FastAPI, uvicorn, asyncssh, SQLAlchemy 2 async, aiosqlite/asyncpg, Pydantic v2, slowapi, ldap3, pyotp, httpx
- **Frontend:** Alpine.js, xterm.js, CodeMirror 6, vanilla CSS (no build step)
- **Storage:** SQLite by default, PostgreSQL via `WEBGATE_DB_URL`. Credentials encrypted at rest with Fernet
- **Recording:** asciinema cast v2 (JSON Lines), replay via embedded asciinema-player from CDN
- **Build/Dev:** uv, ruff, pyright, pytest, Docker (multi-stage)

## Security

- All SSH passwords and private keys are encrypted at rest with **Fernet** (key derived from `WEBGATE_SECRET_KEY`)
- Passwords use **bcrypt**; sessions use **JWT** (HS256)
- **2FA TOTP** available per user
- **API keys** for non-interactive auth (`Authorization: Bearer wg_…`)
- **Rate limiting** on auth endpoints (slowapi)
- **Path traversal** validation on every SFTP operation
- **Per-server access control** — admins can disable SSH or SFTP independently, restrict SFTP to allow-listed paths, mark SFTP read-only
- **Group-based visibility** — non-admin users only see servers in their assigned groups
- **HMAC-signed webhooks** so receivers can verify the payload came from your webgate
- **Recommended:** put webgate behind a TLS-terminating reverse proxy (Caddy/nginx/Traefik) in production

## Requirements

- Python 3.11+ (or just Docker)
- 256 MB RAM minimum (512 MB recommended)
- ~100 MB disk for the image plus your data (DB + uploaded SSH keys + recordings)

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full plan and what's shipped per release.

## License

MIT — see [LICENSE](LICENSE).
