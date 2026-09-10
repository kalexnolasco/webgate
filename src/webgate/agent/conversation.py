"""Per-server conversations with the diagnostic agent.

Investigation is rarely one question. Keeping the transcript means a follow-up like
"now check the nginx error log" builds on the evidence already gathered instead of
re-running the same commands.

Two constraints shape the design:

* **It must survive a worker change.** webgate runs multiple stateless instances
  behind a load balancer, so an in-memory transcript would vanish the moment the
  next message landed elsewhere. The rows live in the database.
* **It must not grow without bound.** Command output dominates the transcript, so
  older tool results are reduced to a note of what ran while recent turns stay whole.

A transcript holds command output from production hosts, so it is scoped to one
user and one server, never shared, and can be cleared from the UI.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from webgate.db.engine import Base

logger = logging.getLogger(__name__)

# Roughly four characters per token; a deliberately coarse estimate, since the point
# is to stay well inside any model's window rather than to fill it exactly.
CHARS_PER_TOKEN = 4
DEFAULT_BUDGET_TOKENS = 24_000
KEEP_RECENT_MESSAGES = 12  # never trimmed, so the current line of enquiry stays intact
STUB = "[earlier output trimmed to keep the conversation within the model's context]"


class AgentConversation(Base):
    __tablename__ = "agent_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    server_id: Mapped[int] = mapped_column(Integer, ForeignKey("servers.id"), index=True)
    messages: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())


async def load(session: AsyncSession, user_id: int, server_id: int) -> list[dict[str, Any]]:
    row = (
        await session.execute(
            select(AgentConversation).where(
                AgentConversation.user_id == user_id,
                AgentConversation.server_id == server_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return []
    try:
        data = json.loads(row.messages or "[]")
    except json.JSONDecodeError:
        logger.warning("Discarding unreadable transcript for server %s", server_id)
        return []
    return data if isinstance(data, list) else []


async def save(
    session: AsyncSession, user_id: int, server_id: int, messages: list[dict[str, Any]]
) -> None:
    row = (
        await session.execute(
            select(AgentConversation).where(
                AgentConversation.user_id == user_id,
                AgentConversation.server_id == server_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = AgentConversation(user_id=user_id, server_id=server_id)
        session.add(row)
    row.messages = json.dumps(messages)
    row.updated_at = datetime.now()
    await session.commit()


async def clear(session: AsyncSession, user_id: int, server_id: int) -> None:
    row = (
        await session.execute(
            select(AgentConversation).where(
                AgentConversation.user_id == user_id,
                AgentConversation.server_id == server_id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.commit()


def _size(messages: list[dict[str, Any]]) -> int:
    return sum(len(json.dumps(m)) for m in messages) // CHARS_PER_TOKEN


def trim(
    messages: list[dict[str, Any]], budget_tokens: int = DEFAULT_BUDGET_TOKENS
) -> list[dict[str, Any]]:
    """Shrink an over-long transcript without breaking its shape.

    Tool results are stubbed before anything is dropped: the model keeps the record
    of *which* commands ran and what was concluded, losing only the raw output it has
    already reasoned about. Assistant messages carrying `tool_calls` must keep their
    matching `tool` replies, so pairs are only ever removed together, from the front.
    """
    if _size(messages) <= budget_tokens:
        return messages

    out = [dict(m) for m in messages]
    head = 1 if out and out[0].get("role") == "system" else 0

    # Pass 1: stub the output of older tool results.
    for message in out[head : max(head, len(out) - KEEP_RECENT_MESSAGES)]:
        if message.get("role") == "tool" and len(str(message.get("content", ""))) > len(STUB):
            message["content"] = STUB
    if _size(out) <= budget_tokens:
        return out

    # Pass 2: drop whole exchanges from the front, keeping the system prompt and the
    # opening question so the model never loses what it was asked to investigate.
    keep_from = head + 1 if len(out) > head + 1 else head
    while _size(out) > budget_tokens and len(out) > keep_from + KEEP_RECENT_MESSAGES:
        del out[keep_from]
        # An assistant turn with tool_calls is meaningless without its results.
        while (
            len(out) > keep_from + KEEP_RECENT_MESSAGES
            and out[keep_from].get("role") == "tool"
        ):
            del out[keep_from]
    if _size(out) <= budget_tokens:
        return out

    # Pass 3: the recent window is protected from the passes above, so a small budget
    # would otherwise be silently overshot -- and overshooting a model's context is a
    # hard failure, not a longer prompt. Losing raw output beats losing the request.
    for message in reversed(out):
        if _size(out) <= budget_tokens:
            break
        if message.get("role") == "tool" and message.get("content") != STUB:
            message["content"] = STUB
    return out


def _asked(content: str) -> str:
    """The question as the person typed it.

    The opening message also carries host details the server composed; showing those
    back would look like the user typed them.
    """
    marker = "\n\n"
    if content.startswith("Host: ") and marker in content:
        return content.split(marker, 1)[1].strip()
    return content


def to_display(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The transcript as the UI shows it: what was asked, answered, and run."""
    turns: list[dict[str, Any]] = []
    pending: list[str] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            continue
        if role == "user":
            turns.append(
                {"role": "user", "text": _asked(message.get("content") or ""), "commands": []}
            )
        elif role == "assistant":
            for call in message.get("tool_calls") or []:
                name = (call.get("function") or {}).get("name")
                if name:
                    pending.append(name)
            text = (message.get("content") or "").strip()
            if text and not message.get("tool_calls"):
                turns.append({"role": "agent", "text": text, "commands": pending})
                pending = []
    if pending and turns:
        turns[-1]["commands"] = turns[-1].get("commands", []) + pending
    return turns
