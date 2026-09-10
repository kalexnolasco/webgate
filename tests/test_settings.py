"""The admin settings panel.

The point of the panel is that a change takes effect, so the tests that matter are
the ones proving a stored value actually reaches the code that reads it -- and that
the things which must not be editable still are not.
"""

import pytest

from webgate.config import settings as env_settings
from webgate.runtime_config import store
from webgate.runtime_config.registry import BY_KEY, SPECS, InvalidSetting


async def _plain_user(client, auth_headers):
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
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------- validation


def test_a_number_outside_its_bounds_is_refused():
    spec = BY_KEY["monitor_interval"]
    assert spec.coerce("30") == 30
    for bad in ("5", "99999", "soon", ""):
        with pytest.raises(InvalidSetting):
            spec.coerce(bad)


def test_a_filter_without_its_placeholder_is_refused():
    """(uid=admin) would sign everyone in as whoever that DN resolves to."""
    spec = BY_KEY["ldap_user_filter"]
    assert spec.coerce("(sAMAccountName={username})")
    with pytest.raises(InvalidSetting):
        spec.coerce("(uid=admin)")


def test_group_mappings_must_be_the_shape_they_claim():
    with pytest.raises(InvalidSetting):
        BY_KEY["ldap_group_map"].coerce("not json")
    with pytest.raises(InvalidSetting):
        BY_KEY["ldap_group_map"].coerce('["a list, not an object"]')
    assert BY_KEY["ldap_group_map"].coerce('{"ops": "prod"}')


def test_an_ldap_url_must_be_an_ldap_url():
    with pytest.raises(InvalidSetting):
        BY_KEY["ldap_url"].coerce("https://ldap.example.com")
    assert BY_KEY["ldap_url"].coerce("ldaps://ldap.example.com:636")


def test_every_spec_names_a_real_setting():
    """A registry entry with no matching field would read as its own default forever."""
    for spec in SPECS:
        assert hasattr(env_settings, spec.key), f"{spec.key} is not a setting"


# ------------------------------------------------------------------- precedence


@pytest.mark.asyncio
async def test_the_environment_applies_until_an_admin_overrides_it(client, auth_headers):
    assert store.get("monitor_interval") == env_settings.monitor_interval
    assert store.source("monitor_interval") in {"environment", "default"}

    await client.put(
        "/api/settings", headers=auth_headers, json={"values": {"monitor_interval": 45}}
    )
    assert store.get("monitor_interval") == 45
    assert store.source("monitor_interval") == "admin"


@pytest.mark.asyncio
async def test_resetting_gives_the_environment_back(client, auth_headers):
    await client.put(
        "/api/settings", headers=auth_headers, json={"values": {"monitor_interval": 45}}
    )
    resp = await client.post(
        "/api/settings/reset", headers=auth_headers, json={"keys": ["monitor_interval"]}
    )
    assert resp.json()["cleared"] == ["monitor_interval"]
    assert store.get("monitor_interval") == env_settings.monitor_interval


@pytest.mark.asyncio
async def test_another_worker_picks_up_the_change(client, auth_headers, db_session):
    """HA workers converge by re-reading, so a write has to survive a fresh load."""
    await client.put(
        "/api/settings", headers=auth_headers, json={"values": {"monitor_interval": 45}}
    )
    store._overrides.clear()
    loaded = await store.refresh(db_session)
    assert loaded["monitor_interval"] == 45


# ---------------------------------------------------------------------- secrets


@pytest.mark.asyncio
async def test_a_secret_is_stored_encrypted_and_never_returned(client, auth_headers, db_session):
    from sqlalchemy import select

    from webgate.runtime_config.store import Setting

    await client.put(
        "/api/settings",
        headers=auth_headers,
        json={"values": {"ldap_bind_password": "s3cret-bind-pw"}},
    )
    row = (
        await db_session.execute(select(Setting).where(Setting.key == "ldap_bind_password"))
    ).scalar_one()
    assert "s3cret-bind-pw" not in row.value

    shown = (await client.get("/api/settings", headers=auth_headers)).json()
    field = next(
        s
        for section in shown["sections"]
        for s in section["settings"]
        if s["key"] == "ldap_bind_password"
    )
    assert field["value"] == "********"
    # ...but the code that binds still gets the real thing.
    assert store.get("ldap_bind_password") == "s3cret-bind-pw"


@pytest.mark.asyncio
async def test_saving_the_form_again_does_not_wipe_the_password(client, auth_headers):
    """The panel cannot render a secret, so it sends back a blank one."""
    await client.put(
        "/api/settings", headers=auth_headers, json={"values": {"ldap_bind_password": "keep-me"}}
    )
    await client.put(
        "/api/settings",
        headers=auth_headers,
        json={"values": {"ldap_bind_password": "", "ldap_url": "ldaps://d.example.com"}},
    )
    assert store.get("ldap_bind_password") == "keep-me"


