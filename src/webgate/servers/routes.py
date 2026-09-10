from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.audit.service import log_action
from webgate.auth.models import UserOut
from webgate.auth.routes import get_current_user
from webgate.db.engine import get_session
from webgate.files.pool import sftp_pool
from webgate.servers.hostkeys import describe
from webgate.servers.models import Server, ServerCreate, ServerImport, ServerOut, ServerUpdate
from webgate.servers.service import (
    create_server,
    delete_server,
    get_server,
    list_groups,
    list_servers,
    server_to_out,
    test_server_connectivity,
    update_last_connected,
    update_server,
)
from webgate.webhooks.dispatcher import fire as fire_webhook

router = APIRouter(prefix="/api/servers", tags=["servers"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[UserOut, Depends(get_current_user)]


def _require_admin(user: UserOut) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


def _user_kwargs(user: UserOut) -> dict[str, object]:
    """Common kwargs for service calls based on user role."""
    return {
        "is_admin": user.is_admin,
        "allowed_groups": user.allowed_groups if not user.is_admin else None,
    }


@router.get("", response_model=list[ServerOut])
async def list_all(
    session: SessionDep,
    current_user: CurrentUserDep,
    group: str | None = None,
    tag: str | None = None,
    search: str | None = None,
) -> list[ServerOut]:
    return await list_servers(
        session, current_user.id, group=group, tag=tag, search=search, **_user_kwargs(current_user)
    )


@router.post("", response_model=ServerOut, status_code=status.HTTP_201_CREATED)
async def create(
    body: ServerCreate, session: SessionDep, current_user: CurrentUserDep
) -> ServerOut:
    _require_admin(current_user)
    server = await create_server(session, body, current_user.id)
    await fire_webhook("server_added", {
        "id": server.id, "name": server.name, "hostname": server.hostname,
        "by": current_user.username,
    })
    return server_to_out(server)


@router.get("/groups", response_model=list[str])
async def groups(session: SessionDep, current_user: CurrentUserDep) -> list[str]:
    return await list_groups(session, **_user_kwargs(current_user))


@router.get("/export", response_model=list[ServerOut])
async def export_servers(session: SessionDep, current_user: CurrentUserDep) -> list[ServerOut]:
    _require_admin(current_user)
    return await list_servers(session, current_user.id, is_admin=True)


@router.post("/import", response_model=list[ServerOut], status_code=status.HTTP_201_CREATED)
async def import_servers(
    body: ServerImport, session: SessionDep, current_user: CurrentUserDep
) -> list[ServerOut]:
    _require_admin(current_user)

    # The exported jump_via_id refers to ids in the SOURCE database. Ids are
    # reassigned here, so carrying one over would silently point a server at
    # whatever host happens to land on that id. Resolve the hop by name instead.
    # The exported jump_via_id refers to ids in the SOURCE database. Ids are
    # reassigned here, so carrying one over would silently point a server at
    # whatever host happens to land on that id. Resolve the hop by name instead.
    exported_names = {s.id: s.name for s in body.servers if s.id is not None}

    made: list[Server] = []
    by_name: dict[str, Server] = {}
    pending: list[tuple[Server, str]] = []

    for item in body.servers:
        target_name = item.jump_via_name or exported_names.get(item.jump_via_id or -1)
        payload = ServerCreate(
            **item.model_dump(exclude={"id", "jump_via_name", "jump_via_id"}),
            jump_via_id=None,
        )
        server = await create_server(session, payload, current_user.id)
        made.append(server)
        by_name[server.name] = server
        if target_name:
            pending.append((server, target_name))

    if pending:
        for other in await list_servers(session, current_user.id, is_admin=True):
            by_name.setdefault(other.name, other)
        touched = False
        for server, target_name in pending:
            target = by_name.get(target_name)
            if target is None or target.id == server.id:
                continue  # unresolvable or self-referencing: leave the hop unset
            server.jump_via_id = target.id
            touched = True
        if touched:
            await session.commit()
            for server in made:
                await session.refresh(server)

    return [server_to_out(s) for s in made]


@router.delete("/{server_id}/host-key")
async def clear_host_key(
    server_id: int, session: SessionDep, current_user: CurrentUserDep
) -> dict[str, str]:
    """Forget the pinned key so the next connection learns the current one.

    This is the deliberate act that accepts a rebuilt host or a rotated key. It is
    admin-only precisely because it re-opens the first-contact window.
    """
    _require_admin(current_user)
    server = await get_server(
        session, server_id, current_user.id, is_admin=True, allowed_groups=None
    )
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    previous = describe(server.host_key or "")
    server.host_key = ""
    await session.commit()
    await sftp_pool.drop(server_id)
    await log_action(
        current_user.id,
        current_user.username,
        "host_key_cleared",
        detail=f"{server.name}: was {previous or 'unpinned'}",
    )
    return {
        "cleared": previous,
        "detail": f"The next connection to {server.name} will pin its key.",
    }


@router.get("/status")
async def all_statuses(current_user: CurrentUserDep) -> dict[str, object]:
    from webgate.servers.monitor import server_monitor

    statuses = server_monitor.get_all_statuses()
    return {
        str(sid): {
            "online": s.online,
            "last_checked": s.last_checked.isoformat(),
            "latency_ms": s.latency_ms,
            "error": s.error,
        }
        for sid, s in statuses.items()
    }


@router.get("/{server_id}/status")
async def single_status(server_id: int, current_user: CurrentUserDep) -> dict[str, object]:
    from webgate.servers.monitor import server_monitor

    s = server_monitor.get_status(server_id)
    if s is None:
        return {"online": None, "last_checked": None, "latency_ms": None, "error": None}
    return {
        "online": s.online,
        "last_checked": s.last_checked.isoformat(),
        "latency_ms": s.latency_ms,
        "error": s.error,
    }


@router.get("/{server_id}", response_model=ServerOut)
async def get_one(
    server_id: int, session: SessionDep, current_user: CurrentUserDep
) -> ServerOut:
    server = await get_server(session, server_id, current_user.id, **_user_kwargs(current_user))
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    return server_to_out(server)


@router.put("/{server_id}", response_model=ServerOut)
async def update(
    server_id: int, body: ServerUpdate, session: SessionDep, current_user: CurrentUserDep
) -> ServerOut:
    _require_admin(current_user)
    server = await get_server(session, server_id, current_user.id, is_admin=True)
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    updated = await update_server(session, server, body)
    return server_to_out(updated)


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    server_id: int, session: SessionDep, current_user: CurrentUserDep
) -> None:
    _require_admin(current_user)
    server = await get_server(session, server_id, current_user.id, is_admin=True)
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    server_info = {"id": server.id, "name": server.name, "hostname": server.hostname}
    await delete_server(session, server)
    await fire_webhook("server_deleted", {**server_info, "by": current_user.username})


@router.post("/{server_id}/test")
async def test_connectivity(
    server_id: int, session: SessionDep, current_user: CurrentUserDep
) -> dict[str, object]:
    server = await get_server(session, server_id, current_user.id, **_user_kwargs(current_user))
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    success, message = await test_server_connectivity(server, session)
    if success:
        await update_last_connected(session, server)
    return {"success": success, "message": message}
