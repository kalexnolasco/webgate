import pytest
from cryptography.fernet import InvalidToken
from httpx import AsyncClient

from webgate.backup.service import seal, unseal

BASTION = {
    "name": "ssh-proxy-eu",
    "hostname": "192.0.2.10",
    "username": "ops",
    "auth_method": "key",
    "private_key": "DUMMY-KEY",
    "group": "core",
}
WEB = {
    "name": "prod-web-01",
    "hostname": "192.0.2.21",
    "username": "deploy",
    "auth_method": "password",
    "password": "s3cret",
    "group": "prod",
    "tags": ["web"],
}


def test_seal_roundtrip():
    payload = {"servers": [{"name": "zzTOPSECRETzz"}]}
    blob = seal(payload, "hunter2")
    assert "ciphertext" in blob and "salt" in blob
    assert "zzTOPSECRETzz" not in blob["ciphertext"]
    assert unseal(blob, "hunter2") == payload


def test_unseal_wrong_passphrase_fails():
    blob = seal({"x": 1}, "right")
    with pytest.raises(InvalidToken):
        unseal(blob, "wrong")


async def _make_fleet(client: AsyncClient, headers: dict[str, str]) -> None:
    """A bastion plus a server that hops through it."""
    bastion = (await client.post("/api/servers", headers=headers, json=BASTION)).json()
    await client.post("/api/servers", headers=headers, json={**WEB, "jump_via_id": bastion["id"]})


@pytest.mark.asyncio
async def test_backup_without_passphrase_omits_credentials(client, auth_headers):
    await _make_fleet(client, auth_headers)
    resp = await client.post("/api/backup/export", headers=auth_headers, json={})
    assert resp.status_code == 200
    data = resp.json()

    assert data["webgate_backup"] == 1
    assert data["encrypted"] is False
    assert data["includes_credentials"] is False
    assert "sealed" not in data
    servers = data["payload"]["servers"]
    assert len(servers) == 2
    assert all("password" not in s and "private_key" not in s for s in servers)


@pytest.mark.asyncio
async def test_backup_with_passphrase_is_sealed(client, auth_headers):
    await _make_fleet(client, auth_headers)
    resp = await client.post(
        "/api/backup/export", headers=auth_headers, json={"passphrase": "migrate-me"}
    )
    data = resp.json()

    assert data["encrypted"] is True
    assert data["includes_credentials"] is True
    assert "payload" not in data  # nothing readable on disk
    assert "s3cret" not in data["sealed"]["ciphertext"]

    payload = unseal(data["sealed"], "migrate-me")
    web = next(s for s in payload["servers"] if s["name"] == "prod-web-01")
    assert web["password"] == "s3cret"
    assert web["jump_via_name"] == "ssh-proxy-eu"


@pytest.mark.asyncio
async def test_backup_records_jump_host_by_name_not_id(client, auth_headers):
    await _make_fleet(client, auth_headers)
    data = (await client.post("/api/backup/export", headers=auth_headers, json={})).json()
    web = next(s for s in data["payload"]["servers"] if s["name"] == "prod-web-01")
    # An id would be meaningless in the target database.
    assert "jump_via_id" not in web
    assert web["jump_via_name"] == "ssh-proxy-eu"


