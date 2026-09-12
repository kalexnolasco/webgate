"""Session recording.

This module had no tests at all, which is how it shipped with a defect that only
appears in the deployment the project documents: each worker wrote casts to its own
container filesystem while the database stored an absolute path, and any worker could
be asked to replay one. Behind the two workers of compose.ha.yml, roughly half of all
replays returned 404 -- and a replaced container took the evidence with it.
"""

import gzip
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from webgate.recordings.models import Recording
from webgate.recordings.recorder import CastRecorder, unpack


def _cast(tmp_path: Path, **kw) -> CastRecorder:
    return CastRecorder(tmp_path / "s.cast", cols=80, rows=24, **kw)


async def _recording(db_session, **kw) -> Recording:
    rec = Recording(
        server_id=None,
        server_name="prod-web-01",
        user_id=1,
        username="admin",
        file_path=kw.pop("file_path", ""),
        **kw,
    )
    db_session.add(rec)
    await db_session.commit()
    await db_session.refresh(rec)
    return rec


# ------------------------------------------------------------------- the artefact


def test_a_finished_cast_comes_back_byte_for_byte(tmp_path):
    rec = _cast(tmp_path)
    rec.write_output("hello\r\n")
    rec.write_output("world\r\n")
    rec.close()
    on_disk = (tmp_path / "s.cast").read_bytes()

    blob = rec.take()
    assert unpack(blob) == on_disk


def test_taking_it_removes_the_local_copy(tmp_path):
    """A cast left on one worker's disk is the bug this replaces."""
    rec = _cast(tmp_path)
    rec.write_output("x")
    rec.close()
    assert (tmp_path / "s.cast").exists()

    rec.take()
    assert not (tmp_path / "s.cast").exists()


def test_it_is_compressed(tmp_path):
    rec = _cast(tmp_path)
    for _ in range(400):
        rec.write_output("the same line over and over\r\n")
    rec.close()
    raw_size = (tmp_path / "s.cast").stat().st_size
    assert len(rec.take()) < raw_size / 4


def test_an_uncompressed_blob_is_still_served(tmp_path):
    """Defensive: anything already stored, however it got there, must still play."""
    assert unpack(b'{"version": 2}\n') == b'{"version": 2}\n'
    assert unpack(None) == b""
    assert unpack(gzip.compress(b"ok")) == b"ok"


# ------------------------------------------------------------------------ the cap


def test_a_runaway_session_stops_instead_of_filling_the_disk(tmp_path):
    rec = _cast(tmp_path, max_bytes=2000)
    for _ in range(500):
        rec.write_output("x" * 100)
    size = rec.close()

    assert rec.truncated
    assert size < 6000, "the cap did not hold"


def test_a_truncated_replay_says_so_rather_than_looking_like_a_crash(tmp_path):
    rec = _cast(tmp_path, max_bytes=1500)
    for _ in range(200):
        rec.write_output("y" * 100)
    rec.close()

    lines = (tmp_path / "s.cast").read_text().strip().splitlines()
    last = json.loads(lines[-1])
    assert "recording stopped" in last[2]


def test_zero_means_no_cap(tmp_path):
    rec = _cast(tmp_path, max_bytes=0)
    for _ in range(300):
        rec.write_output("z" * 100)
    rec.close()
    assert not rec.truncated


# -------------------------------------------------------------------- serving it


@pytest.mark.asyncio
async def test_a_recording_in_the_database_plays_from_any_worker(
    client, auth_headers, db_session, tmp_path
):
    """The regression: this used to depend on which worker answered."""
    rec = _cast(tmp_path)
    rec.write_output("uptime\r\n")
    rec.close()
    row = await _recording(db_session, data=rec.take())

    resp = await client.get(
        f"/api/recordings/{row.id}/cast", params={"token": auth_headers["Authorization"].split()[1]}
    )
    assert resp.status_code == 200
    assert b"uptime" in resp.content


@pytest.mark.asyncio
async def test_an_old_recording_whose_worker_is_gone_explains_itself(
    client, auth_headers, db_session
):
    """Rather than a bare 'file missing', which tells an operator nothing."""
    row = await _recording(db_session, file_path="/data/recordings/9/gone.cast")

    token = auth_headers["Authorization"].split()[1]
    resp = await client.get(f"/api/recordings/{row.id}/cast", params={"token": token})
    assert resp.status_code == 404
    assert "single worker" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_a_recording_still_on_this_host_is_served_from_the_file(
    client, auth_headers, db_session, tmp_path
):
    """Upgrading must not strand recordings made before this release."""
    path = tmp_path / "old.cast"
    path.write_bytes(b'{"version": 2}\n[0.1, "o", "legacy"]\n')
    row = await _recording(db_session, file_path=str(path))

    token = auth_headers["Authorization"].split()[1]
    resp = await client.get(f"/api/recordings/{row.id}/cast", params={"token": token})
    assert resp.status_code == 200
    assert b"legacy" in resp.content


@pytest.mark.asyncio
async def test_a_download_is_named_after_the_server(client, auth_headers, db_session, tmp_path):
    rec = _cast(tmp_path)
    rec.write_output("x")
    rec.close()
    row = await _recording(db_session, data=rec.take())

    token = auth_headers["Authorization"].split()[1]
    resp = await client.get(f"/api/recordings/{row.id}/download", params={"token": token})
    assert resp.status_code == 200
    assert "prod-web-01" in resp.headers["content-disposition"]


# ----------------------------------------------------------------------- opting in


@pytest.mark.asyncio
async def test_a_server_does_not_record_unless_it_opts_in(client, auth_headers):
    """Two switches, like the agent: the gateway allows it, the server chooses."""
    resp = await client.post(
        "/api/servers",
        headers=auth_headers,
        json={"name": "sandbox", "hostname": "192.0.2.9", "username": "u", "password": "p"},
    )
    assert resp.json()["record_sessions"] is False

    updated = await client.put(
        f"/api/servers/{resp.json()['id']}", headers=auth_headers, json={"record_sessions": True}
    )
    assert updated.json()["record_sessions"] is True


@pytest.mark.asyncio
async def test_only_an_admin_sees_someone_elses_recording(client, auth_headers, db_session):
    row = await _recording(db_session, data=gzip.compress(b'{"version": 2}\n'))
    await client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"username": "plain", "password": "plainpass123", "allowed_groups": []},
    )
    token = (
        await client.post("/api/auth/login", json={"username": "plain", "password": "plainpass123"})
    ).json()["access_token"]

    assert (
        await client.get(f"/api/recordings/{row.id}/cast", params={"token": token})
    ).status_code == 404


@pytest.mark.asyncio
async def test_deleting_a_recording_removes_the_row(client, auth_headers, db_session, tmp_path):
    rec = _cast(tmp_path)
    rec.write_output("x")
    rec.close()
    row = await _recording(db_session, data=rec.take())

    assert (
        await client.delete(f"/api/recordings/{row.id}", headers=auth_headers)
    ).status_code == 204
    remaining = await db_session.execute(select(Recording).where(Recording.id == row.id))
    assert remaining.scalar_one_or_none() is None
