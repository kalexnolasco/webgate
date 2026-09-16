"""What the audit log actually records.

Reported by a user: someone deleted a file and the log did not say which one. The
truth was worse -- `files/routes.py` contained no audit call at all, so no SFTP
operation was recorded in any form. Server and user lifecycle changes were missing
too: only clearing a host key pin and signing in were ever written down.

A log that says something happened without saying what is the same as no log.
"""

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from webgate.files.routes import SftpSession


@contextlib.asynccontextmanager
async def _fake_sftp(*_a, **_k):
    client = MagicMock()
    for method in ("delete", "rename", "mkdir", "chmod", "write_text", "upload"):
        setattr(client, method, AsyncMock())
    client.read_bytes = AsyncMock(return_value=b"contents")
    client.stat = AsyncMock(return_value=MagicMock(size=8, name="app.log"))
    yield SftpSession(client, [], False, "prod-web-01")


async def _entries(client, auth_headers, **params):
    resp = await client.get("/api/auth/audit", headers=auth_headers, params=params)
    assert resp.status_code == 200
    return resp.json()


async def _server(client, auth_headers, name="prod-web-01"):
    resp = await client.post(
        "/api/servers",
        headers=auth_headers,
        json={"name": name, "hostname": "192.0.2.1", "username": "u", "password": "p"},
    )
    return resp.json()["id"]


# ------------------------------------------------------------------ file operations


@pytest.mark.asyncio
async def test_a_deleted_file_is_named(client, auth_headers):
    """The report: 'they deleted a file and we do not know which one'."""
    sid = await _server(client, auth_headers)
    with patch("webgate.files.routes._sftp", _fake_sftp):
        await client.delete(
            f"/api/files/{sid}/delete",
            headers=auth_headers,
            params={"path": "/etc/nginx/nginx.conf"},
        )

    entry = next(e for e in await _entries(client, auth_headers) if e["action"] == "sftp_delete")
    assert "/etc/nginx/nginx.conf" in entry["detail"]
    assert "prod-web-01" in entry["detail"]  # which server, not just which path
    assert entry["username"] == "admin"


@pytest.mark.asyncio
async def test_a_rename_records_both_names(client, auth_headers):
    """Only the new name would leave 'where did app.log go' unanswerable."""
    sid = await _server(client, auth_headers)
    with patch("webgate.files.routes._sftp", _fake_sftp):
        await client.post(
            f"/api/files/{sid}/rename",
            headers=auth_headers,
            json={"old_path": "/srv/app.log", "new_path": "/srv/app.log.1"},
        )

    entry = next(e for e in await _entries(client, auth_headers) if e["action"] == "sftp_rename")
    assert "/srv/app.log" in entry["detail"] and "/srv/app.log.1" in entry["detail"]


@pytest.mark.asyncio
async def test_a_download_is_recorded(client, auth_headers):
    """Taking a copy of a file leaves the same trace as deleting it."""
    sid = await _server(client, auth_headers)
    with patch("webgate.files.routes._sftp", _fake_sftp):
        await client.get(
            f"/api/files/{sid}/download", headers=auth_headers, params={"path": "/etc/shadow"}
        )

    entry = next(e for e in await _entries(client, auth_headers) if e["action"] == "sftp_download")
    assert "/etc/shadow" in entry["detail"]


@pytest.mark.asyncio
async def test_writing_and_permission_changes_are_recorded(client, auth_headers):
    sid = await _server(client, auth_headers)
    with patch("webgate.files.routes._sftp", _fake_sftp):
        await client.put(
            f"/api/files/{sid}/write",
            headers=auth_headers,
            json={"path": "/srv/app.conf", "content": "debug = true"},
        )
        await client.post(
            f"/api/files/{sid}/chmod",
            headers=auth_headers,
            json={"path": "/srv/id_rsa", "mode": "777"},
        )

    actions = {e["action"]: e["detail"] for e in await _entries(client, auth_headers)}
    assert "/srv/app.conf" in actions["sftp_write"]
    assert "/srv/id_rsa" in actions["sftp_chmod"] and "777" in actions["sftp_chmod"]


@pytest.mark.asyncio
async def test_an_entry_says_where_it_came_from(client, auth_headers):
    sid = await _server(client, auth_headers)
    with patch("webgate.files.routes._sftp", _fake_sftp):
        await client.delete(
            f"/api/files/{sid}/delete", headers=auth_headers, params={"path": "/tmp/x"}
        )
    entry = next(e for e in await _entries(client, auth_headers) if e["action"] == "sftp_delete")
    assert entry["ip_address"]


