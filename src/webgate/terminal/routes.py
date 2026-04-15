from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status

from webgate.audit.service import log_action
from webgate.auth.models import UserOut
from webgate.auth.routes import get_current_user
from webgate.auth.service import get_user_by_id
from webgate.db.engine import async_session_factory
from webgate.servers.service import (
    get_server,
    get_server_credentials,
    resolve_jump_creds,
    update_last_connected,
)
from datetime import UTC, datetime
from pathlib import Path

from webgate.config import settings
from webgate.db.engine import async_session_factory as _session_factory
from webgate.recordings.models import Recording
from webgate.recordings.recorder import CastRecorder
from webgate.terminal.shared import manager as shared_manager
from webgate.terminal.ws_handler import authenticate_websocket, handle_join_ws, handle_terminal_ws
from webgate.webhooks.dispatcher import fire as fire_webhook

router = APIRouter(tags=["terminal"])

CurrentUserDep = Annotated[UserOut, Depends(get_current_user)]


@router.post("/api/terminal/share/{session_id}")
async def create_share_token(session_id: str, user: CurrentUserDep) -> dict[str, object]:
    """Mint a shareable token for an active terminal session. Only the
    session owner may share; other users will get 403."""
    sess = shared_manager.get_by_id(session_id)
    if sess is None or sess.closed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not active")
    if sess.owner_username != user.username:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the session owner can share")
    token = shared_manager.mint_token(session_id)
    return {
        "token": token,
        "server": sess.server_label,
        "participants": len(sess.participants),
    }


@router.delete("/api/terminal/share/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share_token(session_id: str, user: CurrentUserDep) -> None:
    sess = shared_manager.get_by_id(session_id)
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not active")
    if sess.owner_username != user.username:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the session owner can revoke")
    shared_manager.revoke_token(session_id)


@router.websocket("/api/ws/terminal/quick")
async def ws_terminal_quick(ws: WebSocket) -> None:
    payload = await authenticate_websocket(ws)
    if payload is None:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()

    try:
        first_msg = await ws.receive_json()
    except (WebSocketDisconnect, Exception):
        return

    host = first_msg.get("host", "")
    port = int(first_msg.get("port", 22))
    username = first_msg.get("username", "")
    password = first_msg.get("password")
    private_key = first_msg.get("private_key")
    cols = int(first_msg.get("cols", 80))
    rows = int(first_msg.get("rows", 24))

    if not host or not username:
        await ws.send_json({"type": "error", "message": "host and username required"})
        await ws.close(code=1008)
        return

    payload_username = str(payload.get("username", "user")) if payload else "user"
    await handle_terminal_ws(
        ws, host=host, port=port, username=username,
        password=password, private_key=private_key, cols=cols, rows=rows,
        owner_username=payload_username, server_label=f"{username}@{host}",
    )


@router.websocket("/api/ws/terminal/{server_id}")
async def ws_terminal_server(ws: WebSocket, server_id: int) -> None:
    payload = await authenticate_websocket(ws)
    if payload is None:
        await ws.close(code=4001, reason="Unauthorized")
        return

    user_id_raw = payload.get("sub") if payload else None
    if not user_id_raw:
        await ws.close(code=4001, reason="Unauthorized")
        return

    user_id = int(str(user_id_raw))

    async with async_session_factory() as session:
        user = await get_user_by_id(session, user_id)
        if not user:
            await ws.close(code=4001, reason="Unauthorized")
            return

        user_out = UserOut.model_validate(user)
        server = await get_server(
            session, server_id, user_id,
            is_admin=user_out.is_admin,
            allowed_groups=user_out.allowed_groups if not user_out.is_admin else None,
        )
        if not server:
            await ws.close(code=4004, reason="Server not found")
            return

        if not server.ssh_enabled:
            await ws.close(code=4003, reason="SSH is disabled for this server")
            return

        password, private_key = get_server_credentials(server)
        jump_kwargs = await resolve_jump_creds(session, server)

        await ws.accept()

        # Read optional initial resize from client
        cols = 80
        rows = 24
        try:
            first_msg = await ws.receive_json()
            cols = int(first_msg.get("cols", 80))
            rows = int(first_msg.get("rows", 24))
        except (WebSocketDisconnect, Exception):
            pass

        await update_last_connected(session, server)
        await log_action(user_out.id, user_out.username, "ssh_connect", f"{server.hostname}:{server.port}")
        await fire_webhook("ssh_connect", {
            "user": user_out.username, "server_id": server.id, "server": server.name,
            "host": f"{server.hostname}:{server.port}", "via_jump": server.jump_via_id is not None,
        })

    # Optional session recording (asciinema cast v2)
    recording_id: int | None = None
    recorder: CastRecorder | None = None
    if settings.record_sessions:
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        cast_path = (
            Path(settings.recordings_dir) / str(server.id) / f"{ts}-{user_out.username}.cast"
        )
        recorder = CastRecorder(cast_path, cols=cols, rows=rows)
        async with _session_factory() as db:
            rec = Recording(
                server_id=server.id, server_name=server.name,
                user_id=user_out.id, username=user_out.username,
                file_path=str(cast_path),
            )
            db.add(rec)
            await db.commit()
            recording_id = rec.id

    async def _finalize_recording() -> None:
        if recorder is None or recording_id is None:
            return
        size = recorder.close()
        duration = recorder.duration
        async with _session_factory() as db:
            from sqlalchemy import select as _select
            row = (await db.execute(_select(Recording).where(Recording.id == recording_id))).scalar_one_or_none()
            if row is not None:
                row.ended_at = datetime.now(UTC)
                row.size_bytes = size
                row.duration_s = round(duration, 3)
                await db.commit()

    await handle_terminal_ws(
        ws,
        host=server.hostname,
        port=server.port,
        username=server.username,
        password=password,
        private_key=private_key,
        cols=cols,
        rows=rows,
        jump_kwargs=jump_kwargs,
        owner_username=user_out.username,
        server_label=server.name,
        recorder=recorder,
        on_close=_finalize_recording,
    )


@router.websocket("/api/ws/terminal/join/{token}")
async def ws_terminal_join(ws: WebSocket, token: str, mode: str = "rw") -> None:
    """Join an existing shared SSH session via its share token."""
    payload = await authenticate_websocket(ws)
    if payload is None:
        await ws.close(code=4001, reason="Unauthorized")
        return
    username = str(payload.get("username", "guest"))
    if mode not in ("rw", "ro"):
        mode = "ro"
    await handle_join_ws(ws, share_token=token, username=username, mode=mode)
