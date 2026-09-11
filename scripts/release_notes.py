"""Pull one version's section out of CHANGELOG.md.

Used by the release workflow so the GitHub release body is the changelog entry
rather than a second, drifting description of the same release.

    python scripts/release_notes.py 2.2.0
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


def section(version: str, text: str) -> str:
    """The body of the `## vX.Y.Z ...` heading, without the heading itself."""
    version = version.lstrip("v")
    pattern = rf"^## v{re.escape(version)}(?: .*)?$"
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(pattern, line)), None)
    if start is None:
        raise SystemExit(f"CHANGELOG.md has no section for v{version}")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    body = "\n".join(lines[start + 1 : end]).strip()
    # The file separates entries with a horizontal rule; it is not part of the notes.
    return re.sub(r"\n+---\s*$", "", body).strip()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: release_notes.py <version>")
    print(section(sys.argv[1], CHANGELOG.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
