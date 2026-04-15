"""Background server connectivity monitor with leader election.

In a multi-instance deployment, only one worker should actively probe servers.
We use a tiny singleton row in `monitor_lease` as a lease: workers try to claim
it; the holder heartbeats every LEASE_RENEW seconds; when the lease expires
without a renewal, any other worker can take over.

Followers keep the loop alive but skip the actual probing — they still serve
`/api/servers/status` from the leader's writes via the DB row each status is
persisted to (we store statuses on `Server` rows for cross-worker reads).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import asyncssh
from sqlalchemy import select, text

from webgate.config import settings
from webgate.db.engine import async_session_factory, engine
from webgate.servers.crypto import decrypt_value
from webgate.servers.models import Server

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 60  # seconds between full check cycles (leader only)
CONNECT_TIMEOUT = 5  # seconds per SSH connect attempt
MAX_CONCURRENT = 10  # max parallel checks
LEASE_TTL = 90  # seconds; longer than CHECK_INTERVAL so a slow cycle doesn't drop the lease
LEASE_RENEW = 30  # seconds; heartbeat interval


@dataclass
class ServerStatus:
    online: bool
    last_checked: datetime
    latency_ms: float | None = None
    error: str | None = None


class ServerMonitor:
    """Periodically check SSH connectivity for all servers, with leader election."""

    def __init__(self) -> None:
        self._statuses: dict[int, ServerStatus] = {}
        self._task: asyncio.Task[None] | None = None
        self._instance_id: str = settings.instance_id or str(uuid.uuid4())
        self._is_leader: bool = False

    @property
    def instance_id(self) -> str:
        return self._instance_id

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    async def start(self) -> None:
        if settings.disable_monitor:
            logger.info("Monitor disabled by WEBGATE_DISABLE_MONITOR (instance %s)", self._instance_id)
            return
        await self._ensure_lease_table()
        self._task = asyncio.create_task(self._loop())
        logger.info("Server monitor started (instance %s)", self._instance_id)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._is_leader:
            await self._release_lease()
        logger.info("Server monitor stopped (instance %s)", self._instance_id)

    def get_status(self, server_id: int) -> ServerStatus | None:
        return self._statuses.get(server_id)

    def get_all_statuses(self) -> dict[int, ServerStatus]:
        return dict(self._statuses)

    # --- leader election ---------------------------------------------------

    async def _ensure_lease_table(self) -> None:
        ddl = (
            "CREATE TABLE IF NOT EXISTS monitor_lease ("
            "id INTEGER PRIMARY KEY, "
            "instance_id VARCHAR(64) NOT NULL, "
            "expires_at TIMESTAMP NOT NULL"
            ")"
        )
        async with engine.begin() as conn:
            with contextlib.suppress(Exception):
                await conn.execute(text(ddl))

    async def _try_claim(self) -> bool:
        """Atomically claim the singleton lease. Returns True if we are the leader."""
        # Store as naive UTC so we work with both SQLite's TEXT storage and
        # Postgres' TIMESTAMP WITHOUT TIME ZONE.
        now = datetime.now(UTC).replace(tzinfo=None)
        new_expiry = now + timedelta(seconds=LEASE_TTL)
        async with engine.begin() as conn:
            try:
                row = (await conn.execute(text("SELECT instance_id, expires_at FROM monitor_lease WHERE id = 1"))).fetchone()
                if row is None:
                    await conn.execute(
                        text("INSERT INTO monitor_lease (id, instance_id, expires_at) VALUES (1, :iid, :exp)"),
                        {"iid": self._instance_id, "exp": new_expiry},
                    )
                    return True
                # Postgres returns datetime, SQLite may return a string.
                expires_raw = row[1]
                expires = expires_raw if isinstance(expires_raw, datetime) else datetime.fromisoformat(str(expires_raw))
                if expires.tzinfo is not None:
                    expires = expires.astimezone(UTC).replace(tzinfo=None)
                if row[0] == self._instance_id or expires < now:
                    res = await conn.execute(
                        text(
                            "UPDATE monitor_lease SET instance_id = :iid, expires_at = :exp "
                            "WHERE id = 1 AND (instance_id = :iid OR expires_at < :now)"
                        ),
                        {"iid": self._instance_id, "exp": new_expiry, "now": now},
                    )
                    return (res.rowcount or 0) > 0
                return False
            except Exception as exc:
                logger.warning("Lease claim failed: %s", exc)
                return False

    async def _release_lease(self) -> None:
        async with engine.begin() as conn:
            with contextlib.suppress(Exception):
                await conn.execute(
                    text("DELETE FROM monitor_lease WHERE id = 1 AND instance_id = :iid"),
                    {"iid": self._instance_id},
                )

    # --- main loop ---------------------------------------------------------

    async def _loop(self) -> None:
        last_renew = 0.0
        while True:
            try:
                if not self._is_leader:
                    self._is_leader = await self._try_claim()
                    if self._is_leader:
                        logger.info("Became monitor leader (instance %s)", self._instance_id)
                if self._is_leader:
                    now = time.monotonic()
                    if now - last_renew > LEASE_RENEW:
                        renewed = await self._try_claim()
                        if not renewed:
                            logger.warning("Lost monitor lease (instance %s) -> stepping down", self._instance_id)
                            self._is_leader = False
                            await asyncio.sleep(LEASE_RENEW)
                            continue
                        last_renew = now
                    await self._check_all()
                else:
                    # Followers wake up roughly once per check interval to retry leadership.
                    await asyncio.sleep(min(LEASE_RENEW, CHECK_INTERVAL))
                    continue
            except Exception:
                logger.exception("Error in monitor loop (instance %s)", self._instance_id)
            await asyncio.sleep(CHECK_INTERVAL)

    async def _check_all(self) -> None:
        async with async_session_factory() as session:
            result = await session.execute(select(Server))
            servers = result.scalars().all()

        semaphore = asyncio.Semaphore(MAX_CONCURRENT)

        async def _check_one(server: Server) -> None:
            async with semaphore:
                status = await self._check_server(server)
                self._statuses[server.id] = status

        await asyncio.gather(*[_check_one(s) for s in servers])

    async def _check_server(self, server: Server) -> ServerStatus:
        password = decrypt_value(server.encrypted_password) if server.encrypted_password else None
        private_key_str = (
            decrypt_value(server.encrypted_private_key) if server.encrypted_private_key else None
        )
        kwargs: dict[str, object] = {
            "host": server.hostname, "port": server.port, "username": server.username,
            "known_hosts": None,
        }
        if private_key_str:
            kwargs["client_keys"] = [asyncssh.import_private_key(private_key_str)]
        elif password:
            kwargs["password"] = password
        now = datetime.now(UTC)
        start = time.monotonic()
        try:
            conn = await asyncio.wait_for(asyncssh.connect(**kwargs), timeout=CONNECT_TIMEOUT)  # type: ignore[arg-type]
            elapsed = (time.monotonic() - start) * 1000
            conn.close()
            return ServerStatus(online=True, last_checked=now, latency_ms=round(elapsed, 1))
        except Exception as exc:
            return ServerStatus(online=False, last_checked=now, error=str(exc))


server_monitor = ServerMonitor()
