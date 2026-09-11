# Architecture

A self-hosted gateway that puts SSH and SFTP in a browser. One Python process holds
every credential in the fleet, so most of the design is about what that process is
allowed to do, and what happens when there is more than one of it.

| | |
|---|---|
| Backend | 8,345 lines across 66 files |
| Frontend | 3,733 lines, no build step |
| Surface | 10 REST routers + 3 WebSocket endpoints |
| Tables | 14 |
| Tests | 248 |

## What talks to what

Browsers speak HTTPS and WebSocket to one address. Everything behind it — SSH, SFTP,
LDAP, the model provider — is reached from the gateway, outbound. That is the point: in
most deployments the servers have no route to the internet and the people have no route
to the servers.

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

Only the gateway needs a route to the model provider — inspected hosts never do, because
the agent reaches them over SSH from here. Solid arrows are connections webgate opens;
the dotted ones are channels multiplexed inside a bastion connection.

!!! note "Nothing is installed on the targets"
    No agent, no daemon. A target only has to accept SSH, and some only accept SFTP —
    the AI agent carries a shell-free toolset for exactly those.

## What is inside

Each module is a router, a service and its own tables. The two shared pieces are the
session factory and the runtime settings snapshot; everything else talks through the
database.

```mermaid
flowchart TB
  subgraph edge["Edge"]
    ST["static/index.html<br/>single file, no build step"]
  end

  subgraph api["Routers"]
    AU["/api/auth<br/>JWT, TOTP, API keys, LDAP"]
    SV["/api/servers<br/>registry, host keys"]
    TE["WS /api/ws/terminal<br/>own, quick, join"]
    FI["/api/files<br/>SFTP + transfer budget"]
    AG["/api/agent<br/>per-server chat"]
    SE["/api/settings<br/>admin panel"]
    BR["/api/branding"]
    BK["/api/backup"]
    RE["/api/recordings"]
    SN["/api/snippets"]
    WH["/api/webhooks"]
  end

  subgraph core["Shared"]
    HK["servers/hostkeys<br/>trust on first use"]
    PO["files/pool<br/>SFTP reuse, 300 s"]
    SH["terminal/shared<br/>one PTY, N sockets"]
    MO["servers/monitor<br/>leader-elected sweep"]
    RC["runtime_config<br/>settings snapshot"]
    AUD["audit"]
  end

  DB[("14 tables<br/>servers · users · api_keys<br/>settings · branding · audit_log<br/>agent_* · recordings · snippets<br/>webhooks · schema_migrations<br/>monitor_lease")]

  ST --> AU & SV & TE & FI & AG & SE
  TE --> SH
  FI --> PO
  SV --> MO
  SH --> HK
  PO --> HK
  MO --> HK
  AG --> HK
  RC -.->|"read by"| HK & FI & MO & SH & AU
  AU & SV & FI & AG & SE & BR & BK & RE & SN & WH --> DB
  AUD --> DB
  RC --> DB
```

`hostkeys` and `runtime_config` are the two things almost everything depends on: one
decides whether a connection is allowed to proceed, the other supplies the values it is
judged against.

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
│   ├── shared.py        SharedSession registry: 1 PTY <-> N WebSockets, idle watchdog
│   ├── ws_handler.py    input multiplex / output broadcast
│   └── routes.py        WS endpoints + share-token mint/revoke
├── webhooks/            HMAC-signed event dispatcher
└── static/index.html    single-file frontend (Alpine.js + xterm.js + CodeMirror)
```

## What happens on one request

The host key is checked before authentication runs, so a server presenting the wrong key
never receives the credentials. Everything after that is a pump between one WebSocket and
one PTY.

```mermaid
sequenceDiagram
  autonumber
  participant B as Browser
  participant G as Gateway
  participant D as Database
  participant H as Target host

  B->>G: WS /api/ws/terminal/{server_id}
  G->>G: verify JWT from the first frame
  G->>D: load server + decrypt credentials
  D-->>G: row, incl. pinned host key

  alt A key is pinned
    G->>H: TCP, then key exchange
    H-->>G: presents its host key
    G->>G: compare with the pin
    Note over G,H: A mismatch stops here.<br/>Nothing is sent.
  else First contact
    G->>H: TCP, then key exchange
    G->>D: pin what it presented
  end

  G->>H: authenticate, open PTY
  H-->>G: shell
  G-->>B: {"type":"session","session_id":...}

  loop While either side has something to say
    B->>G: keystrokes
    G->>H: write
    H-->>G: output
    G-->>B: broadcast to every participant
  end

  Note over G: A watchdog closes the session<br/>once idle past session_timeout.<br/>Output counts as activity.
