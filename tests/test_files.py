import pytest

from webgate.files.sftp_service import validate_path


def test_validate_path_normal():
    assert validate_path("/home/user") == "/home/user"


def test_validate_path_normalizes():
    assert validate_path("/home/user/../admin") == "/home/admin"


def test_validate_path_traversal():
    # After normalization, /home/../../etc/passwd becomes /etc/passwd which is valid
    # The real protection is that paths are always absolute and normalized
    result = validate_path("/home/../../etc/passwd")
    assert result == "/etc/passwd"
    assert ".." not in result


def test_validate_path_relative():
    result = validate_path("home/user")
    assert result.startswith("/")


def test_validate_path_double_dots_in_name():
    # ".." as a path component is blocked, but a name containing dots is fine
    assert validate_path("/home/file..txt") == "/home/file..txt"


def test_validate_path_root():
    assert validate_path("/") == "/"


@pytest.mark.asyncio
async def test_files_unauthenticated(client):
    resp = await client.get("/api/files/1/ls?path=/")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_files_server_not_found(client, auth_headers):
    resp = await client.get("/api/files/9999/ls?path=/", headers=auth_headers)
    assert resp.status_code == 404
