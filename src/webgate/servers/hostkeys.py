"""Host key verification, trust-on-first-use.

Without this a gateway hands stored fleet credentials to whatever answers on the
target's address. Anyone able to sit in the middle — a poisoned internal DNS record,
ARP spoofing, a compromised switch — collects them, and the gateway is exactly where
every credential lives.

The model is the one every SSH user already knows:

* **First contact** records the key the host presented. Credentials are exposed on
  that first connection, as they are with any TOFU scheme; what it buys is that every
  connection afterwards is checked.
* **Afterwards** a different key is refused before authentication runs, so nothing is
  sent to the impostor. asyncssh does that check itself, given the key.
* **A legitimate change** — a rebuilt host, a rotated key — is an admin decision, made
  by clearing the pin so the next connection re-learns it.

Keys are matched by identity list rather than by hostname pattern: the server row is
already known, so `[host]:port` matching would add a way to get it subtly wrong.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncssh

from webgate.config import settings

logger = logging.getLogger(__name__)


class HostKeyMismatch(Exception):
    """The host presented a key that is not the pinned one."""

    def __init__(self, server_name: str, expected: str, got: str) -> None:
        self.server_name = server_name
        self.expected = expected
        self.got = got
        super().__init__(
            f"The host key for {server_name} has changed. It was {expected}, it is now "
            f"{got}. This is what a machine-in-the-middle looks like; it is also what a "
            f"rebuilt host looks like. Nothing was sent. An admin can clear the pinned "
            f"key on the server to accept the new one."
        )


def fingerprint(key: Any) -> str:
    """SHA256 fingerprint, in the form ssh-keygen prints."""
    try:
        return key.get_fingerprint()
    except Exception:
        return "unknown"


def export_key(key: Any) -> str:
    """The public key in OpenSSH one-line form, which is what gets stored."""
    try:
        exported = key.export_public_key("openssh")
        text = exported.decode() if isinstance(exported, bytes) else str(exported)
        return text.strip()
    except Exception:
        return ""


def known_hosts_for(stored: str) -> Any:
    """The value to pass asyncssh as `known_hosts`.

    A tuple of key lists is matched without hostname patterns, which is right here:
    the caller already resolved which server this is. `None` means first contact.
    """
    if not settings.verify_host_keys:
        return None
    stored = (stored or "").strip()
    if not stored:
        return None
    try:
        return ([asyncssh.import_public_key(stored)], [], [])
    except Exception:
        logger.warning("Stored host key is unreadable; treating as first contact")
        return None


def learned_key(conn: Any) -> tuple[str, str]:
    """The key a connection actually presented, as (openssh_line, fingerprint)."""
    try:
        key = conn.get_server_host_key()
    except Exception:
        return "", ""
    if key is None:
        return "", ""
    return export_key(key), fingerprint(key)


def describe(stored: str) -> str:
    """A fingerprint for display, from a stored OpenSSH line."""
    if not stored:
        return ""
    try:
        return fingerprint(asyncssh.import_public_key(stored.strip()))
    except Exception:
        return "unreadable"


async def remember(session: Any, server: Any, conn: Any) -> str:
    """Pin the key a first connection presented, and return its fingerprint.

    Only ever fills a blank pin. Overwriting an existing one here would defeat the
    whole mechanism: a changed key must be an admin decision, not a side effect.
    """
    if not settings.verify_host_keys or (server.host_key or "").strip():
        return ""
    line, fp = learned_key(conn)
    if not line:
        return ""
    server.host_key = line
    await session.commit()
    logger.info("Pinned host key for %s: %s", server.name, fp)
    return fp


def translate(exc: Exception, server_name: str, stored: str) -> Exception:
    """Turn asyncssh's verification failure into something an operator can act on."""
    if isinstance(exc, asyncssh.HostKeyNotVerifiable):
        return HostKeyMismatch(server_name, describe(stored) or "unknown", "a different key")
    return exc