@pytest.mark.asyncio
async def test_restore_rejects_wrong_passphrase(client, auth_headers):
    await _make_fleet(client, auth_headers)
    data = (
        await client.post("/api/backup/export", headers=auth_headers, json={"passphrase": "right"})
    ).json()

    resp = await client.post(
        "/api/backup/restore",
        headers=auth_headers,
        json={"data": data, "passphrase": "wrong", "mode": "merge"},
    )
    assert resp.status_code == 400
    assert "passphrase" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_restore_requires_passphrase_for_sealed_backup(client, auth_headers):
    await _make_fleet(client, auth_headers)
    data = (
        await client.post("/api/backup/export", headers=auth_headers, json={"passphrase": "p"})
    ).json()

    resp = await client.post(
        "/api/backup/restore", headers=auth_headers, json={"data": data, "mode": "merge"}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_restore_rejects_foreign_file(client, auth_headers):
    resp = await client.post(
        "/api/backup/restore",
        headers=auth_headers,
        json={"data": {"something": "else"}, "mode": "merge"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_restore_skips_names_that_already_exist(client, auth_headers):
    await _make_fleet(client, auth_headers)
    data = (await client.post("/api/backup/export", headers=auth_headers, json={})).json()

    report = (
        await client.post(
            "/api/backup/restore", headers=auth_headers, json={"data": data, "mode": "merge"}
        )
    ).json()

    assert report["created"]["servers"] == 0
    assert report["skipped"]["servers"] == 2


@pytest.mark.asyncio
async def test_backup_requires_admin(client, auth_headers):
    await client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"username": "plain", "password": "plainpass123", "allowed_groups": []},
    )
    token = (
        await client.post("/api/auth/login", json={"username": "plain", "password": "plainpass123"})
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.post("/api/backup/export", headers=headers, json={})).status_code == 403
    assert (
        await client.post(
            "/api/backup/restore", headers=headers, json={"data": {}, "mode": "merge"}
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_server_import_rebuilds_jump_host_when_ids_shift(client, auth_headers):
    """The regression this whole change exists for.

    An export carries source-database ids. If the importer trusts them, a server
    silently hops through whatever host happens to occupy that id in the target.
    """
    await _make_fleet(client, auth_headers)
    exported = (await client.get("/api/servers/export", headers=auth_headers)).json()

    # Occupy the low ids so the bastion cannot land on its original one.
    for n in ("filler-1", "filler-2", "filler-3"):
        await client.post(
            "/api/servers",
            headers=auth_headers,
            json={"name": n, "hostname": "192.0.2.99", "username": "x", "password": "x"},
        )
    # Rename the originals so the imported copies do not collide by name.
    for srv in (await client.get("/api/servers", headers=auth_headers)).json():
        if srv["name"] in ("ssh-proxy-eu", "prod-web-01"):
            await client.put(
                f"/api/servers/{srv['id']}",
                headers=auth_headers,
                json={"name": "old-" + srv["name"]},
            )

    created = (
        await client.post("/api/servers/import", headers=auth_headers, json={"servers": exported})
    ).json()

    listed = (await client.get("/api/servers", headers=auth_headers)).json()
    by_name = {s["name"]: s for s in listed}
    web = next(s for s in created if s["name"] == "prod-web-01")
    bastion = by_name["ssh-proxy-eu"]

    assert web["jump_via_id"] == bastion["id"]
    assert by_name["prod-web-01"]["jump_via_id"] == bastion["id"]


@pytest.mark.asyncio
async def test_server_import_drops_unresolvable_jump_host(client, auth_headers):
    """A hop that cannot be resolved is left unset, never pointed at a guess."""
    exported = [
        {
            "id": 7,
            "name": "lonely",
            "hostname": "192.0.2.30",
            "username": "u",
            "auth_method": "password",
            "password": "x",
            "jump_via_id": 99,  # not present in this file
        }
    ]
    created = (
        await client.post("/api/servers/import", headers=auth_headers, json={"servers": exported})
    ).json()
    assert created[0]["jump_via_id"] is None


@pytest.mark.asyncio
async def test_server_import_accepts_jump_via_name(client, auth_headers):
    exported = [
        {"name": "gw", "hostname": "192.0.2.10", "username": "u", "password": "x"},
        {
            "name": "app",
            "hostname": "192.0.2.20",
            "username": "u",
            "password": "x",
            "jump_via_name": "gw",
        },
    ]
    created = (
        await client.post("/api/servers/import", headers=auth_headers, json={"servers": exported})
    ).json()
    gw = next(s for s in created if s["name"] == "gw")
    app = next(s for s in created if s["name"] == "app")
    assert app["jump_via_id"] == gw["id"]
