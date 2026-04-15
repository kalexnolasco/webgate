"""Shared SSH session manager.

A SharedSession owns ONE asyncssh process and broadcasts its output to many
connected WebSocket clients. Any client (in `rw` mode) may also send input.

Lifecycle:
- Owner opens an SSH terminal → handle_terminal_ws registers a SharedSession
  with a generated session_id (no share token yet).
- Owner clicks "Share" → POST /api/terminal/share/{session_id} mints a token
  and stores it on the SharedSession.
- Joiner connects WS /api/ws/terminal/join/{token} → added as RW or RO client.
- Owner closes their tab → SharedSession is torn down, all joiners disconnected.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from dataclasses import dataclass, field

from fastapi import WebSocket

from webgate.terminal.ssh_session import SSHSession

logger = logging.getLogger(__name__)


@dataclass
class Participant:
    ws: WebSocket
    username: str
    mode: str = "rw"  # "rw" or "ro"


@dataclass
class SharedSession:
    session_id: str
    server_label: str
    owner_username: str
    ssh: SSHSession
    participants: list[Participant] = field(default_factory=list)
    share_token: str | None = None  # set when owner clicks "Share"
    closed: bool = False

    async def broadcast(self, text: str) -> None:
        dead: list[Participant] = []
        for p in self.participants:
            try:
                await p.ws.send_text(text)
            except Exception:
                dead.append(p)
        for p in dead:
            self.participants.remove(p)

    async def write_input(self, data: str, from_username: str) -> None:
        # Only RW participants can drive input; ROs are no-ops.
        sender = next((p for p in self.participants if p.username == from_username), None)
        if sender is None or sender.mode != "rw":
            return
        await self.ssh.write(data)

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for p in self.participants:
            with contextlib.suppress(Exception):
                await p.ws.close()
        self.participants.clear()
        await self.ssh.close()


class SharedSessionManager:
    """In-memory registry of active shared SSH sessions."""

    def __init__(self) -> None:
        self._by_id: dict[str, SharedSession] = {}
        self._by_token: dict[str, SharedSession] = {}

    def new_session_id(self) -> str:
        return secrets.token_urlsafe(12)

    def register(self, sess: SharedSession) -> None:
        self._by_id[sess.session_id] = sess

    def unregister(self, session_id: str) -> SharedSession | None:
        sess = self._by_id.pop(session_id, None)
        if sess and sess.share_token:
            self._by_token.pop(sess.share_token, None)
        return sess

    def get_by_id(self, session_id: str) -> SharedSession | None:
        return self._by_id.get(session_id)

    def get_by_token(self, token: str) -> SharedSession | None:
        return self._by_token.get(token)

    def mint_token(self, session_id: str) -> str | None:
        sess = self._by_id.get(session_id)
        if sess is None or sess.closed:
            return None
        if sess.share_token is None:
            sess.share_token = secrets.token_urlsafe(16)
            self._by_token[sess.share_token] = sess
        return sess.share_token

    def revoke_token(self, session_id: str) -> None:
        sess = self._by_id.get(session_id)
        if sess and sess.share_token:
            self._by_token.pop(sess.share_token, None)
            sess.share_token = None

    async def run_read_loop(self, sess: SharedSession) -> None:
        """Single read loop per shared session. Broadcasts SSH output to all
        clients. Returns when the SSH session ends or is closed."""
        try:
            while not sess.ssh.is_closed and not sess.closed:
                data = await sess.ssh.read()
                if data is None:
                    break
                await sess.broadcast(data)
        finally:
            await sess.close()


# Module-level singleton
manager = SharedSessionManager()