```

A share token turns the same session into a multi-participant one: joiners attach to the
existing PTY read loop rather than opening a second connection, so what everyone sees is
the same stream.

Host keys are exposed as fingerprints (`SHA256:LRG8dl…`), never as the key itself, and
clearing a pin is an admin-only, audited action. **Seven paths verify**: terminal, SFTP
browser, SFTP pool, status monitor, connection test, agent, and jump hosts — the bastion
most of all, since everything behind it rides that one connection.

## What happens with more than one

Any worker can serve any request. The two things that must not happen N times — sweeping
the fleet for status, and holding the truth about configuration — are handled by a lease
and by a re-read.

```mermaid
flowchart TB
  LB["nginx :8443<br/>sticky by WebSocket"]

  subgraph w1["webgate-1 — leader"]
    L1["SFTP pool · open PTYs<br/>settings snapshot"]
    M1["monitor sweep"]
  end

  subgraph w2["webgate-2 — follower"]
    L2["SFTP pool · open PTYs<br/>settings snapshot"]
    M2["idle, retrying for the lease"]
  end

  PG[("PostgreSQL<br/>every row both workers share")]

  LB --> w1
  LB --> w2
  w1 --> PG
  w2 --> PG
  M1 -->|"renew every 30 s"| PG
  M2 -.->|"claim if the lease expires"| PG
  L1 -.->|"re-read every 15 s"| PG
  L2 -.->|"re-read every 15 s"| PG
```

The lease outlives a full sweep by design — raise the check interval in the panel and the
lease stretches with it, or the leader would drop its own lease mid-sweep. Open sessions
and pooled SFTP connections are per-worker and do not survive one being replaced, which
is why rollouts go one worker at a time.

See [HA deployment](guide/ha.md) for the compose file and the nginx config.

## Where a setting's value comes from

Configuration is stored as key/value, so adding a setting needs no migration. Reads are
synchronous against an in-process snapshot, because they sit on paths like *is this
upload too big* that run per request.

```mermaid
flowchart LR
  ENV["WEBGATE_* variable<br/>or shipped default"]
  PANEL["Admin → Settings<br/>validated by the registry"]
  ROW[("settings table<br/>secrets encrypted")]
  SNAP["snapshot in each worker"]
  READ["hostkeys · limits · monitor<br/>idle watchdog · ldap · jwt"]

  ENV -->|"seeds a fresh install"| SNAP
  PANEL -->|"admin writes"| ROW
  ROW -->|"wins over the environment"| SNAP
  ROW -.->|"every 15 s, on every worker"| SNAP
  SNAP -->|"get(key), synchronous"| READ
```

`WEBGATE_CONFIG_LOCKED=true` removes the middle arrow: values stay visible so an operator
can see what is in force, but only the deployment can change them. Full detail in
[Settings](guide/settings.md).

## Why it is shaped this way

Four constraints decided most of the rest.

**1. The gateway is the credential store.** Every design question resolves against this.
It is why host keys are verified before authentication, why the Fernet key stays in the
environment, and why the agent's tools are read-only.

**2. Workers are interchangeable.** Nothing durable may live in memory or on a worker's
disk. State goes to the database; what stays local — pooled connections, open PTYs — is
reconstructible and expected to be lost.

**3. Migrations are additive, append-only, idempotent.** No column is ever dropped or
retyped, so an older release ignores what it does not know and a rollback is safe. The
contract is enforced by a test that upgrades an aged database and compares it against a
fresh install. See [Upgrading](getting-started/upgrade.md).

**4. The frontend has no build step.** One HTML file, Alpine and xterm from a CDN.
Cloning the repo and running it is the whole setup, and there is no compiled asset that
can drift from the source it came from.
