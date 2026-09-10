"""A ceiling on how much of a transfer the gateway will hold in memory.

There was none. Downloads did `await f.read()` on the whole file, uploads read the
whole body, and a ZIP accumulated an entire directory tree in a BytesIO -- so one
person fetching a 2 GB log asked the gateway for 2 GB, and on a multi-instance
deployment that takes down the worker and everyone else's sessions with it.

`max_upload_size` was already a documented setting. It was read by nobody.
"""

from __future__ import annotations

UNITS = ("B", "KB", "MB", "GB", "TB")


def human(size: int) -> str:
    value = float(size)
    for unit in UNITS:
        if value < 1024 or unit == UNITS[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


class TooLarge(Exception):
    """A transfer that would exceed the limit. Raised before the bytes are read."""

    def __init__(self, limit: int, what: str = "This transfer") -> None:
        self.limit = limit
        super().__init__(
            f"{what} is larger than the {human(limit)} limit. An admin can change it "
            f"under Admin -> Settings -> Security."
        )


class Budget:
    """How many more bytes this one request may pull into memory.

    A budget is per request, not global: two people downloading at once each get
    their own, which is the same shape the limit had when it was only a setting.
    """

    def __init__(self, limit: int) -> None:
        self.limit = max(0, int(limit))
        self.spent = 0

    @property
    def unlimited(self) -> bool:
        return self.limit == 0

    @property
    def remaining(self) -> int:
        return 0 if self.unlimited else max(0, self.limit - self.spent)

    def check(self, size: int, what: str = "This transfer") -> None:
        """Refuse a known size up front, so nothing is read at all."""
        if not self.unlimited and size > self.remaining:
            raise TooLarge(self.limit, what)

    def spend(self, size: int, what: str = "This transfer") -> None:
        """Account for bytes already read, and stop the moment they run over."""
        self.spent += size
        if not self.unlimited and self.spent > self.limit:
            raise TooLarge(self.limit, what)


def budget() -> Budget:
    """The current limit, read at the point of use so a panel change takes effect."""
    from webgate.runtime_config import store as runtime

    return Budget(int(runtime.get("max_upload_size")))
