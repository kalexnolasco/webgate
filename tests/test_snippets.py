"""Saved commands.

A snippet is a button that runs a command on a real server the instant it is
clicked. The cases that matter are the ones where that is dangerous or useless: a
command nobody else can reach, one that needs a value, and one that changes something.
"""

import pytest

from webgate.snippets.routes import placeholders


async def _plain(client, auth_headers, name="plain"):
    await client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"username": name, "password": "plainpass123", "allowed_groups": []},
    )
    token = (
        await client.post("/api/auth/login", json={"username": name, "password": "plainpass123"})
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------- placeholders


@pytest.mark.parametrize(
    "command,expected",
    [
        ("df -h", []),
        ("tail -n {lines} {file}", ["lines", "file"]),
        ("grep {pattern} {file} | head -n {lines}", ["pattern", "file", "lines"]),
        ("echo {same} {same}", ["same"]),  # asked once, substituted everywhere
        ("awk '{print $1}'", []),  # awk braces are not parameters
        ("systemctl status {}", []),
    ],
)
def test_parameters_are_read_in_the_order_they_appear(command, expected):
    assert placeholders(command) == expected


# ------------------------------------------------------------------------ sharing


@pytest.mark.asyncio
async def test_an_admin_can_publish_one_to_everyone(client, auth_headers):
    """A team's standard checks should not be something each person retypes."""
    await client.post(
        "/api/snippets",
        headers=auth_headers,
        json={"name": "Failed units", "command": "systemctl --failed", "shared": True},
    )
    headers = await _plain(client, auth_headers)
    names = [s["name"] for s in (await client.get("/api/snippets", headers=headers)).json()]
    assert "Failed units" in names


@pytest.mark.asyncio
async def test_a_normal_user_cannot_publish_to_everyone(client, auth_headers):
    headers = await _plain(client, auth_headers)
    resp = await client.post(
        "/api/snippets", headers=headers, json={"name": "x", "command": "id", "shared": True}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_a_shared_snippet_is_not_someone_elses_to_delete(client, auth_headers):
    created = await client.post(
        "/api/snippets",
        headers=auth_headers,
        json={"name": "Disk usage", "command": "df -h", "shared": True},
    )
    headers = await _plain(client, auth_headers)

    listed = (await client.get("/api/snippets", headers=headers)).json()
    assert listed[0]["owned"] is False  # so the UI does not offer to delete it
    resp = await client.delete(f"/api/snippets/{created.json()['id']}", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_your_own_snippets_stay_yours(client, auth_headers):
    headers = await _plain(client, auth_headers)
    await client.post("/api/snippets", headers=headers, json={"name": "mine", "command": "id"})

    other = await _plain(client, auth_headers, name="second")
    assert (await client.get("/api/snippets", headers=other)).json() == []


@pytest.mark.asyncio
async def test_the_team_set_is_listed_before_personal_ones(client, auth_headers):
    await client.post(
        "/api/snippets",
        headers=auth_headers,
        json={"name": "zzz team", "command": "a", "shared": True},
    )
    await client.post(
        "/api/snippets", headers=auth_headers, json={"name": "aaa mine", "command": "b"}
    )
    listed = (await client.get("/api/snippets", headers=auth_headers)).json()
    assert listed[0]["name"] == "zzz team"


# ---------------------------------------------------------------------- confirming


@pytest.mark.asyncio
async def test_a_snippet_can_ask_before_it_runs(client, auth_headers):
    """There is no undo on `systemctl restart` against production."""
    resp = await client.post(
        "/api/snippets",
        headers=auth_headers,
        json={"name": "Restart nginx", "command": "systemctl restart nginx", "confirm": True},
    )
    assert resp.json()["confirm"] is True
    assert (await client.get("/api/snippets", headers=auth_headers)).json()[0]["confirm"] is True


@pytest.mark.asyncio
async def test_editing_one_keeps_it_the_same_snippet(client, auth_headers):
    created = await client.post(
        "/api/snippets", headers=auth_headers, json={"name": "Logs", "command": "tail -n 50 {file}"}
    )
    updated = await client.put(
        f"/api/snippets/{created.json()['id']}",
        headers=auth_headers,
        json={"name": "Logs", "command": "tail -n {lines} {file}", "confirm": False},
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == created.json()["id"]
    assert placeholders(updated.json()["command"]) == ["lines", "file"]
