from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

from webgate.auth.service import authenticate_api_key, decode_access_token
from webgate.db.engine import async_session_factory
from webgate.recordings.recorder import CastRecorder
from webgate.runtime_config import store as runtime
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
    recorder: CastRecorder | None = None,
    on_close: object | None = None,
) -> None:
    """Open an SSH session as the owner. The session is registered with the
    shared-session manager so other users can join via a share token."""
    # Checked here rather than at each entry point: both the registry and quick-connect
    # routes come through this function, and it is the last moment before an SSH
    # connection we would only refuse.
    cap = int(runtime.get("max_sessions_per_user"))
    if cap and manager.count_for(owner_username) >= cap:
        logger.info("Refused a session for %s: at the limit of %d", owner_username, cap)
        with contextlib.suppress(Exception):
            await ws.send_json(
                {
                    "type": "error",
                    "message": (
                        f"You already have {cap} terminal"
                        f"{'s' if cap != 1 else ''} open on this gateway. "
                        f"Close one before opening another."
                    ),
                }
            )
        await ws.close(code=4008, reason="Session limit reached")
        return

    session = SSHSession(
        host=host,
        port=port,
        username=username,
        password=password,
        private_key=private_key,
        jump_kwargs=jump_kwargs,
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
        recorder=recorder,
        on_close=on_close,
    )
    sess.participants.append(Participant(ws=ws, username=owner_username, mode="rw"))
    manager.register(sess)

    # Tell the owner their session_id so the UI can build a share URL.
    with contextlib.suppress(Exception):
        await ws.send_text(json.dumps({"type": "session", "session_id": sess.session_id}))

    read_task = asyncio.create_task(manager.run_read_loop(sess))
    idle_task = asyncio.create_task(manager.watch_idle(sess))
    try:
        await _client_input_loop(ws, session, sess, owner_username)
    finally:
        for task in (read_task, idle_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
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
        await ws.send_text(
            json.dumps(
                {
                    "type": "joined",
                    "server": sess.server_label,
                    "owner": sess.owner_username,
                    "mode": mode,
                }
            )
        )
    try:
        await _client_input_loop(ws, sess.ssh, sess, username)
    finally:
        if participant in sess.participants:
            sess.participants.remove(participant)


def _resize_of(message: str) -> tuple[int, int] | None:
    """The (cols, rows) a resize frame carries, or None if this is terminal input.

    A malformed resize still answers as a resize -- with a size that will be thrown
    away -- so that a control frame is never typed into somebody's shell instead.
    """
    try:
        parsed: object = json.loads(message)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or parsed.get("type") != "resize":  # pyright: ignore[reportUnknownMemberType]
        return None
    frame: dict[str, object] = parsed  # pyright: ignore[reportUnknownVariableType]
    try:
        return int(str(frame.get("cols", 0))), int(str(frame.get("rows", 0)))
    except (TypeError, ValueError):
        return 0, 0


async def _client_input_loop(
    ws: WebSocket,
    ssh: SSHSession,
    sess: SharedSession,
    username: str,
) -> None:
    """Receives input + control messages from one client and dispatches to
    the SSH process via the shared session (RO clients can only resize)."""
    try:
        while True:
            message = await ws.receive_text()
            size = _resize_of(message)
            if size is not None:
                cols, rows = size
                # A pane that is hidden, or not laid out yet, measures nothing. There
                # is no such thing as a terminal with no rows, so the far end is not
                # told about one.
                if cols > 0 and rows > 0:
                    try:
                        await ssh.resize(cols, rows)
                    except Exception:
                        # This used to escape into the `except Exception` below, which
                        # ends the loop -- so one failed resize dropped the session,
                        # silently. A window that cannot be resized is not a reason to
                        # take someone's shell away.
                        logger.warning(
                            "Could not resize the terminal for %s", username, exc_info=True
                        )
                continue
            await sess.write_input(message, username)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("Terminal input loop for %s ended", username, exc_info=True)
