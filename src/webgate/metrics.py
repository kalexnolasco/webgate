"""Prometheus metrics.

A self-hosted gateway that a company depends on has to be scrapeable, and nothing
here was. The monitor already probes every server on a timer and the session manager
already knows what is live; both only ever spoke to the browser.

Two things are worth saying about what this exposes, because getting them wrong makes
a dashboard that lies:

* **Session counts are per worker.** Sessions live in memory beside the PTY they
  belong to, so each instance reports its own. Sum them across instances.
* **Server status comes from the monitor, which runs on one instance.** A follower
  has no statuses to report and says so by omitting them -- `webgate_monitor_leader`
  tells a scraper which instance the fleet gauges are coming from, so summing across
  instances does not double-count.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from webgate import __version__
from webgate.auth.models import User
from webgate.servers.models import Server
from webgate.servers.monitor import server_monitor
from webgate.terminal.shared import manager

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _escape(value: str) -> str:
    """Label values are quoted, so a server called `web"01` must not end the string."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _line(name: str, value: object, **labels: str) -> str:
    if labels:
        rendered = ",".join(f'{k}="{_escape(v)}"' for k, v in labels.items())
        return f"{name}{{{rendered}}} {value}"
    return f"{name} {value}"


async def render(session: AsyncSession) -> str:
    """The whole exposition, as one Prometheus text-format document."""
    out: list[str] = []

    def metric(name: str, help_text: str, kind: str) -> None:
        out.append(f"# HELP {name} {help_text}")
        out.append(f"# TYPE {name} {kind}")

    metric("webgate_info", "Build information; the value is always 1.", "gauge")
    out.append(_line("webgate_info", 1, version=__version__, instance=server_monitor.instance_id))

    metric(
        "webgate_monitor_leader",
        "1 on the instance running the server monitor, 0 on the others. "
        "Only the leader reports the webgate_server_* gauges.",
        "gauge",
    )
    out.append(_line("webgate_monitor_leader", int(server_monitor.is_leader)))

    metric(
        "webgate_terminal_sessions",
        "Live SSH sessions held by THIS instance. Sum across instances for the fleet.",
        "gauge",
    )
    out.append(_line("webgate_terminal_sessions", manager.live_count()))

    servers = (await session.execute(select(Server))).scalars().all()
    metric("webgate_servers_total", "Servers in the registry.", "gauge")
    out.append(_line("webgate_servers_total", len(servers)))

    users = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    metric("webgate_users_total", "User accounts, enabled or not.", "gauge")
    out.append(_line("webgate_users_total", users))

    statuses = server_monitor.get_all_statuses()
    if statuses:
        metric(
            "webgate_server_up",
            "1 if the last check reached the server, 0 if it did not. "
            "Absent for a server the monitor has not reached yet.",
            "gauge",
        )
        for server in servers:
            status = statuses.get(server.id)
            if status is not None:
                out.append(_line("webgate_server_up", int(status.online), server=server.name))

        metric(
            "webgate_server_latency_seconds",
            "How long the last successful SSH connection took. Absent while offline.",
            "gauge",
        )
        for server in servers:
            status = statuses.get(server.id)
            if status is not None and status.latency_ms is not None:
                out.append(
                    _line(
                        "webgate_server_latency_seconds",
                        round(status.latency_ms / 1000, 4),
                        server=server.name,
                    )
                )

        metric("webgate_servers_online", "Servers the last sweep reached.", "gauge")
        out.append(_line("webgate_servers_online", sum(1 for s in statuses.values() if s.online)))
        metric("webgate_servers_offline", "Servers the last sweep could not reach.", "gauge")
        out.append(
            _line("webgate_servers_offline", sum(1 for s in statuses.values() if not s.online))
        )

    return "\n".join(out) + "\n"
