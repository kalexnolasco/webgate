"""Agent configuration belongs to the admin, not to the deployment.

These pin the parts that are easy to get wrong when settings move into a database:
the key never leaves the server, a blank field does not silently wipe it, and only
an admin can read or change any of it.
"""

import pytest
from sqlalchemy import select

from webgate.agent.store import AgentSettings, load_config, save_config

KEY = "sk-or-v1-secret-value-that-must-not-leak"


async def _make_user(client, auth_headers, username="plain"):
    await client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"username": username, "password": "plainpass123", "allowed_groups": []},
    )
    token = (
        await client.post(
            "/api/auth/login", json={"username": username, "password": "plainpass123"}
        )
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_fresh_install_is_unconfigured(client, auth_headers):
    resp = await client.get("/api/agent/settings", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["enabled"] is False
    assert body["has_api_key"] is False


@pytest.mark.asyncio
async def test_public_config_reports_unavailable_until_configured(client, auth_headers):
    assert (await client.get("/api/config")).json()["agent_available"] is False

    await client.put(
        "/api/agent/settings",
        headers=auth_headers,
        json={"enabled": True, "provider": "ollama", "base_url": "http://ollama:11434"},
    )
    assert (await client.get("/api/config")).json()["agent_available"] is True


@pytest.mark.asyncio
async def test_diagnose_refuses_until_configured(client, auth_headers):
    srv = await client.post(
        "/api/servers",
        headers=auth_headers,
        json={"name": "s", "hostname": "192.0.2.1", "username": "u", "password": "p"},
    )
    resp = await client.post(
        "/api/agent/diagnose",
        headers=auth_headers,
        json={"server_id": srv.json()["id"]},
    )
    assert resp.status_code == 403
    assert "Admin" in resp.json()["detail"]  # tells the operator where to go


@pytest.mark.asyncio
async def test_api_key_is_never_returned(client, auth_headers):
    resp = await client.put(
        "/api/agent/settings",
        headers=auth_headers,
        json={"enabled": True, "provider": "openrouter", "api_key": KEY},
    )
    body = resp.json()
    assert "api_key" not in body
    assert body["has_api_key"] is True
    assert KEY not in resp.text

    again = await client.get("/api/agent/settings", headers=auth_headers)
    assert KEY not in again.text


@pytest.mark.asyncio
async def test_api_key_is_encrypted_at_rest(client, auth_headers, db_session):
    await client.put(
        "/api/agent/settings",
        headers=auth_headers,
        json={"enabled": True, "provider": "openrouter", "api_key": KEY},
    )
    row = (await db_session.execute(select(AgentSettings))).scalar_one()
    assert row.encrypted_api_key
    assert KEY not in row.encrypted_api_key
    # ...but still readable through the configured Fernet key.
    assert (await load_config(db_session)).api_key == KEY


@pytest.mark.asyncio
async def test_omitting_the_key_keeps_the_stored_one(client, auth_headers):
    """The form never receives the key back, so a blank field must not wipe it."""
    await client.put(
        "/api/agent/settings",
        headers=auth_headers,
        json={"enabled": True, "provider": "openrouter", "api_key": KEY},
    )
    resp = await client.put(
        "/api/agent/settings",
        headers=auth_headers,
        json={"enabled": True, "provider": "openrouter", "model": "some/model"},
    )
    assert resp.json()["has_api_key"] is True
    assert resp.json()["model"] == "some/model"


@pytest.mark.asyncio
async def test_an_explicit_empty_key_clears_it(client, auth_headers):
    await client.put(
        "/api/agent/settings",
        headers=auth_headers,
        json={"enabled": True, "provider": "openrouter", "api_key": KEY},
    )
    resp = await client.put(
        "/api/agent/settings",
        headers=auth_headers,
        json={"enabled": True, "provider": "openrouter", "api_key": ""},
    )
    assert resp.json()["has_api_key"] is False


@pytest.mark.asyncio
async def test_settings_are_admin_only(client, auth_headers):
    headers = await _make_user(client, auth_headers)
    assert (await client.get("/api/agent/settings", headers=headers)).status_code == 403
    assert (
        await client.put("/api/agent/settings", headers=headers, json={"enabled": True})
    ).status_code == 403
    assert (
        await client.post("/api/agent/settings/test", headers=headers, json={"provider": "ollama"})
    ).status_code == 403


@pytest.mark.asyncio
async def test_unknown_provider_is_rejected(client, auth_headers):
    resp = await client.put(
        "/api/agent/settings",
        headers=auth_headers,
        json={"enabled": True, "provider": "definitely-not-a-provider"},
    )
    assert resp.status_code == 422  # rejected by the schema, before it reaches the store


@pytest.mark.asyncio
async def test_limits_are_clamped(db_session):
    config = await save_config(
        db_session,
        enabled=True,
        provider="ollama",
        base_url="http://x:1/",
        model="m",
        api_key=None,
        max_steps=9999,
        command_timeout=1,
        context_budget=999_999,
        cache_ttl=99_999,
        findings_retention_days=99_999,
        updated_by="admin",
    )
    assert config.max_steps == 40
    assert config.command_timeout == 5
    assert config.context_budget == 400_000
    assert config.cache_ttl == 900
    assert config.findings_retention_days == 3650
    assert config.base_url == "http://x:1"  # trailing slash normalised away


@pytest.mark.asyncio
async def test_database_wins_over_environment(db_session):
    """Env vars seed a fresh install; once an admin saves, the panel is the truth."""
    assert (await load_config(db_session)).source == "environment"
    await save_config(
        db_session,
        enabled=True,
        provider="ollama",
        base_url="",
        model="llama3",
        api_key=None,
        max_steps=12,
        command_timeout=20,
        context_budget=24_000,
        cache_ttl=60,
        findings_retention_days=90,
        updated_by="admin",
    )
    config = await load_config(db_session)
    assert config.source == "database"
    assert config.model == "llama3"
