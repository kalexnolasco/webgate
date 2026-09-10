# Changelog

## v2.0.0 (2026-09-10) — AI agent, white-label branding, verified host keys

The first release aimed at a company deploying webgate rather than an individual running
it. It adds a per-server AI agent, full white-label branding, backup and restore, and it
closes the largest hole in the project: until now the gateway handed stored fleet
credentials to whatever answered on a server's address.

Design direction is recorded in `DESIGN.md`, product context in `PRODUCT.md`.

### Upgrading

Stop, pull, start. The schema migrates itself on boot.

```bash
docker compose pull && docker compose up -d
```

Two things worth knowing before you do:

- **Host key verification is on by default.** Existing servers have no pinned key, so the
  next connection to each one pins whatever it presents and nothing breaks. From then on a
  changed key is refused. Set `WEBGATE_VERIFY_HOST_KEYS=false` to postpone it.
- **The AI agent stays off** until an admin configures a provider under **Admin → AI
  agent**, and off per server until it is enabled there.

Rolling back to v0.5.x works: schema changes are additive, so an older webgate simply
ignores the columns it does not know. Full guide, including PostgreSQL and HA:
[Upgrading](getting-started/upgrade.md).

### Security

- **SSH and SFTP now verify the host key (trust on first use).** Every connection the
  gateway made passed `known_hosts=None`, which disables verification entirely: it would
  authenticate to any machine answering on the target's address and hand it the stored
  credentials. A poisoned internal DNS record, ARP spoofing or a compromised switch was
  enough, and the gateway is exactly where every credential in the fleet lives. This was
  demonstrated, not theorised — with a substituted host key, webgate reported *Connection
  successful*.

  The first connection to a server records the key it presents. Every connection after
  that is checked against it **before authentication runs**, so a mismatch sends nothing.
  All seven connection paths verify: terminal, SFTP browser, the SFTP pool, the status
  monitor, connection tests, the agent, and jump hosts — the bastion most of all, since
  everything behind it is reached through that one connection.

- **A changed key stops the connection and explains itself.** The message names both
  possibilities (an interceptor, or a rebuilt host), states that nothing was sent, and says
  how to proceed. Accepting a new key is a deliberate admin action —
  `DELETE /api/servers/{id}/host-key`, audited — never automatic, since silently re-pinning
  would defeat the whole mechanism. Clearing a pin also drops the server's pooled SFTP
  connection, which otherwise served the old one for up to five minutes.

- **The declared auth method is honoured.** A server moved from key to password kept its
  old key row, and connections preferred the key, failing with an unrelated PEM error.
  This applied to connection tests, jump hosts and the status monitor alike.

- **One unusable server no longer blinds the status monitor.** The private key was parsed
  outside the guard, so an unreadable key row raised through the `gather` that checks every
  server and killed the whole cycle: every other server's dot stayed frozen at whatever it
  last showed, with no indication anything had stopped. The monitor had no tests at all,
  which is how both this and a missing import survived in it.

### AI agent

An agent that reads a server and explains it, per server and iterative rather than
one-shot, so a diagnosis can be followed up.

- **Ollama or OpenRouter**, configured by an admin under **Admin → AI agent**: base URL,
  API key (encrypted at rest), and a model picked from a dropdown the provider populates.
  Nothing is read from environment variables — an operator should not need a redeploy to
  change a model. Users see a clear "not configured yet" state instead of a broken feature.
- **Per-server chat with history.** Conversations are stored per server and per user and
  survive a reload. Context is trimmed in three passes as it grows, protecting the most
  recent exchanges.
- **Works on SFTP-only servers.** Many hosts in a fleet expose no shell. The agent has a
  shell-free toolset — read, list, stat, search over SFTP — and picks it automatically, so
  it stays useful where a command-running agent would simply fail.
- **Read-only tools.** Twelve SSH tools and seven SFTP ones, all inspection; every argument
  goes through `shlex.quote`. The agent cannot change a server.
