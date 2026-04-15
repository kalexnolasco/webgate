from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import asyncssh
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.servers.crypto import decrypt_value, encrypt_value
from webgate.servers.models import Server, ServerCreate, ServerOut, ServerUpdate

logger = logging.getLogger(__name__)


def _tags_to_json(tags: list[str]) -> str:
    return json.dumps(tags)


def _tags_from_json(raw: str) -> list[str]:
    try:
        result: object = json.loads(raw)
        if isinstance(result, list):
            return list[str](result)  # pyright: ignore[reportUnknownArgumentType]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _paths_from_json(raw: str) -> list[str]:
    try:
        result: object = json.loads(raw)
        if isinstance(result, list):
            return list[str](result)  # pyright: ignore[reportUnknownArgumentType]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def server_to_out(server: Server) -> ServerOut:
    return ServerOut(
        id=server.id,
        name=server.name,
        hostname=server.hostname,
        port=server.port,
        username=server.username,
        auth_method=server.auth_method,
        group=server.group,
        tags=_tags_from_json(server.tags),
        description=server.description,
        ssh_enabled=server.ssh_enabled,
        sftp_enabled=server.sftp_enabled,
        sftp_allowed_paths=_paths_from_json(server.sftp_allowed_paths),
        sftp_read_only=server.sftp_read_only,
        jump_via_id=server.jump_via_id,
        last_connected_at=server.last_connected_at,
        created_at=server.created_at,
    )


async def list_servers(
    session: AsyncSession,
    user_id: int,
    *,
    is_admin: bool = False,
    allowed_groups: list[str] | None = None,
    group: str | None = None,
    tag: str | None = None,
    search: str | None = None,
) -> list[ServerOut]:
    stmt = select(Server)
    if not is_admin:
        # Non-admin users only see servers in their allowed groups
        if not allowed_groups:
            return []
        stmt = stmt.where(Server.group.in_(allowed_groups))
    if group:
        stmt = stmt.where(Server.group == group)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            Server.name.ilike(pattern)
            | Server.hostname.ilike(pattern)
            | Server.description.ilike(pattern)
        )
    stmt = stmt.order_by(Server.name)
    result = await session.execute(stmt)
    servers = result.scalars().all()
    out = [server_to_out(s) for s in servers]
    if tag:
        out = [s for s in out if tag in s.tags]
    return out


async def get_server(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    *,
    is_admin: bool = False,
    allowed_groups: list[str] | None = None,
) -> Server | None:
    stmt = select(Server).where(Server.id == server_id)
    if not is_admin:
        if not allowed_groups:
            return None
        stmt = stmt.where(Server.group.in_(allowed_groups))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_server(session: AsyncSession, data: ServerCreate, user_id: int) -> Server:
    server = Server(
        name=data.name,
        hostname=data.hostname,
        port=data.port,
        username=data.username,
        auth_method=data.auth_method,
        encrypted_password=encrypt_value(data.password) if data.password else "",
        encrypted_private_key=encrypt_value(data.private_key) if data.private_key else "",
        group=data.group,
        tags=_tags_to_json(data.tags),
        description=data.description,
        ssh_enabled=data.ssh_enabled,
        sftp_enabled=data.sftp_enabled,
        sftp_allowed_paths=_tags_to_json(data.sftp_allowed_paths),
        sftp_read_only=data.sftp_read_only,
        jump_via_id=data.jump_via_id,
        user_id=user_id,
    )
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return server


