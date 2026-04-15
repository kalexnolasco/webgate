"""SFTP connection pool — reuses SSH connections per server."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import asyncssh

from webgate.files.sftp_service import SFTPClient

logger = logging.getLogger(__name__)

# Idle connections are closed after this many seconds
_TTL = 300  # 5 minutes
# How often the cleanup task runs
_CLEANUP_INTERVAL = 60  # 1 minute


@dataclass
class _PoolEntry:
    conn: asyncssh.SSHClientConnection
    client: SFTPClient
    last_used: float = field(default_factory=time.monotonic)
    in_use: int = 0
    jump_conn: asyncssh.SSHClientConnection | None = None


class SFTPPool:
    """Per-server SFTP connection cache with automatic cleanup."""

    def __init__(self) -> None:
        self._pool: dict[str, _PoolEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._cleanup_task: asyncio.Task[None] | None = None

    @staticmethod
    def _key(server_id: int) -> str:
        return str(server_id)

    async def start(self) -> None:
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        for entry in self._pool.values():
            await self._close_entry(entry)
        self._pool.clear()
        self._locks.clear()

    async def acquire(
        self,
        server_id: int,
        *,
        hostname: str,
        port: int,
        username: str,
        password: str | None = None,
        private_key: str | None = None,
        jump_kwargs: dict[str, object] | None = None,
    ) -> SFTPClient:
        key = self._key(server_id)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()

        async with self._locks[key]:
            entry = self._pool.get(key)
            if entry is not None:
                # Check if connection is still alive
                try:
                    # asyncssh connection check
                    if entry.conn._transport is not None:  # type: ignore[attr-defined]
                        entry.last_used = time.monotonic()
                        entry.in_use += 1
                        return entry.client
                except Exception:
                    pass
                # Connection dead, remove it
                await self._close_entry(entry)
                del self._pool[key]

            # Create new connection
            kwargs: dict[str, object] = {
                "host": hostname,
                "port": port,
                "username": username,
                "known_hosts": None,
            }
            if private_key:
                kwargs["client_keys"] = [asyncssh.import_private_key(private_key)]
            elif password:
                kwargs["password"] = password

            jump_conn: asyncssh.SSHClientConnection | None = None
            if jump_kwargs:
                jump_conn = await asyncssh.connect(**jump_kwargs)  # type: ignore[arg-type]
                kwargs["tunnel"] = jump_conn

            conn = await asyncssh.connect(**kwargs)  # type: ignore[arg-type]
            client = SFTPClient(conn)
            await client.connect()
            entry = _PoolEntry(conn=conn, client=client, in_use=1, jump_conn=jump_conn)
            self._pool[key] = entry
            logger.info("SFTP pool: new connection to %s:%s (server_id=%s)", hostname, port, server_id)
            return client

    def release(self, server_id: int) -> None:
        key = self._key(server_id)
        entry = self._pool.get(key)
        if entry and entry.in_use > 0:
            entry.in_use -= 1
            entry.last_used = time.monotonic()

    async def _close_entry(self, entry: _PoolEntry) -> None:
        try:
            await entry.client.close()
        except Exception:
            pass
        try:
            entry.conn.close()
        except Exception:
            pass
        if entry.jump_conn is not None:
            try:
                entry.jump_conn.close()
            except Exception:
                pass

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(_CLEANUP_INTERVAL)
            now = time.monotonic()
            to_remove: list[str] = []
            for key, entry in self._pool.items():
                if entry.in_use == 0 and (now - entry.last_used) > _TTL:
                    to_remove.append(key)
            for key in to_remove:
                entry = self._pool.pop(key)
                await self._close_entry(entry)
                logger.info("SFTP pool: closed idle connection (key=%s)", key)


# Global pool instance
sftp_pool = SFTPPool()
