# Roadmap

Tracks the development plan for **webgate**. Items are organized by release.

> 📦 Latest release: see [GitHub Releases](https://github.com/kalexnolasco/webgate/releases) · [PyPI](https://pypi.org/project/webgate/) · [Docker Hub](https://hub.docker.com/r/kalexnolasco/webgate)

---

## Shipped

### v0.1.x — Foundation (2026-04-08)
- [x] SSH web terminal (xterm.js + asyncssh WebSocket bridge)
- [x] SFTP file browser (ls, upload, download, rename, delete, mkdir, chmod)
- [x] In-browser text editor (CodeMirror 6) + PDF/image preview
- [x] Server registry with groups, tags, encrypted credentials (Fernet)
- [x] Quick Connect for one-off SSH connections
- [x] Admin/user role system with group-based access control
- [x] Forced password change on first login
- [x] User management panel (create, delete, assign groups)
- [x] Multi-tab + split pane (terminal + file browser side by side)
- [x] SSH key management (per-server upload + visual indicator)
- [x] Server import/export (JSON)
- [x] Session persistence across page reloads
- [x] Rate limiting on auth endpoints (slowapi)
- [x] Audit log (admin-viewable action history)
- [x] SFTP connection pool (5 min TTL reuse per server)
- [x] Per-server SSH/SFTP toggles + SFTP path restrictions

### v0.2.x — Access Refinement & UX (2026-04-09 → 2026-04-15)
- [x] SFTP read-only mode per server
- [x] Server status monitoring (background SSH checks, green/red dot)
- [x] Dark/light theme toggle, responsive tablet/mobile layout
- [x] Keyboard shortcuts, drag & drop upload progress, ZIP folder download
- [x] Two-factor authentication (TOTP)
- [x] API key authentication
- [x] **Reverse proxy sub-path support** (`WEBGATE_ROOT_PATH`)
- [x] **Demo mode** for public read-only deployments

### v0.3.x — Operations Pack (2026-04-15)
- [x] **SSH jump host / bastion** (per-server `jump_via_id`, asyncssh tunneling)
- [x] **SSH command snippets** (per-user library, terminal toolbar)
- [x] **PostgreSQL support** (`pip install webgate` ships `asyncpg`; dialect-aware migrations)
- [x] **Webhook notifications** (HMAC-signed POSTs on auth/SSH/SFTP/server events)

### v0.4.x — Collaboration & Compliance (2026-04-15)
- [x] **Shared terminal sessions** (one SSH PTY, N WebSockets, broadcast + multiplexed input)
- [x] **SSH session recording** (asciinema cast v2, browser replay)
- [x] **LDAP / Active Directory authentication** (search-then-bind, group→role mapping)

### v0.5.x — Enterprise & Scale (2026-09)
- [x] **Multi-instance HA deployment** (stateless workers behind a LB on a shared Postgres; `compose.ha.yml`)
- [x] Security hardening: enforced `must_change_password`, 2FA temp-token flow, API-key gates
- [x] Narrowed demo allowlist + sanitized webhook payloads
- [x] **UI redesign** — grouped Admin menu, collapsible chrome, SVG icon system, themed terminal palette, WCAG-AA contrast
- [x] **Backup & restore** — full-state export/import (servers with credentials, users, groups, webhooks, API keys), passphrase-encrypted, portable across instances with different encryption keys

### v2.0.0 — Company deployment (2026-09-10)
- [x] **Verified SSH host keys** (trust on first use) across all seven connection paths, including jump hosts; a changed key is refused before authentication runs, and accepting one is a deliberate audited admin action
- [x] **AI agent** — per-server iterative chat over Ollama or OpenRouter, configured in the admin panel rather than by environment variable, with read-only tools, a TTL cache and searchable findings
- [x] **Agent support for SFTP-only hosts** — a shell-free toolset for servers that expose no shell
- [x] **White-label branding** — app name, logo, sign-in image, browser icon, company colours with palette picker and live preview, light and dark palettes, applied for every user
- [x] **Terminal auto-reconnect** with backoff, and a **command palette** (`Ctrl+P`)
- [x] **Favourites and recents**
- [x] **SFTP sortable columns, hidden-file toggle, multi-select with ZIP download, owner names**
- [x] **A tested upgrade contract** — additive, append-only, idempotent migrations; failures stop startup instead of being swallowed; concurrent HA workers no longer collide

### v2.1.0 — Admin settings panel (2026-09-10)
- [x] **Admin settings panel** — 19 settings across security, monitoring, recording and LDAP, changed in the app rather than the environment, effective without a restart and shared across instances
- [x] **`WEBGATE_CONFIG_LOCKED`** for deployments that manage configuration as code
- [x] **Six documented settings that did nothing now work** — transfer size limits, idle SSH expiry, the three monitor knobs, and `first_run`
- [x] **Transfer size limits** — chunked reads against a per-request budget, so one large file can no longer exhaust a worker

### v2.2.0 — Stability pass (2026-09-11)
- [x] **The shipped default `WEBGATE_SECRET_KEY` is refused** on any address other than loopback; it signs session tokens and derives the credential encryption key, and it is published in this repository
- [x] **Webhook deliveries no longer vanish** — the tasks were unreferenced and could be garbage-collected mid-flight
- [x] **`ruff check src/ tests/` clean**, and the README stops documenting a type-check gate that has never passed

---

## Planned

### v2.1.x — Next
| Feature | Priority | Description |
|---------|----------|-------------|
| Per-user concurrent-session limit | Medium | Nothing caps how many SSH sessions one account may hold open |
| Host key fingerprint in the UI | Medium | The API exposes it and can clear it; the Site Manager does not show it yet |
| Per-server recording opt-in | Medium | Toggle recording on a per-server basis instead of the current global flag |
| Internationalization (i18n) | Low | UI translations starting with English / Spanish |

### Later
| Feature | Priority | Description |
|---------|----------|-------------|
| Scheduled commands | Medium | Run a snippet on a cron schedule against one or more servers |
| Slack / Teams formatter for webhooks | Low | Pre-built payload templates for popular receivers |
| Browser-shareable file download links | Low | Time-limited signed URLs for SFTP downloads |

---

## How to contribute

Feature requests and bug reports go in [GitHub Issues](https://github.com/kalexnolasco/webgate/issues). When proposing a feature please include:

1. **Use case** — what problem does it solve?
2. **Who benefits** — which type of user needs this?
3. **Suggested approach** — how would you implement it (optional)?
