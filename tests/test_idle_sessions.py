"""Closing SSH sessions that have gone quiet.

`session_timeout` was documented and configurable and read by nobody, so an
abandoned tab held an SSH session -- and the credentials behind it -- open for as
long as the gateway ran.
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from webgate.config import settings as env_settings
from webgate.runtime_config import store as runtime
from webgate.terminal.shared import SharedSession, SharedSessionManager


def _session(idle_for: float = 0.0) -> SharedSession:
    ssh = MagicMock()
    ssh.close = AsyncMock()
    ssh.write = AsyncMock()
    sess = SharedSession(
        session_id="s1", server_label="prod-web-01", owner_username="admin", ssh=ssh
    )
    sess.last_activity = time.monotonic() - idle_for
    return sess


@pytest.fixture(autouse=True)
def _short_timeout(monkeypatch):
    monkeypatch.setattr(env_settings, "session_timeout", 60)
    runtime._overrides.clear()
    yield
    runtime._overrides.clear()


@pytest.mark.asyncio
async def test_a_session_idle_past_the_limit_is_closed():
    sess = _session(idle_for=120)
    await SharedSessionManager().watch_idle(sess)

    assert sess.closed
    sess.ssh.close.assert_awaited()


@pytest.mark.asyncio
async def test_the_user_is_told_why_their_terminal_stopped():
    """A terminal that goes dead with no explanation reads as a bug."""
    sess = _session(idle_for=120)
    participant = MagicMock()
    participant.ws.send_text = AsyncMock()
    participant.username, participant.mode = "admin", "rw"
    sess.participants.append(participant)

    await SharedSessionManager().watch_idle(sess)

    sent = " ".join(str(c.args[0]) for c in participant.ws.send_text.await_args_list)
    assert "idle" in sent and "60" in sent


@pytest.mark.asyncio
async def test_zero_means_sessions_are_never_expired(monkeypatch):
    monkeypatch.setattr(env_settings, "session_timeout", 0)
    sess = _session(idle_for=10_000)

    import asyncio

    task = asyncio.create_task(SharedSessionManager().watch_idle(sess))
    await asyncio.sleep(0.05)
    task.cancel()

    assert not sess.closed


@pytest.mark.asyncio
async def test_output_counts_as_activity():
    """Watching a long build scroll past is not idleness."""
    sess = _session(idle_for=120)
    await sess.broadcast("still building...\r\n")
    assert sess.idle_seconds < 1


@pytest.mark.asyncio
async def test_input_counts_as_activity():
    sess = _session(idle_for=120)
    participant = MagicMock()
    participant.username, participant.mode = "admin", "rw"
    sess.participants.append(participant)

    await sess.write_input("ls\n", "admin")
    assert sess.idle_seconds < 1


@pytest.mark.asyncio
async def test_lowering_the_limit_reaches_sessions_that_are_already_open():
    """The limit is read each pass, not captured when the session started."""
    sess = _session(idle_for=120)
    runtime._overrides["session_timeout"] = 3600
    import asyncio

    task = asyncio.create_task(SharedSessionManager().watch_idle(sess))
    await asyncio.sleep(0.05)
    assert not sess.closed

    runtime._overrides["session_timeout"] = 30
    await asyncio.sleep(0.05)
    task.cancel()
    # The watchdog is mid-sleep, so drive one more pass to see the new limit applied.
    await SharedSessionManager().watch_idle(sess)
    assert sess.closed
