"""Read-only tools that need no shell.

Plenty of hosts expose SFTP and nothing else — restricted accounts, managed hosting,
appliances. You can still learn a great deal from them: which logs are growing, what
the distribution is, what a config actually says, when a file last changed. These
tools give the agent that, using only SFTP operations.

Same contract as the shell set: the model picks a name and fills typed arguments,
which are validated here. It never supplies a path fragment that is interpolated
anywhere — every path goes through the SFTP layer's own `validate_path`.
"""

from __future__ import annotations

import posixpath
import re
from typing import Any

from webgate.files.sftp_service import SFTPClient

MAX_READ_BYTES = 512 * 1024  # a log file can be enormous; read a window, not the file
_PATH = re.compile(r"^[A-Za-z0-9._/@+ -]{1,256}$")

# Where a diagnosis usually starts on a Linux host, when the model has no better idea.
COMMON_PATHS = ("/var/log", "/etc", "/tmp", "/home")


class SftpToolError(ValueError):
    """The model asked for something the tool set will not do."""


def _check_path(raw: Any, *, required: bool = True) -> str:
    path = str(raw or "").strip()
    if not path:
        if required:
            raise SftpToolError("A path is required.")
        return ""
    if not _PATH.match(path):
        raise SftpToolError(f"{path!r} is not a plain path.")
    return path


def _clamp(raw: Any, default: int, high: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, high))


def _fmt_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "K", "M", "G", "T"):
        if value < 1024 or unit == "T":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}T"


def _row(entry: Any) -> str:
    kind = "d" if entry.is_dir else "-"
    when = (entry.modified or "")[:19].replace("T", " ")
    return (
        f"{kind} {entry.permissions:<11} {_fmt_size(entry.size):>8} "
        f"{when:<19} {entry.owner:<10} {entry.name}"
    )


async def _list_directory(client: SFTPClient, args: dict[str, Any]) -> str:
    path = _check_path(args.get("path"))
    entries = await client.ls(path)
    if not entries:
        return f"{path} is empty."
    head = f"{path} — {len(entries)} entries\n"
    return head + "\n".join(_row(e) for e in entries[:200])


async def _file_info(client: SFTPClient, args: dict[str, Any]) -> str:
    path = _check_path(args.get("path"))
    entry = await client.stat(path)
    return (
        f"{entry.path}\n"
        f"  type: {'directory' if entry.is_dir else 'file'}\n"
        f"  size: {entry.size} bytes ({_fmt_size(entry.size)})\n"
        f"  permissions: {entry.permissions}\n"
        f"  owner: {entry.owner}  group: {entry.group}\n"
        f"  modified: {entry.modified}"
    )


async def _read_tail(client: SFTPClient, args: dict[str, Any]) -> str:
    """The end of a text file, which is where a log's useful part lives."""
    path = _check_path(args.get("path"))
    limit = _clamp(args.get("limit"), 40, 200)
    entry = await client.stat(path)
    if entry.is_dir:
        raise SftpToolError(f"{path} is a directory.")

    data = await client.read_bytes(path)
    if len(data) > MAX_READ_BYTES:
        data = data[-MAX_READ_BYTES:]
        prefix = f"[showing the last {_fmt_size(MAX_READ_BYTES)} of {_fmt_size(entry.size)}]\n"
    else:
        prefix = ""
    lines = data.decode("utf-8", "replace").splitlines()
    return prefix + "\n".join(lines[-limit:])


async def _search_file(client: SFTPClient, args: dict[str, Any]) -> str:
    path = _check_path(args.get("path"))
    pattern = str(args.get("pattern") or "").strip()
    if not pattern or len(pattern) > 200:
        raise SftpToolError("The search pattern must be 1-200 characters.")
    limit = _clamp(args.get("limit"), 40, 200)

    data = await client.read_bytes(path)
    if len(data) > MAX_READ_BYTES:
        data = data[-MAX_READ_BYTES:]
    needle = pattern.lower()
    hits = [line for line in data.decode("utf-8", "replace").splitlines() if needle in line.lower()]
    if not hits:
        return f"No line in {path} contains {pattern!r}."
    return f"{len(hits)} matching lines in {path} (last {min(limit, len(hits))}):\n" + "\n".join(
        hits[-limit:]
    )


async def _largest_files(client: SFTPClient, args: dict[str, Any]) -> str:
    """Walk a directory tree and report the biggest files.

    Without `df` this is the best signal for a filling filesystem: what is growing.
    """
    root = _check_path(args.get("path"))
    limit = _clamp(args.get("limit"), 15, 50)

    found: list[tuple[int, str]] = []
    visited = 0
    queue = [root]
    while queue and visited < 400:
        current = queue.pop(0)
        visited += 1
        try:
            entries = await client.ls(current)
        except Exception:  # unreadable subtree is normal under restricted accounts
            continue
        for entry in entries:
            if entry.is_dir:
                if len(queue) < 400:
                    queue.append(posixpath.join(current, entry.name))
            else:
                found.append((entry.size, entry.path))
    if not found:
        return f"No readable files under {root}."
    found.sort(reverse=True)
    total = sum(size for size, _ in found)
    body = "\n".join(f"{_fmt_size(size):>8}  {path}" for size, path in found[:limit])
    return f"{len(found)} files under {root}, {_fmt_size(total)} total. Largest:\n{body}"


