# Changelog

## v2.8.0 (2026-09-17) — the editor knows what it is looking at

### Syntax highlighting, by file type

The editor had no language extension at all: `basicSetup` and nothing else, so a
Python script, an nginx config and a log file were the same undifferentiated grey.
The documentation had been claiming *"syntax highlighting (oneDark theme)"* the whole
time, which was the colour scheme for plain text and not highlighting of anything.

Around ninety languages now, through `@codemirror/language-data` — Python, shell,
JavaScript and TypeScript, JSON, YAML, TOML, SQL, Go, Rust, PHP, Perl, Ruby, Lua,
PowerShell, Dockerfile, **nginx** and the rest. Each grammar is fetched only the
first time a file wants it, so a gateway whose users never open a `.rs` never
downloads the Rust parser.

Four things are tried, in order, and the one that won is shown next to the filename —
so a file that is not highlighted reads as *not recognised* rather than as a guess:

1. **The filename**, which settles almost everything.
2. **Template suffixes peeled off**, so `nginx.conf.j2` and `settings.py.tmpl` are
   highlighted as what they will become.
3. **Server conventions** the upstream list does not carry: `.conf`, `.cfg`, `.env`,
   systemd units, apt and yum lists.
4. **The shebang**, for the scripts in `/usr/local/bin` with no extension at all.

### Opening a binary and pressing Save no longer destroys it

Reading a file for the editor decoded with `errors="replace"`, so an executable, an
archive or a database came back as a wall of U+FFFD — with a **Save** button beside
it. Saving wrote those replacement characters back over the real contents. Nothing
warned anybody, and the file was gone.

Binary files and text that is not UTF-8 are now refused. The file is named, the
reason is on screen where the file would have been, and a **Download** button is next
to it. The same panel now handles a file too large for the browser to hold, and one
over the gateway's transfer limit.

That limit is also the other half of this: `/read` was the one read path with no
budget, so the editor was the way around the ceiling every other transfer answers to.

### The editor follows the interface theme

`oneDark` was hardcoded, which left a black rectangle in the middle of the light
interface. It switches with the theme button now, without reopening the file.

### Scrollbars: the app's own styling was cancelling itself

Since Chromium 121, an element that has `scrollbar-color` or `scrollbar-width` has
its `::-webkit-scrollbar` rules ignored. The stylesheet set both, so Chrome, Brave and
Edge threw away the 10px rounded thumb and drew the 15px native bar with arrow
buttons on every scrolling surface. It showed worst on a terminal, where xterm always
reserves the bar — so a session with no history at all had a scrollbar widget down
its right-hand side.

Measured rather than assumed, in a real window of each engine:

| | Chromium 153 | Firefox 145 |
|---|---|---|
| both, as shipped | 15px | 12px |
| the fix | **10px** | **6px** |

Firefox keeps the standard properties, which are all it understands, and goes from a
platform-dependent bar to a consistent thin one.

### Tests

354 → 375. Ten unit tests on what the editor may open, and seven browser tests:
syntax highlighting, shebang detection, the binary refusal, the editor theme, and
three on scrollbars including one that measures a real terminal.

`WEBGATE_E2E_HEADED=1` runs the browser suite in a real window — headless Chromium
draws overlay scrollbars that take no layout space, so anything measuring one has to
be run that way. The tests say what they skipped rather than passing on nothing.

### Upgrading

Nothing to do beyond the upgrade itself: no schema change, no settings change. One
behaviour change worth knowing: a file that used to open as garbage in the editor now
refuses to open, and offers a download instead.

## v2.7.1 (2026-09-17) — the terminal takes what you type

Two defects that the interface hid rather than showed: in both cases the screen said
the feature was working and the code that would have done it was unreachable.

### The terminal never took the focus

Open an SSH session and the prompt appeared, the connection bar said connected, and
every keystroke went nowhere — no echo, no command on Enter. It only started
responding after a click inside the terminal area, and stopped again on the way back
from another tab.

xterm reads keystrokes from a hidden textarea, and nothing in the frontend had ever
called `focus()`. The keys went to `<body>` and `onData` never fired. The socket was
open throughout, which is why it looked like a backend problem and was not one.