- **Results are cached with a TTL** so repeating a question does not re-run every command,
  and **findings are stored and searchable**, so what was learned about a host is still
  there next week.

### Branding (white label)

A company can make the deployment its own, and the look reaches every user, not just the
admin who set it.

- **App name, tagline, logo, sign-in image and browser icon** (emoji or uploaded file,
  PNG/JPEG/SVG/WebP). Uploads are re-encoded from bytes the server decoded itself, so what
  ends up in an `<img src>` is never the string that was submitted.
- **Company colours with a palette picker and live preview**, separate light and dark
  palettes, and a partial palette is fine — set an accent and leave the rest alone.
- **Colours are validated as hex**, so a value like `#fff; background: url(//evil)` is
  rejected rather than injected into the stylesheet.
- Branding travels in a backup, so a migrating company keeps its look.

### SFTP browser

- **Sortable listings** by name, size or modified date, ascending or descending, with
  directories kept together.
- **Hidden files toggle**, off by default.
- **Multi-select with `Shift`/`Ctrl`, and download as a ZIP.** The previous ZIP path
  reported success while silently omitting files it could not read.
- **Owner and group are shown by name** rather than numeric uid/gid where the server
  resolves them.

### Upgrades and schema

Making sure a future release cannot break an existing install.

- **Migrations no longer swallow failures.** The loop caught every exception and continued,
  so a migration that genuinely failed left the column missing and surfaced later at some
  unrelated query, with nothing pointing back to the cause. Whether a change is needed is
  now decided by inspecting the schema, and a real failure stops startup with a message
  that says what to do.
- **A concurrent instance is no longer a failure.** `compose.ha.yml` starts N workers at
  once and they all migrate; losing that race is now recognised as the normal outcome it is.
- **Applied changes are recorded** in a `schema_migrations` table, backfilled for older
  installs. A database written by a newer webgate is recognised and reported rather than
  mistaken for a broken one — which is what makes a rollback safe to attempt.
- **Every table is registered explicitly.** Tables were created only because some router
  happened to import their model; a new model in a module nothing imported at startup would
  have been skipped silently and failed on first use.
- **The contract is tested.** `tests/test_migrations.py` locks it: additive only, append
  only, idempotent. It upgrades an aged database and compares the result against a fresh
  install, checks the rows survive, and asserts that a broken migration stops startup.
- **The version is no longer hardcoded.** The API reported `0.1.0` for six releases.

### Terminal, palette and UI

The UI was the product's weakest part; this release replaces the visual world, adds the
first real defence against dropped SSH sessions, and makes a large registry navigable by
keyboard.

#### Terminal resilience

- **SSH terminals now reconnect automatically.** Previously `ws.onclose` wrote
  `--- Disconnected ---` and stopped there: a three-second network blip during an incident
  killed the session and forced the user to close and reopen the tab. The socket is now
  re-opened with exponential backoff (1s, 2s, 4s, 8s, capped at 15s) for up to 6 attempts,
  reusing the same xterm instance so scrollback survives.
- **Connection state is visible.** A banner above the terminal reports `Connecting…`,
  `Connection lost. Reconnecting in Ns — attempt N of 6`, or a terminal failure, with a
  **Reconnect now** button. The countdown ticks down rather than showing a frozen number.
- **Auth rejections (close code 4001) do not retry** — retrying with the same expired token
  cannot succeed, so the banner asks the user to sign in again instead of burning attempts.
- **Closing a tab cancels its pending retry**, so a closed session can no longer resurrect
  itself or leak a timer. `_destroyTab` also now tears down `split` tabs' terminals, which
  it previously skipped.

#### Command palette

- **`Ctrl+P` (or `Ctrl+Shift+P`) opens a fuzzy palette** over every server and every action.
  Matching runs over name, `user@host`, group, and tags, preferring contiguous matches over
  scattered ones. Arrow keys navigate, `Enter` opens, `Esc` closes.
