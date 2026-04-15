"""Demo mode seeding: pre-populates the demo user and showcase servers.

Activated when WEBGATE_DEMO_MODE=true. Idempotent — safe to call on every startup.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from webgate.auth.service import create_user, get_user_by_username
from webgate.servers.models import ServerCreate
from webgate.servers.service import create_server, list_servers

logger = logging.getLogger(__name__)


DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo"

# Servers pre-registered for the demo. Hostnames must be reachable from the
# webgate container. In Fly.io they resolve via *.internal DNS.
DEMO_SERVERS: list[ServerCreate] = [
    ServerCreate(
        name="demo-server",
        hostname="127.0.0.1",
        port=22,
        username="demo",
        password="demo",
        group="demo",
        tags=["demo", "debian"],
        description="Sandbox SSH/SFTP server (debian). Try `ls`, `htop`, browse /home/demo.",
        sftp_read_only=True,
    ),
]


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
    for srv in DEMO_SERVERS:
        if srv.name in existing_names:
            continue
        await create_server(session, srv, user.id)
        logger.info("Seeded demo server: %s -> %s:%s", srv.name, srv.hostname, srv.port)
