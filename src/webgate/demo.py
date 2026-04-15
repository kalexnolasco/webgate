"""Demo mode seeding: pre-populates the demo user and showcase servers.

Activated when WEBGATE_DEMO_MODE=true. Idempotent — safe to call on every startup.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from webgate.auth.service import create_user, get_user_by_username
from sqlalchemy import select

from webgate.servers.models import ServerCreate
from webgate.servers.service import create_server, list_servers
from webgate.snippets.models import Snippet

logger = logging.getLogger(__name__)


DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo"

def _bastion() -> ServerCreate:
    return ServerCreate(
        name="bastion",
        hostname="127.0.0.1",
        port=22,
        username="demo",
        password="demo",
        group="demo",
        tags=["demo", "bastion"],
        description="Public SSH bastion. Other servers proxy through this one.",
        sftp_read_only=True,
    )


def _internal(jump_via_id: int) -> ServerCreate:
    return ServerCreate(
        name="internal-app",
        hostname="127.0.0.1",
        port=22,
        username="demo",
        password="demo",
        group="demo",
        tags=["demo", "internal"],
        description="App server reachable only via the bastion (jump-host demo).",
        sftp_read_only=True,
        jump_via_id=jump_via_id,
    )


async def seed_demo(session: AsyncSession) -> None:
    user = await get_user_by_username(session, DEMO_USERNAME)
    if user is None:
        user = await create_user(session, DEMO_USERNAME, DEMO_PASSWORD, is_admin=False)
        user.must_change_password = False
        user.allowed_groups = json.dumps(["demo"])
        await session.commit()
        logger.info("Created demo user (%s/%s)", DEMO_USERNAME, DEMO_PASSWORD)

    existing = await list_servers(session, user.id, is_admin=True)
    existing_names = {s.name for s in existing}

    bastion_id: int | None = next((s.id for s in existing if s.name == "bastion"), None)
    if "bastion" not in existing_names:
        bastion = await create_server(session, _bastion(), user.id)
        bastion_id = bastion.id
        logger.info("Seeded demo bastion (id=%s)", bastion_id)

    if "internal-app" not in existing_names and bastion_id is not None:
        await create_server(session, _internal(bastion_id), user.id)
        logger.info("Seeded internal-app via bastion id=%s", bastion_id)

    # Seed a few example snippets so the toolbar isn't empty
    existing_snippets = (
        await session.execute(select(Snippet).where(Snippet.user_id == user.id))
    ).scalars().all()
    if not existing_snippets:
        for name, cmd, desc in [
            ("ls -lah", "ls -lah", "List files (long, human sizes, hidden)"),
            ("disk usage", "df -h", "Mounted filesystems with sizes"),
            ("top procs", "ps aux --sort=-%mem | head", "Top memory-consuming processes"),
            ("uptime", "uptime && uname -a", "Uptime + kernel info"),
        ]:
            session.add(Snippet(name=name, command=cmd, description=desc, user_id=user.id))
        await session.commit()
        logger.info("Seeded %d demo snippets", 4)
