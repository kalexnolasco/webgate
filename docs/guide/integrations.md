# Integrations

## Webhooks

Admins can register HTTPS endpoints that receive a JSON POST when significant events fire:

| Event | Fires on |
|---|---|
| `user_login` | Successful authentication (local or LDAP) |
| `user_login_failed` | Wrong username or password; payload username is sanitized (see below) |
| `ssh_connect` | A user opens an SSH terminal to a registered server |
| `sftp_upload` | Files uploaded via the SFTP browser |
| `sftp_delete` | Files / folders deleted via the SFTP browser |
| `server_added` | Admin creates a new server |
| `server_deleted` | Admin removes a server |
| `server_offline` | The monitor could not reach a server (see below) |
| `server_online` | It answered again |

### Being told when a server goes down

The monitor has always known -- it probes every server on a timer -- and it only ever
painted a dot with what it found, so an outage was noticed by whoever happened to be
looking at the screen.

`server_offline` fires after **Admin -> Settings -> Monitoring -> Failures before
alerting** consecutive failed checks, two by default. One lost packet is not an outage,
and alerting on it is how people learn to ignore alerts. `server_online` fires on the
first check that succeeds again: waiting to be sure a host is *back* helps nobody.

Only a **change** is announced, so a host that stays down is reported once, not on
every sweep. A restart does not announce the whole fleet as up -- but a server that is
already down when the gateway starts is reported, because nobody was told yet.

Both carry the server, its hostname, the error where there is one, and how many checks
had failed:

```json
{
  "event": "server_offline",
  "data": {
    "server": "prod-web-01", "hostname": "10.0.0.7", "port": 22,
    "online": false, "error": "Connection refused",
    "failed_checks": 2, "checked_at": "2026-09-17T13:40:02+00:00"
  }
}
```

Only the instance holding the monitor lease sweeps, so a multi-instance deployment
sends one alert, not one per worker.

### Payload and signing

```
POST https://your-receiver.example.com/wh
Content-Type: application/json
X-Webgate-Signature: sha256=<hmac of body using the webhook's secret>
User-Agent: webgate-webhook/1.0

{
  "event": "ssh_connect",
  "timestamp": "2026-04-16T08:00:00Z",
  "data": {
    "user": "alice",
    "server": "prod-web-01",
    "host": "10.0.1.50:22",
    "via_jump": true
  }
}
```

The HMAC-SHA256 is computed with the per-webhook secret you configured. Receivers should use a constant-time compare (`hmac.compare_digest` in Python) to verify.

### Security of the dispatcher

- Delivery is fire-and-forget — a slow receiver never blocks the caller
- The `user_login_failed` payload sanitizes the attacker-controlled `username`: non-printable characters are stripped and the value is truncated to 64 chars, so a receiver that renders the field verbatim can't be targeted with terminal escapes or HTML
- Each webhook row records `last_fired_at` and `last_status` so admins can see delivery health from the UI

## LDAP / Active Directory

Enable with `WEBGATE_LDAP_ENABLED=true` and login falls back to LDAP after the local credential check. On success, the local `User` row is auto-provisioned or refreshed, and `allowed_groups` + `is_admin` are derived from LDAP group memberships via the mapping env vars.

```mermaid
sequenceDiagram
    participant B as Browser
    participant W as webgate
    participant L as LDAP
    B->>W: POST /api/auth/login (alice, ****)
    W->>W: try local password (miss)
    W->>L: bind(svc-DN, svc-password)
    L-->>W: ok
    W->>L: search(uid=alice) under user_base
    L-->>W: dn=uid=alice,ou=people,...
    W->>L: re-bind(user-DN, user-password)
    L-->>W: ok ✅
    W->>L: search(member=user-DN) under group_base
    L-->>W: [devs, admins]
    W->>W: map → allowed_groups, is_admin
    W->>W: upsert local User row
    W-->>B: JWT
```

See [access model](access-control.md) for how the LDAP group mapping turns into webgate `allowed_groups`.

