# Changelog

## v0.5.0 (2026-04-15)

### Features

- **Multi-instance HA deployment** -- run N webgate workers behind a load balancer, sharing a PostgreSQL database. Only one worker at a time performs server-connectivity probes (leader election via a singleton lease row); all workers serve REST + WS traffic normally.
- **`compose.ha.yml`** reference deployment: 2 webgate replicas + Postgres + nginx LB with `ip_hash` sticky sessions. Verified end-to-end including automatic failover.
- **`/api/health`** now reports `instance_id` (per-worker UUID) and `monitor_role` (`leader` / `follower`) so LB health checks and observability can tell replicas apart.

### Configuration

| Variable | Default | Description |
|---|---|---|
| `WEBGATE_INSTANCE_ID` | auto (UUID) | Stable identifier for this worker |
| `WEBGATE_DISABLE_MONITOR` | `false` | Skip leader election entirely (pure follower worker, useful if a separate process owns the monitor) |

### Details

- New `monitor_lease` singleton table (auto-created at startup) holds the current leader's instance id and expiry. 90 s TTL with 30 s heartbeat.
- On leader loss / expiry, any other worker picks up the probe loop within ~1 check cycle (≤ 90 s).
- Dialect-agnostic (works on SQLite for single-instance dev, PostgreSQL for real HA).

### Known limitation

- Shared terminal sessions (`/api/ws/terminal/join/{token}`) still require owner and joiner to land on the same worker. Sticky-session routing handles same-browser joins; cross-worker cross-engineer sharing needs Redis pub/sub (planned in v0.5.x).

### Verified

`compose.ha.yml` stack (2 replicas + Postgres + nginx):

- Both replicas show `{"instance_id":"…","monitor_role":"follower"|"leader"}`
- Exactly one replica holds the lease row in Postgres
- Servers created on replica A immediately visible from replica B (shared DB)
- Killed the leader → follower promoted automatically, LB kept serving

---

## v0.4.2 (2026-04-15)

### Features

- **LDAP / Active Directory authentication** -- enable with `WEBGATE_LDAP_ENABLED=true` and login flow falls back to LDAP after the local user table. On a successful LDAP bind the user is auto-provisioned (or refreshed) in the local DB, with `allowed_groups` derived from LDAP group memberships and admin status from a configurable list of admin groups.

### Configuration

| Env var | Description |
|---|---|
| `WEBGATE_LDAP_ENABLED` | `true` to enable LDAP login |
| `WEBGATE_LDAP_URL` | `ldap://host:389` or `ldaps://host:636` |
| `WEBGATE_LDAP_BIND_DN` | service account DN, e.g. `cn=admin,dc=example,dc=com` |
| `WEBGATE_LDAP_BIND_PASSWORD` | service account password |
| `WEBGATE_LDAP_USER_BASE` | e.g. `ou=people,dc=example,dc=com` |
| `WEBGATE_LDAP_USER_FILTER` | default `(uid={username})` (AD: `(sAMAccountName={username})`) |
| `WEBGATE_LDAP_GROUP_BASE` | e.g. `ou=groups,dc=example,dc=com` (empty = no group lookup) |
| `WEBGATE_LDAP_GROUP_FILTER` | default `(member={dn})` (AD nested: `(member:1.2.840.113556.1.4.1941:={dn})`) |
| `WEBGATE_LDAP_GROUP_MAP` | JSON `{"ldap-cn":"webgate-group"}` |
| `WEBGATE_LDAP_ADMIN_GROUPS` | JSON list of LDAP CNs that grant admin |

### Details

- Search-then-bind flow: bind as service account, search by username, re-bind as the user with their password
- LDAP filter values are properly escaped (RFC 4515)
- All `ldap3` calls run in `asyncio.to_thread` to avoid blocking the event loop
- Local accounts (admin, API keys, 2FA) keep working as before -- LDAP is only consulted after a local-credential miss
- Re-login refreshes admin status and group mapping from LDAP every time

### Verified

End-to-end against `osixia/openldap` with an `alice` user in groups `devs` and `admins`:

