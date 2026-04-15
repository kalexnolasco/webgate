import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.auth.models import UserOut
from webgate.auth.routes import get_current_user
from webgate.db.engine import get_session
from webgate.webhooks.dispatcher import fire
from webgate.webhooks.models import (
    EVENT_NAMES,
    Webhook,
    WebhookCreate,
    WebhookOut,
    WebhookUpdate,
)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[UserOut, Depends(get_current_user)]


def _to_out(wh: Webhook) -> WebhookOut:
    try:
        events = json.loads(wh.events)
    except json.JSONDecodeError:
        events = ["*"]
    return WebhookOut(
        id=wh.id,
        name=wh.name,
        url=wh.url,
        events=events,
        enabled=wh.enabled,
        has_secret=bool(wh.secret),
        last_fired_at=wh.last_fired_at,
        last_status=wh.last_status,
        created_at=wh.created_at,
    )


def _require_admin(user: UserOut) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


@router.get("", response_model=list[WebhookOut])
async def list_webhooks(session: SessionDep, user: CurrentUserDep) -> list[WebhookOut]:
    _require_admin(user)
    result = await session.execute(select(Webhook).order_by(Webhook.name))
    return [_to_out(w) for w in result.scalars().all()]


@router.get("/events", response_model=list[str])
async def list_events(user: CurrentUserDep) -> list[str]:
    _require_admin(user)
    return EVENT_NAMES


@router.post("", response_model=WebhookOut, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    body: WebhookCreate, session: SessionDep, user: CurrentUserDep
) -> WebhookOut:
    _require_admin(user)
    wh = Webhook(
        name=body.name,
        url=body.url,
        events=json.dumps(body.events or ["*"]),
        enabled=body.enabled,
        secret=body.secret,
        user_id=user.id,
    )
    session.add(wh)
    await session.commit()
    await session.refresh(wh)
    return _to_out(wh)


@router.put("/{webhook_id}", response_model=WebhookOut)
async def update_webhook(
    webhook_id: int, body: WebhookUpdate, session: SessionDep, user: CurrentUserDep
) -> WebhookOut:
    _require_admin(user)
    wh = (
        await session.execute(select(Webhook).where(Webhook.id == webhook_id))
    ).scalar_one_or_none()
    if wh is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    if body.name is not None:
        wh.name = body.name
    if body.url is not None:
        wh.url = body.url
    if body.events is not None:
        wh.events = json.dumps(body.events)
    if body.enabled is not None:
        wh.enabled = body.enabled
    if body.secret is not None:
        wh.secret = body.secret
    await session.commit()
    await session.refresh(wh)
    return _to_out(wh)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(webhook_id: int, session: SessionDep, user: CurrentUserDep) -> None:
    _require_admin(user)
    wh = (
        await session.execute(select(Webhook).where(Webhook.id == webhook_id))
    ).scalar_one_or_none()
    if wh is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    await session.delete(wh)
    await session.commit()


@router.post("/{webhook_id}/test")
async def test_webhook(
    webhook_id: int, session: SessionDep, user: CurrentUserDep
) -> dict[str, object]:
    _require_admin(user)
    wh = (
        await session.execute(select(Webhook).where(Webhook.id == webhook_id))
    ).scalar_one_or_none()
    if wh is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    await fire("test", {"webhook_id": wh.id, "name": wh.name, "triggered_by": user.username})
    return {"queued": True}