- `Ctrl+Shift+P` works even while focus is inside a terminal; plain `Ctrl+P` deliberately
  does not, so readline keeps `previous-command`.

#### Favourites and recents

- **Star any server** in the Site Manager to pin it. Opening a server records it as recent
  (deduplicated, most recent first, capped at 8). Both persist in `localStorage`.
- The Site Manager detail pane, previously an empty placeholder, now lists **Favourites**
  and **Recent** as dense quick-launch rows once there is anything to show.

#### UI redesign

- **Information architecture.** `Users`, `Audit`, `Webhooks`, `Recordings`, `API keys`, and
  `2FA` moved out of the top bar — where they sat as seven flat peers of `Site Manager` —
  into a grouped **Admin** menu. Quick Connect and the activity log are now collapsible and
  remembered in `localStorage`, instead of permanently occupying two horizontal bands.
- **Icon system.** All emoji and Unicode glyphs used as icons (`📹 ☀️ 🌙 ▤ ▦ 🔑 🔗 👥`,
  `&#128193;`, `&#11014;`, `&#8635;` …) were replaced by an inline SVG sprite: 16px, 1.75
  stroke weight, round caps.
- **Typography.** Inter/JetBrains Mono replaced with IBM Plex Sans/Mono. All-caps
  letter-spaced micro-labels removed from table headers, the path bar, and group headers.
- **Terminal palette.** xterm was still on Tokyo Night (`#1a1b26`) while the rest of the app
  had moved. It now derives from the app's own tokens, ships a full ANSI palette for both
  themes, and **repaints when the theme is toggled** — previously an open terminal kept the
  old palette until it was closed and reopened.
- **Colour and contrast.** The status bar is a quiet footer rather than a `#1f6feb` band;
  server rows use a selected fill instead of a 3px accent rail; tabs are underlines, not
  pills. Every remaining hardcoded hex was replaced by a token, and all text now meets
  WCAG AA (`--text-muted` was failing at 3.3:1 on the dark surfaces).
- **Empty states teach.** The Site Manager tells a first-time admin to add a server or use
  Quick Connect, and tells a non-admin with no group access what to ask for.

#### Backup & restore

Migrating an instance previously meant re-entering every credential by hand, and could
silently rewire jump hosts. Both are fixed.

- **`POST /api/backup/export` and `POST /api/backup/restore`**, in the Admin menu under
  **Backup & restore**. Carries servers, users, groups, webhooks and API keys.
- **Credentials travel.** Server credentials are encrypted with a key derived from
  `WEBGATE_SECRET_KEY`, so ciphertext is meaningless on an instance with a different key.
  A backup therefore decrypts them and the restore re-encrypts with the target's own key.
  Because that makes the file a credential dump, credentials are only included when a
  passphrase is supplied, and the payload is then sealed with PBKDF2-HMAC-SHA256
  (480k iterations) + Fernet. Without a passphrase the backup is metadata only.
- **Jump hosts are recorded by name, not id** — see the bug fix below.
- Restore reports what it created and skipped. Users are never deleted by a restore, so a
  bad file cannot lock the operator out. `replace` mode clears servers, webhooks and API
  keys first; `merge` skips anything whose name already exists.
- Session recordings are files on disk and are not included; the backup says so in its
  `excludes` field.

#### Bug fixes

- **Auto-reconnect never gave up, and the attempt counter never advanced.** The retry
  budget was reset in `ws.onopen`, but the socket reaching the gateway says nothing about
  the SSH session behind it: the backend only attempts SSH *after* the client sends its
  connection details, so a refused host still produced a clean `onopen`. Every cycle reset
  the counter, so the log filled with `Reconnected` immediately followed by
  `SSH connection failed`, forever, always reporting attempt `(1/6)`. Success is now what
  the backend confirms — its `session` or `joined` control frame, or real terminal output
  if that frame is lost — not what the transport does. The budget therefore counts, and
  stops at six.
