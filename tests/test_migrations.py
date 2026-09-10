"""The upgrade path.

These tests exist so that a future release cannot break an existing install. They
lock the three properties the whole scheme rests on -- additive, append-only,
idempotent -- and prove the interesting cases end to end: an old database reaching
the current schema with its rows intact, a genuinely broken migration stopping
startup instead of being swallowed, and two HA workers racing to apply the same
change.
"""

import inspect
import re
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

import webgate.db.engine as E
from webgate.db.engine import MigrationError, migration_name

SRC = Path(__file__).resolve().parents[1] / "src" / "webgate"

# The migrations released up to and including v2.0.0. New entries are APPENDED; this
# list is history and never changes. A database that applied these is entitled to
# keep working, so reordering or editing an entry here is a silent schema divergence.
FROZEN_HISTORY: list[tuple[str, str]] = [
    ("servers", "sftp_read_only"),
    ("users", "totp_secret"),
    ("users", "totp_enabled"),
    ("servers", "jump_via_id"),
    ("servers", "agent_enabled"),
    ("servers", "host_key"),
    ("agent_settings", "context_budget"),
    ("agent_settings", "cache_ttl"),
    ("agent_settings", "findings_retention_days"),
]


@pytest.fixture
async def sandbox(tmp_path, monkeypatch):
    """Point the module-global engine at a throwaway file database."""
    path = tmp_path / "upgrade.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{path}")
    monkeypatch.setattr(E, "engine", eng)
    yield path
    await eng.dispose()


def _schema(path: Path) -> dict[str, set[str]]:
    conn = sqlite3.connect(path)
    tables = [
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not r[0].startswith("sqlite_")
    ]
    return {t: {c[1] for c in conn.execute(f'PRAGMA table_info("{t}")')} for t in tables}


def _make_old(path: Path) -> list[tuple[str, str]]:
    """Age a current database by removing migrated columns; returns what was removed.

    `servers.jump_via_id` survives: sqlite refuses to drop a column named in a foreign
    key, and it references servers(id) itself. Every other migration is exercised.
    """
    conn = sqlite3.connect(path)
    removed = []
    for table, column, _, _ in E._MIGRATIONS:
        try:
            conn.execute(f'ALTER TABLE "{table}" DROP COLUMN "{column}"')
            removed.append((table, column))
        except sqlite3.OperationalError:
            pass
    conn.execute(f"DROP TABLE IF EXISTS {E.RECORD_TABLE}")
    conn.commit()
    return removed


# ------------------------------------------------------------------ the contract


def test_the_history_is_append_only():
    """Existing databases already applied these; editing one makes the two disagree."""
    current = [(t, c) for t, c, _, _ in E._MIGRATIONS]
    assert current[: len(FROZEN_HISTORY)] == FROZEN_HISTORY, (
        "Migrations are append-only. Add new entries at the end of _MIGRATIONS; "
        "never reorder, edit or delete an existing one."
    )


def test_every_migration_only_adds():
    """A drop or rename would strand every older webgate still running."""
    forbidden = re.compile(r"\b(drop|rename|delete|truncate|alter|update|insert)\b", re.I)
    for table, column, sqlite_def, pg_def in E._MIGRATIONS:
        for definition in (sqlite_def, pg_def):
            assert not forbidden.search(definition), f"{table}.{column} is not additive"
            assert ";" not in definition, f"{table}.{column} smuggles a second statement"


def test_no_column_is_migrated_twice():
    names = [migration_name(t, c) for t, c, _, _ in E._MIGRATIONS]
    assert len(names) == len(set(names))


def test_every_model_table_is_registered_for_creation():
    """A model in a module nobody imports is a table that never gets created.

    This reads the source of `_import_models` rather than `Base.metadata`, which any
    other test module can populate by importing a model itself -- that would make the
    guard pass or fail depending on test order.
    """
    modules = sorted(
        {
            path.relative_to(SRC.parent).with_suffix("").as_posix().replace("/", ".")
            for path in SRC.rglob("*.py")
            if "__tablename__" in path.read_text("utf-8")
        }
    )
    assert modules, "found no models at all; the search is wrong"

    source = inspect.getsource(E._import_models)
    for dotted in modules:
        package, _, name = dotted.rpartition(".")
        pattern = rf"from\s+{re.escape(package)}\s+import\s+[^\n]*\b{re.escape(name)}\b"
        assert re.search(pattern, source), (
            f"{dotted} declares a table but _import_models() does not import it, "
            f"so create_all would never see it"
        )


# -------------------------------------------------------------------- upgrading


