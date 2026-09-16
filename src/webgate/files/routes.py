from __future__ import annotations

import json
import mimetypes
import posixpath
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated, NamedTuple

import asyncssh
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.audit.service import log_action
from webgate.auth.models import UserOut
from webgate.auth.routes import get_current_user
from webgate.db.engine import get_session
from webgate.files.limits import Budget
from webgate.files.limits import budget as transfer_budget
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
from webgate.servers.crypto import CredentialUnreadable
from webgate.servers.hostkeys import remember, translate
from webgate.servers.models import Server
from webgate.servers.service import get_server, get_server_credentials, resolve_jump_creds
from webgate.webhooks.dispatcher import fire as fire_webhook

UPLOAD_CHUNK = 256 * 1024  # bytes read per pass from a multipart upload

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


class SftpSession(NamedTuple):
    """An open SFTP connection and what the caller needs to know about it.

    `server_name` is here so an audit entry can say *which* server a path was on.
    "deleted /etc/nginx/nginx.conf" is only half an answer.
    """

    client: SFTPClient
    allowed_paths: list[str]
    read_only: bool
    server_name: str


@asynccontextmanager
async def _sftp(
    server_id: int, session: AsyncSession, user: UserOut
) -> AsyncGenerator[SftpSession]:
    server = await get_server(
        session,
        server_id,
        user.id,
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
    try:
        password, private_key = get_server_credentials(server)
    except CredentialUnreadable as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    jump_kwargs = await resolve_jump_creds(session, server)
    try:
        client = await sftp_pool.acquire(
            server_id,
            hostname=server.hostname,
            port=server.port,
            username=server.username,
            password=password,
            private_key=private_key,
            jump_kwargs=jump_kwargs,
            host_key=getattr(server, "host_key", "") or "",
        )
        await remember(session, server, client.conn)
    except asyncssh.HostKeyNotVerifiable as exc:
        # An opaque 500 here would read as "SFTP is broken" rather than "this host is
        # not the one you pinned", which is the whole point of refusing.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(translate(exc, server.name, getattr(server, "host_key", "") or "")),
        ) from exc
    try:
        yield SftpSession(client, allowed_paths, read_only, server.name)
    finally:
        sftp_pool.release(server_id)


async def _audit(
    request: Request, user: CurrentUserDep, sftp: SftpSession, action: str, detail: str
) -> None:
    """Record a file operation against the server and path it touched.

    None of these were recorded at all. A person told that a file had gone could see
    only that *something* happened, which is the same as seeing nothing: the log has
    to name the file, the server and the account, or an incident has no answer.
    """
    await log_action(
        user.id,
        user.username,
        action,
        detail=f"{sftp.server_name}: {detail}",
        ip_address=request.client.host if request.client else "",
    )


@router.get("/{server_id}/ls", response_model=DirectoryListing)
async def list_dir(
    server_id: int,
    session: SessionDep,
    current_user: CurrentUserDep,
    path: str = "/",
) -> DirectoryListing:
    async with _sftp(server_id, session, current_user) as sftp:
        client, allowed_paths, _read_only = sftp.client, sftp.allowed_paths, sftp.read_only
        try:
            check_path_allowed(path, allowed_paths)
            entries = await client.ls(path)
            return DirectoryListing(path=validate_path(path), entries=entries)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{server_id}/stat", response_model=FileEntry)
async def file_stat(
    server_id: int,
    session: SessionDep,
    current_user: CurrentUserDep,
    path: str = "/",
) -> FileEntry:
    async with _sftp(server_id, session, current_user) as sftp:
        client, allowed_paths, _read_only = sftp.client, sftp.allowed_paths, sftp.read_only
        try:
            check_path_allowed(path, allowed_paths)
            return await client.stat(path)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{server_id}/read")
