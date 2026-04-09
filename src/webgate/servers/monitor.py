from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncssh
from sqlalchemy import select

from webgate.db.engine import async_session_factory
from webgate.servers.crypto import decrypt_value
from webgate.servers.models import Server

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 60  # seconds between full check cycles
CONNECT_TIMEOUT = 5  # seconds per SSH connect attempt
MAX_CONCURRENT = 10  # max parallel checks


@dataclass
class ServerStatus:
    online: bool
    last_checked: datetime
    latency_ms: float | None = None
    error: str | None = None


class ServerMonitor:
    """Background monitor that periodically checks SSH connectivity for all servers."""

    def __init__(self) -> None:
        self._statuses: dict[int, ServerStatus] = {}
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Launch the background check loop."""
        self._task = asyncio.create_task(self._check_loop())
        logger.info("Server monitor started")

    async def stop(self) -> None:
        """Cancel the background task."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("Server monitor stopped")

    def get_status(self, server_id: int) -> ServerStatus | None:
        return self._statuses.get(server_id)

    def get_all_statuses(self) -> dict[int, ServerStatus]:
        return dict(self._statuses)

    async def _check_loop(self) -> None:
        """Run connectivity checks every CHECK_INTERVAL seconds."""
        while True:
            try:
                await self._check_all()
            except Exception:
                logger.exception("Error during server status check cycle")
            await asyncio.sleep(CHECK_INTERVAL)

    async def _check_all(self) -> None:
        """Load all servers from DB and check each one concurrently."""
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
        """Attempt an SSH connection to determine if the server is reachable."""
        password = decrypt_value(server.encrypted_password) if server.encrypted_password else None
        private_key_str = (
            decrypt_value(server.encrypted_private_key)
            if server.encrypted_private_key
            else None
        )

        kwargs: dict[str, object] = {
            "host": server.hostname,
            "port": server.port,
            "username": server.username,
            "known_hosts": None,
        }
        if private_key_str:
            kwargs["client_keys"] = [asyncssh.import_private_key(private_key_str)]
        elif password:
            kwargs["password"] = password

        now = datetime.now(UTC)
        start = time.monotonic()
        try:
            conn = await asyncio.wait_for(
                asyncssh.connect(**kwargs),  # type: ignore[arg-type]
                timeout=CONNECT_TIMEOUT,
            )
            elapsed = (time.monotonic() - start) * 1000
            conn.close()
            return ServerStatus(online=True, last_checked=now, latency_ms=round(elapsed, 1))
        except Exception as exc:
            return ServerStatus(online=False, last_checked=now, error=str(exc))


server_monitor = ServerMonitor()
