from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.audit.models import AuditEntry, AuditOut
from webgate.db.engine import async_session_factory


async def log_action(
    user_id: int,
    username: str,
    action: str,
    detail: str = "",
    ip_address: str = "",
) -> None:
    """Fire-and-forget audit log entry."""
    async with async_session_factory() as session:
        entry = AuditEntry(
            user_id=user_id,
            username=username,
            action=action,
            detail=detail,
            ip_address=ip_address,
        )
        session.add(entry)
        await session.commit()


async def get_audit_log(
    session: AsyncSession,
    limit: int = 100,
    offset: int = 0,
    username: str | None = None,
    action: str | None = None,
    search: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[AuditOut]:
    """Entries, newest first.

    `search` matches the detail as well as the username, because the thing an
    operator actually has is a filename -- "who deleted nginx.conf" is the question,
    and filtering by action first requires already knowing it was a delete.
    """
    stmt = select(AuditEntry).order_by(AuditEntry.created_at.desc())
    if username:
        stmt = stmt.where(AuditEntry.username == username)
    if action:
        stmt = stmt.where(AuditEntry.action == action)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                AuditEntry.detail.ilike(pattern),
                AuditEntry.username.ilike(pattern),
                AuditEntry.action.ilike(pattern),
            )
        )
    if since:
        stmt = stmt.where(AuditEntry.created_at >= since)
    if until:
        stmt = stmt.where(AuditEntry.created_at <= until)
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return [AuditOut.model_validate(e) for e in result.scalars().all()]


async def audit_actions(session: AsyncSession) -> list[str]:
    """Every action kind present, so the filter can be a list rather than guesswork."""
    stmt = select(AuditEntry.action).distinct().order_by(AuditEntry.action)
    return [row[0] for row in (await session.execute(stmt)).all()]