The focus is now handed over on every path that puts a terminal in front of someone:

- **opening one**, after the fit rather than before it;
- **switching back to its tab** — which also re-fits `split` tabs, missed by the old
  `=== 'terminal'` check even though a split carries a terminal too;
- **closing the tab in front of it** and landing on one;
- **running a snippet**, which had left the focus on the button it was clicked with;
- **a session coming back** after a drop.

Only the last of those is focus nobody asked for, so it is the only one that defers:
it leaves the caret where it is if a field, an editor or a dialog has it.

Now that terminals hold the focus, the keyboard shortcuts see an input. That is right
for Ctrl+N, Ctrl+P and Ctrl+K — readline bindings the shell owns, which is why the
command palette already had Ctrl+Shift+P. Ctrl+1 means nothing to a shell, so it still
reaches the app from inside a terminal.

### Snippet parameters and confirmation had been dead since v2.3.0

`runSnippet` was defined twice in the same object, so the later one won — and it was
the version from before v2.3.0, which sends the command straight to the socket.
Everything that release added was therefore inert:

- **`{parameter}` placeholders were never filled in.** The literal text `{host}` went
  to the shell.
- **`confirm` never asked.** A snippet flagged as needing confirmation — the flag
  exists precisely for the ones that change a server — ran the moment it was clicked,
  with no prompt and no undo.

The `!` marker was painted and the tooltip said *asks before running* the whole time.

### Tests

Four browser tests that type at the page and never at the terminal, covering a plain
SSH tab, coming back to it from the Site Manager, a split tab, and a real reconnection
landing while the caret is in the Quick Connect field. Three of them fail on v2.7.0
with the remote prompt on screen and nothing after it.

Browser tests: 9 → 13. Total: 354 → 358.

### Upgrading

Nothing to do beyond the upgrade itself: no schema change, no settings change.

## v2.7.0 (2026-09-17) — single sign-on

LDAP already existed, but no company running Entra ID, Okta or Google Workspace is
going to keep a second directory for one tool. It was the first thing anyone asked
about, and the thing most likely to decide whether webgate gets deployed at all.

### Single sign-on (OpenID Connect)

**Admin → Settings → Single sign-on**, alongside local accounts and LDAP rather than
instead of them. Register one redirect URI with your provider, fill in the issuer,
client ID, secret and scopes, and everything else — the endpoints, the signing keys —
comes from the provider's discovery document.

- **The ID token is actually verified**: signature against the provider's published
  keys, plus issuer, audience, expiry, and a nonce tied to that one sign-in, so a token
  captured from another flow cannot be replayed into this one. A token that merely
  decodes proves nothing.
- **Authorization code with PKCE**, so it is safe with or without a client secret.
- **The in-progress sign-in lives in the database**, not in worker memory. The browser
  can come back to a different worker than the one it left, which is the whole point of
  the stateless design.
- **The session token never travels in a URL.** The callback hands the page a one-time
  code, good for about a minute, which it trades for a session — so nothing sensitive
  reaches browser history or a proxy log.
- **A provider group grants nothing until an admin maps it**, exactly as LDAP works. A
  directory group created next month cannot quietly open a webgate group that happens
  to share its name. A separate admin-groups list grants admin.
- Sign-ins are audited as `sso_login`, with the groups granted.
- Accounts created this way have **no local password** — nothing to reset, nothing to
  leak.

Twenty-one tests, run against a real identity provider started for the test: it
publishes a discovery document and a JWKS and signs its own tokens, so the
verification is exercised rather than mocked away. A token signed with the wrong key,
issued for another audience, expired, or carrying another sign-in's nonce is refused,
and each of those is a test.

