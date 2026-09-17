"""Fixtures for the browser tests.

These start a real webgate against a throwaway database and a real SSH/SFTP host, then
drive the actual UI. The unit suite can prove an endpoint writes an audit entry; only
this can prove that clicking **Delete** in the file browser ends up in the audit panel
with the file's name on it, which is the thing that was reported broken.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]
ADMIN_PASSWORD = "e2e-admin-password"
SHOTS = Path(os.environ.get("WEBGATE_E2E_SHOTS", REPO / "docs" / "screenshots" / "v2"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for(check: Any, what: str, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except Exception as exc:  # the server is still starting
            last = exc
        time.sleep(0.25)
    raise RuntimeError(f"{what} never came up: {last}")


@pytest.fixture(scope="session")
def lab(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    """A real SSH/SFTP host, with a few files to act on."""
    root = tmp_path_factory.mktemp("lab")
    files = root / "srv"
    files.mkdir()
    (files / "nginx.conf").write_text("worker_processes auto;\n")
    (files / "app.log").write_text("started\n")
    (files / "old-backup.tar.gz").write_text("not really a tarball\n")
    # One file per way the editor can work out what it is looking at.
    (files / "deploy.py").write_text("import sys\n\n\ndef main() -> int:\n    return 0\n")
    (files / "healthcheck").write_text("#!/bin/bash\nset -euo pipefail\necho ok\n")
    (files / "service.db").write_bytes(b"SQLite format 3\x00" + bytes(64))

    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "tests" / "e2e" / "sshlab.py"), str(port), str(root)],
        cwd=files,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    _wait_for(
        lambda: socket.create_connection(("127.0.0.1", port), timeout=1) and True,
        f"ssh lab on {port}",
    )
    yield {"port": port, "root": root, "files": files}
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def lab2(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    """A second host, so copying a file between two of them can be tested at all."""
    root = tmp_path_factory.mktemp("lab2")
    files = root / "srv"
    files.mkdir()
    (files / "already-here.txt").write_text("the destination is not empty\n")

    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "tests" / "e2e" / "sshlab.py"), str(port), str(root), "lab2"],
        cwd=files,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    _wait_for(
        lambda: socket.create_connection(("127.0.0.1", port), timeout=1) and True,
        f"second ssh lab on {port}",
    )
    yield {"port": port, "root": root, "files": files}
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def server(
    tmp_path_factory: pytest.TempPathFactory, lab: dict[str, Any], lab2: dict[str, Any]
) -> Iterator[str]:
    """webgate itself, on a throwaway database, seeded the way a small fleet looks."""
    data = tmp_path_factory.mktemp("webgate")
    port = _free_port()
    env = {
        **os.environ,
        "WEBGATE_DB_URL": f"sqlite+aiosqlite:///{data / 'e2e.db'}",
        "WEBGATE_HOST": "127.0.0.1",
        "WEBGATE_PORT": str(port),
        "WEBGATE_SECRET_KEY": "e2e-secret-key-not-a-real-one",
        "WEBGATE_RECORDINGS_DIR": str(data / "recordings"),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "webgate"],
        cwd=REPO,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    _wait_for(lambda: httpx.get(f"{base}/api/health", timeout=2).status_code == 200, base)

    _seed(base, lab, lab2)
    yield base
    proc.terminate()
    proc.wait(timeout=10)


def _seed(base: str, lab: dict[str, Any], lab2: dict[str, Any]) -> None:
    """A fleet worth looking at: the lab host plus a few that are plainly offline."""
    with httpx.Client(base_url=base, timeout=20) as http:
        token = http.post(
            "/api/auth/login", json={"username": "admin", "password": "admin"}
        ).json()["access_token"]
        head = {"Authorization": f"Bearer {token}"}
        http.post("/api/auth/change-password", headers=head, json={"new_password": ADMIN_PASSWORD})
        token = http.post(
            "/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
        ).json()["access_token"]
        head = {"Authorization": f"Bearer {token}"}

        http.post(
            "/api/servers",
            headers=head,
            json={
                "name": "prod-web-01",
                "hostname": "127.0.0.1",
                "port": lab["port"],
                "username": "demo",
                "auth_method": "password",
                "password": "demo",
                "group": "prod",
                "tags": ["web", "nginx"],
                "description": "Front-end, behind the bastion",
            },
        )
        # A second reachable host, so a file can actually be copied between two.
        http.post(
            "/api/servers",
            headers=head,
            json={
                "name": "prod-web-02",
                "hostname": "127.0.0.1",
                "port": lab2["port"],
                "username": "demo",
                "auth_method": "password",
                "password": "demo",
                "group": "prod",
                "tags": ["web", "nginx"],
                "description": "The other front-end",
            },
        )
        for name, host, group, tags in [
            ("prod-db-primary", "198.51.100.31", "prod", ["db", "postgres"]),
            ("prod-cache-01", "198.51.100.41", "prod", ["cache"]),
            ("staging-app-01", "198.51.100.11", "staging", ["app"]),
            ("core-logs", "198.51.100.52", "core", ["logging"]),
            ("edge-cdn-lhr", "203.0.113.10", "edge", ["cdn"]),
        ]:
            http.post(
                "/api/servers",
                headers=head,
                json={
                    "name": name,
                    "hostname": host,
                    "port": 22,
                    "username": "ops",
                    "auth_method": "password",
                    "password": "not-a-real-password",
                    "group": group,
                    "tags": tags,
                },
            )
        for name, command, shared, confirm in [
            ("Disk usage", "df -h", True, False),
            ("Failed units", "systemctl --failed --no-pager", True, False),
            ("Tail log", "tail -n {lines} {file}", True, False),
            ("Restart nginx", "systemctl restart nginx", True, True),
        ]:
            http.post(
                "/api/snippets",
                headers=head,
                json={"name": name, "command": command, "shared": shared, "confirm": confirm},
            )
        people = [("alice", ["prod"]), ("bob", ["staging"]), ("carol", ["prod", "core"])]
        for user, groups in people:
            http.post(
                "/api/auth/users",
                headers=head,
                json={"username": user, "password": "example-pass-123", "allowed_groups": groups},
            )


@pytest.fixture(scope="session")
def browser() -> Iterator[Any]:
    playwright = pytest.importorskip("playwright.sync_api", reason="playwright is not installed")
    # WEBGATE_E2E_HEADED=1 opens a real window. Headless Chromium draws overlay
    # scrollbars, which take no layout space, so anything that measures one has to
    # be run this way to see anything at all.
    headless = os.environ.get("WEBGATE_E2E_HEADED", "") not in ("1", "true", "yes")
    with playwright.sync_playwright() as p:
        instance = p.chromium.launch(headless=headless)
        yield instance
        instance.close()


@pytest.fixture(scope="session")
def admin_token(server: str) -> str:
    """A token for the API tests, which do not need a browser."""
    return str(
        httpx.post(
            f"{server}/api/auth/login",
            json={"username": "admin", "password": ADMIN_PASSWORD},
            timeout=20,
        ).json()["access_token"]
    )


@pytest.fixture(scope="session")
def signed_in_state(browser: Any, server: str, tmp_path_factory: pytest.TempPathFactory) -> str:
    """Sign in once and keep the session for every test.

    Signing in per test trips webgate's own rate limit -- ten attempts a minute from
    one address -- and the suite then fails on the login screen with nothing to say
    about the feature under test. Reusing the token is also what a person does.
    """
    context = browser.new_context()
    page = context.new_page()
    page.goto(server, wait_until="networkidle")
    page.fill("#login-user", "admin")
    page.fill("#login-pass", ADMIN_PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_selector(".fz-serverlist", timeout=20_000)
    path = tmp_path_factory.mktemp("state") / "auth.json"
    context.storage_state(path=str(path))
    context.close()
    return str(path)


@pytest.fixture
def page(browser: Any, server: str, signed_in_state: str) -> Iterator[Any]:
    """A signed-in page, sized so a screenshot of it is worth putting in the docs."""
    context = browser.new_context(
        viewport={"width": 1600, "height": 1000}, storage_state=signed_in_state
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    page.goto(server, wait_until="networkidle")
    page.wait_for_selector(".fz-serverlist", timeout=20_000)

    yield page

    # A page that threw while we were clicking around is a failure even if every
    # assertion passed -- the UI has no build step and no type checker behind it.
    assert not errors, f"the page raised: {errors}"
    context.close()


@pytest.fixture
def shot(page: Any) -> Any:
    """Save a screenshot into the docs, so they show the build the tests just drove."""

    def take(name: str, **kw: Any) -> Path:
        SHOTS.mkdir(parents=True, exist_ok=True)
        target = SHOTS / f"{name}.png"
        page.screenshot(path=str(target), **kw)
        return target

    return take


HERE = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark only what lives here.

    A conftest hook is handed the whole session's items, not just the ones under its
    own directory -- marking them all made `-m "not e2e"` deselect the entire suite.
    """
    for item in items:
        if HERE in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.e2e)


def pytest_sessionstart(session: pytest.Session) -> None:
    if not shutil.which("bash"):  # pragma: no cover
        pytest.skip("the lab needs bash", allow_module_level=True)
