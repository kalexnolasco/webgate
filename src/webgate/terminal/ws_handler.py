from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

from webgate.auth.service import authenticate_api_key, decode_access_token
from webgate.db.engine import async_session_factory
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
) -> None:
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

    async def ssh_to_ws() -> None:
        try:
            while not session.is_closed:
                data = await session.read()
                if data is None:
                    break
                await ws.send_text(data)
        except Exception:
            pass
        finally:
            if not session.is_closed:
                await session.close()
            with contextlib.suppress(Exception):
                await ws.close()

    read_task = asyncio.create_task(ssh_to_ws())

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
                        await session.resize(int(str(c)), int(str(r)))
                        continue
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
            await session.write(message)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        read_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await read_task
        await session.close()
