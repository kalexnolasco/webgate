"""Short-lived cache for tool output.

Caching a diagnosis is not like caching a web page. `df` from ten minutes ago on a
filesystem that just filled produces a confident, wrong answer — worse than no answer
at all. So two rules hold here:

* **The TTL is short**, and it is the operator's setting, not a constant.
* **Age travels with the value.** Every cached result is handed to the model with how
  old it is, and the UI shows the same, so stale data can never pass as fresh.

The cache lives in the process. A different worker simply re-runs the command, which
is correct behaviour rather than a miss to engineer around.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

MAX_ENTRIES = 512


@dataclass
class _Entry:
    value: str
    stored_at: float


@dataclass
class ToolCache:
    ttl_seconds: int = 60
    _entries: dict[tuple[int, str], _Entry] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def get(self, server_id: int, key: str) -> tuple[str, int] | None:
        """Return the cached value and its age in seconds, or None."""
        if self.ttl_seconds <= 0:
            return None
        with self._lock:
            entry = self._entries.get((server_id, key))
            if entry is None:
                return None
            age = time.monotonic() - entry.stored_at
            if age > self.ttl_seconds:
                del self._entries[(server_id, key)]
                return None
            return entry.value, int(age)

    def put(self, server_id: int, key: str, value: str) -> None:
        if self.ttl_seconds <= 0:
            return
        with self._lock:
            if len(self._entries) >= MAX_ENTRIES:
                # Drop the oldest rather than grow without bound; this is a cache,
                # not a store, and a wrong eviction only costs one re-run.
                oldest = min(self._entries, key=lambda k: self._entries[k].stored_at)
                del self._entries[oldest]
            self._entries[(server_id, key)] = _Entry(value=value, stored_at=time.monotonic())

    def invalidate(self, server_id: int) -> None:
        with self._lock:
            for key in [k for k in self._entries if k[0] == server_id]:
                del self._entries[key]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def annotate(value: str, age_seconds: int) -> str:
    """Mark a reused result so the model cannot mistake it for a fresh reading."""
    return f"[cached {age_seconds}s ago — re-run if you need a current value]\n{value}"


tool_cache = ToolCache()
