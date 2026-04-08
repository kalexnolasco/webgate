from __future__ import annotations

from sqlalchemy import select
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
) -> list[AuditOut]:
    stmt = select(AuditEntry).order_by(AuditEntry.created_at.desc())
    if username:
        stmt = stmt.where(AuditEntry.username == username)
    if action:
        stmt = stmt.where(AuditEntry.action == action)
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return [AuditOut.model_validate(e) for e in result.scalars().all()]
