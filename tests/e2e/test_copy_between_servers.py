"""Copying a file from one host to another, through the gateway.

Until now the only way was to download it to your own machine and upload it again:
slower, and it puts production data on a laptop. The gateway is already connected to
both ends and already holds the credentials for both.

These run against two real SSH hosts, because that is the only way to prove the bytes
arrived and that both sides were checked.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

SOURCE = "prod-web-01"
TARGET = "prod-web-02"


def _api(server: str, token: str) -> httpx.Client:
    return httpx.Client(base_url=server, headers={"Authorization": f"Bearer {token}"}, timeout=30)


@pytest.fixture
def api(server: str, admin_token: str) -> Any:
    with _api(server, admin_token) as client:
        yield client


def _id_of(api: Any, name: str) -> int:
    servers = api.get("/api/servers").json()
    return next(s["id"] for s in servers if s["name"] == name)


def test_a_file_arrives_on_the_other_host(
    api: Any, lab: dict[str, Any], lab2: dict[str, Any]
) -> None:
    (lab["files"] / "ship-me.conf").write_text("upstream app { server 127.0.0.1; }\n")
    landed = lab2["files"] / "ship-me.conf"
    assert not landed.exists(), "the fixture is not clean before we start"

    resp = api.post(
        f"/api/files/{_id_of(api, SOURCE)}/copy-to",
        json={
            "source_path": str(lab["files"] / "ship-me.conf"),
            "target_server_id": _id_of(api, TARGET),
            "target_path": str(lab2["files"] / "ship-me.conf"),
        },
    )
    assert resp.status_code == 200, resp.text
    assert landed.read_text() == "upstream app { server 127.0.0.1; }\n"
    assert resp.json()["bytes"] == landed.stat().st_size
    assert resp.json()["server"] == TARGET


def test_a_directory_destination_keeps_the_filename(
    api: Any, lab: dict[str, Any], lab2: dict[str, Any]
) -> None:
    """`scp host:/f other:/dir/` puts it in the directory. So does this."""
    (lab["files"] / "keeps-its-name.txt").write_text("named\n")

    resp = api.post(
        f"/api/files/{_id_of(api, SOURCE)}/copy-to",
        json={
            "source_path": str(lab["files"] / "keeps-its-name.txt"),
            "target_server_id": _id_of(api, TARGET),
            "target_path": str(lab2["files"]),
        },
    )
    assert resp.status_code == 200, resp.text
    assert (lab2["files"] / "keeps-its-name.txt").read_text() == "named\n"


def test_a_directory_source_is_refused_with_something_useful_to_do(
    api: Any, lab: dict[str, Any]
) -> None:
    resp = api.post(
        f"/api/files/{_id_of(api, SOURCE)}/copy-to",
        json={
            "source_path": str(lab["files"]),
            "target_server_id": _id_of(api, TARGET),
            "target_path": "/tmp/whatever",
        },
    )
    assert resp.status_code == 400
    assert "ZIP" in resp.json()["detail"], "the refusal should say what to do instead"


def test_both_ends_end_up_in_the_audit_log(
    api: Any, lab: dict[str, Any], lab2: dict[str, Any]
) -> None:
    """An incident on either host has to find this in its own log."""
    (lab["files"] / "audited.txt").write_text("trace me\n")
    api.post(
        f"/api/files/{_id_of(api, SOURCE)}/copy-to",
        json={
            "source_path": str(lab["files"] / "audited.txt"),
            "target_server_id": _id_of(api, TARGET),
            "target_path": str(lab2["files"] / "audited.txt"),
        },
    )
    rows = api.get("/api/auth/audit", params={"search": "audited.txt", "limit": 50}).json()
    actions = {r["action"] for r in rows}
    assert "sftp_copy_out" in actions, "the source host has no record of the file leaving"
    assert "sftp_copy_in" in actions, "the destination has no record of it arriving"
    out = next(r for r in rows if r["action"] == "sftp_copy_out")
    assert TARGET in out["detail"], "the source entry does not say where it went"
