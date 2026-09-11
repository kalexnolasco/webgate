"""Background status checks.

The monitor had no tests, which is how a missing import and a fatal key-parse both
survived in it. These cover the two things that decide whether the dashboard tells the
truth: one unusable server must not blind the rest, and a probe must use the auth
method the server actually declares.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from webgate.servers.crypto import encrypt_value
from webgate.servers.models import Server
from webgate.servers.monitor import ServerMonitor


def _server(**kw) -> Server:
    defaults = dict(
        id=1,
        name="prod-web-01",
        hostname="192.0.2.1",
        port=22,
        username="root",
        auth_method="password",
        encrypted_password="",
        encrypted_private_key="",
        host_key="",
    )
    return Server(**{**defaults, **kw})


@pytest.mark.asyncio
async def test_an_unreadable_key_marks_one_server_offline_instead_of_raising():
    """It used to raise out through the gather in _check_all and kill the cycle,
    leaving every other server's status frozen at whatever it last was."""
    server = _server(auth_method="key", encrypted_private_key=encrypt_value("not a key"))
    status = await ServerMonitor()._check_server(server)

    assert status.online is False
    assert status.error


@pytest.mark.asyncio
async def test_one_broken_server_does_not_stop_the_others():
    monitor = ServerMonitor()
    servers = [
        _server(id=1, auth_method="key", encrypted_private_key=encrypt_value("junk")),
        _server(id=2, name="prod-web-02", encrypted_password=encrypt_value("pw")),
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = servers
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    with patch("webgate.servers.monitor.async_session_factory") as factory:
        factory.return_value.__aenter__.return_value = session
        await monitor._check_all()

    assert set(monitor._statuses) == {1, 2}


@pytest.mark.asyncio
async def test_the_declared_auth_method_wins_over_a_stale_key_row():
    """A server moved from key to password keeps its old key. Preferring the key
    probes with the wrong credential and reports a working host as offline."""
    server = _server(
        auth_method="password",
        encrypted_password=encrypt_value("hunter2"),
        encrypted_private_key=encrypt_value("a stale key nobody removed"),
    )
    with patch("webgate.servers.monitor.asyncssh.connect", new_callable=AsyncMock) as connect:
        connect.return_value = MagicMock()
        await ServerMonitor()._check_server(server)

    kwargs = connect.await_args.kwargs
    assert kwargs["password"] == "hunter2"
    assert "client_keys" not in kwargs


@pytest.mark.asyncio
async def test_the_pinned_host_key_is_carried_into_the_probe():
    """A probe that skipped verification would re-learn nothing but would still be
    one more path handing credentials to whatever answers."""
    import asyncssh

    key = asyncssh.generate_private_key("ssh-ed25519").export_public_key("openssh").decode()
    server = _server(encrypted_password=encrypt_value("pw"), host_key=key.strip())
    with patch("webgate.servers.monitor.asyncssh.connect", new_callable=AsyncMock) as connect:
        connect.return_value = MagicMock()
        await ServerMonitor()._check_server(server)

    assert connect.await_args.kwargs["known_hosts"] is not None
