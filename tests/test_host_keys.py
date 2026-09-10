"""Host key pinning.

Without this the gateway hands stored fleet credentials to whatever answers on the
target's address. The tests that matter are the ones proving a changed key is refused
*before* authentication runs, and that a pin is never overwritten by accident.
"""

from unittest.mock import AsyncMock, MagicMock

import asyncssh
import pytest

from webgate.config import settings
from webgate.servers.hostkeys import (
    HostKeyMismatch,
    describe,
    export_key,
    known_hosts_for,
    learned_key,
    remember,
    translate,
)

KEY = asyncssh.generate_private_key("ssh-ed25519")
LINE = KEY.export_public_key("openssh").decode().strip()
OTHER = asyncssh.generate_private_key("ssh-ed25519").export_public_key("openssh").decode().strip()


@pytest.fixture(autouse=True)
def _verification_on():
    before = settings.verify_host_keys
    settings.verify_host_keys = True
    yield
    settings.verify_host_keys = before


def _conn(line: str = LINE):
    conn = MagicMock()
    conn.get_server_host_key = MagicMock(return_value=asyncssh.import_public_key(line))
    return conn


def _server(host_key: str = "", name: str = "prod-web-01"):
    server = MagicMock()
    server.host_key = host_key
    server.name = name
    return server


# --------------------------------------------------------------------- the argument


def test_a_pinned_key_is_handed_to_asyncssh_as_a_trusted_key():
    """The tuple form skips hostname matching: the caller already knows the server."""
    result = known_hosts_for(LINE)
    assert isinstance(result, tuple)
    trusted, cas, revoked = result
    assert len(trusted) == 1
    assert cas == [] and revoked == []


def test_no_pin_means_first_contact():
    assert known_hosts_for("") is None
    assert known_hosts_for("   ") is None


def test_a_corrupt_pin_falls_back_rather_than_locking_the_host_out():
    """A truncated row must not make a server permanently unreachable."""
    assert known_hosts_for("ssh-ed25519 this-is-not-a-key") is None


def test_verification_can_be_switched_off_for_a_lab():
    settings.verify_host_keys = False
    assert known_hosts_for(LINE) is None


# ------------------------------------------------------------------------- learning


@pytest.mark.asyncio
async def test_a_first_connection_pins_the_key():
    session, server = AsyncMock(), _server()
    fp = await remember(session, server, _conn())

    assert server.host_key == LINE
    assert fp.startswith("SHA256:")
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_an_existing_pin_is_never_overwritten():
    """Silently re-pinning on change would defeat the entire mechanism."""
    session, server = AsyncMock(), _server(host_key=LINE)
    assert await remember(session, server, _conn(OTHER)) == ""
    assert server.host_key == LINE
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_nothing_is_pinned_when_verification_is_off():
    settings.verify_host_keys = False
    session, server = AsyncMock(), _server()
    assert await remember(session, server, _conn()) == ""
    assert server.host_key == ""


@pytest.mark.asyncio
async def test_a_host_that_reveals_no_key_is_not_pinned():
    session, server = AsyncMock(), _server()
    conn = MagicMock()
    conn.get_server_host_key = MagicMock(return_value=None)
    assert await remember(session, server, conn) == ""
    assert server.host_key == ""


# -------------------------------------------------------------------------- display


def test_a_fingerprint_is_shown_not_the_raw_key():
    assert describe(LINE).startswith("SHA256:")
    assert describe("") == ""
    assert describe("garbage") == "unreadable"


def test_the_learned_key_round_trips():
    line, fp = learned_key(_conn())
    assert line == LINE
    assert describe(line) == fp


def test_export_of_a_bad_key_does_not_raise():
    assert export_key(object()) == ""


# ----------------------------------------------------------------------- the message


def test_a_mismatch_explains_both_possibilities_and_the_way_out():
    exc = translate(asyncssh.HostKeyNotVerifiable("nope"), "prod-web-01", LINE)
    assert isinstance(exc, HostKeyMismatch)
    text = str(exc)
    assert "prod-web-01" in text
    assert "machine-in-the-middle" in text  # names the danger
    assert "rebuilt host" in text           # and the innocent explanation
    assert "Nothing was sent" in text       # what did NOT happen
    assert "clear the pinned key" in text   # how to proceed


def test_other_errors_pass_through_untouched():
    original = ConnectionRefusedError("refused")
    assert translate(original, "x", "") is original


# ------------------------------------------------------------------------------ API


@pytest.mark.asyncio
async def test_only_an_admin_can_clear_a_pin(client, auth_headers):
    srv = await client.post(
        "/api/servers",
        headers=auth_headers,
        json={"name": "s", "hostname": "192.0.2.1", "username": "u", "password": "p"},
    )
    sid = srv.json()["id"]
    await client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"username": "plain", "password": "plainpass123", "allowed_groups": []},
    )
    token = (
        await client.post(
            "/api/auth/login", json={"username": "plain", "password": "plainpass123"}
        )
    ).json()["access_token"]
    resp = await client.delete(
        f"/api/servers/{sid}/host-key", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_clearing_a_pin_reports_what_was_forgotten(client, auth_headers, db_session):
    from sqlalchemy import select

    from webgate.servers.models import Server

    srv = await client.post(
        "/api/servers",
        headers=auth_headers,
        json={"name": "pinned", "hostname": "192.0.2.1", "username": "u", "password": "p"},
    )
    sid = srv.json()["id"]
    row = (await db_session.execute(select(Server).where(Server.id == sid))).scalar_one()
    row.host_key = LINE
    await db_session.commit()

    resp = await client.delete(f"/api/servers/{sid}/host-key", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["cleared"].startswith("SHA256:")

    listed = (await client.get("/api/servers", headers=auth_headers)).json()
    assert next(s for s in listed if s["id"] == sid)["host_key_fingerprint"] == ""


@pytest.mark.asyncio
async def test_the_fingerprint_is_exposed_but_never_the_key(client, auth_headers, db_session):
    from sqlalchemy import select

    from webgate.servers.models import Server

    srv = await client.post(
        "/api/servers",
        headers=auth_headers,
        json={"name": "fp", "hostname": "192.0.2.1", "username": "u", "password": "p"},
    )
    row = (
        await db_session.execute(select(Server).where(Server.id == srv.json()["id"]))
    ).scalar_one()
    row.host_key = LINE
    await db_session.commit()

    listed = await client.get("/api/servers", headers=auth_headers)
    entry = next(s for s in listed.json() if s["id"] == srv.json()["id"])
    assert entry["host_key_fingerprint"].startswith("SHA256:")
    assert "host_key" not in entry
