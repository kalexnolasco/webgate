"""webgate -- self-hosted SSH terminal and SFTP file browser."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version
from pathlib import Path


def _read_version() -> str:
    """The running version, from package metadata or the VERSION file.

    Metadata is authoritative for an install; the file is the fallback for a plain
    source checkout, where nothing is registered to read metadata from.
    """
    try:
        return _installed_version("webgate")
    except PackageNotFoundError:
        pass
    version_file = Path(__file__).resolve().parents[2] / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


__version__ = _read_version()

__all__ = ["__version__"]
