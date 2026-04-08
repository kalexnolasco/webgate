import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.mark.asyncio
async def test_ws_terminal_no_token(app):
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/ws/terminal/quick"),
    ):
        pass


@pytest.mark.asyncio
async def test_ws_terminal_invalid_token(app):
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/ws/terminal/quick?token=badtoken"),
    ):
        pass


@pytest.mark.asyncio
async def test_ws_terminal_auth_required(app, auth_token):
    """Verify that a valid token allows WebSocket connection to be accepted."""
    with (
        TestClient(app) as client,
        client.websocket_connect(f"/api/ws/terminal/quick?token={auth_token}") as ws,
    ):
        ws.send_json({
            "host": "127.0.0.1",
            "port": 99999,
            "username": "test",
            "password": "test",
            "cols": 80,
            "rows": 24,
        })
        data = ws.receive_json()
        assert data["type"] == "error"
        assert "SSH connection failed" in data["message"]


@pytest.mark.asyncio
async def test_ws_terminal_missing_host(app, auth_token):
    with (
        TestClient(app) as client,
        client.websocket_connect(f"/api/ws/terminal/quick?token={auth_token}") as ws,
    ):
        ws.send_json({
            "host": "",
            "port": 22,
            "username": "",
            "password": "test",
        })
        data = ws.receive_json()
        assert data["type"] == "error"
        assert "required" in data["message"]
