"""Fire-and-forget webhook dispatcher.

Webhooks are sent asynchronously without blocking the request that triggered
them. Failures are logged and stored on the webhook row (last_status) but
never propagate back to the caller.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select

from webgate.db.engine import async_session_factory
from webgate.webhooks.models import Webhook

logger = logging.getLogger(__name__)

# Strong references to in-flight deliveries; see fire().
_pending: set[asyncio.Task[None]] = set()

_TIMEOUT = 5.0  # seconds


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _deliver(webhook_id: int, url: str, secret: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "webgate-webhook/1.0"}
    if secret:
        headers["X-Webgate-Signature"] = "sha256=" + _sign(secret, body)
    status: int | None = None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, content=body, headers=headers)
            status = resp.status_code
    except Exception as e:
        logger.warning("Webhook %s -> %s failed: %s", webhook_id, url, e)
    finally:
        async with async_session_factory() as session:
            wh = (
                await session.execute(select(Webhook).where(Webhook.id == webhook_id))
            ).scalar_one_or_none()
            if wh is not None:
                wh.last_fired_at = datetime.now(UTC)
                wh.last_status = status
                await session.commit()


async def fire(event: str, data: dict[str, Any]) -> None:
    """Fire-and-forget: schedule webhook deliveries for this event."""
    payload = {
        "event": event,
        "timestamp": datetime.now(UTC).isoformat(),
        "data": data,
    }
    async with async_session_factory() as session:
        result = await session.execute(select(Webhook).where(Webhook.enabled.is_(True)))
        hooks = list(result.scalars().all())
    for wh in hooks:
        try:
            events = json.loads(wh.events)
        except json.JSONDecodeError:
            events = ["*"]
        if "*" not in events and event not in events:
            continue
        # Detached, but held: the event loop keeps only a weak reference to a
        # task, so one that nothing else refers to can be garbage-collected
        # mid-flight and the delivery disappears with no error anywhere.
        task = asyncio.create_task(_deliver(wh.id, wh.url, wh.secret, payload))
        _pending.add(task)
        task.add_done_callback(_pending.discard)
