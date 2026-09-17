"""The Prometheus endpoint.

A gateway a company depends on has to be scrapeable, and nothing here was. The
monitor already probed every server on a timer and the session manager already knew
what was live; both only ever spoke to the browser.

Two things are easy to get wrong and make a dashboard that lies, so both are pinned
here: the exposition must be authenticated, because it names every server in the
registry, and it must say which instance the fleet gauges came from, because only the
monitor leader has any.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from webgate.servers.monitor import ServerStatus


def _metric(body: str, name: str) -> list[str]:
    """Every sample line for one metric, help and type lines excluded."""
    return [
        line
        for line in body.splitlines()
        if line.startswith(name + " ") or line.startswith(name + "{")
    ]


# ---------------------------------------------------------------------- access


@pytest.mark.asyncio
async def test_metrics_are_not_public(client):
    """The exposition names every server in the registry."""
    resp = await client.get("/metrics")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_metrics_are_admin_only(client, auth_headers):
    resp = await client.get("/metrics", headers=auth_headers)
    assert resp.status_code == 200, "an admin should be able to scrape"


@pytest.mark.asyncio
async def test_a_non_admin_is_refused(client, auth_headers):
    await client.post(
        "/api/auth/users",
        json={"username": "scraper", "password": "not-an-admin-1", "is_admin": False},
        headers=auth_headers,
    )
    token = (
        await client.post(
            "/api/auth/login", json={"username": "scraper", "password": "not-an-admin-1"}
        )
    ).json()["access_token"]
    resp = await client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


# ------------------------------------------------------------------- the shape


@pytest.mark.asyncio
async def test_the_content_type_is_the_one_prometheus_expects(client, auth_headers):
    resp = await client.get("/metrics", headers=auth_headers)
    assert resp.headers["content-type"].startswith("text/plain")
    assert "version=0.0.4" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_every_metric_is_declared(client, auth_headers):
    """A sample with no HELP and TYPE above it is a metric nobody can read."""
    body = (await client.get("/metrics", headers=auth_headers)).text
    declared = {line.split()[2] for line in body.splitlines() if line.startswith("# TYPE ")}
    sampled = {
        line.split("{")[0].split()[0]
        for line in body.splitlines()
        if line and not line.startswith("#")
    }
    assert sampled <= declared, f"undeclared: {sampled - declared}"


@pytest.mark.asyncio
async def test_the_build_and_the_instance_are_reported(client, auth_headers):
    from webgate import __version__

    body = (await client.get("/metrics", headers=auth_headers)).text
    info = _metric(body, "webgate_info")
    assert len(info) == 1
    assert f'version="{__version__}"' in info[0]
    assert "instance=" in info[0]


@pytest.mark.asyncio
async def test_the_scraper_can_tell_which_instance_holds_the_fleet(client, auth_headers):
    """Without this, summing a gauge across instances double-counts or reports zero."""
    body = (await client.get("/metrics", headers=auth_headers)).text
    assert _metric(body, "webgate_monitor_leader"), "nothing says who the leader is"


# ------------------------------------------------------------ the fleet gauges


@pytest.mark.asyncio
async def test_a_follower_reports_no_server_gauges(client, auth_headers):
    """It has no statuses, and inventing zeroes would read as a fleet-wide outage."""
    body = (await client.get("/metrics", headers=auth_headers)).text
    assert _metric(body, "webgate_server_up") == []


@pytest.mark.asyncio
async def test_the_leader_reports_one_gauge_per_server(client, auth_headers):
    await client.post(
        "/api/servers",
        json={
            "name": "prod-web-01",
            "hostname": "10.0.0.7",
            "port": 22,
            "username": "deploy",
            "auth_method": "password",
            "password": "s3cret",
        },
        headers=auth_headers,
    )
    server_id = (await client.get("/api/servers", headers=auth_headers)).json()[0]["id"]
    statuses = {
        server_id: ServerStatus(online=True, last_checked=datetime.now(UTC), latency_ms=12.5)
    }
    with patch("webgate.metrics.server_monitor.get_all_statuses", return_value=statuses):
        body = (await client.get("/metrics", headers=auth_headers)).text

    assert 'webgate_server_up{server="prod-web-01"} 1' in body
    assert 'webgate_server_latency_seconds{server="prod-web-01"} 0.0125' in body
    assert "webgate_servers_online 1" in body
    assert "webgate_servers_offline 0" in body


@pytest.mark.asyncio
async def test_an_offline_server_reports_no_latency(client, auth_headers):
    """A gauge for a connection that never happened would be a made-up number."""
    await client.post(
        "/api/servers",
        json={
            "name": "db-01",
            "hostname": "10.0.0.8",
            "port": 22,
            "username": "deploy",
            "auth_method": "password",
            "password": "s3cret",
        },
        headers=auth_headers,
    )
    server_id = (await client.get("/api/servers", headers=auth_headers)).json()[0]["id"]
    statuses = {
        server_id: ServerStatus(
            online=False, last_checked=datetime.now(UTC), error="Connection refused"
        )
    }
    with patch("webgate.metrics.server_monitor.get_all_statuses", return_value=statuses):
        body = (await client.get("/metrics", headers=auth_headers)).text

    assert 'webgate_server_up{server="db-01"} 0' in body
    assert _metric(body, "webgate_server_latency_seconds") == []


@pytest.mark.asyncio
async def test_a_quote_in_a_server_name_cannot_break_the_exposition(client, auth_headers):
    """A label value ends at the next quote, so an unescaped one corrupts the scrape."""
    await client.post(
        "/api/servers",
        json={
            "name": 'we"ird\\host',
            "hostname": "10.0.0.9",
            "port": 22,
            "username": "deploy",
            "auth_method": "password",
            "password": "s3cret",
        },
        headers=auth_headers,
    )
    server_id = (await client.get("/api/servers", headers=auth_headers)).json()[0]["id"]
    statuses = {server_id: ServerStatus(online=True, last_checked=datetime.now(UTC))}
    with patch("webgate.metrics.server_monitor.get_all_statuses", return_value=statuses):
        body = (await client.get("/metrics", headers=auth_headers)).text

    import re

    line = _metric(body, "webgate_server_up")[0]
    # A label value runs to the next unescaped quote, so this is the shape the
    # exposition format requires: every inner quote and backslash carries one.
    assert re.fullmatch(r'webgate_server_up\{server="(?:[^"\\]|\\.)*"\} 1', line), line
    assert r"we\"ird\\host" in line
