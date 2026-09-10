"""A ceiling on what one transfer may pull into the gateway's memory.

There was none, and `max_upload_size` -- documented, configurable -- was read by
nobody. The cases worth proving are the ones that used to be unbounded: a single
large file, an upload whose declared size lies, and a ZIP that accumulates a whole
directory tree.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from webgate.files.limits import Budget, TooLarge, human
from webgate.files.sftp_service import SFTPClient


def _client() -> SFTPClient:
    c = SFTPClient(MagicMock())
    c._sftp = MagicMock()
    return c


def _handle(payload: bytes):
    """A file handle that hands out `payload` in whatever chunk size is asked for."""
    state = {"pos": 0}

    async def read(size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk = payload[state["pos"] :]
            state["pos"] = len(payload)
            return chunk
        chunk = payload[state["pos"] : state["pos"] + size]
        state["pos"] += len(chunk)
        return chunk

    handle = MagicMock()
    handle.read = read
    handle.__aenter__ = AsyncMock(return_value=handle)
    handle.__aexit__ = AsyncMock(return_value=False)
    return handle


# --------------------------------------------------------------------- the budget


def test_a_known_size_is_refused_before_anything_is_read():
    with pytest.raises(TooLarge):
        Budget(1024).check(2048)
    Budget(1024).check(1024)  # exactly at the limit is allowed


def test_spending_stops_the_moment_it_runs_over():
    budget = Budget(100)
    budget.spend(60)
    with pytest.raises(TooLarge):
        budget.spend(60)


def test_zero_means_no_limit():
    budget = Budget(0)
    assert budget.unlimited
    budget.check(10**12)
    budget.spend(10**12)


def test_the_message_says_where_to_change_it():
    """An operator hitting a limit should not have to find the setting themselves."""
    with pytest.raises(TooLarge) as exc:
        Budget(1024).check(2048, "server.log")
    text = str(exc.value)
    assert "server.log" in text
    assert "1.0 KB" in text
    assert "Settings" in text


def test_sizes_read_the_way_people_write_them():
    assert human(512) == "512 B"
    assert human(1024) == "1.0 KB"
    assert human(100 * 1024 * 1024) == "100.0 MB"


# ----------------------------------------------------------------------- reading


@pytest.mark.asyncio
async def test_a_file_over_the_limit_is_refused_partway():
    """It used to be one read() of the whole file, whatever its size."""
    c = _client()
    c._sftp.open = MagicMock(return_value=_handle(b"x" * 10_000))
    with pytest.raises(TooLarge):
        await c.read_bytes("/var/log/huge.log", Budget(1024))


@pytest.mark.asyncio
async def test_a_file_within_the_limit_still_arrives_whole():
    c = _client()
    c._sftp.open = MagicMock(return_value=_handle(b"y" * 5_000))
    assert await c.read_bytes("/etc/motd", Budget(10_000)) == b"y" * 5_000


@pytest.mark.asyncio
async def test_without_a_budget_nothing_changes():
    c = _client()
    c._sftp.open = MagicMock(return_value=_handle(b"z" * 3_000))
    assert len(await c.read_bytes("/etc/motd")) == 3_000


# --------------------------------------------------------------------------- zip


@pytest.mark.asyncio
async def test_an_archive_over_the_limit_fails_instead_of_arriving_partial():
    """Silently dropping the file that broke the budget is how a ZIP loses data."""
    import asyncssh

    c = _client()
    entries = []
    for name in ("a.log", "b.log"):
        item = MagicMock()
        item.filename = name
        item.attrs.type = asyncssh.FILEXFER_TYPE_REGULAR
        entries.append(item)
    c._sftp.readdir = AsyncMock(return_value=entries)
    c._sftp.open = MagicMock(side_effect=lambda *a, **k: _handle(b"q" * 4_000))

    with pytest.raises(TooLarge):
        await c.read_directory_as_zip("/var/log", Budget(5_000))


@pytest.mark.asyncio
async def test_an_archive_within_the_limit_is_built():
    import asyncssh

    c = _client()
    item = MagicMock()
    item.filename = "a.log"
    item.attrs.type = asyncssh.FILEXFER_TYPE_REGULAR
    c._sftp.readdir = AsyncMock(return_value=[item])
    c._sftp.open = MagicMock(side_effect=lambda *a, **k: _handle(b"q" * 100))

    assert await c.read_directory_as_zip("/var/log", Budget(10_000))
