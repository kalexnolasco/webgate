"""Database engine and schema evolution.

webgate ships lightweight, append-only migrations rather than Alembic: the schema is
small, and upgrading should be one `docker pull` for an operator who never asked to
learn a migration tool. The price of that choice is a contract, enforced by
`tests/test_migrations.py` so a future release cannot quietly break an existing
install:

1. **Additive only.** A migration adds a column. It never drops, renames or retypes
   one. That is what makes a rollback safe: an older webgate ignores columns it does
   not know about, so a bad release can be rolled back without touching the database.
2. **Append only.** Entries go at the end. Editing or reordering an existing one does
   nothing to databases that already applied it, so the two would silently disagree.
3. **Idempotent.** Applying the list to an up-to-date database is a no-op.

Every applied change is recorded in `schema_migrations`, which is also how a database
written by a *newer* webgate is recognised and reported instead of being mistaken for
a corrupt one.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import MetaData, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from webgate import __version__
from webgate.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.db_url, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=convention)


async def get_session() -> AsyncGenerator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


class MigrationError(RuntimeError):
    """A schema change could not be applied.

    Raised rather than swallowed. A column that is still missing after startup does
    not fail here; it fails later at some unrelated query, with an error nobody can
    trace back to a migration.
    """


# (table, column, sqlite_def, postgres_def) -- APPEND ONLY, see the module docstring.
Migration = tuple[str, str, str, str]

_MIGRATIONS: list[Migration] = [
    ("servers", "sftp_read_only", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT FALSE"),
    # Singleton lease table for monitor leader election (id always = 1).
    # Created lazily by ServerMonitor.start() on first call; rows added there too.
    ("users", "totp_secret", "VARCHAR(255) DEFAULT ''", "VARCHAR(255) DEFAULT ''"),
    ("users", "totp_enabled", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT FALSE"),
    (
        "servers",
        "jump_via_id",
        "INTEGER REFERENCES servers(id)",
        "INTEGER REFERENCES servers(id)",
    ),
    ("servers", "agent_enabled", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT FALSE"),
    ("servers", "host_key", "TEXT DEFAULT ''", "TEXT DEFAULT ''"),
    ("agent_settings", "context_budget", "INTEGER DEFAULT 24000", "INTEGER DEFAULT 24000"),
    ("agent_settings", "cache_ttl", "INTEGER DEFAULT 60", "INTEGER DEFAULT 60"),
    ("agent_settings", "findings_retention_days", "INTEGER DEFAULT 90", "INTEGER DEFAULT 90"),
]

RECORD_TABLE = "schema_migrations"

_RECORD_DDL = f"""
CREATE TABLE IF NOT EXISTS {RECORD_TABLE} (
    name VARCHAR(255) NOT NULL PRIMARY KEY,
    applied_at VARCHAR(32) NOT NULL,
    app_version VARCHAR(32) NOT NULL
)
"""


def migration_name(table: str, column: str) -> str:
    return f"{table}.{column}"


def _import_models() -> None:
    """Put every table in `Base.metadata` before create_all runs.

    A table reaches the metadata only if its module has been imported. Today the
    routers happen to import all of them, so a new model in a module nothing imports
    at startup would be skipped silently and fail later on its first query. Importing
    them here makes that impossible. The imports live inside the function because
    those modules import `Base` from this one.
    """
    from webgate.agent import conversation, memory, store  # noqa: F401
    from webgate.audit import models as audit_models  # noqa: F401
    from webgate.auth import models as auth_models  # noqa: F401
    from webgate.branding import store as branding_store  # noqa: F401
    from webgate.recordings import models as recording_models  # noqa: F401
    from webgate.runtime_config import store as runtime_settings  # noqa: F401
    from webgate.servers import models as server_models  # noqa: F401
    from webgate.snippets import models as snippet_models  # noqa: F401
    from webgate.webhooks import models as webhook_models  # noqa: F401


def _columns_of(sync_conn: Any, table: str) -> set[str] | None:
    """Columns of `table`, or None when the table is not there at all."""
    insp = inspect(sync_conn)
    if not insp.has_table(table):
        return None
    return {c["name"] for c in insp.get_columns(table)}


async def _existing_columns(table: str) -> set[str] | None:
    async with engine.begin() as conn:
        return await conn.run_sync(_columns_of, table)


async def _recorded() -> set[str]:
    async with engine.begin() as conn:
        rows = await conn.execute(text(f"SELECT name FROM {RECORD_TABLE}"))
        return {row[0] for row in rows}


async def _record(name: str) -> None:
    """Bookkeeping, not correctness: a failure here must not stop a good upgrade."""
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    f"INSERT INTO {RECORD_TABLE} (name, applied_at, app_version) "
                    "VALUES (:n, :a, :v)"
                ),
                {
                    "n": name,
                    "a": datetime.now(UTC).isoformat(timespec="seconds"),
                    "v": __version__,
                },
            )
    except Exception:
        logger.debug("Could not record migration %s", name, exc_info=True)


async def init_db() -> None:
    _import_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(_RECORD_DDL))

    dialect = engine.dialect.name  # "sqlite", "postgresql", ...
    recorded = await _recorded()
    applied: list[str] = []

    # Each ALTER runs in its OWN transaction. PostgreSQL aborts the whole transaction
    # on any error, so batching them would poison create_all on a fresh database the
    # moment one of them failed.
    for table, column, sqlite_def, pg_def in _MIGRATIONS:
        name = migration_name(table, column)
        columns = await _existing_columns(table)

        if columns is None:
            # A migration for a table no longer in the models: dead, but harmless.
            logger.debug("Migration %s skipped: table %s is not present", name, table)
            continue

        if column in columns:
            if name not in recorded:
                # An install predating this bookkeeping. Backfill, so the record
                # describes the schema that is actually there.
                await _record(name)
            continue

        col_def = pg_def if dialect == "postgresql" else sqlite_def
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))
        except Exception as exc:
            # compose.ha.yml starts N workers at once, so another instance may have
            # applied the same migration between the check above and this ALTER.
            # Losing that race is fine; a column that is still missing is not.
            columns = await _existing_columns(table)
            if columns is not None and column in columns:
                logger.debug("Migration %s was applied concurrently", name)
            else:
                raise MigrationError(
                    f"Could not add {name}. The database is half-upgraded and webgate "
                    f"will not start on it. Restore your pre-upgrade backup and open an "
                    f"issue with this error: {exc}"
                ) from exc
        else:
            logger.info("Migration applied: %s", name)
            applied.append(name)

        await _record(name)

    if applied:
        logger.info("Schema upgraded to webgate %s (%d change(s))", __version__, len(applied))

    unknown = recorded - {migration_name(t, c) for t, c, _, _ in _MIGRATIONS}
    if unknown:
        logger.warning(
            "This database carries %d schema change(s) this version does not know about "
            "(%s). It was last written by a newer webgate. Migrations are additive, so "
            "this release runs against it; the extra columns are simply unused.",
            len(unknown),
            ", ".join(sorted(unknown)[:5]),
        )


async def close_db() -> None:
    await engine.dispose()
