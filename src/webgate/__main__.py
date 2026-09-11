"""Server entry point.

The secret-key check lives here rather than in `create_app` because it is about
starting a server, not about constructing the application: importing the app to
generate an OpenAPI schema or run a test should not be gated on it.
"""

from __future__ import annotations

import ipaddress
import logging
import sys

import uvicorn

from webgate.config import settings

logger = logging.getLogger(__name__)

DEFAULT_SECRET = "change-me-in-production"

_MESSAGE = """
WEBGATE_SECRET_KEY is still the shipped default.

That key signs every session token and derives the Fernet key that encrypts every
stored SSH password and private key. Because it is published in this repository,
anyone can mint a valid admin token for this deployment and decrypt its credentials.

Set one before starting:

    export WEBGATE_SECRET_KEY=$(openssl rand -hex 32)

Changing it invalidates existing sessions and makes already-stored credentials
unreadable, so on an existing install export a backup first
(Admin -> Backup & restore), set the key, then restore.

To start anyway -- only sensible on a machine nobody else can reach:

    WEBGATE_ALLOW_INSECURE_SECRET=true
"""


def _is_loopback(host: str) -> bool:
    """Whether this bind address can only be reached from the machine itself."""
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_secret_key(
    secret: str, host: str, *, allow_insecure: bool = False
) -> str | None:
    """The reason to refuse to start, or None to go ahead.

    A default key on a loopback bind is someone trying webgate out, and warning is
    the right response. The same key on an address other machines can reach is a
    deployment handing out its own credentials, so that one stops.
    """
    if secret != DEFAULT_SECRET or allow_insecure:
        return None
    if _is_loopback(host):
        logger.warning(
            "WEBGATE_SECRET_KEY is the shipped default. Fine for a look around on "
            "localhost; set a real one before this is reachable from anywhere else."
        )
        return None
    return _MESSAGE


def main() -> None:
    refusal = check_secret_key(
        settings.secret_key,
        settings.host,
        allow_insecure=settings.allow_insecure_secret,
    )
    if refusal:
        print(refusal, file=sys.stderr)
        raise SystemExit(1)

    uvicorn.run(
        "webgate.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
