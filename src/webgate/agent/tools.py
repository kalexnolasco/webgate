"""The agent's command surface.

The model never supplies a command line. It picks a name from `READ_ONLY_COMMANDS`
and fills in typed arguments, which are validated here and then substituted with
`shlex.quote`. That inversion is the whole safety story: a model that hallucinates,
is prompt-injected by the contents of a log file, or is simply wrong can only ever
cause one of these commands to run with quoted arguments.

Every command below reads. None writes, restarts, kills, or installs.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Any

# Argument shapes. Deliberately narrow — a path is a path, not a shell fragment.
_PATH = re.compile(r"^[A-Za-z0-9._/@+-]{1,256}$")
_UNIT = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")
_WORD = re.compile(r"^[A-Za-z0-9._/@:+-]{1,128}$")


@dataclass(frozen=True)
class Command:
    name: str
    description: str
    template: str
    args: dict[str, dict[str, Any]] = field(default_factory=dict)
    required: tuple[str, ...] = ()


READ_ONLY_COMMANDS: dict[str, Command] = {
    c.name: c
    for c in [
        Command(
            name="disk_usage",
            description="Filesystem usage, human readable. Start here for 'disk full' symptoms.",
            template="df -hP",
        ),
        Command(
            name="largest_files",
            description="The biggest files under a directory. Use when a filesystem is full.",
            template="du -xah {path} 2>/dev/null | sort -rh | head -n {limit}",
            args={
                "path": {"type": "string", "description": "Directory to scan, e.g. /var/log"},
                "limit": {"type": "integer", "description": "How many entries (1-50)"},
            },
            required=("path",),
        ),
        Command(
            name="memory",
            description="Memory and swap usage.",
            template="free -h",
        ),
        Command(
            name="load_and_processes",
            description="Load average and the top processes by CPU and memory.",
            template=(
                "uptime; echo '---'; "
                "ps -eo pid,user,pcpu,pmem,etime,cmd --sort=-pcpu | head -n 15"
            ),
        ),
        Command(
            name="service_status",
            description="Status of one systemd unit, including its recent log lines.",
            template="systemctl status {unit} --no-pager --lines=20",
            args={"unit": {"type": "string", "description": "Unit name, e.g. nginx"}},
            required=("unit",),
        ),
        Command(
            name="failed_services",
            description="Every systemd unit currently in a failed state.",
            template="systemctl list-units --state=failed --no-pager --no-legend",
        ),
        Command(
            name="journal",
            description="Recent journal entries, optionally for one unit and priority.",
            template="journalctl --no-pager -n {limit} {unit_flag} {priority_flag}",
            args={
                "unit": {"type": "string", "description": "Optional unit to filter by"},
                "priority": {
                    "type": "string",
                    "description": "Optional max priority: err, warning, info",
                },
                "limit": {"type": "integer", "description": "How many lines (1-200)"},
            },
        ),
        Command(
            name="listening_ports",
            description="Listening TCP/UDP sockets and the processes behind them.",
            template="ss -tulpn 2>/dev/null || netstat -tulpn 2>/dev/null",
        ),
        Command(
            name="tail_file",
            description="Last lines of a text file. Use for application logs.",
            template="tail -n {limit} -- {path}",
            args={
                "path": {"type": "string", "description": "File to read, e.g. /var/log/syslog"},
                "limit": {"type": "integer", "description": "How many lines (1-200)"},
            },
            required=("path",),
        ),
        Command(
            name="search_file",
            description="Case-insensitive fixed-string search in a file. Not a regex.",
            template="grep -iF -- {pattern} {path} | tail -n {limit}",
            args={
                "path": {"type": "string", "description": "File to search"},
                "pattern": {"type": "string", "description": "Literal text to look for"},
                "limit": {"type": "integer", "description": "How many matches (1-200)"},
            },
            required=("path", "pattern"),
        ),
        Command(
            name="list_directory",
            description="Long listing of a directory.",
            template="ls -lAh -- {path}",
            args={"path": {"type": "string", "description": "Directory to list"}},
            required=("path",),
        ),
        Command(
            name="system_info",
            description="Kernel, distribution, uptime and hostname.",
            template="uname -a; echo '---'; cat /etc/os-release 2>/dev/null; echo '---'; uptime",
        ),
    ]
}


class ToolInputError(ValueError):
    """The model asked for something the allowlist will not build."""


def _clamp(raw: Any, default: int, high: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, high))


def build_command(name: str, arguments: dict[str, Any]) -> str:
    """Turn a validated tool call into a shell string, or refuse."""
    command = READ_ONLY_COMMANDS.get(name)
    if command is None:
        raise ToolInputError(f"{name!r} is not an available command.")

    arguments = arguments or {}
    for key in command.required:
        if not str(arguments.get(key, "")).strip():
            raise ToolInputError(f"{name} needs {key!r}.")

    values: dict[str, str] = {}

    if "path" in command.args:
        path = str(arguments.get("path", "")).strip()
        if path and not _PATH.match(path):
            raise ToolInputError(
                f"{path!r} is not a plain path. Shell metacharacters are not accepted."
            )
        values["path"] = shlex.quote(path) if path else ""

    if "unit" in command.args:
        unit = str(arguments.get("unit", "")).strip()
        if unit and not _UNIT.match(unit):
            raise ToolInputError(f"{unit!r} is not a valid unit name.")
        if name == "journal":
            values["unit_flag"] = f"-u {shlex.quote(unit)}" if unit else ""
        else:
            values["unit"] = shlex.quote(unit)

    if "priority" in command.args:
        priority = str(arguments.get("priority", "")).strip().lower()
        allowed = {"emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"}
        if priority and priority not in allowed:
            raise ToolInputError(f"{priority!r} is not a journal priority.")
        values["priority_flag"] = f"-p {priority}" if priority else ""

    if "pattern" in command.args:
        pattern = str(arguments.get("pattern", "")).strip()
        if not pattern or len(pattern) > 200:
            raise ToolInputError("The search pattern must be 1-200 characters.")
        values["pattern"] = shlex.quote(pattern)

    if "limit" in command.args:
        high = 50 if name == "largest_files" else 200
        values["limit"] = str(_clamp(arguments.get("limit"), 40, high))

    try:
        return command.template.format(**values)
    except KeyError as exc:  # a template referencing an argument we did not build
        raise ToolInputError(f"{name} is misconfigured: missing {exc}.") from exc


def _word_guard(value: str) -> bool:
    return bool(_WORD.match(value))


def tool_schemas() -> list[dict[str, Any]]:
    """The allowlist rendered as OpenAI-compatible function definitions."""
    schemas: list[dict[str, Any]] = []
    for command in READ_ONLY_COMMANDS.values():
        properties = {
            key: {"type": spec["type"], "description": spec["description"]}
            for key, spec in command.args.items()
        }
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": command.name,
                    "description": command.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": list(command.required),
                        "additionalProperties": False,
                    },
                },
            }
        )
    return schemas
