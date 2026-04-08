import pytest
from httpx import AsyncClient

from webgate.servers.crypto import decrypt_value, encrypt_value

SERVER_DATA = {
    "name": "test-srv",
    "hostname": "10.0.1.50",
    "port": 22,
    "username": "deploy",
    "auth_method": "password",
    "password": "secret",
    "group": "prod",
    "tags": ["web"],
    "description": "Test server",
}


def test_encrypt_decrypt():
    encrypted = encrypt_value("hello")
    assert encrypted != "hello"
    assert decrypt_value(encrypted) == "hello"


def test_encrypt_empty():
    assert encrypt_value("") == ""
    assert decrypt_value("") == ""


@pytest.mark.asyncio
async def test_create_server(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.post("/api/servers", headers=auth_headers, json=SERVER_DATA)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test-srv"
    assert data["group"] == "prod"


@pytest.mark.asyncio
async def test_list_servers(client: AsyncClient, auth_headers: dict[str, str]):
    await client.post("/api/servers", headers=auth_headers, json=SERVER_DATA)
    resp = await client.get("/api/servers", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_list_servers_filter_group(client: AsyncClient, auth_headers: dict[str, str]):
    await client.post("/api/servers", headers=auth_headers, json=SERVER_DATA)
    resp = await client.get("/api/servers?group=prod", headers=auth_headers)
    assert resp.status_code == 200
    assert all(s["group"] == "prod" for s in resp.json())


@pytest.mark.asyncio
async def test_list_servers_search(client: AsyncClient, auth_headers: dict[str, str]):
    await client.post("/api/servers", headers=auth_headers, json=SERVER_DATA)
    resp = await client.get("/api/servers?search=test", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_get_server(client: AsyncClient, auth_headers: dict[str, str]):
    create = await client.post("/api/servers", headers=auth_headers, json=SERVER_DATA)
    sid = create.json()["id"]
    resp = await client.get(f"/api/servers/{sid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["hostname"] == "10.0.1.50"


@pytest.mark.asyncio
async def test_update_server(client: AsyncClient, auth_headers: dict[str, str]):
    create = await client.post("/api/servers", headers=auth_headers, json=SERVER_DATA)
    sid = create.json()["id"]
    resp = await client.put(f"/api/servers/{sid}", headers=auth_headers, json={"name": "updated"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "updated"


@pytest.mark.asyncio
async def test_delete_server(client: AsyncClient, auth_headers: dict[str, str]):
    create = await client.post("/api/servers", headers=auth_headers, json=SERVER_DATA)
    sid = create.json()["id"]
    resp = await client.delete(f"/api/servers/{sid}", headers=auth_headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_server_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.get("/api/servers/9999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_groups(client: AsyncClient, auth_headers: dict[str, str]):
    await client.post("/api/servers", headers=auth_headers, json=SERVER_DATA)
    resp = await client.get("/api/servers/groups", headers=auth_headers)
    assert resp.status_code == 200
    assert "prod" in resp.json()


@pytest.mark.asyncio
async def test_import_export(client: AsyncClient, auth_headers: dict[str, str]):
    await client.post("/api/servers", headers=auth_headers, json=SERVER_DATA)
    resp = await client.get("/api/servers/export", headers=auth_headers)
    assert resp.status_code == 200
    exported = resp.json()
    assert len(exported) >= 1


@pytest.mark.asyncio
async def test_non_admin_cannot_create(client: AsyncClient, auth_headers: dict[str, str]):
    # Create non-admin user
    await client.post("/api/auth/users", headers=auth_headers, json={
        "username": "viewer", "password": "viewer", "allowed_groups": ["prod"]
    })
    login = await client.post("/api/auth/login", json={"username": "viewer", "password": "viewer"})
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post("/api/servers", headers=viewer_headers, json=SERVER_DATA)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_non_admin_sees_only_allowed_groups(client: AsyncClient, auth_headers: dict[str, str]):
    # Create servers in two groups
    await client.post("/api/servers", headers=auth_headers, json={**SERVER_DATA, "group": "prod"})
    await client.post("/api/servers", headers=auth_headers, json={**SERVER_DATA, "name": "stg", "group": "staging"})

    # Create user with access to prod only
    await client.post("/api/auth/users", headers=auth_headers, json={
        "username": "dev2", "password": "dev2", "allowed_groups": ["prod"]
    })
    login = await client.post("/api/auth/login", json={"username": "dev2", "password": "dev2"})
    dev_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.get("/api/servers", headers=dev_headers)
    servers = resp.json()
    assert all(s["group"] == "prod" for s in servers)
