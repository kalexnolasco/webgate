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

---

## Planned

### v0.5.x — Enterprise & Scale
| Feature | Priority | Description |
|---------|----------|-------------|
| Multi-instance HA deployment | High | Multiple stateless webgate workers behind a LB sharing a Postgres DB |
| Backup / restore UI | Medium | Export & import full state (users, servers, audit, recordings) from the admin panel |
| Per-server recording opt-in | Medium | Toggle recording on a per-server basis instead of the current global flag |
| Custom branding | Low | Configurable logo, app name, color scheme |
| Internationalization (i18n) | Low | UI translations starting with English / Spanish |

### v0.6.x — Workflow & Automation
| Feature | Priority | Description |
|---------|----------|-------------|
| Scheduled commands | Medium | Run a snippet on a cron schedule against one or more servers |
| Per-user dashboard | Medium | Recent connections, favorite servers, personal stats |
| Slack / Teams formatter for webhooks | Low | Pre-built payload templates for popular receivers |
| Browser-shareable file download links | Low | Time-limited signed URLs for SFTP downloads |

---

## How to contribute

Feature requests and bug reports go in [GitHub Issues](https://github.com/kalexnolasco/webgate/issues). When proposing a feature please include:

1. **Use case** — what problem does it solve?
2. **Who benefits** — which type of user needs this?
3. **Suggested approach** — how would you implement it (optional)?
