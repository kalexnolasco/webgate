# Upgrading

Stop, pull, start. The schema migrates itself on boot; there is no migration command to
run and no tool to learn.

=== "Docker"

    ```bash
    docker compose pull && docker compose up -d
    ```

=== "pip / uv"

    ```bash
    pip install --upgrade webgate   # or: uv pip install --upgrade webgate
    ```

Check what you got:

```bash
curl -s localhost:8443/openapi.json | jq -r .info.version
```

## Back up first

One file for SQLite, one command for PostgreSQL — or use webgate's own export, which
carries credentials, users, webhooks and branding in an encrypted bundle
(**Admin → Backup & restore**, or `POST /api/backup/export`).

```bash
cp webgate.db webgate.db.bak           # SQLite
pg_dump "$WEBGATE_DB_URL" > webgate.sql  # PostgreSQL
```

## What happens on boot

webgate compares the database to the schema it expects and adds what is missing, each
change in its own transaction, recording it in `schema_migrations`. Applying an
up-to-date database is a no-op, so restarting twice is safe.

If a change cannot be applied, **webgate stops** with a message naming it. It does not
start half-upgraded: a missing column would otherwise surface much later, at some
unrelated query, with nothing pointing back to the cause. Restore your backup and open
an issue.

## Rolling back

Schema changes are **additive only** — no column is ever dropped, renamed or retyped.
An older webgate ignores columns it does not know about, so downgrading works:

```bash
docker compose down && docker compose up -d   # with the previous image tag
```

The old version logs a warning that the database carries changes it does not recognise.
That is informational; it runs, and the extra columns sit unused.

!!! note "This is a guarantee, not an accident"
    The three properties the upgrade path rests on — additive, append-only,
    idempotent — are enforced by `tests/test_migrations.py`, which upgrades an aged
    database and compares the result against a fresh install. A change that would break
    an existing install fails CI. See [Contributing a
    migration](#contributing-a-migration).

## Multiple instances (HA)

Start them however you like. Workers race to apply the same change and losing that race
is the expected outcome, not an error. Every instance ends up on the same schema.

Roll one worker at a time if you want zero downtime; mixed versions are fine during the
rollout precisely because the schema is additive.

## Upgrading to v2.2.0

**If you never set `WEBGATE_SECRET_KEY`, webgate will now refuse to start.** That key
signs every session token and derives the key that encrypts stored SSH credentials, and
its default is published in this repository — anyone can mint an admin token for a
deployment still using it.

Setting a real key invalidates existing sessions and makes already-stored credentials
unreadable, so migrate deliberately:

1. **Before upgrading**, export a backup: **Admin → Backup & restore**, or
   `POST /api/backup/export`. The bundle is passphrase-encrypted and independent of the
   secret key, which is what makes this possible.
2. Set the key and start:

    ```bash
    export WEBGATE_SECRET_KEY=$(openssl rand -hex 32)
    docker compose up -d
    ```

3. Restore the backup. Servers, users and credentials come back, re-encrypted under the
   new key.

If you need to postpone, `WEBGATE_ALLOW_INSECURE_SECRET=true` starts anyway. It is an
explicit choice rather than a silent default, which is the whole point.

Binding to loopback only (`WEBGATE_HOST=127.0.0.1`) warns instead of refusing — trying
webgate out on your own machine should not need a ceremony.

## Upgrading to v2.0.0

Two changes are worth knowing about before you pull.

**Host key verification is on by default.** Existing servers have no pinned key, so the
next connection to each one records what it presents and nothing breaks. From then on a
changed key is refused, and accepting a new one is a deliberate admin action
(**Site Manager → the server → Clear pinned key**). To postpone it:

```bash
WEBGATE_VERIFY_HOST_KEYS=false
```

**The AI agent is off** until an admin sets a provider under **Admin → AI agent**. No
environment variable turns it on; it is configured in the UI and stored encrypted.

## Contributing a migration

Append a `(table, column, sqlite_def, postgres_def)` entry to `_MIGRATIONS` in
`src/webgate/db/engine.py`, add the matching column to the model, and add its
`(table, column)` pair to `FROZEN_HISTORY` in `tests/test_migrations.py`.

Three rules, all of them tested:

1. **Additive only.** Add a column. Never drop, rename or retype one — that is what
   makes rollback safe.
2. **Append only.** New entries go at the end. Existing databases already applied the
   earlier ones, so editing or reordering one makes the two disagree silently.
3. **Idempotent.** Applying the list to an up-to-date database does nothing.

Need to remove a column? Stop writing to it and leave it. Reclaiming the space is worth
less than an upgrade path that always works.
