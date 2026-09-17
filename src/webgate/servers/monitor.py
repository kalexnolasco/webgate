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
from webgate.runtime_config import store as runtime
from webgate.servers.crypto import CredentialUnreadable, decrypt_value
from webgate.servers.hostkeys import known_hosts_for
from webgate.servers.models import Server
from webgate.webhooks.dispatcher import fire as fire_webhook

logger = logging.getLogger(__name__)

# These were fixed constants and the three matching settings were read by nobody.
# They are now the floor and the fallback; the effective values come from the admin
# panel, which is why they are read at the point of use rather than captured once.
LEASE_TTL_FLOOR = 90  # seconds


def _interval() -> int:
    return int(runtime.get("monitor_interval"))


def _connect_timeout() -> int:
    return int(runtime.get("monitor_timeout"))


def _concurrency() -> int:
    return int(runtime.get("monitor_concurrency"))


def _lease_ttl() -> int:
    """The lease has to outlast a full sweep, or the leader drops it mid-cycle.

    That invariant used to hold because both numbers were constants. Now that an
    admin can stretch the interval, the lease has to follow it.
    """
    return max(LEASE_TTL_FLOOR, int(_interval() * 1.5))


LEASE_RENEW = 30  # seconds; heartbeat interval


def _alert_after() -> int:
    return max(1, int(runtime.get("monitor_alert_after")))


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
        # What each server was last *reported* as, and how many sweeps in a row it
        # has failed. Both only ever touched by the leader, which is the only
        # instance that sweeps -- so followers cannot double-announce an outage.
        self._announced: dict[int, bool] = {}
        self._failures: dict[int, int] = {}
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
        if runtime.get("disable_monitor"):
            logger.info("Monitor disabled (instance %s)", self._instance_id)
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
        new_expiry = now + timedelta(seconds=_lease_ttl())
        async with engine.begin() as conn:
            try:
                lease = await conn.execute(
                    text("SELECT instance_id, expires_at FROM monitor_lease WHERE id = 1")
                )
                row = lease.fetchone()
                if row is None:
                    await conn.execute(
                        text(
                            "INSERT INTO monitor_lease (id, instance_id, expires_at) "
                            "VALUES (1, :iid, :exp)"
                        ),
                        {"iid": self._instance_id, "exp": new_expiry},
                    )
                    return True
                # Postgres returns datetime, SQLite may return a string.
                expires_raw = row[1]
                expires = (
                    expires_raw
                    if isinstance(expires_raw, datetime)
                    else datetime.fromisoformat(str(expires_raw))
                )
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
                if runtime.get("disable_monitor"):
                    # Toggled off in the panel while running: stand down, but keep the
                    # loop alive so turning it back on does not need a restart.
                    if self._is_leader:
                        await self._release_lease()
                        self._is_leader = False
                    await asyncio.sleep(min(LEASE_RENEW, _interval()))
                    continue
                if not self._is_leader:
                    self._is_leader = await self._try_claim()
                    if self._is_leader:
                        logger.info("Became monitor leader (instance %s)", self._instance_id)
                if self._is_leader:
                    now = time.monotonic()
                    if now - last_renew > LEASE_RENEW:
                        renewed = await self._try_claim()
                        if not renewed:
                            logger.warning(
                                "Lost monitor lease (instance %s) -> stepping down",
                                self._instance_id,
                            )
                            self._is_leader = False
                            await asyncio.sleep(LEASE_RENEW)
                            continue
                        last_renew = now
                    await self._check_all()
                else:
                    # Followers wake up roughly once per check interval to retry leadership.
                    await asyncio.sleep(min(LEASE_RENEW, _interval()))
                    continue
            except Exception:
                logger.exception("Error in monitor loop (instance %s)", self._instance_id)
            await asyncio.sleep(_interval())

    async def _check_all(self) -> None:
        async with async_session_factory() as session:
            result = await session.execute(select(Server))
            servers = result.scalars().all()

        semaphore = asyncio.Semaphore(_concurrency())

        async def _check_one(server: Server) -> None:
            async with semaphore:
                status = await self._check_server(server)
                self._statuses[server.id] = status
                await self._announce(server, status)

        await asyncio.gather(*[_check_one(s) for s in servers])

    async def _announce(self, server: Server, status: ServerStatus) -> None:
        """Fire a webhook when a server changes state, and only then.

        The monitor has always known when a host went down and has only ever painted
        a dot with it. Somebody has to be looking at the dot.

        Coming back is announced on the first successful check: a recovery is good
        news and nobody minds hearing it early. Going down waits for
        `monitor_alert_after` consecutive failures, because one lost packet is not an
        outage and alerting on it is how people learn to ignore the alerts.
        """
        if status.online:
            self._failures[server.id] = 0
        else:
            self._failures[server.id] = self._failures.get(server.id, 0) + 1
            if self._failures[server.id] < _alert_after():
                return

        was = self._announced.get(server.id)
        if was is status.online:
            return
        # The first sweep after a restart establishes the baseline. Announcing every
        # host as "up" on every deploy is noise, so only a *change* is news -- but a
        # host that is already down when we start is news, because nobody was told.
        first_look = was is None
        self._announced[server.id] = status.online
        if first_look and status.online:
            return

        await fire_webhook(
            "server_online" if status.online else "server_offline",
            {
                "server": server.name,
                "hostname": server.hostname,
                "port": server.port,
                "online": status.online,
                "latency_ms": status.latency_ms,
                "error": status.error,
                "failed_checks": self._failures.get(server.id, 0),
                "checked_at": status.last_checked.isoformat(),
            },
        )
        logger.info("%s is %s", server.name, "back online" if status.online else "unreachable")

    def forget(self, server_id: int) -> None:
        """Drop a deleted server, so a re-added one starts from a clean baseline."""
        self._statuses.pop(server_id, None)
        self._announced.pop(server_id, None)
        self._failures.pop(server_id, None)

    async def _check_server(self, server: Server) -> ServerStatus:
        now = datetime.now(UTC)
        try:
            password = (
                decrypt_value(server.encrypted_password, server.name)
                if server.encrypted_password
                else None
            )
            private_key_str = (
                decrypt_value(server.encrypted_private_key, server.name)
                if server.encrypted_private_key
                else None
            )
        except CredentialUnreadable as exc:
            # Reported against this server, not raised: the sweep has other hosts to
            # check, and the operator needs to know which one is unreadable.
            return ServerStatus(online=False, last_checked=now, error=str(exc))
        kwargs: dict[str, object] = {
            "host": server.hostname,
            "port": server.port,
            "username": server.username,
            "known_hosts": known_hosts_for(getattr(server, "host_key", "") or ""),
        }
        start = time.monotonic()
        try:
            # Parsing the key belongs inside the try. An unreadable key row raised out
            # of here, through the gather in _check_all, and killed the whole monitor
            # cycle: one bad server left every other status stale.
            # Honour the declared auth method too, so a server moved from key to
            # password is not probed with the key it still carries.
            if server.auth_method == "key" and private_key_str:
                kwargs["client_keys"] = [asyncssh.import_private_key(private_key_str)]
            elif password:
                kwargs["password"] = password
            elif private_key_str:
                kwargs["client_keys"] = [asyncssh.import_private_key(private_key_str)]
            conn = await asyncio.wait_for(asyncssh.connect(**kwargs), timeout=_connect_timeout())  # type: ignore[arg-type]
            elapsed = (time.monotonic() - start) * 1000
            conn.close()
            return ServerStatus(online=True, last_checked=now, latency_ms=round(elapsed, 1))
        except Exception as exc:
            return ServerStatus(online=False, last_checked=now, error=str(exc))


server_monitor = ServerMonitor()