[Setup, and what to do when nobody gets any groups](https://kalexnolasco.github.io/webgate/guide/sso/).

354 tests: 345 unit, 9 browser.

---

## v2.6.0 (2026-09-16) — rotating the secret key no longer breaks everything

### Fixed

- **A changed `WEBGATE_SECRET_KEY` made webgate fall over instead of explaining
  itself.** v2.2.0 refuses the shipped default, which asks every existing install to
  set a real one; doing that leaves rows encrypted under the old key. `decrypt_value`
  raised a bare Fernet error from twelve call sites and none of them caught it. The
  status monitor died on its first sweep and froze every server's dot; opening a
  terminal failed the WebSocket **upgrade**, so the browser got a 500 with nothing in
  it. Found on the public demo, by walking into it.

  An unreadable credential is now its own error, naming the server, why it happened
  and what to do. The monitor marks that one server offline and carries on, the
  terminal answers with an error frame, SFTP returns 502, and a connection test
  reports it.

- **The demo banner covered the top of the interface.** It was `position: fixed` with
  nothing making room for it, so the app bar sat underneath. It is in flow now, which
  also holds when it wraps to two lines on a narrow screen. Only visible with
  `WEBGATE_DEMO_MODE=true`, which is why no test caught it.

- **Diagrams that did not show.** Nine style directives set a pale fill and left the
  label to the theme, so on GitHub's dark background they were light text on a light
  box. All 21 diagrams in the repository now render, and every label is readable on
  both grounds — checked with the Mermaid version GitHub actually uses, in a browser,
  one diagram per page.

### Added

- **The pinned host key is visible.** The fingerprint has been in the API since
  v2.0.0 and nothing showed it. Servers carry a shield when a key is pinned, the edit
  form shows the fingerprint, and an admin can clear it there — with the consequence
  spelled out, since accepting a new key is the one moment the protection is stood
  down.
- **A cap on concurrent SSH sessions per account** (**Admin → Settings → Security**,
  0 for none). There was nothing stopping a looping tab from opening sessions until
  the worker ran out. Checked before the SSH connection is made, and counted per
  worker — which the setting says, because a gateway behind a load balancer allows
  that many on each.

333 tests.

---

## v2.5.0 (2026-09-16) — browser tests

The audit gap in v2.4.0 was reported by a person using the interface, and no test in
this repository could have found it: the suite exercised the API, and the API was never
the part that was wrong. There are now tests that drive the actual browser.

### End-to-end suite

`tests/e2e` starts a real webgate against a throwaway database, a real SSH/SFTP host,
and a real Chromium, then uses the interface the way a person does. The one that
matters selects a file in the browser, clicks **Delete**, checks the file is gone from
the host, opens the audit panel, searches for its name and asserts the entry names the
file, the server and the account.

- Opt-in — they start two servers, so `pytest tests/` still runs only the unit suite.
  `pytest tests/e2e -m e2e` runs these.
- The SSH lab that made this possible moved out of a scratch directory and into
  `tests/e2e/sshlab.py`, so the suite is self-contained and runs in CI.
- A page that throws while a test clicks around fails that test, even if every
  assertion passed. The frontend has no build step and no type checker behind it.
- **The screenshots in the documentation are taken by these tests**, from the build
  they just drove. They can no longer drift into showing an interface that does not
  exist — which is exactly what had happened by v2.1.2, when every shot was from v0.3.

### Found while writing them

- **Signing in nine times in a row trips webgate's own rate limit**, ten attempts a
  minute from one address, and the suite then fails on the login screen with nothing to
  say about the feature under test. The tests sign in once and reuse the session, which
  is also what a person does.
- Two of the first failures were the tests, not the app, and worth recording because
  the same shape will catch the next person: `.fz-modal` matches every modal, since they
  all sit in the DOM and only hide with `x-show`; and the first row of a file listing is
  the `..` entry, which is never visible at the root.

### CI

A fourth job installs Chromium and runs the browser suite on every push, and uploads
the screenshots it took. A Dockerfile only breaks when someone builds it; an interface
only breaks when someone uses it.

320 tests: 311 unit, 9 browser.

---

## v2.4.0 (2026-09-16) — the audit log records what happened

Reported by a user: someone deleted a file and the log did not say which one.

The truth was worse. **`files/routes.py` contained no audit call at all** — not for
delete, not for upload, rename, write, mkdir, chmod or download. No SFTP operation was
recorded in any form. Two of them fired a webhook, which is why anything was seen at
all. A log that says something happened without saying what is the same as no log.

Registry and account changes had the same hole: of everything an admin can do, only
clearing a host key pin and signing in were ever written down. Creating a server,
deleting one along with its stored credentials, creating an account, moving somebody
between groups, resetting a password — none of it left a trace.

### Now recorded

Every entry names the account, the action, what it touched, the time and the originating
IP.

- **Every SFTP operation**, with the server and the full path. A rename records both
  names, a chmod records the mode, a ZIP download records what went into it. Taking a
  copy of a file now leaves the same trace as deleting it.
- **Registry changes** — created, updated, deleted. An update records **which fields**
  changed and never their values, because one of them is a password. Deleting a server
  says that its stored credentials went with it.
- **Account changes** — created, deleted, groups changed (before and after), password
  reset. These are changes to who can reach the fleet.

Directory listings and file previews are deliberately left out: they are high volume and
low signal, and burying a delete under ten thousand `ls` entries makes the log worse.

### Finding an entry

Filtering was exact-match on username or action, which is no use to someone holding a
filename and no idea what happened to it.

- **Search matches the detail**, as well as the user and the action, case-insensitively.
  Type `nginx.conf` and see everything that touched it.
- **Filter by action** from a list of the kinds actually present, rather than guessing a
  name.
- **Filter by date**, and see how many entries matched.
- `GET /api/auth/audit` takes `search`, `since` and `until`; `GET /api/auth/audit/actions`
  lists the kinds.

311 tests.

---

## v2.3.0 (2026-09-12) — snippets that are worth clicking, recordings that survive

### Upgrading

Stop, pull, start. Two columns are added; nothing changes behaviour on its own.

One thing to know: **session recording is now opt-in per server.** If you had
`WEBGATE_RECORD_SESSIONS=true`, recording continues to be *allowed* but no server
records until you enable it on that server (**edit the server → Record SSH sessions**).
That is deliberate — a sandbox and a production bastion were being held to the same
policy by accident.

### Fixed

- **Session recordings were broken in the deployment this project documents.** Each
  worker wrote casts to its own container filesystem while the database stored an
  absolute path, and any worker could be asked to replay one. Behind the two workers of
  `compose.ha.yml` — which shares a volume for PostgreSQL and nothing else — roughly
  **half of all replays returned 404**, and replacing a container took the evidence with
  it. The module had no tests at all, which is how it shipped.

  A finished cast is now stored, gzipped, in the database. The live session still writes
  locally, because the PTY genuinely is on that worker; only the finished artefact needs
  to travel. Recordings made before this release still play if their file is still
  there, and say clearly why they cannot when it is not.

  Backups carry recordings from now on, since the backup already covers the database.

### Session recording

- **Off by default, and opted into per server**, the same shape the AI agent already
  uses: the gateway allows it, each server chooses. Recordings capture everything typed
  and printed, secrets included, so "everywhere or nowhere" was the wrong granularity.
- **A size cap per session** (25 MB by default, in the admin panel). A recording that
  reaches it stops and writes that into the cast itself — a replay that simply ends
  looks like a crash, which is worse than a truncated one that says so.
- **Fourteen tests**, where there were none.

### Command snippets

Saved commands existed: a button in the terminal toolbar that sends a command and
Enter. Three things it could not do, each of which mattered.

- **Shared with the team.** A snippet belonged to one user, so a team's standard checks
  were something every member retyped from memory. An admin can publish one to
  everyone; shared snippets are marked and listed first, and only an admin can edit or
  remove them.
- **Parameters.** `{lines}`, `{file}`, `{pattern}` anywhere in the command are asked for
  before anything is sent. The same placeholder twice is asked once, cancelling any
  prompt sends nothing, and `awk '{print $1}'` is left alone.
- **Asking first.** A snippet marked *confirm* shows the command and the server before
  running, and carries a `!` in the toolbar. A snippet runs the instant it is clicked
  and there is no undo on `systemctl restart nginx`.
- Snippets can now be **edited**; previously the only options were create and delete.

298 tests.

---

## v2.2.0 (2026-09-11) — stability pass

A release aimed at being deployable rather than at adding anything. One real bug, one
security default closed, and the quality gates made honest.

### Upgrading

**If you never set `WEBGATE_SECRET_KEY`, webgate will now refuse to start.** Read
[Upgrading](https://kalexnolasco.github.io/webgate/getting-started/upgrade/) before you
pull: setting a real key makes already-stored credentials unreadable, so it needs a
backup and restore, not just a restart. `WEBGATE_ALLOW_INSECURE_SECRET=true` postpones
it; binding to loopback only warns instead of refusing.

### Security

- **The shipped default secret key is no longer accepted on a reachable address.** That
  key signs every session token and derives the Fernet key protecting every stored SSH
  password and private key — and it is published in this repository. A deployment that
  never changed it hands a valid admin token to anyone who asks for one, and decrypting
  its credential store needs no secret at all. Nothing checked. The failure was
  invisible, because everything worked.

  This is not hypothetical: during development, a token minted against one instance
  authenticated against a completely different database on the same machine, because
  both signed with the same published key and the user ids collided.

  webgate now stops at startup and prints what to do. On a loopback-only bind it warns
  instead, because trying it out on your own machine should not need a ceremony.

### Fixed

- **Webhook deliveries could vanish.** They were scheduled with
  `asyncio.create_task` and the task was never referenced, so the event loop held only a
  weak reference to it. A delivery could be garbage-collected mid-flight and disappear
  with no error in any log — the worst shape a failure can take. In-flight deliveries are
  now held until they finish.
- **Command output that is not valid UTF-8 no longer breaks an agent investigation.**
  asyncssh returns `str` or `bytes` depending on the connection's encoding; the two were
  concatenated directly.

### Quality

- **`ruff check src/ tests/` is clean**, from 33 findings: a dangling task, five
  `try/except/pass` blocks that should have been `contextlib.suppress`, seven imports
  sitting below module-level code, a collapsible branch, and nineteen over-long lines.
- **The login flow states its invariant instead of assuming it.** Ten separate places
  read attributes off a user the type checker could not prove was non-`None`. It always
  was; now it is checked, and it fails closed if that ever changes.
- **Model registration is explicit.** `_import_models()` used eleven imports whose only
  purpose was their side effect, which reads as dead code to every linter. It now walks a
  named list, and the test that guards it checks that list.
- **The README no longer documents a type-check gate that has never passed.** pyright
  runs in strict mode with ~100 findings, about 80 of them `reportUnknown*` from
  asyncssh and ldap3 shipping no type information. Said plainly, with the advice to watch
  the count rather than expect zero.

Every runtime-risk finding the type checker reported was checked against the running
code rather than assumed: the QR-code call and the agent result assignment it flagged
are stub errors, and are unchanged.

264 tests.

---

## v2.1.2 (2026-09-11) — the README stops describing an older product

Documentation only. No code, schema or API changes.

The README had been patched release by release and had drifted into describing a
product that no longer exists.

- **Every screenshot was from v0.3 or v0.4**, with a note admitting the interface had
  been redesigned since. Replaced with ten taken from v2.1.1 — the Site Manager, a real
  SSH session opened through a bastion, the file browser, the command palette, and the
  admin panels for settings, the agent, branding and users, in both themes. The terminal
  and file shots are live sessions against an SSH host, not mockups.
- **v0.x is now marked legacy and unsupported**, with the reason stated plainly: every
  connection it makes runs with host key verification disabled. The section also explains
  why there is no v1.x.
- **Instructions that stopped being true.** Session recording was still documented as
  `WEBGATE_RECORD_SESSIONS=true`; LDAP group mapping and admin groups were still
  described as environment variables. All three moved to the admin panel in v2.1.0.
- **The API reference was missing three routers** — settings, agent and branding.
- **The `beta` badge** is gone; `compose.yml` no longer offers to uncomment settings that
  are now configured in the app.

---

## v2.1.1 (2026-09-11) — architecture documentation

Documentation only. No code, schema or API changes; upgrading is optional.

- **[Architecture](https://kalexnolasco.github.io/webgate/architecture/) is a page now**, with five diagrams: what talks to
  what and in which direction, the module map, an SSH session *including the branch that
  refuses*, the multi-instance topology, and how a setting resolves between the
  environment and the admin panel. It also records the four constraints the rest of the
  design follows from.
- **The README's module tree was two releases stale.** It listed neither the agent,
  backup, branding nor runtime settings modules, and none of `hostkeys.py`, `limits.py`
  or the migration engine.
- **The README's request-lifecycle diagram was wrong**, not merely incomplete: it showed
  a connection path with no host key verification in it, which has not been true since
  v2.0.0. Replaced with an accurate one that shows the trust boundary and the outbound-only
  direction of travel.

---

## v2.1.0 (2026-09-10) — admin settings panel

### Upgrading

Stop, pull, start, as always. The settings table is created on boot; there is no
migration, which is the point of storing settings as key/value rather than a column
each. Nothing changes behaviour until an admin sets something: every setting starts at
whatever your environment already configures.

```bash
docker compose pull && docker compose up -d
```

Two of the settings that now work were previously ignored, so their configured values
start applying:

- **`WEBGATE_MAX_UPLOAD_SIZE`** (default 100 MB) now limits downloads as well as
  uploads. If you move large files through webgate, raise it before upgrading, or set
  it to `0` to keep the old unlimited behaviour.
- **`WEBGATE_SESSION_TIMEOUT`** (default 3600) now closes idle SSH sessions. `0`
  disables it.


Configuration moves out of the environment and into the app. **Admin → Settings** now
owns 19 settings across security, monitoring, recording and LDAP; they take effect
without a restart and apply to every instance.

### Settings panel

- **A value set in the panel overrides the environment**, and an environment variable
  still seeds a fresh install, so automated provisioning keeps working. Each setting
  shows where its value came from — the panel, a named variable, or the shipped
  default — and can be reset back.
- **`WEBGATE_CONFIG_LOCKED=true` makes the panel read-only**, for deployments whose
  configuration is managed as code. Values stay visible so an operator can see what is
  in force.
- **Settings are stored as key/value, not a column each.** Adding one needs no
  migration, which is what keeps the upgrade contract cheap to honour.
- **The panel is generated from a registry**, so a new setting appears in the UI with
  no HTML change, and the same entry supplies its validation.
- **The LDAP bind password is encrypted** with the key that protects server
  credentials, and the API never returns it. Saving the form again with the field blank
  keeps what is stored rather than wiping it.
- **A batch is validated before anything is written**, so one bad value cannot leave
  the panel half-applied. Changes are audited by key; the values are not logged.
- **What cannot be moved is listed, with the reason.** `WEBGATE_SECRET_KEY` decrypts
  what is in the database and so cannot live there; `WEBGATE_DEMO_MODE` would block the
  writes needed to turn it off. An admin hunting for a missing knob finds out why.

### Six settings that did nothing

Each was documented in the README, accepted from the environment, and read by no code
at all. They are now real.

- **`max_upload_size`** — there were no size checks anywhere. Downloads read the whole
  file into memory, uploads read the whole body, and a ZIP accumulated an entire
  directory tree, so one person fetching a 2 GB log asked the gateway for 2 GB and took
  the worker down with every session on it. Transfers are now chunked against a budget
  and refused with `413` and a message naming the file, the limit, and where to change
  it. A ZIP that runs over fails rather than arriving quietly incomplete.
- **`session_timeout`** — an abandoned tab held an SSH session, and the credentials
  behind it, open for as long as the gateway ran. Sessions now close when idle, counting
  output as well as input so watching a long build is not idleness. Lowering the limit
  reaches sessions that are already open.
- **`monitor_interval`, `monitor_timeout`, `monitor_concurrency`** — the monitor used
  hardcoded constants. The leader's lease now stretches with the interval, which the
  constants used to guarantee implicitly; without that, raising the interval would have
  made the leader drop its own lease mid-sweep. Turning the monitor off no longer needs
  a restart.
- **`first_run`** — documented as suppressing the default `admin`/`admin` account. It
  was created regardless.

### Fixes

- **The test suite was writing to the developer's real database.** Several modules hold
  their own reference to the global session factory and so bypassed the fixture's
  override: every audit entry, webhook lookup and settings read during a test went to
  whatever `WEBGATE_DB_URL` pointed at. Test users `plain`, `viewer` and `dev2` had
  accumulated hundreds of audit rows in a real install. No test could assert on audit
  behaviour either, which is why none did.
- **Tables in tests are registered the way production registers them**, so the test
  schema is a fresh install's schema rather than whatever the imports happened to pull
  in.

---

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