- `alice / alicepass` → 200, JWT issued, `/api/auth/me` returns `is_admin=true`, `allowed_groups=["all","production"]` (mapped from LDAP CNs)
- `alice / WRONG` → 401 Invalid credentials
- `admin / admin` (local fallback) → still works

---

## v0.4.1 (2026-04-15)

### Features

- **SSH session recording** -- when `WEBGATE_RECORD_SESSIONS=true`, every SSH terminal session is captured to an asciinema cast v2 file under `WEBGATE_RECORDINGS_DIR` (default `./recordings`). Both owner-only and shared sessions are recorded. A new `recordings` table tracks file path, server, user, start/end, duration and size.
- **Built-in web replay** -- `📹 Recordings` button (top toolbar) opens a list with **▶ Play** / **DL** / **Del** actions. Play opens an asciinema-player tab that streams the cast directly from the API. Non-admins see only their own recordings; admins see everyone's.
- **Compliance-grade audit trail** -- the recording captures the full PTY output that every participant saw, including pasted commands and environment, in a portable, replayable, vendor-independent format (you can also `asciinema play file.cast` locally).

### Details

- New `WEBGATE_RECORD_SESSIONS` and `WEBGATE_RECORDINGS_DIR` settings (both off / `./recordings` by default)
- New `Recording` model + REST CRUD at `/api/recordings`
- New `webgate.recordings.recorder.CastRecorder` writes asciinema cast v2 (JSON Lines) line-buffered, very low overhead
- Hook in `SharedSession.broadcast` -- recorder receives the same byte stream as every WS client
- Player endpoint accepts a `?token=` query param (Authorization header isn't available when opening a tab)

### Verified

End-to-end against a real container with `WEBGATE_RECORD_SESSIONS=true`:

- Open SSH, run `echo HELLO_RECORDED` + `uname -n`, disconnect
- DB row populated: `started_at`, `ended_at`, `duration_s=3.0`, `size_bytes=1142`
- File on disk: valid asciinema v2 cast, captures welcome banner + commands + responses
- Open `/api/recordings/{id}/play?token=...` in browser → asciinema-player loads, hit Play → terminal replays the captured commands

---

## v0.4.0 (2026-04-15)

### Features

- **Shared terminal sessions** -- the killer feature. The owner of an active SSH terminal can click **🔗 Share** to mint a one-time URL; anyone they send it to can join the same live session. Output is broadcast to every participant, and any RW participant can type. Useful for pair debugging in production, onboarding juniors, or remote support.
  - Backend: new `SharedSession` registry holds one `asyncssh` process per session and broadcasts its PTY output to N WebSockets. `_client_input_loop` multiplexes input from any RW client into the same `stdin`.
  - Endpoints: `POST /api/terminal/share/{session_id}` mints/returns the token, `DELETE` revokes, `WS /api/ws/terminal/join/{token}?mode=rw|ro` attaches a joiner.
  - Frontend: **🔗 Share** button copies the URL to clipboard; toolbar shows `👥 joined (rw|ro)` for participants. Pasting `?join=<token>` into the URL after login auto-attaches.
  - Demo middleware whitelists `/api/terminal/share/*` so the public demo can showcase the feature.

### Verified

End-to-end with two browser sessions against the local container:

- Owner opens SSH to `bastion`, clicks Share → token minted, URL copied
- Joiner navigates to `?join=<token>` → "Joined session of demo on bastion (rw)"
- Joiner types `echo HELLO_FROM_JOINER` → output appears in BOTH terminals
- Owner types `uname -n` → output appears in BOTH terminals

---

## v0.3.3 (2026-04-15)

### Fixed

- Snippets toolbar was empty after a fresh login until the page was reloaded. `loadSnippets()` was only called from `init()` (which only runs when a token is already in localStorage). Now also called after a successful login and after a forced password change.

### Docs

- Added end-to-end UI screenshots for v0.3.x features: jump host, snippets toolbar, snippet execution, SFTP browse via jump, webhooks management modal with delivery telemetry, server form with Jump Via dropdown.
- Browser-tested every UI flow with `playwright-cli` against both the live Fly.io demo and a local container.

---

## v0.3.2 (2026-04-15)

### Features

- **Webhook notifications** -- admin can register HTTPS endpoints that receive a JSON POST when significant events fire. Supported events: `user_login`, `user_login_failed`, `ssh_connect`, `sftp_upload`, `sftp_delete`, `server_added`, `server_deleted`. Each webhook can subscribe to all events (`*`) or a specific subset.
- **HMAC-SHA256 signing** -- optional shared secret per webhook; the dispatcher signs the body and sends it as `X-Webgate-Signature: sha256=<hex>` so the receiver can verify authenticity.
- **Test button + delivery telemetry** -- one-click test fire from the admin UI; each webhook row shows the last HTTP status and timestamp.

### Details

- New `Webhook` model + REST CRUD at `/api/webhooks` (admin-only)
- New `webgate.webhooks.dispatcher.fire(event, data)` -- fire-and-forget, schedules HTTP delivery via `httpx`, never blocks the caller
- Frontend: "Webhooks" button in the top toolbar (admin only) with full management modal
- New base dependency: `httpx>=0.28.0` (used by the dispatcher)

Verified end-to-end against a real HTTP echo receiver: `user_login`, `server_added` and a manual test all delivered with HTTP 200 and signature header.

---

## v0.3.1 (2026-04-15)

### Fixed

- **PostgreSQL actually works in Docker now.** v0.3.0 advertised PostgreSQL support but two bugs prevented it from working:
  1. `asyncpg` was an optional extra (`webgate[postgres]`), so the official Docker image (and `pip install webgate`) didn't have the driver. Now bundled by default.
  2. Lightweight migrations ran inside the same transaction as `create_all`. PostgreSQL aborts the entire transaction on any error (even when caught), so the first "column already exists" error rolled back table creation on subsequent runs. Each migration now uses its own transaction.

Verified end-to-end against a real `postgres:16-alpine` container: tables created, login works, server creation and persistence across restarts confirmed.

---

## v0.3.0 (2026-04-15)

### Features

- **SSH jump host / bastion** -- per-server `jump_via_id` field. Webgate opens a tunneled SSH connection through the bastion using `asyncssh`'s `tunnel=` parameter. Works for both the terminal WebSocket and the SFTP browser. Solves the common "internal servers reachable only through one public bastion" scenario.
- **SSH command snippets** -- per-user library of named commands. Click a snippet button in the terminal toolbar to send the command (with Enter) to the active session. Right-click to delete, `+` to create.
- **PostgreSQL support** -- install with `pip install 'webgate[postgres]'` and set `WEBGATE_DB_URL=postgresql+asyncpg://...`. SQLite remains the default. Lightweight migrations are now dialect-aware.

### Details

- New `Server.jump_via_id` (FK to `servers.id`, nullable) + `resolve_jump_creds()` helper
- New `Snippet` model + REST CRUD at `/api/snippets`
- Frontend: dropdown to pick a jump host in the Add/Edit Server modal; `↺` badge in the server card when a jump is configured
- Frontend: snippet toolbar in the terminal tab (hidden when there are no snippets)
- Demo seed pre-populates `bastion` + `internal-app` (jump-host pair) and 4 example snippets

---

## v0.2.2 (2026-04-15)

### Features

- **Demo mode** (`WEBGATE_DEMO_MODE=true`) -- read-only public demo deployments. Blocks every write request on `/api/*` (except login), disables the WebSocket quick-connect endpoint, seeds a `demo`/`demo` user with a sample server, and shows a top banner in the UI.
- **`Dockerfile.demo`** -- single-container image bundling webgate + a sandboxed `sshd` target via supervisord. Ready for free hosting tiers.
- **`fly.toml`** -- Fly.io configuration for one-command demo deployments (`flyctl deploy`).

### Details

- New public endpoint `GET /api/config` exposes `{"demo_mode": bool}` for the frontend to render the banner before login
- `WEBGATE_DEMO_MODE=true` adds an HTTP middleware that returns `403` for any `POST/PUT/PATCH/DELETE` on `/api/*` (allowlist: `/api/auth/login`, `/api/auth/totp/verify`)
- Demo seed (`webgate.demo`) is idempotent and only runs when the flag is on
- Hourly state reset for the public demo can be done with a cron pinging the container restart, so DB returns to seed state

---

## v0.2.1 (2026-04-15)

### Features

- **Reverse proxy sub-path support** -- webgate can now be served behind a reverse proxy at a URL prefix (e.g. `https://example.com/webgate/`). Previously the frontend used absolute `/api/...` paths that broke under any prefix.

### Details

- New config setting: `WEBGATE_ROOT_PATH` (default `""`), passed to FastAPI's `root_path` for correct OpenAPI URLs behind proxies
- Frontend derives the path prefix at runtime from `window.location.pathname` and prepends it to all REST calls and the terminal WebSocket URL
- README documents nginx, Apache, and Traefik reverse-proxy configurations for sub-path deployments
- The proxy must forward the prefix unchanged (do not strip it) -- webgate handles the prefix natively

---

## v0.2.0 (2026-04-09)

### Features

- **SFTP read-only mode** -- per-server flag to allow browse and download only, blocking all write operations (upload, write, mkdir, rename, delete, chmod)
- **Server status monitoring** -- background task checks SSH connectivity every 60 seconds; online/offline indicator (green/red dot) on server dashboard
- **Dark/light theme toggle** -- user preference saved in localStorage; CSS custom properties for full theme support; terminal and editor adapt to theme
- **Keyboard shortcuts** -- Escape closes modals, Ctrl+1 goes to Site Manager, Ctrl+N opens New Server
- **Drag & drop upload progress** -- visual progress bar with percentage during file uploads
- **Folder download as ZIP** -- right-click a directory in SFTP browser to download it as a ZIP archive
- **Lightweight DB migrations** -- automatic ALTER TABLE for new columns on existing databases

### Details

- New server model field: `sftp_read_only` (bool, default false)
- New file: `servers/monitor.py` — ServerMonitor class with asyncio background task
- New API endpoints: `GET /api/servers/status`, `GET /api/servers/{id}/status`
- New API endpoint: `GET /api/files/{id}/download-zip?path=`
- Config settings: `monitor_interval`, `monitor_timeout`, `monitor_concurrency`
- CSS variables for theming: `--bg-primary`, `--text-primary`, `--accent`, etc.
- Terminal theme switches between dark (Tokyo Night) and light on toggle

---

## v0.1.1 (2026-04-08)

### Features

- **Per-server SSH/SFTP toggles** -- admin can enable or disable SSH terminal and SFTP file browser independently for each server
- **SFTP path restrictions** -- admin can configure allowed directory paths per server; users are restricted to only those directories and their subdirectories (empty list = unrestricted)

### Details

- New server model fields: `ssh_enabled` (bool), `sftp_enabled` (bool), `sftp_allowed_paths` (JSON list of paths)
- SSH disabled servers return WebSocket close code 4003
- SFTP disabled servers return HTTP 403
- Path restriction enforced on all SFTP operations (ls, read, write, upload, download, mkdir, rename, delete, chmod)
- Rename operations validate both source and destination paths against allowed paths
- All existing tests continue to pass (34 tests)

---

## v0.1.0 (2026-04-08)

First public release.

### Features

- SSH web terminal (xterm.js + asyncssh WebSocket bridge)
- SFTP file browser (directory listing, upload, download, rename, delete, mkdir, chmod)
- In-browser text editor (CodeMirror 6 with oneDark theme)
- PDF and image preview (PDF, PNG, JPG, GIF, SVG, WebP)
- Server registry with groups, tags, and encrypted credentials (Fernet)
- Quick Connect toolbar for one-off SSH connections
- Admin/user role system with group-based access control
- Default admin account with forced password change on first login
- User management panel (create, delete, assign groups)
- Multi-tab split pane (terminal + file browser side by side)
- File search/filter within SFTP listings
- Server import/export (JSON) from the UI
- Session persistence across page reloads
- Rate limiting on auth endpoints (slowapi)
- Audit log (admin-viewable action history)
- SFTP connection pool (reuse per server, 5 min TTL)
- Modern dark UI (GitHub-inspired theme)
- Docker multi-stage build with demo SSH container
- 34 automated tests
