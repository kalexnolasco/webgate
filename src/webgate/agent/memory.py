"""What the agent found before.

"Has this happened here already?" is the question an on-call engineer actually asks,
and answering it turns a one-off diagnosis into something that compounds.

Search is plain `LIKE` over the words you type, for two reasons. A findings corpus is
thousands of rows, so FTS5 or `tsvector` would buy nothing at this scale while adding
a virtual table kept in sync by triggers, and a dialect split between SQLite and
Postgres. And in an incident you almost always know the string - `OOM`, `disk`, the
unit name - which is exactly what a literal match is best at.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from webgate.db.engine import Base

logger = logging.getLogger(__name__)

MAX_RESULTS = 20
_WORD = re.compile(r"[A-Za-z0-9_./-]{2,}")


class AgentFinding(Base):
    """One completed answer, kept so it can be found again."""

    __tablename__ = "agent_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(Integer, ForeignKey("servers.id"), index=True)
    server_name: Mapped[str] = mapped_column(String(255), default="")
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    username: Mapped[str] = mapped_column(String(150), default="")
    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    tools: Mapped[str] = mapped_column(Text, default="[]")  # JSON array of tool names
    model: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )


async def record(
    session: AsyncSession,
    *,
    server_id: int,
    server_name: str,
    user_id: int,
    username: str,
    question: str,
    answer: str,
    tools: list[str],
    model: str,
) -> AgentFinding:
    finding = AgentFinding(
        server_id=server_id,
        server_name=server_name,
        user_id=user_id,
        username=username,
        question=question[:2000],
        answer=answer,
        tools=json.dumps(tools),
        model=model,
    )
    session.add(finding)
    await session.commit()
    await session.refresh(finding)
    return finding


def _visible(stmt, user_id: int, server_ids: list[int] | None):
    """A finding is readable if you own it or can reach the server it is about."""
    if server_ids is None:  # admin
        return stmt
    if not server_ids:
        return stmt.where(AgentFinding.user_id == user_id)
    return stmt.where(or_(AgentFinding.user_id == user_id, AgentFinding.server_id.in_(server_ids)))


async def search_keywords(
    session: AsyncSession,
    query: str,
    *,
    user_id: int,
    server_ids: list[int] | None,
    server_id: int | None = None,
    limit: int = MAX_RESULTS,
) -> list[AgentFinding]:
    stmt = select(AgentFinding)
    stmt = _visible(stmt, user_id, server_ids)
    if server_id is not None:
        stmt = stmt.where(AgentFinding.server_id == server_id)

    # Every word must appear somewhere in the finding; that is what people expect
    # when they type two words, and it keeps the result set small without ranking.
    for word in _WORD.findall(query or "")[:8]:
        pattern = f"%{word}%"
        stmt = stmt.where(
            or_(
                AgentFinding.answer.ilike(pattern),
                AgentFinding.question.ilike(pattern),
                AgentFinding.server_name.ilike(pattern),
            )
        )
    stmt = stmt.order_by(AgentFinding.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def recent(
    session: AsyncSession,
    *,
    user_id: int,
    server_ids: list[int] | None,
    server_id: int | None = None,
    limit: int = MAX_RESULTS,
) -> list[AgentFinding]:
    stmt = _visible(select(AgentFinding), user_id, server_ids)
    if server_id is not None:
        stmt = stmt.where(AgentFinding.server_id == server_id)
    stmt = stmt.order_by(AgentFinding.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def forget(session: AsyncSession, finding_id: int, *, user_id: int, is_admin: bool) -> bool:
    stmt = select(AgentFinding).where(AgentFinding.id == finding_id)
    if not is_admin:
        stmt = stmt.where(AgentFinding.user_id == user_id)
    finding = (await session.execute(stmt)).scalar_one_or_none()
    if finding is None:
        return False
    await session.delete(finding)
    await session.commit()
    return True


async def purge_older_than(session: AsyncSession, days: int) -> int:
    """Findings hold production command output; they should not live forever."""
    if days <= 0:
        return 0
    cutoff = datetime.now().timestamp() - days * 86400
    stmt = select(AgentFinding.id, AgentFinding.created_at)
    rows = (await session.execute(stmt)).all()
    stale = [row.id for row in rows if row.created_at and row.created_at.timestamp() < cutoff]
    if stale:
        await session.execute(delete(AgentFinding).where(AgentFinding.id.in_(stale)))
        await session.commit()
    return len(stale)


def to_dict(finding: AgentFinding) -> dict[str, Any]:
    try:
        tools = json.loads(finding.tools or "[]")
    except json.JSONDecodeError:
        tools = []
    return {
        "id": finding.id,
        "server_id": finding.server_id,
        "server": finding.server_name,
        "username": finding.username,
        "question": finding.question,
        "answer": finding.answer,
        "tools": tools,
        "model": finding.model,
        "created_at": finding.created_at.isoformat() if finding.created_at else "",
    }