### Config

| Variable | Default | Description |
|---|---|---|
| `WEBGATE_LDAP_ENABLED` | `false` | Enable LDAP fallback after local check |
| `WEBGATE_LDAP_URL` | `` | `ldap://host:389` or `ldaps://host:636` |
| `WEBGATE_LDAP_BIND_DN` | `` | Service account DN |
| `WEBGATE_LDAP_BIND_PASSWORD` | `` | Service account password |
| `WEBGATE_LDAP_USER_BASE` | `` | e.g. `ou=people,dc=example,dc=com` |
| `WEBGATE_LDAP_USER_FILTER` | `(uid={username})` | AD: `(sAMAccountName={username})` |
| `WEBGATE_LDAP_GROUP_BASE` | `` | Empty skips group lookup |
| `WEBGATE_LDAP_GROUP_FILTER` | `(member={dn})` | AD nested: `(member:1.2.840.113556.1.4.1941:={dn})` |
| `WEBGATE_LDAP_GROUP_MAP` | `{}` | JSON `{"ldap-cn":"webgate-group"}` |
| `WEBGATE_LDAP_ADMIN_GROUPS` | `[]` | JSON list of LDAP CNs that grant admin |

### Implementation notes

- Search-then-bind flow with proper RFC 4515 filter-value escaping
- All `ldap3` calls run in `asyncio.to_thread` to avoid blocking the event loop
- Local accounts (admin, API keys, 2FA) keep working as before — LDAP is only consulted after a local-credential miss
- Re-login refreshes admin status and group mapping from LDAP every time

## API keys

Admins and users can generate long-lived bearer tokens for non-interactive use (scripts, CI/CD, cron):

```bash
curl -H "Authorization: Bearer wg_<your-key>" \
     https://webgate.example.com/api/servers
```

Manage them from the **Keys** button in the top toolbar. Keys inherit the owning user's `allowed_groups` and `is_admin` status. Since v0.5.1, API keys cannot bypass a forced password change (`must_change_password=True`) — the owner has to rotate their password before the key becomes usable.

## Prometheus metrics

`GET /metrics` returns the standard text exposition. It is **admin-only** and
authenticated like everything else, because it names every server in the registry --
an API key from **Admin -> API keys** is the right credential for a scraper, since it
is revocable and shows up in the audit log.

```yaml
scrape_configs:
  - job_name: webgate
    metrics_path: /metrics
    authorization:
      credentials: wg_your_api_key_here
    static_configs:
      - targets: ["webgate.internal:8443"]
```

| Metric | |
|---|---|
| `webgate_info{version,instance}` | Always 1; the labels are the point |
| `webgate_monitor_leader` | 1 on the instance running the monitor, 0 elsewhere |
| `webgate_terminal_sessions` | Live SSH sessions **on this instance** |
| `webgate_servers_total`, `webgate_users_total` | Registry and account counts |
| `webgate_server_up{server}` | 1 if the last check reached it |
| `webgate_server_latency_seconds{server}` | The last successful connection; absent while offline |
| `webgate_servers_online`, `webgate_servers_offline` | Fleet totals |

Two things to know before building a dashboard on this:

- **Session counts are per instance.** Sessions live in memory beside the PTY they
  belong to. Sum them across instances.
- **The fleet gauges come from one instance.** Only the monitor leader has any
  statuses; the others omit the `webgate_server_*` series entirely rather than
  reporting zeroes, which would read as a fleet-wide outage. `webgate_monitor_leader`
  says which instance they came from.

## Reverse proxy

webgate runs behind any modern HTTP reverse proxy. TLS termination is recommended in production.

For sub-path deployments (e.g. `https://example.com/webgate/`), set `WEBGATE_ROOT_PATH=/webgate` and **forward the prefix unchanged** — webgate handles `/webgate/api/...` natively.

Configs for nginx, Apache 2.4, Caddy and Traefik are in the [README](https://github.com/kalexnolasco/webgate#behind-a-reverse-proxy-with-tls).
