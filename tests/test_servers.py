import pytest
from httpx import AsyncClient

from webgate.servers.crypto import decrypt_value, encrypt_value


@pytest.mark.asyncio
async def test_encryption_roundtrip():
    original = "my-secret-password"
    encrypted = encrypt_value(original)
    assert encrypted != original
    assert decrypt_value(encrypted) == original


@pytest.mark.asyncio
async def test_encrypt_empty():
    assert encrypt_value("") == ""
    assert decrypt_value("") == ""


@pytest.mark.asyncio
async def test_create_server(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.post(
        "/api/servers",
        json={
            "name": "test-server",
            "hostname": "10.0.0.1",
            "port": 22,
            "username": "root",
            "password": "secret",
            "group": "production",
            "tags": ["web", "nginx"],
            "description": "Test server",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test-server"
    assert data["hostname"] == "10.0.0.1"
    assert data["group"] == "production"
    assert data["tags"] == ["web", "nginx"]
    assert "password" not in data
    assert "encrypted_password" not in data


@pytest.mark.asyncio
async def test_list_servers(client: AsyncClient, auth_headers: dict[str, str]):
    await client.post(
        "/api/servers",
        json={"name": "srv1", "hostname": "1.1.1.1", "username": "u", "group": "dev"},
        headers=auth_headers,
    )
    await client.post(
        "/api/servers",
        json={"name": "srv2", "hostname": "2.2.2.2", "username": "u", "group": "prod"},
        headers=auth_headers,
    )
    resp = await client.get("/api/servers", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


@pytest.mark.asyncio
async def test_list_servers_filter_group(client: AsyncClient, auth_headers: dict[str, str]):
    await client.post(
        "/api/servers",
        json={"name": "s1", "hostname": "1.1.1.1", "username": "u", "group": "dev"},
        headers=auth_headers,
    )
    await client.post(
        "/api/servers",
        json={"name": "s2", "hostname": "2.2.2.2", "username": "u", "group": "prod"},
        headers=auth_headers,
    )
    resp = await client.get("/api/servers?group=dev", headers=auth_headers)
    data = resp.json()
    assert len(data) == 1
    assert data[0]["group"] == "dev"


@pytest.mark.asyncio
async def test_list_servers_search(client: AsyncClient, auth_headers: dict[str, str]):
    await client.post(
        "/api/servers",
        json={"name": "web-server", "hostname": "1.1.1.1", "username": "u"},
        headers=auth_headers,
    )
    await client.post(
        "/api/servers",
        json={"name": "db-server", "hostname": "2.2.2.2", "username": "u"},
        headers=auth_headers,
    )
    resp = await client.get("/api/servers?search=web", headers=auth_headers)
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "web-server"


@pytest.mark.asyncio
async def test_get_server(client: AsyncClient, auth_headers: dict[str, str]):
    create_resp = await client.post(
        "/api/servers",
        json={"name": "myserver", "hostname": "10.0.0.1", "username": "root"},
        headers=auth_headers,
    )
    server_id = create_resp.json()["id"]
    resp = await client.get(f"/api/servers/{server_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "myserver"


@pytest.mark.asyncio
async def test_update_server(client: AsyncClient, auth_headers: dict[str, str]):
    create_resp = await client.post(
        "/api/servers",
        json={"name": "old-name", "hostname": "10.0.0.1", "username": "root"},
        headers=auth_headers,
    )
    server_id = create_resp.json()["id"]
    resp = await client.put(
        f"/api/servers/{server_id}",
        json={"name": "new-name"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "new-name"


@pytest.mark.asyncio
async def test_delete_server(client: AsyncClient, auth_headers: dict[str, str]):
    create_resp = await client.post(
        "/api/servers",
        json={"name": "todelete", "hostname": "10.0.0.1", "username": "root"},
        headers=auth_headers,
    )
    server_id = create_resp.json()["id"]
    resp = await client.delete(f"/api/servers/{server_id}", headers=auth_headers)
    assert resp.status_code == 204
    resp = await client.get(f"/api/servers/{server_id}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_server_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.get("/api/servers/9999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_groups(client: AsyncClient, auth_headers: dict[str, str]):
    await client.post(
        "/api/servers",
        json={"name": "a", "hostname": "1.1.1.1", "username": "u", "group": "dev"},
        headers=auth_headers,
    )
    await client.post(
        "/api/servers",
        json={"name": "b", "hostname": "2.2.2.2", "username": "u", "group": "prod"},
        headers=auth_headers,
    )
    resp = await client.get("/api/servers/groups", headers=auth_headers)
    assert resp.status_code == 200
    groups = resp.json()
    assert "dev" in groups
    assert "prod" in groups


@pytest.mark.asyncio
async def test_import_export(client: AsyncClient, auth_headers: dict[str, str]):
    import_resp = await client.post(
        "/api/servers/import",
        json={
            "servers": [
                {"name": "imp1", "hostname": "1.1.1.1", "username": "u"},
                {"name": "imp2", "hostname": "2.2.2.2", "username": "u"},
            ]
        },
        headers=auth_headers,
    )
    assert import_resp.status_code == 201
    assert len(import_resp.json()) == 2

    export_resp = await client.get("/api/servers/export", headers=auth_headers)
    assert export_resp.status_code == 200
    assert len(export_resp.json()) == 2


@pytest.mark.asyncio
async def test_unauthenticated_access(client: AsyncClient):
    resp = await client.get("/api/servers")
    assert resp.status_code in (401, 403)
