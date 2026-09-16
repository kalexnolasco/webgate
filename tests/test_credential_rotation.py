"""What happens after WEBGATE_SECRET_KEY changes.

v2.2.0 refuses the shipped default key, which pushes every existing install to set a
real one. Doing that makes rows encrypted under the old key unreadable -- and nothing
handled it. The monitor died on its first sweep, and opening a terminal failed the
WebSocket upgrade with a bare 500 that told the operator nothing.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from webgate.config import settings as env_settings
from webgate.servers.crypto import CredentialUnreadable, decrypt_value, encrypt_value


def _rotate(monkeypatch, value: str = "hunter2") -> str:
    """A token written under one key, read under another."""
    monkeypatch.setattr(env_settings, "secret_key", "the-key-it-was-saved-with")
    token = encrypt_value(value)
    monkeypatch.setattr(env_settings, "secret_key", "the-key-in-force-now")
    return token


def test_an_unreadable_credential_says_what_happened_and_what_to_do(monkeypatch):
    token = _rotate(monkeypatch)
    with pytest.raises(CredentialUnreadable) as exc:
        decrypt_value(token, "prod-web-01")

    message = str(exc.value)
    assert "prod-web-01" in message  # which server
    assert "WEBGATE_SECRET_KEY" in message  # why
    assert "backup" in message  # and the way out


def test_a_matching_key_still_round_trips(monkeypatch):
    monkeypatch.setattr(env_settings, "secret_key", "steady")
    assert decrypt_value(encrypt_value("hunter2")) == "hunter2"


def test_an_empty_value_is_not_an_error(monkeypatch):
    monkeypatch.setattr(env_settings, "secret_key", "steady")
    assert decrypt_value("") == ""


@pytest.mark.asyncio
async def test_one_unreadable_server_does_not_stop_the_monitor(monkeypatch):
    """It used to raise through the gather and end the sweep for every host."""
    from webgate.servers.models import Server
    from webgate.servers.monitor import ServerMonitor

    token = _rotate(monkeypatch)
    server = Server(
        id=1,
        name="prod-web-01",
        hostname="192.0.2.1",
        port=22,
        username="root",
        auth_method="password",
        encrypted_password=token,
        encrypted_private_key="",
        host_key="",
    )
    status = await ServerMonitor()._check_server(server)

    assert status.online is False
    assert "prod-web-01" in status.error
    assert "WEBGATE_SECRET_KEY" in status.error


@pytest.mark.asyncio
async def test_the_connection_test_reports_it_rather_than_raising(monkeypatch):
    from webgate.servers.models import Server
    from webgate.servers.service import test_server_connectivity

    token = _rotate(monkeypatch)
    server = Server(
        id=1,
        name="prod-db",
        hostname="192.0.2.2",
        port=22,
        username="postgres",
        auth_method="password",
        encrypted_password=token,
        encrypted_private_key="",
        host_key="",
    )
    ok, message = await test_server_connectivity(server)
    assert ok is False
    assert "prod-db" in message


@pytest.mark.asyncio
async def test_a_terminal_answers_with_an_error_frame_not_a_failed_handshake(monkeypatch):
    """A raised exception here fails the WebSocket upgrade itself, and the browser
    gets a 500 with nothing in it."""
    from webgate.servers.models import Server
    from webgate.servers.service import get_server_credentials

    token = _rotate(monkeypatch)
    server = Server(
        id=1,
        name="prod-web-01",
        hostname="192.0.2.1",
        port=22,
        username="root",
        auth_method="password",
        encrypted_password=token,
        encrypted_private_key="",
        host_key="",
    )
    # The route catches exactly this and turns it into {"type": "error", ...}.
    with pytest.raises(CredentialUnreadable):
        get_server_credentials(server)

    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    try:
        get_server_credentials(server)
    except CredentialUnreadable as exc:
        await ws.send_json({"type": "error", "message": str(exc)})
        await ws.close(code=1011)
    assert "prod-web-01" in str(ws.send_json.await_args)
