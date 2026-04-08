from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.auth.models import UserOut
from webgate.auth.routes import get_current_user
from webgate.db.engine import get_session
from webgate.servers.models import ServerCreate, ServerImport, ServerOut, ServerUpdate
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
    results: list[ServerOut] = []
    for srv in body.servers:
        server = await create_server(session, srv, current_user.id)
        results.append(server_to_out(server))
    return results


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
    await delete_server(session, server)


@router.post("/{server_id}/test")
async def test_connectivity(
    server_id: int, session: SessionDep, current_user: CurrentUserDep
) -> dict[str, object]:
    server = await get_server(session, server_id, current_user.id, **_user_kwargs(current_user))
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    success, message = await test_server_connectivity(server)
    if success:
        await update_last_connected(session, server)
    return {"success": success, "message": message}
