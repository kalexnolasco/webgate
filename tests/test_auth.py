import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_first_user(client: AsyncClient):
    resp = await client.post(
        "/api/auth/register",
        json={"username": "admin", "password": "secret123"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "admin"
    assert data["is_admin"] is True


@pytest.mark.asyncio
async def test_register_blocked_after_first(client: AsyncClient):
    await client.post(
        "/api/auth/register",
        json={"username": "admin", "password": "secret123"},
    )
    resp = await client.post(
        "/api/auth/register",
        json={"username": "another", "password": "secret123"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    await client.post(
        "/api/auth/register",
        json={"username": "admin", "password": "secret123"},
    )
    resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    await client.post(
        "/api/auth/register",
        json={"username": "admin", "password": "secret123"},
    )
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


@pytest.mark.asyncio
async def test_me_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_me_invalid_token(client: AsyncClient):
    resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer invalid"})
    assert resp.status_code == 401
