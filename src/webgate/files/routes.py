from __future__ import annotations

import mimetypes
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.auth.models import UserOut
from webgate.auth.routes import get_current_user
from webgate.db.engine import get_session
from webgate.files.models import (
    ChmodRequest,
    DirectoryListing,
    FileEntry,
    FileWriteRequest,
    MkdirRequest,
    RenameRequest,
)
from webgate.files.pool import sftp_pool
from webgate.files.sftp_service import SFTPClient, validate_path
from webgate.servers.service import get_server, get_server_credentials

router = APIRouter(prefix="/api/files", tags=["files"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[UserOut, Depends(get_current_user)]


@asynccontextmanager
async def _sftp(
    server_id: int, session: AsyncSession, user: UserOut
) -> AsyncGenerator[SFTPClient]:
    server = await get_server(
        session, server_id, user.id,
        is_admin=user.is_admin,
        allowed_groups=user.allowed_groups if not user.is_admin else None,
    )
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    password, private_key = get_server_credentials(server)
    try:
        client = await sftp_pool.acquire(
            server_id,
            hostname=server.hostname,
            port=server.port,
            username=server.username,
            password=password,
            private_key=private_key,
        )
        yield client
    finally:
        sftp_pool.release(server_id)


@router.get("/{server_id}/ls", response_model=DirectoryListing)
async def list_dir(
    server_id: int, session: SessionDep, current_user: CurrentUserDep, path: str = "/",
) -> DirectoryListing:
    async with _sftp(server_id, session, current_user) as client:
        try:
            entries = await client.ls(path)
            return DirectoryListing(path=validate_path(path), entries=entries)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{server_id}/stat", response_model=FileEntry)
async def file_stat(
    server_id: int, session: SessionDep, current_user: CurrentUserDep, path: str = "/",
) -> FileEntry:
    async with _sftp(server_id, session, current_user) as client:
        try:
            return await client.stat(path)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{server_id}/read")
async def read_file(
    server_id: int, session: SessionDep, current_user: CurrentUserDep, path: str = "/",
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as client:
        try:
            content = await client.read_text(path)
            return {"path": validate_path(path), "content": content}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{server_id}/download")
async def download_file(
    server_id: int, session: SessionDep, current_user: CurrentUserDep, path: str = "/",
) -> Response:
    async with _sftp(server_id, session, current_user) as client:
        try:
            safe_path = validate_path(path)
            data = await client.read_bytes(safe_path)
            filename = safe_path.rsplit("/", 1)[-1] or "download"
            media_type, _ = mimetypes.guess_type(filename)
            return Response(
                content=data,
                media_type=media_type or "application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{server_id}/upload")
async def upload_files(
    server_id: int, session: SessionDep, current_user: CurrentUserDep,
    path: str = "/", files: list[UploadFile] = [],  # noqa: B006
) -> dict[str, object]:
    async with _sftp(server_id, session, current_user) as client:
        try:
            safe_path = validate_path(path)
            uploaded: list[str] = []
            for f in files:
                if not f.filename:
                    continue
                dest = f"{safe_path}/{f.filename}" if safe_path != "/" else f"/{f.filename}"
                data = await f.read()
                await client.upload(dest, data)
                uploaded.append(dest)
            return {"uploaded": uploaded, "count": len(uploaded)}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.put("/{server_id}/write")
async def write_file(
    server_id: int, body: FileWriteRequest, session: SessionDep, current_user: CurrentUserDep,
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as client:
        try:
            await client.write_text(body.path, body.content)
            return {"path": validate_path(body.path), "status": "saved"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{server_id}/mkdir")
async def make_dir(
    server_id: int, body: MkdirRequest, session: SessionDep, current_user: CurrentUserDep,
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as client:
        try:
            await client.mkdir(body.path)
            return {"path": validate_path(body.path), "status": "created"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{server_id}/rename")
async def rename_item(
    server_id: int, body: RenameRequest, session: SessionDep, current_user: CurrentUserDep,
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as client:
        try:
            await client.rename(body.old_path, body.new_path)
            return {"old_path": body.old_path, "new_path": body.new_path, "status": "renamed"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/{server_id}/delete")
async def delete_item(
    server_id: int, session: SessionDep, current_user: CurrentUserDep, path: str = "/",
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as client:
        try:
            await client.delete(path)
            return {"path": validate_path(path), "status": "deleted"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{server_id}/chmod")
async def chmod_item(
    server_id: int, body: ChmodRequest, session: SessionDep, current_user: CurrentUserDep,
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as client:
        try:
            mode = int(body.mode, 8)
            await client.chmod(body.path, mode)
            return {"path": validate_path(body.path), "mode": body.mode, "status": "changed"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