@pytest.mark.asyncio
async def test_an_old_database_reaches_the_schema_of_a_fresh_install(sandbox):
    await E.init_db()
    fresh = _schema(sandbox)

    removed = _make_old(sandbox)
    assert removed, "the simulation removed nothing, so it proves nothing"
    aged = _schema(sandbox)
    assert aged != fresh

    await E.init_db()
    assert _schema(sandbox) == fresh


@pytest.mark.asyncio
async def test_upgrading_keeps_the_rows(sandbox):
    await E.init_db()
    _make_old(sandbox)

    conn = sqlite3.connect(sandbox)
    conn.execute(
        "INSERT INTO servers (name, hostname, port, username, auth_method, "
        "encrypted_password, encrypted_private_key, \"group\", tags, description, "
        "ssh_enabled, sftp_enabled, sftp_allowed_paths, user_id) "
        "VALUES ('prod-web-01', '10.0.0.9', 22, 'root', 'password', '', '', "
        "'prod', '[]', '', 1, 1, '[]', 1)"
    )
    conn.commit()
    conn.close()

    await E.init_db()

    conn = sqlite3.connect(sandbox)
    row = conn.execute("SELECT name, hostname, host_key FROM servers").fetchone()
    assert row[:2] == ("prod-web-01", "10.0.0.9")
    assert row[2] in ("", None)  # the new column arrives with its default


@pytest.mark.asyncio
async def test_running_it_twice_changes_nothing(sandbox):
    await E.init_db()
    once = _schema(sandbox)
    await E.init_db()
    await E.init_db()
    assert _schema(sandbox) == once


@pytest.mark.asyncio
async def test_what_was_applied_is_recorded(sandbox):
    await E.init_db()
    conn = sqlite3.connect(sandbox)
    recorded = {r[0] for r in conn.execute(f"SELECT name FROM {E.RECORD_TABLE}")}
    assert recorded == {migration_name(t, c) for t, c, _, _ in E._MIGRATIONS}


@pytest.mark.asyncio
async def test_an_install_predating_the_bookkeeping_is_backfilled(sandbox):
    """The record must describe the schema that is really there, not just new work."""
    await E.init_db()
    conn = sqlite3.connect(sandbox)
    conn.execute(f"DROP TABLE {E.RECORD_TABLE}")
    conn.commit()
    conn.close()

    await E.init_db()
    conn = sqlite3.connect(sandbox)
    assert conn.execute(f"SELECT count(*) FROM {E.RECORD_TABLE}").fetchone()[0] == len(
        E._MIGRATIONS
    )


# ------------------------------------------------------------------ going wrong


@pytest.mark.asyncio
async def test_a_migration_that_genuinely_fails_stops_startup(sandbox, monkeypatch):
    """A UNIQUE column, which sqlite refuses to add to an existing table.

    That is a plausible future migration -- an api token, a slug -- and the old code
    swallowed the refusal. The column then stayed missing and the failure surfaced
    later, at an unrelated query, with nothing pointing back here.
    """
    await E.init_db()
    monkeypatch.setattr(E, "_MIGRATIONS", [("servers", "oops", "TEXT UNIQUE", "TEXT UNIQUE")])
    with pytest.raises(MigrationError) as exc:
        await E.init_db()
    assert "servers.oops" in str(exc.value)
    assert "backup" in str(exc.value)  # tells the operator what to do


@pytest.mark.asyncio
async def test_losing_the_race_to_another_instance_is_not_an_error(sandbox, monkeypatch):
    """compose.ha.yml starts N workers at once; they all try to migrate."""
    await E.init_db()
    _make_old(sandbox)

    real = E._existing_columns
    calls = {"n": 0}

    async def racing(table: str):
        # Report host_key missing once, then let the real ALTER collide with the
        # column another worker just added.
        cols = await real(table)
        if table == "servers" and calls["n"] == 0:
            calls["n"] = 1
            sqlite3.connect(sandbox).execute(
                'ALTER TABLE servers ADD COLUMN host_key TEXT DEFAULT ""'
            ).connection.commit()
            return cols - {"host_key"}
        return cols

    monkeypatch.setattr(E, "_existing_columns", racing)
    await E.init_db()  # must not raise
    assert "host_key" in _schema(sandbox)["servers"]


@pytest.mark.asyncio
async def test_a_database_from_a_newer_webgate_still_runs(sandbox, caplog):
    """Rollback has to work. Additive-only is what makes it safe, so say so."""
    await E.init_db()
    conn = sqlite3.connect(sandbox)
    conn.execute(
        f"INSERT INTO {E.RECORD_TABLE} (name, applied_at, app_version) "
        "VALUES ('servers.from_the_future', '2099-01-01T00:00:00+00:00', '9.9.9')"
    )
    conn.commit()
    conn.close()

    with caplog.at_level("WARNING"):
        await E.init_db()
    assert "newer webgate" in caplog.text
    assert "servers.from_the_future" in caplog.text