- **A first connection to a host that refuses is no longer retried.** Reconnecting exists
  for sessions that worked and then dropped; retrying six times against a host that plainly
  answered "connection refused" is noise. The banner and log now name the backend's own
  reason instead of a generic line, and **Reconnect now** still gets a full budget.
- **Server import silently rewired jump hosts.**
 `POST /api/servers/import` copied the
  exported `jump_via_id` verbatim, but the target database assigns its own ids. A server
  would then tunnel through whatever host happened to occupy that id. With bastions named
  `bastion-*` this went unnoticed — they sort first alphabetically and tended to land on
  the same ids — but with a convention like `ssh-proxy-*` or `gw-*`, all six jump routes in
  a test fleet pointed at the wrong host, including production servers hopping through the
  backup box. The import now resolves the hop by name and leaves it unset when it cannot,
  rather than pointing at a guess. Export files also accept an explicit `jump_via_name`.
- **Login errors are shown on the form**
 instead of a toast that vanished after 4 seconds,
  and the submit button reports its in-flight state.
- **The 2FA QR `<img>` no longer renders broken** before its `src` arrives; it is now created
  only once the QR is available, and has alt text.
- **The activity-log splitter works again.** It was bound on `DOMContentLoaded`, but the
  panel is now inside an `x-if` template, so the element did not exist at bind time. Drag
  handling is delegated from `document`.
- **The plain-text editor fallback** was hardcoded to a white background with dark text
  regardless of theme.
- The three one-time-code inputs had three different treatments; they now share one.

#### Docs

- `ROADMAP.md`: multi-instance HA was still listed as *planned* although it shipped in
  v0.5.0. Moved to **Shipped** along with the v0.5.x security work.
- `VERSION` said `0.1.0` while `pyproject.toml` said `0.5.3`. It is now the fallback the
  running app reads when package metadata is unavailable, rather than a file nobody read.

---

## v0.5.3 (2026-04-16) — UI hotfix: server dashboard

### Bug fixes

- **Site Manager sidebar no longer hides servers behind the status bar.** With enough registered servers, the left-hand list expanded past the viewport because the sidebar flex column was missing `min-height:0`, so the inner `.fz-serverlist` never clipped. The last cards scrolled off-screen underneath the blue status bar. Root cause was Alpine's `x-show` stripping the inline `display:flex` from the dashboard row when it toggled visibility. Fixed by introducing a `.fz-flex-row` CSS class (mirror of the existing `.fz-flex-col`) so the flex layout survives the `x-show` toggle, plus a proper `min-height:0` / `overflow:hidden` chain all the way down to the scrollable list.
- **Global status bar no longer leaks file-browser state onto the dashboard.** When an SFTP tab was open in the background and the user switched to Site Manager, the bottom status bar kept showing `75 items (38 directories, 37 files)` / `/home/wdna`. The dashboard view now shows its own summary: `N servers · X online · Y offline · Z unchecked` on the left and the active filter (`group: RAN` or `search: "foo"`) on the right.
- **`auth/models.py` committed.** The `User.totp_secret` / `User.totp_enabled` columns and the `ApiKey` model had been in use by `auth/routes.py` and `auth/service.py` since the 2FA / API-keys features shipped, but `auth/models.py` had never been rolled into a commit. A fresh `git clone` of `main` failed to start with `ImportError: cannot import name 'ApiKey' from 'webgate.auth.models'`. Docker Hub and fly.io kept working because those builds happened from the dirty working tree. Committing the file resolves the drift.

### Dashboard redesign (triggered by the fix above)

While fixing the overflow bug, the Site Manager's server list was redesigned to scale to fleets of dozens of servers without becoming a wall of buttons.

