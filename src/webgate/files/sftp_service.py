from __future__ import annotations

import io
import logging
import posixpath
import stat
import zipfile
from datetime import UTC, datetime
from typing import Any

import asyncssh

from webgate.files.limits import Budget, TooLarge
from webgate.files.models import FileEntry
from webgate.servers.hostkeys import known_hosts_for

logger = logging.getLogger(__name__)

READ_CHUNK = 256 * 1024  # bytes pulled per round trip when a budget applies


_ID_FILE_LIMIT = 512 * 1024  # generous for /etc/passwd on a large directory host


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
        # uid/gid -> name, resolved once per connection. The protocol only gives us
        # numeric ids, and nobody reads a directory listing by uid.
        self._users: dict[int, str] | None = None
        self._groups: dict[int, str] | None = None

    async def connect(self) -> None:
        self._sftp = await self._conn.start_sftp_client()

    @property
    def conn(self) -> asyncssh.SSHClientConnection:
        """The underlying connection, so a caller can pin the key it presented."""
        return self._conn

    @property
    def sftp(self) -> asyncssh.SFTPClient:
        if self._sftp is None:
            raise RuntimeError("SFTP client not connected")
        return self._sftp

    async def _load_id_maps(self) -> None:
        """Best-effort uid/gid name lookup from the remote passwd and group files.

        Hosts that lack or hide these (LDAP-only directories, minimal containers)
        simply keep numeric ids; this never fails a listing.
        """
        if self._users is not None:
            return
        self._users, self._groups = {}, {}
        for remote, target in (("/etc/passwd", self._users), ("/etc/group", self._groups)):
            try:
                async with self.sftp.open(remote, "rb") as fh:
                    raw = await fh.read(_ID_FILE_LIMIT)
                text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
                for line in text.splitlines():
                    parts = line.split(":")
                    if len(parts) > 2 and parts[2].isdigit():
                        target[int(parts[2])] = parts[0]
            except Exception:
                logger.debug("Could not read %s for id names", remote)

    @staticmethod
    def _name_for(raw_id: int | None, table: dict[int, str] | None) -> str:
        if raw_id is None:
            return ""
        return (table or {}).get(raw_id) or str(raw_id)

    async def ls(self, path: str) -> list[FileEntry]:
        safe_path = validate_path(path)
        await self._load_id_maps()
        entries: list[FileEntry] = []
        items = await self.sftp.readdir(safe_path)
        for item in items:
            name = _to_str(item.filename)
            if name in (".", ".."):
                continue
            attrs = item.attrs
            is_dir = bool(attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY) if attrs.type else False
            size = attrs.size or 0
            perms = (
                stat.filemode(attrs.permissions) if attrs.permissions is not None else "----------"
            )
            owner = self._name_for(attrs.uid, self._users)
            group = self._name_for(attrs.gid, self._groups)
            mtime = (
                datetime.fromtimestamp(attrs.mtime, tz=UTC).isoformat()
                if attrs.mtime is not None
                else ""
            )
            entries.append(
                FileEntry(
                    name=name,
                    path=posixpath.join(safe_path, name),
                    is_dir=is_dir,
                    size=size,
                    permissions=perms,
                    owner=owner,
                    group=group,
                    modified=mtime,
                )
            )
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    async def stat(self, path: str) -> FileEntry:
        safe_path = validate_path(path)
        attrs = await self.sftp.stat(safe_path)
        is_dir = bool(attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY) if attrs.type else False
        perms = stat.filemode(attrs.permissions) if attrs.permissions is not None else "----------"
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

    async def read_bytes(self, path: str, budget: Budget | None = None) -> bytes:
        """Read a file, refusing to accumulate more than `budget` allows.

        Chunked rather than one `read()`: with no budget the whole file lands in the
        gateway's memory regardless of size, which is how a single large log could
        take a worker down.
        """
        safe_path = validate_path(path)
        async with self.sftp.open(safe_path, "rb") as f:  # pyright: ignore[reportUnknownMemberType]
            if budget is None or budget.unlimited:
                data: bytes = await f.read()  # pyright: ignore[reportUnknownMemberType]
                return data
            chunks: list[bytes] = []
            while True:
                chunk: bytes = await f.read(READ_CHUNK)  # pyright: ignore[reportUnknownMemberType]
                if not chunk:
                    break
                budget.spend(len(chunk), posixpath.basename(safe_path))
                chunks.append(chunk)
            return b"".join(chunks)

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

    async def read_directory_as_zip(self, path: str, budget: Budget | None = None) -> bytes:
        """Recursively read a directory and return its contents as a ZIP archive."""
        safe_path = validate_path(path)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            await self._add_to_zip(zf, safe_path, base_path=safe_path, budget=budget)
        return buffer.getvalue()

    async def read_paths_as_zip(
        self, paths: list[str], base_path: str, budget: Budget | None = None
    ) -> tuple[bytes, list[str]]:
        """Zip a caller-chosen set of files and directories.

        Archive names are relative to ``base_path``, so a selection made in one
        directory unpacks as that directory's contents rather than a deep tree.
        Returns the archive and the names that could not be read, so the caller can
        say so instead of handing back a quietly incomplete download.
        """
        safe_base = validate_path(base_path)
        skipped: list[str] = []
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for raw in paths:
                safe = validate_path(raw)
                name = safe.rsplit("/", 1)[-1] or safe
                try:
                    attrs = await self.sftp.stat(safe)
                except Exception:
                    logger.warning("Skipping missing path in ZIP: %s", safe)
                    skipped.append(name)
                    continue
                if attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY:
                    await self._add_to_zip(zf, safe, base_path=safe_base, budget=budget)
                else:
                    try:
                        rel = posixpath.relpath(safe, safe_base)
                        zf.writestr(rel, await self.read_bytes(safe, budget))
                    except TooLarge:
                        raise  # the archive is over budget; skipping would hide that
                    except Exception:
                        logger.warning("Skipping unreadable file in ZIP: %s", safe)
                        skipped.append(name)
        return buffer.getvalue(), skipped

    async def _add_to_zip(
        self, zf: zipfile.ZipFile, path: str, base_path: str, budget: Budget | None = None
    ) -> None:
        items = await self.sftp.readdir(path)
        for item in items:
            name = _to_str(item.filename)
            if name in (".", ".."):
                continue
            child = posixpath.join(path, name)
            rel_path = posixpath.relpath(child, base_path)
            if item.attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY:
                await self._add_to_zip(zf, child, base_path, budget)
            else:
                try:
                    data = await self.read_bytes(child, budget)
                    zf.writestr(rel_path, data)
                except TooLarge:
                    raise  # over budget: the caller must be told, not handed a partial zip
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
    host_key: str = "",
) -> tuple[asyncssh.SSHClientConnection, SFTPClient]:
    kwargs: dict[str, Any] = {
        "host": hostname,
        "port": port,
        "username": username,
        "known_hosts": known_hosts_for(host_key),
    }
    if private_key:
        kwargs["client_keys"] = [asyncssh.import_private_key(private_key)]
    elif password:
        kwargs["password"] = password

    conn = await asyncssh.connect(**kwargs)
    client = SFTPClient(conn)
    await client.connect()
    return conn, client
