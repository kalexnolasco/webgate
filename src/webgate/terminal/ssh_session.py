from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

import asyncssh

logger = logging.getLogger(__name__)


@dataclass
class SSHSession:
    host: str
    port: int
    username: str
    password: str | None = None
    private_key: str | None = None
    _conn: asyncssh.SSHClientConnection | None = field(default=None, repr=False)
    _process: asyncssh.SSHClientProcess[str] | None = field(default=None, repr=False)
    _closed: bool = field(default=False, repr=False)

    async def connect(self, cols: int = 80, rows: int = 24) -> None:
        connect_kwargs: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "known_hosts": None,
        }
        if self.private_key:
            connect_kwargs["client_keys"] = [asyncssh.import_private_key(self.private_key)]
        elif self.password:
            connect_kwargs["password"] = self.password

        self._conn = await asyncssh.connect(**connect_kwargs)
        self._process = await self._conn.create_process(
            term_type="xterm-256color",
            term_size=(cols, rows),
            encoding="utf-8",
        )

    async def read(self) -> str | None:
        proc = self._process
        if proc is None:
            return None
        try:
            data: str = await proc.stdout.read(4096)  # pyright: ignore[reportUnknownMemberType]
            if not data:
                return None
            return data
        except (asyncssh.BreakReceived, asyncssh.SignalReceived):
            return None
        except (asyncssh.ConnectionLost, asyncssh.DisconnectError, OSError):
            return None

    async def write(self, data: str) -> None:
        proc = self._process
        if proc is None:
            return
        proc.stdin.write(data)  # pyright: ignore[reportUnknownMemberType]

    async def resize(self, cols: int, rows: int) -> None:
        if self._process is not None:
            self._process.change_terminal_size(cols, rows)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._process is not None:
            self._process.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._process.wait_closed(), timeout=2.0)
        if self._conn is not None:
            self._conn.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._conn.wait_closed(), timeout=2.0)

    @property
    def is_closed(self) -> bool:
        return self._closed
