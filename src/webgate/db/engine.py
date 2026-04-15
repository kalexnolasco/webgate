import logging
from collections.abc import AsyncGenerator

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

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


# (table, column, sqlite_def, postgres_def)
_MIGRATIONS: list[tuple[str, str, str, str]] = [
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
]


async def init_db() -> None:
    dialect = engine.dialect.name  # "sqlite", "postgresql", ...
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Lightweight migrations: each in its OWN transaction. PostgreSQL aborts
    # the whole transaction on any error (even one we catch), so running
    # multiple ALTERs in a single txn would poison create_all on a fresh DB
    # the moment the first "column already exists" fires.
    for table, column, sqlite_def, pg_def in _MIGRATIONS:
        col_def = pg_def if dialect == "postgresql" else sqlite_def
        sql = f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql))
                logger.info("Migration applied: %s.%s", table, column)
        except Exception:
            pass  # Column already exists, or table not yet present on fresh DB


async def close_db() -> None:
    await engine.dispose()