# ------------------------------------------------------------------------ rules


@pytest.mark.asyncio
async def test_only_an_admin_sees_or_changes_settings(client, auth_headers):
    headers = await _plain_user(client, auth_headers)
    assert (await client.get("/api/settings", headers=headers)).status_code == 403
    assert (
        await client.put("/api/settings", headers=headers, json={"values": {}})
    ).status_code == 403
    assert (
        await client.post("/api/settings/reset", headers=headers, json={})
    ).status_code == 403


@pytest.mark.asyncio
async def test_an_unknown_key_is_refused_rather_than_stored(client, auth_headers):
    resp = await client.put(
        "/api/settings", headers=auth_headers, json={"values": {"db_url": "sqlite://elsewhere"}}
    )
    assert resp.status_code == 400
    assert "db_url" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_one_bad_value_does_not_half_apply_the_batch(client, auth_headers):
    resp = await client.put(
        "/api/settings",
        headers=auth_headers,
        json={"values": {"monitor_interval": 45, "monitor_timeout": 9999}},
    )
    assert resp.status_code == 400
    assert store.source("monitor_interval") != "admin"


@pytest.mark.asyncio
async def test_a_locked_deployment_refuses_changes(client, auth_headers, monkeypatch):
    monkeypatch.setattr(env_settings, "config_locked", True)
    resp = await client.put(
        "/api/settings", headers=auth_headers, json={"values": {"monitor_interval": 45}}
    )
    assert resp.status_code == 400
    assert "WEBGATE_CONFIG_LOCKED" in resp.json()["detail"]
    assert (await client.get("/api/settings", headers=auth_headers)).json()["locked"] is True


@pytest.mark.asyncio
async def test_a_change_is_audited_without_logging_the_value(client, auth_headers):
    await client.put(
        "/api/settings",
        headers=auth_headers,
        json={"values": {"ldap_bind_password": "s3cret-bind-pw"}},
    )
    entries = (await client.get("/api/auth/audit", headers=auth_headers)).json()
    entry = next(e for e in entries if e["action"] == "settings_update")
    assert "ldap_bind_password" in entry["detail"]
    assert "s3cret-bind-pw" not in entry["detail"]


@pytest.mark.asyncio
async def test_the_panel_says_what_it_cannot_change(client, auth_headers):
    """An admin hunting for a knob that is not there should find out why."""
    panel = (await client.get("/api/settings", headers=auth_headers)).json()
    fixed = {f["env_var"] for f in panel["fixed"]}
    assert "WEBGATE_SECRET_KEY" in fixed
    assert "WEBGATE_DB_URL" in fixed


# ------------------------------------------------------- the change takes effect


@pytest.mark.asyncio
async def test_turning_host_key_verification_off_reaches_the_ssh_layer(client, auth_headers):
    """The whole point of the panel: a stored value changes what the code does."""
    import asyncssh

    from webgate.servers.hostkeys import known_hosts_for

    key = asyncssh.generate_private_key("ssh-ed25519").export_public_key("openssh").decode()
    assert known_hosts_for(key) is not None

    await client.put(
        "/api/settings", headers=auth_headers, json={"values": {"verify_host_keys": False}}
    )
    assert known_hosts_for(key) is None


@pytest.mark.asyncio
async def test_the_transfer_limit_reaches_the_file_layer(client, auth_headers):
    from webgate.files.limits import budget

    await client.put(
        "/api/settings", headers=auth_headers, json={"values": {"max_upload_size": 1024}}
    )
    assert budget().limit == 1024


@pytest.mark.asyncio
async def test_the_monitor_interval_reaches_the_monitor(client, auth_headers):
    from webgate.servers import monitor

    await client.put(
        "/api/settings", headers=auth_headers, json={"values": {"monitor_interval": 600}}
    )
    assert monitor._interval() == 600
    # The lease has to stretch with it or the leader drops it mid-sweep.
    assert monitor._lease_ttl() > 600


# --------------------------------------------- settings that stay in the environment


@pytest.mark.asyncio
async def test_first_run_false_suppresses_the_default_admin(monkeypatch):
    """It was documented as doing this and read by nobody: admin/admin appeared anyway."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from webgate.auth.service import get_user_count, seed_admin
    from webgate.db.engine import Base, _import_models

    _import_models()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    monkeypatch.setattr(env_settings, "first_run", False)
    async with factory() as session:
        await seed_admin(session)
        assert await get_user_count(session) == 0

    monkeypatch.setattr(env_settings, "first_run", True)
    async with factory() as session:
        await seed_admin(session)
        assert await get_user_count(session) == 1
    await engine.dispose()
