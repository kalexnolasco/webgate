from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from webgate.auth.models import UserOut
from webgate.auth.service import get_user_by_id
from webgate.db.engine import async_session_factory
from webgate.servers.service import get_server, get_server_credentials, update_last_connected
from webgate.terminal.ws_handler import authenticate_websocket, handle_terminal_ws

router = APIRouter(tags=["terminal"])


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

    await handle_terminal_ws(
        ws,
        host=host,
        port=port,
        username=username,
        password=password,
        private_key=private_key,
        cols=cols,
        rows=rows,
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

        password, private_key = get_server_credentials(server)

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

    await handle_terminal_ws(
        ws,
        host=server.hostname,
        port=server.port,
        username=server.username,
        password=password,
        private_key=private_key,
        cols=cols,
        rows=rows,
    )