async def read_file(
    server_id: int,
    session: SessionDep,
    current_user: CurrentUserDep,
    path: str = "/",
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as sftp:
        client, allowed_paths, _read_only = sftp.client, sftp.allowed_paths, sftp.read_only
        try:
            check_path_allowed(path, allowed_paths)
            content = await client.read_text(path)
            return {"path": validate_path(path), "content": content}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


async def _read_upload(f: UploadFile, budget: Budget) -> bytes:
    """Read an upload in chunks so an oversized one is stopped, not swallowed."""
    chunks: list[bytes] = []
    while True:
        chunk = await f.read(UPLOAD_CHUNK)
        if not chunk:
            break
        budget.spend(len(chunk), f.filename or "This upload")
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/{server_id}/download")
async def download_file(
    server_id: int,
    request: Request,
    session: SessionDep,
    current_user: CurrentUserDep,
    path: str = "/",
) -> Response:
    async with _sftp(server_id, session, current_user) as sftp:
        client, allowed_paths, _read_only = sftp.client, sftp.allowed_paths, sftp.read_only
        try:
            safe_path = validate_path(path)
            check_path_allowed(safe_path, allowed_paths)
            budget = transfer_budget()
            entry = await client.stat(safe_path)
            budget.check(entry.size, entry.name or "This file")
            data = await client.read_bytes(safe_path, budget)
            await _audit(request, current_user, sftp, "sftp_download", safe_path)
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
    server_id: int,
    request: Request,
    session: SessionDep,
    current_user: CurrentUserDep,
    path: str = "/",
) -> Response:
    async with _sftp(server_id, session, current_user) as sftp:
        client, allowed_paths, _read_only = sftp.client, sftp.allowed_paths, sftp.read_only
        try:
            safe_path = validate_path(path)
            check_path_allowed(safe_path, allowed_paths)
            data = await client.read_directory_as_zip(safe_path, transfer_budget())
            await _audit(request, current_user, sftp, "sftp_download", f"{safe_path} (as zip)")
            folder_name = safe_path.rsplit("/", 1)[-1] or "download"
            return Response(
                content=data,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{folder_name}.zip"'},
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


class ZipSelection(BaseModel):
    """A set of paths to archive together, named relative to ``base_path``."""

    paths: list[str] = Field(min_length=1, max_length=500)
    base_path: str = "/"


@router.post("/{server_id}/download-zip")
async def download_zip_selection(
    server_id: int,
    request: Request,
    body: ZipSelection,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    """Archive a caller-chosen selection.

    The GET form above zips one whole directory; this takes the files and folders the
    user actually ticked, which is what a listing selection means.
    """
    # Shape of the request is checked before opening SSH: a traversal attempt should
    # cost a 400, not a connection attempt that has to time out first.
    try:
        safe_base = validate_path(body.base_path)
        safe_paths = [validate_path(raw) for raw in body.paths]
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    async with _sftp(server_id, session, current_user) as sftp:
        client, allowed_paths, _read_only = sftp.client, sftp.allowed_paths, sftp.read_only
        try:
            check_path_allowed(safe_base, allowed_paths)
            for safe in safe_paths:
                check_path_allowed(safe, allowed_paths)
            data, skipped = await client.read_paths_as_zip(safe_paths, safe_base, transfer_budget())
            await _audit(
                request,
                current_user,
                sftp,
                "sftp_download",
                f"{len(safe_paths)} item(s) as zip from {safe_base}: " + ", ".join(safe_paths[:20]),
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    folder = safe_base.rsplit("/", 1)[-1] or "download"
    name = folder if len(safe_paths) > 1 else safe_paths[0].rsplit("/", 1)[-1] or folder
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}.zip"',
            # Unreadable entries are dropped rather than failing the whole archive;
            # say so, so the download is never quietly incomplete.
            "X-Skipped-Count": str(len(skipped)),
            "X-Skipped-Names": ", ".join(skipped[:10]),
        },
    )


