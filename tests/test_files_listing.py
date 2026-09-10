"""Listing ergonomics: uid/gid name resolution and archiving a chosen selection."""

import io
import zipfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from webgate.files.sftp_service import SFTPClient

PASSWD = (
    b"root:x:0:0:root:/root:/bin/bash\n"
    b"alex:x:1000:1000:Alex:/home/alex:/bin/bash\n"
    b"broken-line\n"
)
GROUP = b"root:x:0:\nalex:x:1000:\n"


def _client() -> SFTPClient:
    c = SFTPClient(MagicMock())
    c._sftp = MagicMock()
    return c


def _file_handle(payload: bytes):
    handle = MagicMock()
    handle.read = AsyncMock(return_value=payload)
    handle.__aenter__ = AsyncMock(return_value=handle)
    handle.__aexit__ = AsyncMock(return_value=False)
    return handle


@pytest.mark.asyncio
async def test_id_maps_resolve_names():
    c = _client()
    c._sftp.open = MagicMock(
        side_effect=lambda path, mode: _file_handle(PASSWD if "passwd" in path else GROUP)
    )
    await c._load_id_maps()

    assert c._users[0] == "root"
    assert c._users[1000] == "alex"
    assert c._groups[1000] == "alex"
    assert c._name_for(1000, c._users) == "alex"


@pytest.mark.asyncio
async def test_unknown_id_falls_back_to_the_number():
    c = _client()
    c._sftp.open = MagicMock(side_effect=lambda path, mode: _file_handle(PASSWD))
    await c._load_id_maps()

    assert c._name_for(4242, c._users) == "4242"
    assert c._name_for(None, c._users) == ""


@pytest.mark.asyncio
async def test_hosts_without_passwd_keep_numeric_ids():
    """LDAP-only hosts and minimal containers must still list files."""
    c = _client()
    c._sftp.open = MagicMock(side_effect=PermissionError("nope"))
    await c._load_id_maps()

    assert c._users == {}
    assert c._name_for(1000, c._users) == "1000"


@pytest.mark.asyncio
async def test_id_maps_are_loaded_once():
    c = _client()
    opener = MagicMock(side_effect=lambda path, mode: _file_handle(PASSWD))
    c._sftp.open = opener
    await c._load_id_maps()
    calls = opener.call_count
    await c._load_id_maps()

    assert opener.call_count == calls  # cached for the life of the connection


@pytest.mark.asyncio
async def test_zip_of_a_selection_is_relative_to_the_base():
    c = _client()
    c._sftp.stat = AsyncMock(return_value=MagicMock(type=1))  # not a directory
    c.read_bytes = AsyncMock(side_effect=[b"one", b"two"])

    data, skipped = await c.read_paths_as_zip(["/var/log/a.log", "/var/log/b.log"], "/var/log")

    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert names == ["a.log", "b.log"]  # not the full path
    assert skipped == []


@pytest.mark.asyncio
async def test_unreadable_entries_are_reported_not_swallowed():
    """A partial archive must say what it dropped, or the user loses files silently."""
    c = _client()
    c._sftp.stat = AsyncMock(return_value=MagicMock(type=1))
    c.read_bytes = AsyncMock(side_effect=[b"ok", PermissionError("denied")])

    data, skipped = await c.read_paths_as_zip(["/etc/hosts", "/etc/shadow"], "/etc")

    assert zipfile.ZipFile(io.BytesIO(data)).namelist() == ["hosts"]
    assert skipped == ["shadow"]


@pytest.mark.asyncio
async def test_missing_paths_are_reported():
    c = _client()
    c._sftp.stat = AsyncMock(side_effect=FileNotFoundError("gone"))

    data, skipped = await c.read_paths_as_zip(["/tmp/gone.txt"], "/tmp")

    assert zipfile.ZipFile(io.BytesIO(data)).namelist() == []
    assert skipped == ["gone.txt"]


@pytest.mark.asyncio
async def test_zip_selection_rejects_traversal(client, auth_headers):
    srv = await client.post(
        "/api/servers",
        headers=auth_headers,
        json={"name": "zt", "hostname": "192.0.2.1", "username": "u", "password": "p"},
    )
    sid = srv.json()["id"]
    resp = await client.post(
        f"/api/files/{sid}/download-zip",
        headers=auth_headers,
        json={"paths": ["../../etc/shadow"], "base_path": "/tmp"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_zip_selection_rejects_empty(client, auth_headers):
    srv = await client.post(
        "/api/servers",
        headers=auth_headers,
        json={"name": "ze", "hostname": "192.0.2.1", "username": "u", "password": "p"},
    )
    sid = srv.json()["id"]
    resp = await client.post(
        f"/api/files/{sid}/download-zip",
        headers=auth_headers,
        json={"paths": [], "base_path": "/tmp"},
    )
    assert resp.status_code == 422
