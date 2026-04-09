from __future__ import annotations

import json
import mimetypes
import posixpath
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
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
from webgate.servers.models import Server
from webgate.servers.service import get_server, get_server_credentials

router = APIRouter(prefix="/api/files", tags=["files"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[UserOut, Depends(get_current_user)]


def _get_allowed_paths(server: Server) -> list[str]:
    """Parse sftp_allowed_paths JSON. Empty list means unrestricted."""
    try:
        result: object = json.loads(server.sftp_allowed_paths)
        if isinstance(result, list):
            return [posixpath.normpath(p) for p in result if isinstance(p, str) and p]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def check_path_allowed(path: str, allowed_paths: list[str]) -> None:
    """Raise 403 if path is outside all allowed paths. No-op if allowed_paths is empty."""
    if not allowed_paths:
        return
    normalized = posixpath.normpath(path)
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    for allowed in allowed_paths:
        # Path is allowed if it equals or is under an allowed directory
        if normalized == allowed or normalized.startswith(allowed + "/"):
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Access denied: path '{path}' is outside allowed directories",
    )


def check_read_only(read_only: bool) -> None:
    """Raise HTTP 403 if the server's SFTP is in read-only mode."""
    if read_only:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SFTP is in read-only mode for this server",
        )


@asynccontextmanager
async def _sftp(
    server_id: int, session: AsyncSession, user: UserOut
) -> AsyncGenerator[tuple[SFTPClient, list[str], bool]]:
    server = await get_server(
        session, server_id, user.id,
        is_admin=user.is_admin,
        allowed_groups=user.allowed_groups if not user.is_admin else None,
    )
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    if not server.sftp_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="SFTP is disabled for this server"
        )
    allowed_paths = _get_allowed_paths(server)
    read_only = server.sftp_read_only
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
        yield client, allowed_paths, read_only
    finally:
        sftp_pool.release(server_id)


@router.get("/{server_id}/ls", response_model=DirectoryListing)
async def list_dir(
    server_id: int, session: SessionDep, current_user: CurrentUserDep, path: str = "/",
) -> DirectoryListing:
    async with _sftp(server_id, session, current_user) as (client, allowed_paths, _read_only):
        try:
            check_path_allowed(path, allowed_paths)
            entries = await client.ls(path)
            return DirectoryListing(path=validate_path(path), entries=entries)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{server_id}/stat", response_model=FileEntry)
async def file_stat(
    server_id: int, session: SessionDep, current_user: CurrentUserDep, path: str = "/",
) -> FileEntry:
    async with _sftp(server_id, session, current_user) as (client, allowed_paths, _read_only):
        try:
            check_path_allowed(path, allowed_paths)
            return await client.stat(path)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{server_id}/read")
async def read_file(
    server_id: int, session: SessionDep, current_user: CurrentUserDep, path: str = "/",
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as (client, allowed_paths, _read_only):
        try:
            check_path_allowed(path, allowed_paths)
            content = await client.read_text(path)
            return {"path": validate_path(path), "content": content}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{server_id}/download")
async def download_file(
    server_id: int, session: SessionDep, current_user: CurrentUserDep, path: str = "/",
) -> Response:
    async with _sftp(server_id, session, current_user) as (client, allowed_paths, _read_only):
        try:
            safe_path = validate_path(path)
            check_path_allowed(safe_path, allowed_paths)
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


@router.get("/{server_id}/download-zip")
async def download_zip(
    server_id: int, session: SessionDep, current_user: CurrentUserDep, path: str = "/",
) -> Response:
    async with _sftp(server_id, session, current_user) as (client, allowed_paths, _read_only):
        try:
            safe_path = validate_path(path)
            check_path_allowed(safe_path, allowed_paths)
            data = await client.read_directory_as_zip(safe_path)
            folder_name = safe_path.rsplit("/", 1)[-1] or "download"
            return Response(
                content=data,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{folder_name}.zip"'},
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{server_id}/upload")
async def upload_files(
    server_id: int, session: SessionDep, current_user: CurrentUserDep,
    path: str = "/", files: list[UploadFile] = [],  # noqa: B006
) -> dict[str, object]:
    async with _sftp(server_id, session, current_user) as (client, allowed_paths, read_only):
        try:
            check_read_only(read_only)
            safe_path = validate_path(path)
            check_path_allowed(safe_path, allowed_paths)
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
    async with _sftp(server_id, session, current_user) as (client, allowed_paths, read_only):
        try:
            check_read_only(read_only)
            check_path_allowed(body.path, allowed_paths)
            await client.write_text(body.path, body.content)
            return {"path": validate_path(body.path), "status": "saved"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{server_id}/mkdir")
async def make_dir(
    server_id: int, body: MkdirRequest, session: SessionDep, current_user: CurrentUserDep,
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as (client, allowed_paths, read_only):
        try:
            check_read_only(read_only)
            check_path_allowed(body.path, allowed_paths)
            await client.mkdir(body.path)
            return {"path": validate_path(body.path), "status": "created"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{server_id}/rename")
async def rename_item(
    server_id: int, body: RenameRequest, session: SessionDep, current_user: CurrentUserDep,
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as (client, allowed_paths, read_only):
        try:
            check_read_only(read_only)
            check_path_allowed(body.old_path, allowed_paths)
            check_path_allowed(body.new_path, allowed_paths)
            await client.rename(body.old_path, body.new_path)
            return {"old_path": body.old_path, "new_path": body.new_path, "status": "renamed"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/{server_id}/delete")
async def delete_item(
    server_id: int, session: SessionDep, current_user: CurrentUserDep, path: str = "/",
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as (client, allowed_paths, read_only):
        try:
            check_read_only(read_only)
            check_path_allowed(path, allowed_paths)
            await client.delete(path)
            return {"path": validate_path(path), "status": "deleted"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{server_id}/chmod")
async def chmod_item(
    server_id: int, body: ChmodRequest, session: SessionDep, current_user: CurrentUserDep,
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as (client, allowed_paths, read_only):
        try:
            check_read_only(read_only)
            check_path_allowed(body.path, allowed_paths)
            mode = int(body.mode, 8)
            await client.chmod(body.path, mode)
            return {"path": validate_path(body.path), "mode": body.mode, "status": "changed"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
