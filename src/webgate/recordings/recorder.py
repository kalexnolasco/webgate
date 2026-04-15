"""asciinema cast v2 writer.

The cast format is JSON Lines:
- First line: header object {"version": 2, "width": N, "height": N, "timestamp": <unix>}
- Each subsequent line: [time_offset_seconds, "o" | "i", "data"]

Reference: https://github.com/asciinema/asciinema/blob/develop/doc/asciicast-v2.md
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from pathlib import Path
from typing import IO

logger = logging.getLogger(__name__)


class CastRecorder:
    def __init__(self, path: Path, cols: int, rows: int) -> None:
        self.path = path
        self._fh: IO[str] | None = None
        self._start = time.monotonic()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("w", encoding="utf-8", buffering=1)  # line-buffered
        header = {
            "version": 2,
            "width": cols,
            "height": rows,
            "timestamp": int(time.time()),
            "env": {"TERM": "xterm-256color", "SHELL": "/bin/bash"},
        }
        self._fh.write(json.dumps(header) + "\n")

    def write_output(self, data: str) -> None:
        fh = self._fh
        if fh is None or fh.closed:
            return
        try:
            offset = time.monotonic() - self._start
            fh.write(json.dumps([round(offset, 6), "o", data]) + "\n")
        except Exception as e:
            logger.warning("CastRecorder write failed for %s: %s", self.path, e)

    @property
    def duration(self) -> float:
        return time.monotonic() - self._start

    def close(self) -> int:
        """Close the recorder and return the final byte size."""
        fh = self._fh
        self._fh = None
        if fh is not None and not fh.closed:
            with contextlib.suppress(Exception):
                fh.flush()
                fh.close()
        try:
            return self.path.stat().st_size
        except OSError:
            return 0
