from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

from webgate.auth.service import authenticate_api_key, decode_access_token
from webgate.db.engine import async_session_factory
from webgate.terminal.shared import Participant, SharedSession, manager
from webgate.terminal.ssh_session import SSHSession

logger = logging.getLogger(__name__)


async def authenticate_websocket(ws: WebSocket) -> dict[str, object] | None:
    token = ws.query_params.get("token")
    if not token:
        return None

    # Support API key authentication (keys start with "wg_")
    if token.startswith("wg_"):
        async with async_session_factory() as session:
            user = await authenticate_api_key(session, token)
            if user:
                return {"sub": str(user.id), "username": user.username}
            return None

    payload = decode_access_token(token)
    return payload


async def handle_terminal_ws(
    ws: WebSocket,
    host: str,
    port: int,
    username: str,
    password: str | None = None,
    private_key: str | None = None,
    cols: int = 80,
    rows: int = 24,
    jump_kwargs: dict[str, object] | None = None,
    owner_username: str = "owner",
    server_label: str | None = None,
) -> None:
    """Open an SSH session as the owner. The session is registered with the
    shared-session manager so other users can join via a share token."""
    session = SSHSession(
        host=host, port=port, username=username,
        password=password, private_key=private_key, jump_kwargs=jump_kwargs,
    )
    try:
        await session.connect(cols=cols, rows=rows)
    except Exception as e:
        logger.error("SSH connection failed: %s", e)
        await ws.send_json({"type": "error", "message": f"SSH connection failed: {e}"})
        await ws.close(code=1011)
        return

    sess = SharedSession(
        session_id=manager.new_session_id(),
        server_label=server_label or f"{username}@{host}",
        owner_username=owner_username,
        ssh=session,
    )
    sess.participants.append(Participant(ws=ws, username=owner_username, mode="rw"))
    manager.register(sess)

    # Tell the owner their session_id so the UI can build a share URL.
    with contextlib.suppress(Exception):
        await ws.send_text(json.dumps({"type": "session", "session_id": sess.session_id}))

    read_task = asyncio.create_task(manager.run_read_loop(sess))
    try:
        await _client_input_loop(ws, session, sess, owner_username)
    finally:
        read_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await read_task
        manager.unregister(sess.session_id)


async def handle_join_ws(ws: WebSocket, share_token: str, username: str, mode: str) -> None:
    """Attach a joiner to an existing SharedSession via its share token."""
    sess = manager.get_by_token(share_token)
    if sess is None or sess.closed:
        await ws.close(code=4004, reason="Share session not found or closed")
        return
    await ws.accept()
    participant = Participant(ws=ws, username=username, mode=mode)
    sess.participants.append(participant)
    with contextlib.suppress(Exception):
        await ws.send_text(json.dumps({
            "type": "joined",
            "server": sess.server_label,
            "owner": sess.owner_username,
            "mode": mode,
        }))
    try:
        await _client_input_loop(ws, sess.ssh, sess, username)
    finally:
        if participant in sess.participants:
            sess.participants.remove(participant)


async def _client_input_loop(
    ws: WebSocket, ssh: SSHSession, sess: SharedSession, username: str,
) -> None:
    """Receives input + control messages from one client and dispatches to
    the SSH process via the shared session (RO clients can only resize)."""
    try:
        while True:
            message = await ws.receive_text()
            try:
                raw: object = json.loads(message)
                if isinstance(raw, dict):
                    parsed: dict[str, object] = raw  # pyright: ignore[reportUnknownVariableType]
                    if parsed.get("type") == "resize":
                        c = parsed.get("cols", 80)
                        r = parsed.get("rows", 24)
                        await ssh.resize(int(str(c)), int(str(r)))
                        continue
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
            await sess.write_input(message, username)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
