"""The GitHub release body comes from CHANGELOG.md.

A second, hand-written description of the same release is a second thing to keep
true, and it never is.
"""

import pytest

from scripts.release_notes import section

SAMPLE = """# Changelog

## v2.2.0 (2026-09-11) — stability pass

One real bug, one security default closed.

### Fixed

- Webhook deliveries could vanish.

---

## v2.1.2 (2026-09-11) — docs

Documentation only.
"""


def test_it_returns_one_version_and_stops_at_the_next():
    body = section("2.2.0", SAMPLE)
    assert "Webhook deliveries could vanish" in body
    assert "Documentation only" not in body


def test_the_heading_and_the_trailing_rule_are_not_part_of_the_notes():
    body = section("2.2.0", SAMPLE)
    assert not body.startswith("##")
    assert not body.rstrip().endswith("---")


def test_a_leading_v_is_accepted():
    assert section("v2.2.0", SAMPLE) == section("2.2.0", SAMPLE)


def test_the_last_entry_runs_to_the_end_of_the_file():
    assert "Documentation only" in section("2.1.2", SAMPLE)


def test_an_unknown_version_fails_loudly_rather_than_shipping_empty_notes():
    with pytest.raises(SystemExit):
        section("9.9.9", SAMPLE)


def test_the_real_changelog_has_notes_for_the_current_version():
    """The release workflow reads this file; a version with no entry stops the release."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    body = section(version, (root / "CHANGELOG.md").read_text(encoding="utf-8"))
    assert len(body) > 200, f"v{version} has a suspiciously thin changelog entry"


def test_the_version_is_the_same_everywhere():
    """webgate reported 0.1.0 from its own API for six releases because nothing
    compared the places a version is written down."""
    import re
    import tomllib
    from pathlib import Path

    import webgate

    root = Path(__file__).resolve().parents[1]
    file_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    pyproject_version = project["project"]["version"]

    assert file_version == pyproject_version, "VERSION and pyproject.toml disagree"
    assert webgate.__version__ == file_version, (
        f"the installed package reports {webgate.__version__}; reinstall, or they "
        f"have genuinely drifted"
    )
    assert re.fullmatch(r"\d+\.\d+\.\d+", file_version), "not a release version"
