# Advanced features

## Jump host (SSH bastion)

When the target server is only reachable from a specific bastion (not directly from webgate), pick the bastion from the **Jump Via** dropdown in the Add/Edit Server form. webgate opens the SSH connection to the bastion first and tunnels the target connection through it using `asyncssh`'s native `tunnel=` parameter. The same tunnel is used for the SFTP browser.

```mermaid
flowchart LR
    B["Browser"]
    WG["webgate"]
    BAST["bastion<br/>10.0.0.1"]
    INT["internal-app<br/>10.0.1.50"]
    B -- HTTPS/WSS --> WG
    WG -- SSH --> BAST
    BAST -- SSH (tunneled) --> INT
    style WG fill:#5cb85c,stroke:#449d44,color:#fff
    style BAST fill:#ffcc02,stroke:#e6a800,color:#333
```

The jump host must be registered in the server registry first so it has credentials. A cycle is prevented (server cannot point to itself); deeper chains (jumping through N bastions) are not supported yet — pick one.

## Command snippets

Named shell commands as buttons in the terminal toolbar. Click one and it is sent to
the active session, followed by Enter.

- **Create**: the `+` button in the toolbar
- **Use**: click the button
- **Delete**: right-click → confirm (only on snippets that are yours)

### Shared with the team

An admin can publish a snippet to everyone. Shared ones are marked with a dot and
listed first, because they are the agreed set; a personal snippet with the same name
then reads as the variation it is. Everyone can run them; only an admin can edit or
remove them.

Without this, a team's standard checks were something each person retyped from memory.

### Parameters

Write `{name}` anywhere in the command and you are asked for it before anything is
sent:

```
tail -n {lines} {file}
grep {pattern} /var/log/syslog
```

The same placeholder used twice is asked once. Cancelling any prompt cancels the whole
thing — a half-substituted command is never sent. `awk '{print $1}'` is left alone:
a placeholder has to start with a letter.

### Asking first

Mark a snippet **confirm** and it shows what will run, on which server, before sending.
Marked snippets carry a `!` in the toolbar.

A snippet runs the instant it is clicked and there is no undo, so anything that
changes a server — `systemctl restart`, a deploy, a truncate — should be marked.

## Shared terminal sessions

Click **🔗 Share** in the terminal toolbar of an active SSH session. A one-time URL is copied to your clipboard. Anyone you send it to will join the **same live PTY** — output is broadcast, input from any RW participant is multiplexed into the same `stdin`.

```mermaid
flowchart LR
    O["Owner WS"]
    J1["Joiner WS (rw)"]
    J2["Joiner WS (ro)"]
    SS["SharedSession"]
    PTY["asyncssh PTY"]
    O -- input --> SS
    J1 -- input --> SS
    J2 -. no input .-> SS
    SS -- write stdin --> PTY
    PTY -- stdout --> SS
    SS -- broadcast --> O
    SS -- broadcast --> J1
    SS -- broadcast --> J2
    style SS fill:#5cb85c,stroke:#449d44,color:#fff
```

The share URL includes a `?join=<token>` query param — if the joiner isn't logged in yet, they land on the login screen and are auto-attached after login. If you close the owner tab, all joiners disconnect.

!!! note "HA limitation"
    In a multi-worker deployment (see [HA deployment](ha.md)), the owner and joiner must land on the same worker for the session to match. Sticky-session routing mitigates this for same-browser cases; fully cross-worker sharing needs Redis pub/sub (not yet implemented).

## Session recording

Set `WEBGATE_RECORD_SESSIONS=true` and every SSH terminal session is captured to a standard [asciinema cast v2](https://docs.asciinema.org/manual/asciicast/v2/) file under `WEBGATE_RECORDINGS_DIR` (default `./recordings`).

A new **📹 Recordings** button appears in the top toolbar:

- **▶ Play** opens an embedded asciinema-player tab that streams the cast directly from the API
- **DL** downloads the `.cast` file — you can also `asciinema play ./session.cast` locally
- **Del** removes the DB row and the file

Non-admins see only their own recordings; admins see everyone's. The recorder is hooked into `SharedSession.broadcast`, so shared sessions are captured exactly once (not once per participant).

!!! tip "Compliance"
    The recording captures the full PTY output every participant saw — including pasted commands and environment — in a portable, vendor-independent format. Good enough for many audit/compliance requirements without investing in a heavier SIEM.