# ------------------------------------------------------------- registry and accounts


@pytest.mark.asyncio
async def test_registering_and_removing_a_server_is_recorded(client, auth_headers):
    """A server row carries credentials; deleting one was invisible."""
    sid = await _server(client, auth_headers, name="prod-db")
    await client.delete(f"/api/servers/{sid}", headers=auth_headers)

    actions = {e["action"]: e["detail"] for e in await _entries(client, auth_headers)}
    assert "prod-db" in actions["server_created"]
    assert "prod-db" in actions["server_deleted"]
    assert "credentials" in actions["server_deleted"]


@pytest.mark.asyncio
async def test_a_server_update_names_the_fields_but_never_the_values(client, auth_headers):
    """An update carries a password. The log must say what changed, not to what."""
    sid = await _server(client, auth_headers)
    await client.put(
        f"/api/servers/{sid}", headers=auth_headers, json={"password": "hunter2", "port": 2222}
    )

    entry = next(e for e in await _entries(client, auth_headers) if e["action"] == "server_updated")
    assert "password" in entry["detail"] and "port" in entry["detail"]
    assert "hunter2" not in entry["detail"]


@pytest.mark.asyncio
async def test_account_changes_are_recorded(client, auth_headers):
    created = await client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"username": "erin", "password": "erinpass123", "allowed_groups": ["prod"]},
    )
    uid = created.json()["id"]
    await client.put(
        f"/api/auth/users/{uid}/groups", headers=auth_headers, json={"allowed_groups": ["edge"]}
    )
    await client.put(
        f"/api/auth/users/{uid}/password",
        headers=auth_headers,
        json={"username": "erin", "password": "newpass123456"},
    )
    await client.delete(f"/api/auth/users/{uid}", headers=auth_headers)

    actions = {e["action"]: e["detail"] for e in await _entries(client, auth_headers)}
    assert "erin" in actions["user_created"] and "prod" in actions["user_created"]
    assert "prod" in actions["user_groups_changed"] and "edge" in actions["user_groups_changed"]
    assert actions["user_password_reset"] == "erin"
    assert actions["user_deleted"] == "erin"
    assert "newpass123456" not in str(actions)


# ----------------------------------------------------------------------- finding it


@pytest.mark.asyncio
async def test_you_can_search_for_the_filename(client, auth_headers):
    """What an operator has is a filename, not the action kind."""
    sid = await _server(client, auth_headers)
    with patch("webgate.files.routes._sftp", _fake_sftp):
        await client.delete(
            f"/api/files/{sid}/delete", headers=auth_headers, params={"path": "/etc/nginx.conf"}
        )
        await client.delete(
            f"/api/files/{sid}/delete", headers=auth_headers, params={"path": "/var/log/other.log"}
        )

    found = await _entries(client, auth_headers, search="nginx")
    assert len(found) == 1
    assert "/etc/nginx.conf" in found[0]["detail"]


@pytest.mark.asyncio
async def test_the_search_is_case_insensitive(client, auth_headers):
    sid = await _server(client, auth_headers)
    with patch("webgate.files.routes._sftp", _fake_sftp):
        await client.delete(
            f"/api/files/{sid}/delete", headers=auth_headers, params={"path": "/srv/README.md"}
        )
    assert await _entries(client, auth_headers, search="readme")


@pytest.mark.asyncio
async def test_a_date_range_narrows_it(client, auth_headers):
    await _server(client, auth_headers)
    assert await _entries(client, auth_headers, since="2000-01-01T00:00:00")
    assert await _entries(client, auth_headers, until="2000-01-01T00:00:00") == []


@pytest.mark.asyncio
async def test_the_action_kinds_present_are_listed(client, auth_headers):
    """So the filter is a list to pick from rather than a name to guess."""
    await _server(client, auth_headers)
    resp = await client.get("/api/auth/audit/actions", headers=auth_headers)
    assert "server_created" in resp.json()


@pytest.mark.asyncio
async def test_only_an_admin_reads_the_log(client, auth_headers):
    await client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"username": "plain", "password": "plainpass123", "allowed_groups": []},
    )
    token = (
        await client.post("/api/auth/login", json={"username": "plain", "password": "plainpass123"})
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.get("/api/auth/audit", headers=headers)).status_code == 403
    assert (await client.get("/api/auth/audit/actions", headers=headers)).status_code == 403
