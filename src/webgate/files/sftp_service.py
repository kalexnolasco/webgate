from __future__ import annotations

import io
import logging
import posixpath
import stat
import zipfile
from datetime import UTC, datetime
from typing import Any

import asyncssh

from webgate.files.models import FileEntry

logger = logging.getLogger(__name__)


def validate_path(path: str) -> str:
    normalized = posixpath.normpath(path)
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    parts = normalized.split("/")
    if ".." in parts:
        raise ValueError("Path traversal detected")
    return normalized


def _to_str(val: str | bytes) -> str:
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return val


class SFTPClient:
    def __init__(self, conn: asyncssh.SSHClientConnection) -> None:
        self._conn = conn
        self._sftp: asyncssh.SFTPClient | None = None

    async def connect(self) -> None:
        self._sftp = await self._conn.start_sftp_client()

    @property
    def sftp(self) -> asyncssh.SFTPClient:
        if self._sftp is None:
            raise RuntimeError("SFTP client not connected")
        return self._sftp

    async def ls(self, path: str) -> list[FileEntry]:
        safe_path = validate_path(path)
        entries: list[FileEntry] = []
        items = await self.sftp.readdir(safe_path)
        for item in items:
            name = _to_str(item.filename)
            if name in (".", ".."):
                continue
            attrs = item.attrs
            is_dir = (
                bool(attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY) if attrs.type else False
            )
            size = attrs.size or 0
            perms = (
                stat.filemode(attrs.permissions) if attrs.permissions is not None else "----------"
            )
            owner = str(attrs.uid) if attrs.uid is not None else ""
            group = str(attrs.gid) if attrs.gid is not None else ""
            mtime = (
                datetime.fromtimestamp(attrs.mtime, tz=UTC).isoformat()
                if attrs.mtime is not None
                else ""
            )
            entries.append(FileEntry(
                name=name,
                path=posixpath.join(safe_path, name),
                is_dir=is_dir,
                size=size,
                permissions=perms,
                owner=owner,
                group=group,
                modified=mtime,
            ))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    async def stat(self, path: str) -> FileEntry:
        safe_path = validate_path(path)
        attrs = await self.sftp.stat(safe_path)
        is_dir = bool(attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY) if attrs.type else False
        perms = (
            stat.filemode(attrs.permissions) if attrs.permissions is not None else "----------"
        )
        return FileEntry(
            name=posixpath.basename(safe_path),
            path=safe_path,
            is_dir=is_dir,
            size=attrs.size or 0,
            permissions=perms,
            owner=str(attrs.uid) if attrs.uid is not None else "",
            group=str(attrs.gid) if attrs.gid is not None else "",
            modified=(
                datetime.fromtimestamp(attrs.mtime, tz=UTC).isoformat()
                if attrs.mtime is not None
                else ""
            ),
        )

    async def read_text(self, path: str) -> str:
        safe_path = validate_path(path)
        data = await self.read_bytes(safe_path)
        return data.decode("utf-8", errors="replace")

    async def write_text(self, path: str, content: str) -> None:
        safe_path = validate_path(path)
        async with self.sftp.open(safe_path, "w") as f:  # pyright: ignore[reportUnknownMemberType]
            await f.write(content)  # pyright: ignore[reportUnknownMemberType]

    async def read_bytes(self, path: str) -> bytes:
        safe_path = validate_path(path)
        async with self.sftp.open(safe_path, "rb") as f:  # pyright: ignore[reportUnknownMemberType]
            data: bytes = await f.read()  # pyright: ignore[reportUnknownMemberType]
            return data

    async def upload(self, remote_path: str, data: bytes) -> None:
        safe_path = validate_path(remote_path)
        async with self.sftp.open(safe_path, "wb") as f:  # pyright: ignore[reportUnknownMemberType]
            await f.write(data)  # pyright: ignore[reportUnknownMemberType]

    async def mkdir(self, path: str) -> None:
        safe_path = validate_path(path)
        await self.sftp.mkdir(safe_path)

    async def rename(self, old_path: str, new_path: str) -> None:
        safe_old = validate_path(old_path)
        safe_new = validate_path(new_path)
        await self.sftp.rename(safe_old, safe_new)

    async def delete(self, path: str) -> None:
        safe_path = validate_path(path)
        attrs = await self.sftp.stat(safe_path)
        if attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY:
            await self._rmdir_recursive(safe_path)
        else:
            await self.sftp.remove(safe_path)

    async def _rmdir_recursive(self, path: str) -> None:
        items = await self.sftp.readdir(path)
        for item in items:
            name = _to_str(item.filename)
            if name in (".", ".."):
                continue
            child = posixpath.join(path, name)
            if item.attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY:
                await self._rmdir_recursive(child)
            else:
                await self.sftp.remove(child)
        await self.sftp.rmdir(path)

    async def chmod(self, path: str, mode: int) -> None:
        safe_path = validate_path(path)
        await self.sftp.chmod(safe_path, mode)

    async def read_directory_as_zip(self, path: str) -> bytes:
        """Recursively read a directory and return its contents as a ZIP archive."""
        safe_path = validate_path(path)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            await self._add_to_zip(zf, safe_path, base_path=safe_path)
        return buffer.getvalue()

    async def _add_to_zip(
        self, zf: zipfile.ZipFile, path: str, base_path: str
    ) -> None:
        items = await self.sftp.readdir(path)
        for item in items:
            name = _to_str(item.filename)
            if name in (".", ".."):
                continue
            child = posixpath.join(path, name)
            rel_path = posixpath.relpath(child, base_path)
            if item.attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY:
                await self._add_to_zip(zf, child, base_path)
            else:
                try:
                    data = await self.read_bytes(child)
                    zf.writestr(rel_path, data)
                except Exception:
                    logger.warning("Skipping file in ZIP: %s", child)

    async def close(self) -> None:
        if self._sftp:
            self._sftp.exit()
            self._sftp = None


async def create_sftp_client(
    hostname: str,
    port: int,
    username: str,
    password: str | None = None,
    private_key: str | None = None,
) -> tuple[asyncssh.SSHClientConnection, SFTPClient]:
    kwargs: dict[str, Any] = {
        "host": hostname,
        "port": port,
        "username": username,
        "known_hosts": None,
    }
    if private_key:
        kwargs["client_keys"] = [asyncssh.import_private_key(private_key)]
    elif password:
        kwargs["password"] = password

    conn = await asyncssh.connect(**kwargs)
    client = SFTPClient(conn)
    await client.connect()
    return conn, client
