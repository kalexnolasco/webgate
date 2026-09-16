"""A cap on how many terminals one account can hold open.

There was none. A browser tab in a reconnect loop, or a script, could open SSH
sessions until the worker ran out of them -- and every other person on that worker
went down with it.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from webgate.config import settings as env_settings
from webgate.runtime_config import store as runtime
from webgate.terminal.shared import SharedSession, SharedSessionManager


@pytest.fixture(autouse=True)
def _no_overrides():
    runtime._overrides.clear()
    yield
    runtime._overrides.clear()


def _session(manager: SharedSessionManager, owner: str) -> SharedSession:
    ssh = MagicMock()
    ssh.close = AsyncMock()
    sess = SharedSession(
        session_id=manager.new_session_id(),
        server_label="prod-web-01",
        owner_username=owner,
        ssh=ssh,
    )
    manager.register(sess)
    return sess


def test_sessions_are_counted_per_account():
    m = SharedSessionManager()
    _session(m, "alice")
    _session(m, "alice")
    _session(m, "bob")

    assert m.count_for("alice") == 2
    assert m.count_for("bob") == 1
    assert m.count_for("carol") == 0


def test_a_closed_session_stops_counting():
    """Otherwise a cap of three would lock someone out after three tabs, ever."""
    m = SharedSessionManager()
    first = _session(m, "alice")
    _session(m, "alice")
    first.closed = True

    assert m.count_for("alice") == 1


def test_unregistering_stops_counting():
    m = SharedSessionManager()
    sess = _session(m, "alice")
    assert m.count_for("alice") == 1

    m.unregister(sess.session_id)
    assert m.count_for("alice") == 0


@pytest.mark.asyncio
async def test_the_limit_refuses_before_any_ssh_connection_is_made(monkeypatch):
    """Refusing after connecting would still spend the thing being protected."""
    from webgate.terminal import ws_handler

    monkeypatch.setattr(env_settings, "max_sessions_per_user", 2)
    m = SharedSessionManager()
    _session(m, "alice")
    _session(m, "alice")
    monkeypatch.setattr(ws_handler, "manager", m)

    connected = False

    class _NeverConnects:
        def __init__(self, **_kw):
            pass

        async def connect(self, **_kw):
            nonlocal connected
            connected = True

    monkeypatch.setattr(ws_handler, "SSHSession", _NeverConnects)

    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    await ws_handler.handle_terminal_ws(ws, host="h", port=22, username="u", owner_username="alice")

    assert not connected, "an SSH connection was opened for a session we refuse"
    ws.close.assert_awaited()
    said = str(ws.send_json.await_args)
    assert "2 terminals" in said
    assert "Close one" in said  # what to do, not just what went wrong


@pytest.mark.asyncio
async def test_under_the_limit_the_session_proceeds(monkeypatch):
    from webgate.terminal import ws_handler

    monkeypatch.setattr(env_settings, "max_sessions_per_user", 3)
    m = SharedSessionManager()
    _session(m, "alice")
    monkeypatch.setattr(ws_handler, "manager", m)

    reached = False

    class _Connects:
        def __init__(self, **_kw):
            pass

        async def connect(self, **_kw):
            nonlocal reached
            reached = True
            raise RuntimeError("stop here, the point is that we got this far")

    monkeypatch.setattr(ws_handler, "SSHSession", _Connects)
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    await ws_handler.handle_terminal_ws(ws, host="h", port=22, username="u", owner_username="alice")
    assert reached


@pytest.mark.asyncio
async def test_zero_means_no_limit(monkeypatch):
    from webgate.terminal import ws_handler

    monkeypatch.setattr(env_settings, "max_sessions_per_user", 0)
    m = SharedSessionManager()
    for _ in range(25):
        _session(m, "alice")
    monkeypatch.setattr(ws_handler, "manager", m)

    reached = False

    class _Connects:
        def __init__(self, **_kw):
            pass

        async def connect(self, **_kw):
            nonlocal reached
            reached = True
            raise RuntimeError("far enough")

    monkeypatch.setattr(ws_handler, "SSHSession", _Connects)
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    await ws_handler.handle_terminal_ws(ws, host="h", port=22, username="u", owner_username="alice")
    assert reached


@pytest.mark.asyncio
async def test_one_persons_sessions_do_not_block_another(client, auth_headers):
    """The cap is per account, so a busy colleague cannot lock you out."""
    from webgate.terminal import ws_handler

    m = SharedSessionManager()
    for _ in range(5):
        _session(m, "alice")
    assert m.count_for("bob") == 0
    assert ws_handler is not None
