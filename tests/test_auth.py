import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "testpass123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_authenticated(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin"
    assert data["is_admin"] is True


@pytest.mark.asyncio
async def test_me_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_change_password(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.post(
        "/api/auth/change-password",
        headers=auth_headers,
        json={"new_password": "newpass123"},
    )
    assert resp.status_code == 200
    assert resp.json()["must_change_password"] is False


@pytest.mark.asyncio
async def test_admin_create_user(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"username": "dev1", "password": "dev1pass", "allowed_groups": ["prod"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "dev1"
    assert data["is_admin"] is False
    assert data["allowed_groups"] == ["prod"]


@pytest.mark.asyncio
async def test_admin_list_users(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.get("/api/auth/users", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
