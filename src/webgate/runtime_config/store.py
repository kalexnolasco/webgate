"""Runtime settings: what the admin panel writes, and what the rest of the app reads.

Stored as key/value rather than a column per setting, which is what makes adding a
setting free: no migration, and so no way for a new release to break an existing
database on a knob nobody has set yet.

Precedence follows what the agent settings already established -- an environment
variable seeds a fresh install, and once an admin has set a value in the UI it wins,
so changing one never needs a redeploy. `WEBGATE_CONFIG_LOCKED=true` turns the panel
read-only for deployments whose configuration is managed as code.

Reads are synchronous and go to an in-process snapshot, because they sit on paths
like "is this upload too big" that run per request. The snapshot is refreshed at
startup, immediately after a write, and every REFRESH_SECONDS -- which is also how a
change made on one HA worker reaches the others.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from webgate.config import settings as env_settings
from webgate.db.engine import Base, async_session_factory
from webgate.runtime_config.registry import BY_KEY, InvalidSetting, Spec
from webgate.servers.crypto import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 15


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # JSON for everything except secrets, which hold Fernet ciphertext.
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    updated_by: Mapped[str] = mapped_column(String(150), default="")


_overrides: dict[str, Any] = {}
_task: asyncio.Task[None] | None = None


# --------------------------------------------------------------------- reading


def get(key: str) -> Any:
    """The effective value of a setting.

    Synchronous on purpose: callers are request handlers and connection paths, and
    an await here would spread through all of them for a value that changes rarely.
    """
    if key in _overrides:
        return _overrides[key]
    return getattr(env_settings, key)


def source(key: str) -> str:
    """Where the effective value came from, for the panel to show."""
    if key in _overrides:
        return "admin"
    if key in env_settings.model_fields_set:
        return "environment"
    return "default"


def is_locked() -> bool:
    return bool(getattr(env_settings, "config_locked", False))


def _decode(spec: Spec, raw: str) -> Any:
    if spec.kind == "secret":
        return decrypt_value(raw)
    return json.loads(raw)


def _encode(spec: Spec, value: Any) -> str:
    if spec.kind == "secret":
        return encrypt_value(value)
    return json.dumps(value)


async def refresh(session: AsyncSession | None = None) -> dict[str, Any]:
    """Reload the snapshot from the database."""

    async def _load(s: AsyncSession) -> dict[str, Any]:
        rows = (await s.execute(select(Setting))).scalars().all()
        loaded: dict[str, Any] = {}
        for row in rows:
            spec = BY_KEY.get(row.key)
            if spec is None:
                # A setting this version no longer offers, or one written by a newer
                # webgate. Leave the row alone; the value is simply not applied.
                continue
            try:
                loaded[row.key] = _decode(spec, row.value)
            except Exception:
                logger.warning("Ignoring unreadable stored setting %s", row.key)
        return loaded

    if session is not None:
        new = await _load(session)
    else:
        async with async_session_factory() as s:
            new = await _load(s)

    _overrides.clear()
    _overrides.update(new)
    return dict(new)


# --------------------------------------------------------------------- writing


async def apply(session: AsyncSession, changes: dict[str, Any], *, actor: str) -> list[str]:
    """Validate and store a batch of changes. Returns the keys that actually changed.

    The whole batch is validated before anything is written, so a typo in one field
    cannot leave the panel half-applied.
    """
    if is_locked():
        raise InvalidSetting(
            "Settings are managed by the deployment (WEBGATE_CONFIG_LOCKED). "
            "Change them where the deployment is defined."
        )

    unknown = set(changes) - set(BY_KEY)
    if unknown:
        raise InvalidSetting(f"Unknown setting: {', '.join(sorted(unknown))}")

    validated: dict[str, Any] = {}
    for key, raw in changes.items():
        spec = BY_KEY[key]
        # A blank secret means "leave it alone": the panel never sends one back.
        if spec.kind == "secret" and raw == "":
            continue
        validated[key] = spec.coerce(raw)

    changed: list[str] = []
    for key, value in validated.items():
        if get(key) == value and source(key) == "admin":
            continue
        spec = BY_KEY[key]
        found = await session.execute(select(Setting).where(Setting.key == key))
        row = found.scalar_one_or_none()
        encoded = _encode(spec, value)
        if row is None:
            session.add(Setting(key=key, value=encoded, updated_by=actor))
        else:
            row.value = encoded
            row.updated_by = actor
            row.updated_at = datetime.now()
        changed.append(key)

    if changed:
        await session.commit()
        await refresh(session)
    return changed


async def reset(session: AsyncSession, keys: list[str] | None = None) -> list[str]:
    """Drop admin overrides so the environment (or the default) applies again."""
    if is_locked():
        raise InvalidSetting("Settings are managed by the deployment (WEBGATE_CONFIG_LOCKED).")

    stmt = delete(Setting)
    if keys is not None:
        unknown = set(keys) - set(BY_KEY)
        if unknown:
            raise InvalidSetting(f"Unknown setting: {', '.join(sorted(unknown))}")
        stmt = stmt.where(Setting.key.in_(keys))
    cleared = [k for k in (keys if keys is not None else list(BY_KEY)) if k in _overrides]
    await session.execute(stmt)
    await session.commit()
    await refresh(session)
    return cleared


# ------------------------------------------------------------- background reload


async def _watch() -> None:
    while True:
        await asyncio.sleep(REFRESH_SECONDS)
        try:
            await refresh()
        except Exception:
            logger.debug("Settings refresh failed; keeping the current snapshot", exc_info=True)


async def start() -> None:
    """Load the snapshot and keep it current. Safe to call when the table is empty."""
    global _task
    try:
        await refresh()
    except Exception:
        logger.warning("Could not load runtime settings; using the environment", exc_info=True)
    if _task is None:
        _task = asyncio.create_task(_watch())


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