@router.post("/{server_id}/upload")
async def upload_files(
    server_id: int,
    request: Request,
    session: SessionDep,
    current_user: CurrentUserDep,
    path: str = "/",
    files: list[UploadFile] = [],  # noqa: B006
) -> dict[str, object]:
    async with _sftp(server_id, session, current_user) as sftp:
        client, allowed_paths, read_only = sftp.client, sftp.allowed_paths, sftp.read_only
        try:
            check_read_only(read_only)
            safe_path = validate_path(path)
            check_path_allowed(safe_path, allowed_paths)
            uploaded: list[str] = []
            budget = transfer_budget()
            for f in files:
                if not f.filename:
                    continue
                dest = f"{safe_path}/{f.filename}" if safe_path != "/" else f"/{f.filename}"
                # The multipart parser knows the size, so refuse before reading. It is
                # only a hint, though -- the chunked read below is what enforces it.
                if f.size is not None:
                    budget.check(f.size, f.filename)
                data = await _read_upload(f, budget)
                await client.upload(dest, data)
                uploaded.append(dest)
            await _audit(
                request, current_user, sftp, "sftp_upload", ", ".join(uploaded) or "(nothing)"
            )
            await fire_webhook(
                "sftp_upload",
                {
                    "user": current_user.username,
                    "server_id": server_id,
                    "paths": uploaded,
                    "count": len(uploaded),
                },
            )
            return {"uploaded": uploaded, "count": len(uploaded)}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.put("/{server_id}/write")
async def write_file(
    server_id: int,
    request: Request,
    body: FileWriteRequest,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as sftp:
        client, allowed_paths, read_only = sftp.client, sftp.allowed_paths, sftp.read_only
        try:
            check_read_only(read_only)
            check_path_allowed(body.path, allowed_paths)
            await client.write_text(body.path, body.content)
            await _audit(
                request,
                current_user,
                sftp,
                "sftp_write",
                f"{validate_path(body.path)} ({len(body.content)} bytes)",
            )
            return {"path": validate_path(body.path), "status": "saved"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{server_id}/mkdir")
async def make_dir(
    server_id: int,
    request: Request,
    body: MkdirRequest,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as sftp:
        client, allowed_paths, read_only = sftp.client, sftp.allowed_paths, sftp.read_only
        try:
            check_read_only(read_only)
            check_path_allowed(body.path, allowed_paths)
            await client.mkdir(body.path)
            await _audit(request, current_user, sftp, "sftp_mkdir", validate_path(body.path))
            return {"path": validate_path(body.path), "status": "created"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{server_id}/rename")
async def rename_item(
    server_id: int,
    request: Request,
    body: RenameRequest,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as sftp:
        client, allowed_paths, read_only = sftp.client, sftp.allowed_paths, sftp.read_only
        try:
            check_read_only(read_only)
            check_path_allowed(body.old_path, allowed_paths)
            check_path_allowed(body.new_path, allowed_paths)
            await client.rename(body.old_path, body.new_path)
            await _audit(
                request,
                current_user,
                sftp,
                "sftp_rename",
                f"{validate_path(body.old_path)} -> {validate_path(body.new_path)}",
            )
            return {"old_path": body.old_path, "new_path": body.new_path, "status": "renamed"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/{server_id}/delete")
async def delete_item(
    server_id: int,
    request: Request,
    session: SessionDep,
    current_user: CurrentUserDep,
    path: str = "/",
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as sftp:
        client, allowed_paths, read_only = sftp.client, sftp.allowed_paths, sftp.read_only
        try:
            check_read_only(read_only)
            check_path_allowed(path, allowed_paths)
            await client.delete(path)
            # The reported gap: a person told a file had gone could see only that
            # *something* happened, which is the same as seeing nothing.
            await _audit(request, current_user, sftp, "sftp_delete", validate_path(path))
            await fire_webhook(
                "sftp_delete",
                {
                    "user": current_user.username,
                    "server_id": server_id,
                    "path": path,
                },
            )
            return {"path": validate_path(path), "status": "deleted"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{server_id}/chmod")
async def chmod_item(
    server_id: int,
    request: Request,
    body: ChmodRequest,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> dict[str, str]:
    async with _sftp(server_id, session, current_user) as sftp:
        client, allowed_paths, read_only = sftp.client, sftp.allowed_paths, sftp.read_only
        try:
            check_read_only(read_only)
            check_path_allowed(body.path, allowed_paths)
            mode = int(body.mode, 8)
            await client.chmod(body.path, mode)
            await _audit(
                request,
                current_user,
                sftp,
                "sftp_chmod",
                f"{validate_path(body.path)} -> {body.mode}",
            )
            return {"path": validate_path(body.path), "mode": body.mode, "status": "changed"}
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