async def update_server(
    session: AsyncSession, server: Server, data: ServerUpdate
) -> Server:
    if data.name is not None:
        server.name = data.name
    if data.hostname is not None:
        server.hostname = data.hostname
    if data.port is not None:
        server.port = data.port
    if data.username is not None:
        server.username = data.username
    if data.auth_method is not None:
        server.auth_method = data.auth_method
    if data.password is not None:
        server.encrypted_password = encrypt_value(data.password) if data.password else ""
    if data.private_key is not None:
        server.encrypted_private_key = (
            encrypt_value(data.private_key) if data.private_key else ""
        )
    if data.group is not None:
        server.group = data.group
    if data.tags is not None:
        server.tags = _tags_to_json(data.tags)
    if data.description is not None:
        server.description = data.description
    if data.ssh_enabled is not None:
        server.ssh_enabled = data.ssh_enabled
    if data.sftp_enabled is not None:
        server.sftp_enabled = data.sftp_enabled
    if data.sftp_allowed_paths is not None:
        server.sftp_allowed_paths = _tags_to_json(data.sftp_allowed_paths)
    if data.sftp_read_only is not None:
        server.sftp_read_only = data.sftp_read_only
    if data.jump_via_id is not None:
        server.jump_via_id = data.jump_via_id or None  # 0 means "clear"
    await session.commit()
    await session.refresh(server)
    return server


async def delete_server(session: AsyncSession, server: Server) -> None:
    await session.delete(server)
    await session.commit()


async def test_server_connectivity(
    server: Server, session: AsyncSession | None = None
) -> tuple[bool, str]:
    password = decrypt_value(server.encrypted_password) if server.encrypted_password else None
    private_key_str = (
        decrypt_value(server.encrypted_private_key) if server.encrypted_private_key else None
    )

    kwargs: dict[str, object] = {
        "host": server.hostname,
        "port": server.port,
        "username": server.username,
        "known_hosts": None,
    }
    if private_key_str:
        kwargs["client_keys"] = [asyncssh.import_private_key(private_key_str)]
    elif password:
        kwargs["password"] = password

    jump_conn = None
    if session is not None:
        jump_kwargs = await resolve_jump_creds(session, server)
        if jump_kwargs:
            try:
                jump_conn = await asyncssh.connect(**jump_kwargs)  # type: ignore[arg-type]
                kwargs["tunnel"] = jump_conn
            except Exception as e:
                return False, f"Jump host failed: {e}"

    try:
        conn = await asyncssh.connect(**kwargs)  # type: ignore[arg-type]
        conn.close()
        return True, "Connection successful" + (" (via jump host)" if jump_conn else "")
    except Exception as e:
        return False, str(e)
    finally:
        if jump_conn is not None:
            jump_conn.close()


async def update_last_connected(session: AsyncSession, server: Server) -> None:
    server.last_connected_at = datetime.now(UTC)
    await session.commit()


async def list_groups(
    session: AsyncSession,
    *,
    is_admin: bool = False,
    allowed_groups: list[str] | None = None,
) -> list[str]:
    stmt = select(Server.group).where(Server.group != "").distinct().order_by(Server.group)
    if not is_admin and allowed_groups:
        stmt = stmt.where(Server.group.in_(allowed_groups))
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def resolve_jump_creds(
    session: AsyncSession, server: Server
) -> dict[str, object] | None:
    """If `server` has a jump_via_id, return connect kwargs for the bastion.

    Returns None when no jump host is configured. Cycles are silently broken
    (server pointing to itself, or to its own jump, etc.) by following at most
    one hop.
    """
    if server.jump_via_id is None or server.jump_via_id == server.id:
        return None
    stmt = select(Server).where(Server.id == server.jump_via_id)
    jump = (await session.execute(stmt)).scalar_one_or_none()
    if jump is None:
        return None
    password, private_key = get_server_credentials(jump)
    kwargs: dict[str, object] = {
        "host": jump.hostname,
        "port": jump.port,
        "username": jump.username,
        "known_hosts": None,
    }
    if private_key:
        kwargs["client_keys"] = [asyncssh.import_private_key(private_key)]
    elif password:
        kwargs["password"] = password
    return kwargs


def get_server_credentials(server: Server) -> tuple[str | None, str | None]:
    password = decrypt_value(server.encrypted_password) if server.encrypted_password else None
    private_key = (
        decrypt_value(server.encrypted_private_key) if server.encrypted_private_key else None
    )
    return password, private_key