async def _find_recent(client: SFTPClient, args: dict[str, Any]) -> str:
    """Most recently modified files — what changed just before things broke."""
    root = _check_path(args.get("path"))
    limit = _clamp(args.get("limit"), 15, 50)
    try:
        entries = await client.ls(root)
    except Exception as exc:
        raise SftpToolError(f"Cannot list {root}: {exc}") from exc
    files = [e for e in entries if not e.is_dir and e.modified]
    if not files:
        return f"No readable files with timestamps in {root}."
    files.sort(key=lambda e: e.modified, reverse=True)
    body = "\n".join(
        f"{(e.modified or '')[:19].replace('T', ' '):<19} {_fmt_size(e.size):>8}  {e.name}"
        for e in files[:limit]
    )
    return f"Most recently modified in {root}:\n{body}"


async def _system_identity(client: SFTPClient, args: dict[str, Any]) -> str:
    """What this host is, read from the files that say so."""
    del args
    out: list[str] = []
    for path in ("/etc/os-release", "/etc/hostname"):
        try:
            text = (await client.read_bytes(path)).decode("utf-8", "replace")
            out.append(f"--- {path} ---\n{text.strip()[:800]}")
        except Exception:
            out.append(f"--- {path} --- (not readable)")
    return "\n".join(out)


SFTP_TOOLS: dict[str, dict[str, Any]] = {
    "list_directory": {
        "handler": _list_directory,
        "description": (
            "List a directory: names, sizes, permissions, owners and modification times. "
            f"Useful starting points on a Linux host: {', '.join(COMMON_PATHS)}."
        ),
        "args": {"path": {"type": "string", "description": "Directory to list"}},
        "required": ["path"],
    },
    "file_info": {
        "handler": _file_info,
        "description": "Size, permissions, owner and modification time of one path.",
        "args": {"path": {"type": "string", "description": "File or directory"}},
        "required": ["path"],
    },
    "read_tail": {
        "handler": _read_tail,
        "description": "The last lines of a text file. Use for logs and config files.",
        "args": {
            "path": {"type": "string", "description": "File to read"},
            "limit": {"type": "integer", "description": "How many lines (1-200)"},
        },
        "required": ["path"],
    },
    "search_file": {
        "handler": _search_file,
        "description": "Case-insensitive literal search inside a text file. Not a regex.",
        "args": {
            "path": {"type": "string", "description": "File to search"},
            "pattern": {"type": "string", "description": "Literal text to look for"},
            "limit": {"type": "integer", "description": "How many matches (1-200)"},
        },
        "required": ["path", "pattern"],
    },
    "largest_files": {
        "handler": _largest_files,
        "description": (
            "Walk a directory tree and report the biggest files. Without disk usage "
            "commands this is the best signal for a filesystem that is filling up."
        ),
        "args": {
            "path": {"type": "string", "description": "Directory to walk, e.g. /var/log"},
            "limit": {"type": "integer", "description": "How many entries (1-50)"},
        },
        "required": ["path"],
    },
    "find_recent": {
        "handler": _find_recent,
        "description": "Most recently modified files in a directory — what changed lately.",
        "args": {
            "path": {"type": "string", "description": "Directory to inspect"},
            "limit": {"type": "integer", "description": "How many entries (1-50)"},
        },
        "required": ["path"],
    },
    "system_identity": {
        "handler": _system_identity,
        "description": "Distribution and hostname, read from /etc/os-release and /etc/hostname.",
        "args": {},
        "required": [],
    },
}


def sftp_tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": {
                    "type": "object",
                    "properties": {
                        key: {"type": a["type"], "description": a["description"]}
                        for key, a in spec["args"].items()
                    },
                    "required": list(spec["required"]),
                    "additionalProperties": False,
                },
            },
        }
        for name, spec in SFTP_TOOLS.items()
    ]


def describe(name: str, arguments: dict[str, Any]) -> str:
    """A short label for the audit log and the UI, in place of a command line."""
    parts = [f"{k}={v!r}" for k, v in (arguments or {}).items() if v not in (None, "")]
    return f"sftp:{name}({', '.join(parts)})"


async def run_sftp_tool(client: SFTPClient, name: str, arguments: dict[str, Any]) -> str:
    spec = SFTP_TOOLS.get(name)
    if spec is None:
        raise SftpToolError(f"{name!r} is not an available tool.")
    for key in spec["required"]:
        if not str((arguments or {}).get(key, "")).strip():
            raise SftpToolError(f"{name} needs {key!r}.")
    return await spec["handler"](client, arguments or {})
