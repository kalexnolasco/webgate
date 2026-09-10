# Settings

**Admin → Settings.** Changes take effect immediately, apply to every instance of the
gateway, and need no restart.

Anything an operator would reasonably want to change while the service is running lives
here: host key verification, session and transfer limits, how the status monitor
sweeps, session recording, and the whole LDAP configuration.

## Where a value comes from

Each setting shows its source next to the label:

| Badge | Meaning |
|---|---|
| `set here` | An admin changed it in this panel. It overrides the environment |
| `WEBGATE_…` | It came from that environment variable |
| `default` | Nothing set it; this is what webgate ships with |

An environment variable seeds a fresh install — which is what makes automated
provisioning work — and once a value is set in the panel, the panel wins. **Reset**
next to a setting drops the override so the environment applies again.

!!! tip "Configuration as code"
    Set `WEBGATE_CONFIG_LOCKED=true` and the panel becomes read-only: values are still
    shown, so an operator can see what is in force, but only the deployment can change
    them.

## What cannot be changed here

Some settings are read before webgate can serve the request that would change them, and
some would let the panel lock itself out. The panel lists them, with the reason, under
*Set by the deployment, not here* — `WEBGATE_SECRET_KEY` and `WEBGATE_DB_URL` are the
obvious ones: a key that decrypts the database cannot live inside it.

## Notes on individual settings

**Verify SSH host keys** is on, and should stay on. With it off, webgate connects to
whatever answers on a server's address and sends it the stored credentials. See
[Server management](servers.md).

**Maximum transfer size** applies to downloads as well as uploads: a download is read
into the gateway before being sent on, so a 2 GB log asks the gateway for 2 GB. Setting
it to `0` removes the limit and the protection with it. An oversized transfer is
refused with `413` and a message naming the file and the limit.

**Idle SSH timeout** counts input *and* output, so watching a long build scroll past is
not idleness. `0` disables expiry. Lowering it applies to sessions that are already
open.

**LDAP bind password** is encrypted at rest with the same key that protects server
credentials, and the API never returns it. The panel shows it as saved; leaving the
field blank keeps what is stored.

## Multiple instances

Settings live in the database, so every worker sees the same values. A change reaches
the others within about 15 seconds, when they next re-read. Nothing needs restarting
and no worker needs to be the leader.

## Audit

Every change is recorded in the audit log as `settings_update` (or `settings_reset`)
with the admin's name and which keys changed. The **values** are not logged — one of
them is a bind password.
