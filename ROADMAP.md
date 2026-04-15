# Roadmap

This document tracks the development plan for **webgate**. Items are organized by release milestone.

---

## v0.1.0 -- Foundation (Released 2026-04-08)

- [x] SSH web terminal (xterm.js + asyncssh WebSocket bridge)
- [x] SFTP file browser (ls, upload, download, rename, delete, mkdir, chmod)
- [x] In-browser text editor (CodeMirror 6 with oneDark theme)
- [x] PDF and image preview (PDF, PNG, JPG, GIF, SVG, WebP)
- [x] Server registry with groups, tags, and encrypted credentials (Fernet)
- [x] Quick Connect toolbar for one-off SSH connections
- [x] Admin/user role system with group-based access control
- [x] Default admin account with forced password change on first login
- [x] User management panel (create, delete, assign groups)
- [x] Multi-tab split pane (terminal + file browser side by side)
- [x] SSH key management (per-server key upload with visual indicator)
- [x] File search/filter within SFTP listings
- [x] Server import/export (JSON) from the UI
- [x] Session persistence across page reloads
- [x] Rate limiting on auth endpoints (slowapi)
- [x] Audit log (admin-viewable action history)
- [x] SFTP connection pool (reuse per server, 5 min TTL)
- [x] Docker multi-stage build with demo SSH container
- [x] 34 automated tests

## v0.1.1 -- Per-Server Access Control (Released 2026-04-08)

- [x] Per-server SSH toggle (admin can disable SSH terminal for specific servers)
- [x] Per-server SFTP toggle (admin can disable SFTP file browser for specific servers)
- [x] SFTP path restrictions (admin can limit SFTP access to specific directories per server)
- [x] Path enforcement on all SFTP operations (ls, read, write, upload, download, mkdir, rename, delete, chmod)

---

## v0.2.0 -- Access Refinement & UX (Released 2026-04-09)

- [x] SFTP read-only mode (per-server flag: browse/download only, block upload/write/delete/rename/mkdir/chmod)
- [x] Server status monitoring (background SSH checks every 60s, green/red dot on dashboard)
- [x] Dark/light theme toggle (CSS variables, localStorage persistence, terminal/editor adapt)
- [x] Responsive tablet layout (CSS media queries for 1024px and 768px breakpoints)
- [x] Keyboard shortcuts (Escape closes modals, Ctrl+1 Site Manager, Ctrl+N New Server)
- [x] Drag & drop upload progress bar (XHR with progress events, percentage display)
- [x] Folder download as ZIP (server-side zip compression, right-click context menu)

## v0.2.1 -- Reverse Proxy Sub-Path (Released 2026-04-15)

- [x] Serve webgate behind a reverse proxy at any URL prefix (`WEBGATE_ROOT_PATH`)
- [x] nginx, Apache and Traefik examples in README

## v0.2.2 -- Demo Mode (Released 2026-04-15)

- [x] `WEBGATE_DEMO_MODE` middleware blocks writes for public read-only deployments
- [x] `Dockerfile.demo` (webgate + sshd via supervisord) and `fly.toml` for one-command Fly.io deploys
- [x] Live demo at https://webgate-demo.fly.dev/

## v0.3.0 -- Operations Pack (Released 2026-04-15)

- [x] **SSH jump host / bastion** (per-server `jump_via_id`, asyncssh tunneling)
- [x] **SSH command snippets** (per-user library, terminal toolbar, click to send)
- [x] **PostgreSQL support** (`pip install 'webgate[postgres]'`, dialect-aware migrations)
- [x] Two-factor authentication (TOTP) -- already in v0.2.x
- [x] API key authentication -- already in v0.2.x

## v0.3.x -- Planned

| Feature | Priority | Description |
|---------|----------|-------------|
| Shared terminal sessions | High | Multiple users can watch/interact with the same SSH session in real time |
| Session recording & playback | High | Record terminal sessions for audit trail and training; replay in browser |
| Webhook notifications | Medium | Fire webhooks on events: user login, SSH connect, file upload, server added |
| LDAP / Active Directory | Medium | Authenticate users against corporate LDAP/AD; auto-map groups |

## v0.4.0 -- Enterprise & Scale

| Feature | Priority | Description |
|---------|----------|-------------|
| Multi-instance deployment | Medium | Multiple webgate instances sharing a single database (stateless workers behind LB) |
| Custom branding | Low | Configurable logo, application name, and color scheme |
| Backup/restore UI | Medium | Export/import full application state (users, servers, audit log) from admin panel |
| Internationalization (i18n) | Low | Multi-language support for the UI (starting with English and Spanish) |

---

## How to Contribute

Feature requests and bug reports go in [GitHub Issues](https://github.com/kalexnolasco/webgate/issues). When proposing a new feature, please include:

1. **Use case** -- What problem does it solve?
2. **Who benefits** -- Which type of user needs this?
3. **Suggested approach** -- How would you implement it (optional)?
