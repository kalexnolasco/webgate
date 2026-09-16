# webgate

[![PyPI](https://img.shields.io/pypi/v/webgate?style=flat-square)](https://pypi.org/project/webgate/)
[![Python](https://img.shields.io/pypi/pyversions/webgate?style=flat-square)](https://pypi.org/project/webgate/)
[![License](https://img.shields.io/pypi/l/webgate?style=flat-square)](https://github.com/kalexnolasco/webgate/blob/main/LICENSE)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://hub.docker.com/r/kalexnolasco/webgate)
[![Tests](https://img.shields.io/badge/tests-248%20passing-3dcf8e?style=flat-square)](https://github.com/kalexnolasco/webgate/tree/main/tests)
[![Docs](https://img.shields.io/badge/docs-kalexnolasco.github.io-blue?style=flat-square)](https://kalexnolasco.github.io/webgate/)

Self-hosted web app for remote server management — **SSH terminal**, **SFTP file browser**, **server registry**, all in your browser. Host keys are verified, credentials are encrypted at rest, and an admin configures the whole thing from inside the app. A modern Python replacement that combines the best of [webssh](https://github.com/huashengdun/webssh) and [filebrowser](https://github.com/filebrowser/filebrowser) into a single tool. It borrows FileZilla's workflow — a site list, quick connect, a path bar — without copying its chrome: a dense, keyboard-first console meant to sit behind a terminal for hours.

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

### Upgrading

```bash
docker compose pull && docker compose up -d
```

The schema migrates itself on boot — no migration command, no tool to learn. Changes are **additive only**, so rolling back to an older image works if you need it. Back up first (`cp webgate.db webgate.db.bak`, or **Admin → Backup & restore**). Full guide: [Upgrading](docs/getting-started/upgrade.md).

> **On v0.x?** That line is **legacy and unsupported** — see [Legacy versions](#legacy-versions) before upgrading.

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
| **Audit & compliance** | Centralized access point, an audit log that names every file touched and every access change, optional asciinema session recording |
| **Multi-client / agency** | One webgate per client, isolated server registries; run lots of them cheaply |

---

## Features

| Category | Capabilities |
|---|---|
| **Terminal** | xterm.js + asyncssh, multi-tab, resize, copy/paste, **auto-reconnect** with backoff on a dropped link, **shared sessions** with one-click URL, **command snippets** — team-shared, with `{parameters}` and confirm-before-running |
| **SFTP** | Full file ops + drag & drop upload, **sortable columns**, **multi-select** with batch ZIP download and delete, hidden-file toggle, in-browser editor (CodeMirror 6), PDF/image preview |
| **Server Registry** | Groups, tags, password/key auth, encrypted at rest (Fernet), **verified host keys** (TOFU), **favourites and recents**, import/export JSON, **jump host / bastion** chaining |
| **Access Control** | Admin/user roles, per-server SSH/SFTP toggles, SFTP path restrictions, read-only SFTP mode, group-based visibility |
| **Auth** | JWT + bcrypt locally, **2FA TOTP**, **API keys** for automation, **LDAP / Active Directory** with group→role mapping |
| **Compliance** | **Session recording** to asciinema cast files with browser replay, off by default and opted into per server, **audit log** covering every SFTP operation, registry and account change, searchable by filename, **webhooks** (HMAC-signed) on key events |
| **Migration** | **Full-state backup and restore** — servers with credentials, users, groups, webhooks and API keys in one passphrase-encrypted file, portable between instances |
| **AI agent** | Per-server iterative chat over **Ollama** or **OpenRouter**, read-only inspection tools, **works on SFTP-only hosts**, cached results and searchable findings — configured in the admin panel, off until then |
| **Branding** | White-label the deployment: app name, logo, sign-in image, browser icon, company colours with a palette picker and live preview, light and dark palettes — applied for every user |
| **Monitoring** | Background SSH connectivity probes, online/offline indicator |
| **Deployment** | Multi-stage Docker image, SQLite default or PostgreSQL, runs behind any reverse proxy at any sub-path, **demo mode** for public read-only deployments |
| **UX** | **Command palette** (`Ctrl+P`), dark/light theme, responsive, vanilla JS + Alpine.js (no npm needed), session persistence across reloads |

### Keyboard

| Shortcut | Action |
|---|---|
| `Ctrl+P` / `Ctrl+Shift+P` | Command palette — fuzzy jump to any server or action |
| `Ctrl+K` | Quick Connect |
| `Ctrl+1` | Site Manager |
| `Ctrl+N` | New server (admin) |
| `Esc` | Close the palette, a dialog, or the quick-connect bar |

`Ctrl+Shift+P` reaches the palette from inside a terminal too; plain `Ctrl+P` is deliberately left alone there so readline keeps `previous-command`.

---

## Screenshots

Taken from v2.1.1. The terminal and file browser are real sessions against a live SSH
host reached through a bastion.

### Site Manager, terminal, SFTP, command palette

| | |
|---|---|
| ![Site Manager](docs/screenshots/v2/site-manager.png) | ![SSH terminal](docs/screenshots/v2/terminal.png) |
| ![SFTP browser](docs/screenshots/v2/sftp.png) | ![Command palette](docs/screenshots/v2/palette.png) |

Left to right: the registry with live status dots and grouped servers; an SSH session
opened through `bastion-eu`; the file browser with sortable columns, owner names and
multi-select; `Ctrl+P` over every server and action.

### Admin

| | |
|---|---|
| ![Settings](docs/screenshots/v2/settings.png) | ![AI agent](docs/screenshots/v2/agent.png) |
| ![Branding](docs/screenshots/v2/branding.png) | ![Users](docs/screenshots/v2/users.png) |

**Settings** shows where each value comes from — this panel, a named environment
variable, or the shipped default — and warns in red where a choice loosens something.
**AI agent** is off until a provider is configured. **Branding** white-labels the
deployment for every user.

### Light theme, and the sign-in screen

| | |
|---|---|
| ![Light theme](docs/screenshots/v2/light.png) | ![Sign in](docs/screenshots/v2/login.png) |

---

## Architecture

### Project layout

```
src/webgate/
├── __main__.py          uvicorn launcher
├── app.py               FastAPI factory, lifespan, middleware
├── config.py            boot settings (env only); the rest live in the admin panel
├── agent/               per-server AI chat: provider, tools, SFTP-only tools, cache
├── audit/               immutable action log
├── auth/                JWT + bcrypt, 2FA TOTP, API keys, LDAP, user management
├── backup/              full-state export/import, passphrase-encrypted
├── branding/            white-label store: name, logo, colours, favicon
├── db/                  async engine + additive, append-only migrations
├── files/
│   ├── sftp_service.py  SFTP operations, chunked reads, ZIP builders
│   ├── pool.py          connection reuse, 300 s TTL
│   ├── limits.py        per-request transfer budget
│   └── routes.py        REST endpoints
├── recordings/          asciinema cast v2 writer + browser replay
├── runtime_config/
│   ├── registry.py      every setting an admin may change, with its validation
│   ├── store.py         key/value rows, encrypted secrets, in-process snapshot
│   └── routes.py        /api/settings
├── servers/
│   ├── hostkeys.py      trust-on-first-use pinning and verification
│   ├── monitor.py       leader-elected status sweep
│   ├── crypto.py        Fernet credential encryption
│   └── service.py       registry CRUD, jump-host resolution
├── snippets/            per-user command library
├── terminal/
│   ├── ssh_session.py   asyncssh wrapper, optional jump tunnel
│   ├── shared.py        SharedSession registry: 1 PTY ↔ N WebSockets, idle watchdog
│   ├── ws_handler.py    input multiplex / output broadcast
│   └── routes.py        WS endpoints + share-token mint/revoke
├── webhooks/            HMAC-signed event dispatcher
└── static/index.html    single-file frontend (Alpine.js + xterm.js + CodeMirror)
```

### What talks to what

Browsers speak HTTPS and WebSocket to one address. Everything behind it — SSH, SFTP, LDAP, the model provider — is reached from the gateway, **outbound**. That is the point: in most deployments the servers have no route to the internet and the people have no route to the servers.

```mermaid
flowchart LR
  subgraph people["People"]
    B["Browser<br/>Alpine.js + xterm.js"]
  end

  subgraph gw["Gateway — the only host with both routes"]
    W["webgate<br/>FastAPI :8443"]
    DB[("SQLite or PostgreSQL<br/>credentials encrypted<br/>with Fernet")]
  end

  subgraph fleet["Internal network — no inbound internet"]
    BAS["Bastion"]
    S1["prod-web-01 :22"]
    S2["prod-db-primary :22"]
    S3["SFTP-only host"]
  end

  subgraph ext["Outbound, optional"]
    LD["LDAP / AD"]
    AI["Ollama or OpenRouter"]
    WH["Webhook receivers"]
  end

  B -->|"HTTPS + WebSocket"| W
  W --- DB
  W -->|"SSH / SFTP"| BAS
  BAS -.->|"tunnel"| S1
  BAS -.->|"tunnel"| S2
  W -->|"SFTP only"| S3
  W -->|"bind + search"| LD
  W -->|"chat completions"| AI
  W -->|"HMAC-signed POST"| WH
```

Only the gateway needs a route to the model provider — inspected hosts never do, because the agent reaches them over SSH from here. Nothing is installed on the targets: a server only has to accept SSH, and some only accept SFTP.

> 📐 **Full architecture, with five diagrams** — module map, the SSH session including the part that refuses, multi-instance topology, and how a setting resolves: **[docs/architecture.md](docs/architecture.md)** ([rendered](https://kalexnolasco.github.io/webgate/architecture/)).

### Four constraints that decided the rest

1. **The gateway is the credential store.** It is why host keys are verified before authentication, why the Fernet key stays in the environment, and why the agent's tools are read-only.
2. **Workers are interchangeable.** Nothing durable lives in memory or on a worker's disk. What stays local — pooled connections, open PTYs — is reconstructible and expected to be lost.
3. **Migrations are additive, append-only, idempotent.** No column is ever dropped or retyped, so an older release ignores what it does not know and a rollback is safe. A test enforces it.
4. **The frontend has no build step.** One HTML file. There is no compiled asset that can drift from the source it came from.

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

The owner's terminal is registered with a `SharedSession`. When the owner clicks **Share**, a token is minted and any joiner with the URL attaches a second WebSocket. There's still **one** SSH PTY — output is broadcast to all clients, input from any RW client is multiplexed into the same `stdin`.

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
| `User.is_admin` | bool | admin (Users panel) **or** an LDAP admin group | admins see everything regardless of `allowed_groups` |

**With LDAP**, the admin still controls **which group names exist** by typing them when registering each server. LDAP only populates the user side of the equation:

```mermaid
flowchart LR
    subgraph LDAP
        L1["alice ∈ cn=devs"]
        L2["alice ∈ cn=admins"]
    end
    subgraph "Group mapping<br/>(Admin → Settings → LDAP)"
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

- LDAP **does not create** groups on the webgate side. The right-hand value of the group mapping must match exactly what you typed in `Server.group`.
- An LDAP group that isn't in the map is silently ignored.
- **Admin groups** is independent of the map: any membership in those groups grants admin (and admins see all servers).
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

Most settings live in **Admin → Settings**, in the app. They take effect without a
restart and apply to every instance of the gateway, so changing a monitor interval or
pointing at a different LDAP server is not a redeploy.

The rest are environment variables prefixed with `WEBGATE_`, because they are read
before webgate can serve the request that would change them — or because letting the
panel change them would be a way to lock yourself out.

### In the admin panel

| Setting | Default | What it does |
|---|---|---|
| Verify SSH host keys | `true` | Pin each server's key on first connection and refuse a changed one. Off means the gateway hands stored credentials to whatever answers — only sensible in a throwaway lab |
| Session token lifetime | `1440` | Minutes a sign-in stays valid |
| Idle SSH timeout | `3600` | Seconds a session may sit with no input or output before it is closed. `0` disables it |
| Maximum transfer size | `104857600` | Bytes, for uploads and downloads alike. `0` removes the limit, and with it the protection against one large file exhausting the gateway |
| Disable status checks | `false` | Stop probing servers for their online/offline dot |
| Check interval / timeout / parallel checks | `60` / `5` / `10` | How the status monitor sweeps the registry |
| Allow session recording | `false` | Lets servers record SSH sessions to asciinema cast files. Each server opts in separately |
| Maximum recording size | `26214400` | Bytes per session. A recording that reaches it stops and says so inside the replay |
| LDAP (10 settings) | off | Directory URL, bind account, search bases and filters, group mapping, admin groups |

Each one shows where its current value comes from — this panel, an environment
variable, or the shipped default — and can be reset back to the environment.

An environment variable still seeds a fresh install, which is what makes automated
provisioning work; once a value is set in the panel, the panel wins. To keep
configuration entirely in your manifests, set `WEBGATE_CONFIG_LOCKED=true` and the
panel becomes read-only.

### Environment only

| Variable | Default | Description | Why not in the panel |
|---|---|---|---|
| `WEBGATE_SECRET_KEY` | *none — you must set it* | Signs session tokens and derives the Fernet key for stored credentials. **webgate refuses to start** with the shipped default on any address other than loopback | It decrypts what is in the database, so it cannot live there |
| `WEBGATE_ALLOW_INSECURE_SECRET` | `false` | Start anyway with the default key. Only sensible where nothing else can reach the machine | It is the override itself |
| `WEBGATE_DB_URL` | `sqlite+aiosqlite:///./webgate.db` | SQLAlchemy async URL. Use `postgresql+asyncpg://user:pass@host:5432/webgate` for Postgres | It is how the database is reached |
| `WEBGATE_HOST` | `0.0.0.0` | Bind address | Read before the app can serve a request |
| `WEBGATE_PORT` | `8443` | Bind port | Read before the app can serve a request |
| `WEBGATE_ROOT_PATH` | `` (empty) | URL prefix behind a reverse proxy (e.g. `/webgate`); the proxy must forward it unchanged | Routes are mounted at startup |
| `WEBGATE_LOG_LEVEL` | `info` | uvicorn log level | Read once by the server process |
| `WEBGATE_DEMO_MODE` | `false` | Read-only public demo: blocks writes, hides admin UI, seeds `demo`/`demo`, shows a banner | Enabling it from the panel would block turning it off |
| `WEBGATE_JWT_ALGORITHM` | `HS256` | JWT algorithm | One typo away from accepting unsigned tokens |
| `WEBGATE_FIRST_RUN` | `true` | Create the default `admin`/`admin` account when no users exist. Set `false` when accounts come from LDAP or a restored backup | Decided before anyone can sign in |
| `WEBGATE_CONFIG_LOCKED` | `false` | Make the settings panel read-only | It is the lock itself |
| `WEBGATE_ALLOWED_ORIGINS` | `*` | CORS origins (comma-separated) | Middleware is built at startup |
| `WEBGATE_RECORDINGS_DIR` | `./recordings` | Scratch space while a session is live; the finished cast is stored in the database so any worker can serve it | A filesystem path, not a preference |
| `WEBGATE_INSTANCE_ID` | auto | Unique per worker; a UUID is generated when empty | Identifies the process |

Every panel setting also accepts its `WEBGATE_`-prefixed variable as the initial
value: `WEBGATE_MONITOR_INTERVAL`, `WEBGATE_LDAP_URL`, and so on.

### LDAP / Active Directory

The same fields, for seeding them from the environment:

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

### Backup, restore and migration

**Admin → Backup & restore**, or the API directly. One file carries servers, users, groups,
webhooks and API keys.

```bash
# Back up, credentials included, encrypted under a passphrase you choose
curl -X POST https://gate.example.com/api/backup/export \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"passphrase":"choose-a-strong-one","include_audit":false}' \
  -o webgate-backup.json

# Restore onto another instance
curl -X POST https://new-gate.example.com/api/backup/restore \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"passphrase\":\"choose-a-strong-one\",\"mode\":\"merge\",\"data\":$(cat webgate-backup.json)}"
```

**Why the passphrase matters.** Server credentials are encrypted with a key derived from
`WEBGATE_SECRET_KEY`, so the stored ciphertext is meaningless on an instance with a
different key. A backup therefore decrypts them, and the restore re-encrypts with the
target's own key — which is what makes the file portable, and also what makes it a
credential dump. Supplying a passphrase seals the payload with PBKDF2-HMAC-SHA256
(480k iterations) + Fernet. **Without a passphrase the backup is metadata only** and you
would re-enter every credential by hand.

| | |
|---|---|
| `mode: "merge"` | Keeps what is already there; anything whose name exists is skipped |
| `mode: "replace"` | Clears servers, webhooks and API keys first |
| Users | **Never deleted by a restore** — a bad file cannot lock the operator out |
| Jump hosts | Stored **by name**, so bastion routes survive the id renumbering a new database performs |
| Session recordings | Files on disk, not database rows — copy `WEBGATE_RECORDINGS_DIR` separately |

A fresh instance blocks writes until the seeded admin password is changed, so change it
before restoring into one.

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
| **Files (SFTP)** | `GET /ls`, `GET /read`, `GET /download`, `GET /download-zip` (one directory), `POST /download-zip` (a chosen selection), `POST /upload`, `PUT /write`, `POST /mkdir`, `POST /rename`, `DELETE /delete`, `POST /chmod`, `GET /stat` (all under `/api/files/{server_id}/`) |
| **Settings** | `GET /api/settings`, `PUT /api/settings`, `POST /api/settings/reset` (admin only) |
| **Agent** | `GET/PUT /api/agent/settings`, `POST /api/agent/models`, `POST /api/agent/chat/{server_id}`, `GET/DELETE /api/agent/conversations/{server_id}`, `GET /api/agent/findings` |
| **Branding** | `GET /api/branding` (public), `PUT/DELETE /api/branding` (admin only) |
| **Backup** | `POST /api/backup/export`, `POST /api/backup/restore` (admin only) |
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

# lint — clean, and expected to stay that way
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# types — pyright runs in strict mode and does NOT pass yet (~100 findings,
# about 80 of them `reportUnknown*` where asyncssh and ldap3 ship no type
# information). Treat a change to that count as the signal, not zero.
uv run pyright src/

# build wheel
uv build
```

Every push runs the same checks in CI, plus a Docker build that has to start and answer, and a strict docs build. Cutting a release is one tag — see **[RELEASING.md](RELEASING.md)** for what that triggers and the one-time setup behind it.

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

- **Host keys are verified** — trust on first use. The first connection to a server records the key it presents; every connection after that is checked against it *before authentication runs*, so a mismatch sends nothing. Accepting a changed key is a deliberate, audited admin action. This covers the terminal, SFTP, the connection pool, the status monitor, the agent and jump hosts
- All SSH passwords and private keys are encrypted at rest with **Fernet** (key derived from `WEBGATE_SECRET_KEY`)
- **The default secret key is refused.** That key signs every session token and derives the credential encryption key, and its default is published in this repository — a deployment that never changed it will hand a valid admin token to anyone who asks. webgate now stops at startup rather than serving under it, unless it is bound to loopback only
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

## Legacy versions

**v2.x is the only supported line.** Everything before it — v0.1 through v0.5.3 — is
legacy: no fixes, no backports, and it is missing the security work v2 exists for.

| | |
|---|---|
| **Supported** | v2.x |
| **Legacy, unsupported** | v0.1.0 – v0.5.3 |

If you are running v0.x, the thing to know is that **every SSH and SFTP connection it
makes runs with host key verification disabled**. It authenticates to whatever answers
on a server's address and hands it the stored credentials. That is fixed in v2.0.0, and
it is the reason to move.

Upgrading from v0.x is the same command as any other upgrade — the schema migrates
itself, additively, and your servers, users and credentials come across untouched:

```bash
docker compose pull && docker compose up -d
```

Two things change on first boot. Existing servers have no pinned host key, so the next
connection to each one records what it presents and nothing breaks; from then on a
changed key is refused. And `WEBGATE_MAX_UPLOAD_SIZE` and `WEBGATE_SESSION_TIMEOUT`,
which v0.x accepted and ignored, now actually apply. Full detail:
[Upgrading](docs/getting-started/upgrade.md).

There is no v1.x. The jump from v0.5.3 to v2.0.0 was deliberate: the release changed
what the product is responsible for, and a minor bump would have undersold that.

---

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full plan and what's shipped per release.

## License

MIT — see [LICENSE](LICENSE).
