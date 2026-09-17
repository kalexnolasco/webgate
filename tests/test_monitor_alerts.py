"""The monitor telling somebody when a server goes down.

It has always known -- it probes every server on a timer -- and it has only ever
painted a dot with what it found. Webhooks existed too, firing on file operations,
server registration and sign-ins. The two halves were never connected, so an outage
was only ever noticed by whoever happened to be looking at the screen.

What matters here is not that a webhook fires. It is that it fires on a *change*,
once, and not on every sweep for as long as the host stays down.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from webgate.servers.monitor import ServerMonitor, ServerStatus


class _Server:
    def __init__(self, sid: int = 1, name: str = "prod-web-01") -> None:
        self.id = sid
        self.name = name
        self.hostname = "10.0.0.7"
        self.port = 22


def _status(online: bool, error: str | None = None) -> ServerStatus:
    return ServerStatus(
        online=online,
        last_checked=datetime.now(UTC),
        latency_ms=12.5 if online else None,
        error=error,
    )


async def _sweep(monitor: ServerMonitor, server: _Server, *results: bool) -> list[Any]:
    """Run the announcement for each result in turn, collecting what it fired."""
    fired: list[Any] = []
    with patch("webgate.servers.monitor.fire_webhook", new=AsyncMock()) as fire:
        for online in results:
            await monitor._announce(server, _status(online))
        fired = [(c.args[0], c.args[1]) for c in fire.await_args_list]
    return fired


@pytest.fixture
def monitor() -> ServerMonitor:
    return ServerMonitor()


# ------------------------------------------------------------------ going down


@pytest.mark.asyncio
async def test_a_single_failed_check_is_not_an_outage(monitor: ServerMonitor):
    """One lost packet is not news. Paging on it teaches people to ignore paging."""
    assert await _sweep(monitor, _Server(), True, False) == []


@pytest.mark.asyncio
async def test_a_server_that_stays_down_is_announced_once(monitor: ServerMonitor):
    fired = await _sweep(monitor, _Server(), True, False, False, False, False)
    assert [e for e, _ in fired] == ["server_offline"], "one sweep, one alert"


@pytest.mark.asyncio
async def test_the_alert_says_which_server_and_why(monitor: ServerMonitor):
    server = _Server()
    with patch("webgate.servers.monitor.fire_webhook", new=AsyncMock()) as fire:
        await monitor._announce(server, _status(True))
        await monitor._announce(server, _status(False, "Connection refused"))
        await monitor._announce(server, _status(False, "Connection refused"))
    _, payload = fire.await_args_list[-1].args
    assert payload["server"] == "prod-web-01"
    assert payload["hostname"] == "10.0.0.7"
    assert payload["error"] == "Connection refused"
    assert payload["online"] is False
    assert payload["failed_checks"] == 2


# ----------------------------------------------------------------- coming back


@pytest.mark.asyncio
async def test_recovery_is_announced_on_the_first_good_check(monitor: ServerMonitor):
    """Waiting to be sure a host is *back* helps nobody."""
    fired = await _sweep(monitor, _Server(), True, False, False, True)
    assert [e for e, _ in fired] == ["server_offline", "server_online"]


@pytest.mark.asyncio
async def test_a_flap_that_never_completes_says_nothing(monitor: ServerMonitor):
    """Alternating results never reach the threshold, so there is nothing to report."""
    assert await _sweep(monitor, _Server(), True, False, True, False, True, False) == []


@pytest.mark.asyncio
async def test_a_healthy_server_is_never_mentioned(monitor: ServerMonitor):
    assert await _sweep(monitor, _Server(), True, True, True, True) == []


# ------------------------------------------------------------- the first sweep


@pytest.mark.asyncio
async def test_a_restart_does_not_announce_the_whole_fleet_as_up(monitor: ServerMonitor):
    """Every deploy would otherwise fire one webhook per healthy server."""
    assert await _sweep(monitor, _Server(), True) == []


@pytest.mark.asyncio
async def test_a_server_already_down_at_startup_is_still_reported(monitor: ServerMonitor):
    """Nobody was told about this one, so the restart is not a reason to stay quiet."""
    fired = await _sweep(monitor, _Server(), False, False)
    assert [e for e, _ in fired] == ["server_offline"]


@pytest.mark.asyncio
async def test_a_deleted_server_leaves_no_history_behind(monitor: ServerMonitor):
    """Ids get reused. The next server to take this one must start from scratch,
    not inherit a state that would make its first check look like a change."""
    server = _Server()
    await _sweep(monitor, server, True, False, False)
    monitor.forget(server.id)
    assert await _sweep(monitor, server, True) == [], "the new server was announced"


# -------------------------------------------------------------- the threshold


@pytest.mark.asyncio
async def test_the_threshold_is_configurable(monitor: ServerMonitor):
    with patch("webgate.servers.monitor._alert_after", return_value=4):
        fired = await _sweep(monitor, _Server(), True, False, False, False)
        assert fired == [], "three failures, threshold of four"
        fired = await _sweep(monitor, _Server(), False)
    assert [e for e, _ in fired] == ["server_offline"]
