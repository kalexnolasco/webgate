"""asciinema cast v2 writer.

The cast format is JSON Lines:
- First line: header object {"version": 2, "width": N, "height": N, "timestamp": <unix>}
- Each subsequent line: [time_offset_seconds, "o" | "i", "data"]

Reference: https://github.com/asciinema/asciinema/blob/develop/doc/asciicast-v2.md
"""

from __future__ import annotations

import contextlib
import gzip
import json
import logging
import time
from pathlib import Path
from typing import IO

logger = logging.getLogger(__name__)


class CastRecorder:
    def __init__(self, path: Path, cols: int, rows: int, max_bytes: int = 0) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.truncated = False
        self._written = 0
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
            line = json.dumps([round(offset, 6), "o", data]) + "\n"
            if self.max_bytes and self._written + len(line) > self.max_bytes:
                # Stop rather than let one session fill the disk, and say so inside
                # the cast itself: a replay that just ends looks like a crash.
                if not self.truncated:
                    self.truncated = True
                    note = "\r\n\x1b[33m*** recording stopped: size limit reached ***\x1b[0m\r\n"
                    fh.write(json.dumps([round(offset, 6), "o", note]) + "\n")
                    fh.flush()
                return
            fh.write(line)
            self._written += len(line)
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

    def take(self) -> bytes:
        """The finished cast, gzipped, with the local file removed.

        A live session is worker-local -- the PTY is on this worker, so writing here
        is right. The finished artefact is not: any worker may be asked to replay it,
        and a replaced container must not take the evidence with it.
        """
        try:
            raw = self.path.read_bytes()
        except OSError as e:
            logger.warning("Could not read cast %s: %s", self.path, e)
            return b""
        with contextlib.suppress(OSError):
            self.path.unlink()
        return gzip.compress(raw, compresslevel=6)


def unpack(blob: bytes | None) -> bytes:
    """The raw cast from what `take()` stored."""
    if not blob:
        return b""
    try:
        return gzip.decompress(blob)
    except (OSError, gzip.BadGzipFile):
        # Written before compression, or by something else. Serve it as it is.
        return blob
