"""Webhook deliveries are fire-and-forget, but they still have to be fired.

`asyncio.create_task` hands the event loop only a weak reference. A task nothing
else refers to can be collected mid-flight, and a webhook then vanishes with no
error in any log -- the worst shape a delivery failure can take.
"""

import asyncio
import gc
from unittest.mock import AsyncMock, patch

import pytest

from webgate.webhooks import dispatcher


@pytest.fixture(autouse=True)
def _no_leftovers():
    dispatcher._pending.clear()
    yield
    dispatcher._pending.clear()


async def _hook(client, auth_headers, events="[\"*\"]"):
    import json as _json

    resp = await client.post(
        "/api/webhooks",
        headers=auth_headers,
        json={
            "name": "ops-channel",
            "url": "https://example.invalid/hook",
            "events": _json.loads(events),
            "secret": "s3cret",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_an_in_flight_delivery_is_held_strongly(client, auth_headers):
    await _hook(client, auth_headers)

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(*_a, **_k):
        started.set()
        await release.wait()

    with patch.object(dispatcher, "_deliver", slow):
        await dispatcher.fire("user_login", {"username": "admin"})
        await started.wait()
        # The only thing that can be keeping this alive is the module's own set.
        gc.collect()
        assert len(dispatcher._pending) == 1
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    assert dispatcher._pending == set(), "a finished delivery must not be retained"


@pytest.mark.asyncio
async def test_a_delivery_survives_a_collection_while_it_runs(client, auth_headers):
    """The regression itself: collect aggressively and the delivery still lands."""
    await _hook(client, auth_headers)
    delivered = []

    async def deliver(webhook_id, url, secret, payload):
        await asyncio.sleep(0)
        gc.collect()
        await asyncio.sleep(0)
        delivered.append(payload["event"])

    with patch.object(dispatcher, "_deliver", deliver):
        await dispatcher.fire("ssh_connect", {"server": "prod-web-01"})
        for _ in range(6):
            gc.collect()
            await asyncio.sleep(0)

    assert delivered == ["ssh_connect"]


@pytest.mark.asyncio
async def test_a_hook_that_does_not_want_the_event_is_not_fired(client, auth_headers):
    await _hook(client, auth_headers, events='["ssh_connect"]')
    with patch.object(dispatcher, "_deliver", new_callable=AsyncMock) as deliver:
        await dispatcher.fire("user_login", {"username": "admin"})
        await asyncio.sleep(0)
    deliver.assert_not_awaited()
    assert dispatcher._pending == set()


@pytest.mark.asyncio
async def test_the_payload_carries_the_event_and_a_timestamp(client, auth_headers):
    await _hook(client, auth_headers)
    seen = {}

    async def deliver(webhook_id, url, secret, payload):
        seen.update(payload)

    with patch.object(dispatcher, "_deliver", deliver):
        await dispatcher.fire("server_created", {"name": "prod-web-01"})
        for _ in range(4):
            await asyncio.sleep(0)

    assert seen["event"] == "server_created"
    assert seen["data"] == {"name": "prod-web-01"}
    assert seen["timestamp"]