- **Compact cards with hover-reveal secondary actions.** Each server row now shows `SSH` and `SFTP` by default; `Split`, `Test`, `Edit`, and `Del` only appear when the row is hovered or selected. This drops the per-row visual weight from ~100 px with 6 visible buttons to ~55 px with 2 primary buttons, while keeping every action one hover away.
- **Sticky group headers in the sidebar.** When the "All Groups" filter is active and the fleet spans multiple groups, the list gets per-group headers (`CORE 12`, `RAN 20`, `STAGING 4` …) that stay pinned while you scroll. Per-card group pills are automatically hidden when the header is showing, since the grouping context is already visible.
- **Compact / comfortable density toggle** (`▦` / `▤` button in the sidebar header) persisted in `localStorage`. Compact mode hides host:port and all action buttons until hover — roughly doubles the number of servers visible per screen.
- **Server count next to the `Servers` heading** (`Servers (43)`) updates with the current filter.
- **Status bar filter context.** When a group filter or search is active, the right-hand status cell shows `group: <name>` or `search: "<query>"` so the current view state is always visible.

### Tests

- `test_health` was stale since v0.5.0 introduced HA (`instance_id` + `monitor_role` in the payload). Updated to assert the current shape instead of the original two-key response.

---

## v0.5.2 (2026-04-16) — Hardening

Defense-in-depth follow-ups to v0.5.1's security hotfix — no active exploit fixed here, but the attack surface is reduced.

### Hardening

- **Demo-mode write allowlist is now an exact (method, path) list** instead of a `startswith("/api/terminal/share/")` prefix. Previously any `POST /api/terminal/share/<anything-here>` slipped past the middleware; now only the two real share routes (`POST` and `DELETE /api/terminal/share/{session_id}`) plus login and totp/verify are allowed. Any future endpoint accidentally added under that prefix stays blocked unless its route is explicitly added.
- **`user_login_failed` webhook payload is now sanitized.** An unauthenticated attacker can hit `/api/auth/login` with any `username` string, which used to be dispatched verbatim to admin-configured webhook receivers (Slack, Discord, in-house). The dispatcher now strips non-printable characters (terminal escapes, NULLs) and truncates to 64 chars before emitting, so receivers that render the payload directly can't be targeted with control codes or HTML.

### Docs

- `CLAUDE.md`: corrected a stale line that described the access model as "each user sees only their own servers". The actual model is team-access-by-group: admins assign a server to a `group` and any user with that group in their `allowed_groups` can reach it. README already documented this correctly in the "Access model" section.

---

## v0.5.1 (2026-04-16) — Security hotfix

### Security (please upgrade)

Three authentication gaps fixed after a focused security review.

- **`must_change_password` is now enforced server-side**. Previously the flag was only surfaced by the UI; a valid JWT from a `admin/admin` first-run login let attackers hit every admin endpoint (`/api/auth/users`, `/api/servers`, audit log, ...) without ever changing the password. `get_current_user` now returns `403 Password change required` for any path other than `/api/auth/me` and `/api/auth/change-password` while the flag is `True`. *(Credit: user report on the public demo.)*
- **Pre-2FA "temp token" is now truly short-lived and scoped.** The `create_access_token({"pending_2fa": True, "exp_minutes": 2})` call ignored `exp_minutes` — the token got the full 24-hour session TTL, and no endpoint checked the `pending_2fa` claim, so the "temp" token bypassed 2FA completely. Fixed by: adding `expires_minutes` parameter to `create_access_token`, setting it to 2, and rejecting any token with `pending_2fa=True` on every endpoint except `/api/auth/login` itself.
- **API keys cannot bypass forced password change.** An account with `must_change_password=True` can no longer create or use an API key until the password has been rotated. Prevents workaround paths when an admin issues a temporary password.
- **Recording replay page no longer leaks the session token via Referer.** `GET /api/recordings/{id}/play` now sends `Referrer-Policy: no-referrer` and `Cache-Control: private, no-store`, and all third-party assets on the page (asciinema-player CDN) are fetched with `referrerpolicy="no-referrer"`.

### Docs

- README: screenshot sub-sections renamed to functional titles (jump host / snippets / shared terminal / session recording / demo mode) instead of release-pack labels, so the README always describes what the current version ships.

---

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
