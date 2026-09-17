"""What the text editor is allowed to open.

`read_text` used to decode with `errors="replace"`, so an executable or an archive
opened in the editor as a wall of U+FFFD -- with a **Save** button beside it. Saving
wrote those replacement characters back, which rewrote the file as mangled text and
destroyed it. Nothing warned anybody, and the file was gone.

It was also the one read path with no budget, so the editor was the way around the
transfer limit every other path enforces.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from webgate.files.limits import Budget, TooLarge
from webgate.files.sftp_service import NotEditable, SFTPClient


def _client(payload: bytes) -> SFTPClient:
    """An SFTP client whose every file is `payload`."""

    def _handle(_path: str, _mode: str):
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

    client = SFTPClient(MagicMock())
    client._sftp = MagicMock()
    client._sftp.open = _handle
    return client


# ----------------------------------------------------------------- what opens


@pytest.mark.asyncio
async def test_text_still_opens():
    text = "server {\n    listen 80;\n}\n"
    assert await _client(text.encode()).read_text("/etc/nginx/nginx.conf") == text


@pytest.mark.asyncio
async def test_an_empty_file_opens():
    """Nothing in an empty file is binary, and refusing one would be absurd."""
    assert await _client(b"").read_text("/tmp/new.conf") == ""


@pytest.mark.asyncio
async def test_utf8_beyond_ascii_opens():
    """Accents and box drawing are text; only the lossy decode made them look risky."""
    text = "# Configuración — límite: 5 MB\nrutas = ['/var/log']\n"
    assert await _client(text.encode()).read_text("/srv/app.py") == text


@pytest.mark.asyncio
async def test_a_nul_late_in_a_long_text_file_still_opens():
    """The sniff is the first few KB, deliberately: reading the whole of a large log
    to look for one NUL would cost more than the check is worth."""
    payload = b"log line\n" * 4000 + b"\x00"
    assert (await _client(payload).read_text("/var/log/app.log")).startswith("log line")


# -------------------------------------------------------------- what is refused


@pytest.mark.asyncio
async def test_a_binary_file_is_refused_rather_than_mangled():
    """The reported shape of the loss: open /bin/ls, press Save, lose /bin/ls."""
    with pytest.raises(NotEditable) as exc:
        await _client(b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00").read_text("/bin/ls")
    assert "ls" in str(exc.value)
    assert "download" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_an_archive_is_refused():
    with pytest.raises(NotEditable):
        await _client(b"PK\x03\x04\x14\x00\x00\x00\x08\x00").read_text("/tmp/backup.zip")


@pytest.mark.asyncio
async def test_text_that_is_not_utf8_is_refused():
    """A latin-1 config has no NUL byte, so the sniff passes it. Saving it would
    still have rewritten every accented byte, so it is refused on the decode."""
    with pytest.raises(NotEditable) as exc:
        await _client("configuración\n".encode("latin-1")).read_text("/etc/app.cfg")
    assert "UTF-8" in str(exc.value)


@pytest.mark.asyncio
async def test_the_refusal_names_the_file():
    """A message that does not say which file is a message nobody can act on."""
    with pytest.raises(NotEditable) as exc:
        await _client(b"\x00\x01\x02").read_text("/var/lib/webgate/webgate.db")
    assert "webgate.db" in str(exc.value)


# ---------------------------------------------------------------- the budget


@pytest.mark.asyncio
async def test_reading_for_the_editor_respects_the_budget():
    """The gap: every other read path was bounded and this one was not."""
    with pytest.raises(TooLarge):
        await _client(b"x" * (2 * 1024 * 1024)).read_text("/var/log/huge.log", Budget(1024))


@pytest.mark.asyncio
async def test_a_file_inside_the_budget_is_unaffected():
    payload = b"fits\n" * 100
    assert await _client(payload).read_text("/etc/hosts", Budget(1024 * 1024)) == (payload.decode())
