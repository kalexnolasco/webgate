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

## v0.2.0 -- Access Refinement & UX

| Feature | Priority | Description |
|---------|----------|-------------|
| SFTP read-only mode | High | Per-server flag: allow browse/download but block upload, write, delete, rename, mkdir, chmod |
| Server status monitoring | High | Background connectivity checks with online/offline indicator on dashboard |
| Dark/light theme toggle | Medium | User preference saved in localStorage, apply to terminal and file browser |
| Responsive tablet layout | Medium | Adapt split-pane UI for iPad/tablet screen sizes |
| Keyboard shortcuts | Medium | Configurable shortcuts for common actions (new tab, switch pane, focus search) |
| Drag & drop upload progress | Low | Visual progress bar for multi-file uploads with cancel support |
| Folder download as ZIP | Low | Server-side ZIP compression for directory downloads |

## v0.3.0 -- Collaboration & Operations

| Feature | Priority | Description |
|---------|----------|-------------|
| Shared terminal sessions | High | Multiple users can watch/interact with the same SSH session in real time |
| Session recording & playback | High | Record terminal sessions for audit trail and training; replay in browser |
| SSH command snippets | Medium | Save and execute common commands per server or globally; share across team |
| Webhook notifications | Medium | Fire webhooks on events: user login, SSH connect, file upload, server added |
| Two-factor authentication (TOTP) | High | Optional TOTP (Google Authenticator, Authy) for user accounts |
| LDAP / Active Directory | Medium | Authenticate users against corporate LDAP/AD; auto-map groups |
| API key authentication | Low | Generate API keys for programmatic access (automation, scripts, CI/CD) |

## v0.4.0 -- Enterprise & Scale

| Feature | Priority | Description |
|---------|----------|-------------|
| PostgreSQL support | High | Test, document, and CI-verify PostgreSQL as alternative to SQLite |
| Multi-instance deployment | Medium | Multiple webgate instances sharing a single database (stateless workers behind LB) |
| SSH jump host / bastion | High | Connect through a bastion/jump host to reach servers not directly reachable |
| Custom branding | Low | Configurable logo, application name, and color scheme |
| Backup/restore UI | Medium | Export/import full application state (users, servers, audit log) from admin panel |
| Internationalization (i18n) | Low | Multi-language support for the UI (starting with English and Spanish) |

---

## How to Contribute

Feature requests and bug reports go in [GitHub Issues](https://github.com/kalexnolasco/webgate/issues). When proposing a new feature, please include:

1. **Use case** -- What problem does it solve?
2. **Who benefits** -- Which type of user needs this?
3. **Suggested approach** -- How would you implement it (optional)?
