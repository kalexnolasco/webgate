"""LDAP / Active Directory authentication.

Search-then-bind flow:
1. Bind to the directory as the service account (`ldap_bind_dn`)
2. Search under `ldap_user_base` with `ldap_user_filter` to resolve the user's DN
3. Re-bind as that DN with the user-supplied password to verify credentials
4. (Optional) Search under `ldap_group_base` with `ldap_group_filter` to list
   the user's group memberships -- used to compute admin status and the
   allowed-groups list via `ldap_group_map` and `ldap_admin_groups`.

All operations run in a worker thread (`asyncio.to_thread`) because `ldap3`
is sync-only.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from ldap3 import ALL, SIMPLE, SUBTREE, Connection, Server
from ldap3.core.exceptions import LDAPException

from webgate.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LdapResult:
    dn: str
    cn: str
    email: str
    member_of_cns: list[str]
    is_admin: bool
    allowed_groups: list[str]


def _server() -> Server:
    return Server(settings.ldap_url, get_info=ALL)


def _service_bind() -> Connection:
    conn = Connection(
        _server(),
        user=settings.ldap_bind_dn or None,
        password=settings.ldap_bind_password or None,
        authentication=SIMPLE if settings.ldap_bind_dn else None,
        auto_bind=True,
    )
    return conn


def _find_user_dn(conn: Connection, username: str) -> tuple[str, dict[str, object]] | None:
    """Resolve a username to (DN, attrs) under ldap_user_base."""
    flt = settings.ldap_user_filter.replace("{username}", _escape(username))
    conn.search(
        search_base=settings.ldap_user_base,
        search_filter=flt,
        search_scope=SUBTREE,
        attributes=["cn", "mail"],
    )
    if not conn.entries:
        return None
    entry = conn.entries[0]
    attrs: dict[str, object] = {
        "cn": str(entry.cn) if "cn" in entry else username,
        "mail": str(entry.mail) if "mail" in entry else "",
    }
    return str(entry.entry_dn), attrs


def _list_group_cns(conn: Connection, user_dn: str) -> list[str]:
    if not settings.ldap_group_base:
        return []
    flt = settings.ldap_group_filter.replace("{dn}", _escape(user_dn))
    conn.search(
        search_base=settings.ldap_group_base,
        search_filter=flt,
        search_scope=SUBTREE,
        attributes=["cn"],
    )
    return [str(e.cn) for e in conn.entries if "cn" in e]


def _escape(value: str) -> str:
    """Escape LDAP filter special characters (RFC 4515 section 3)."""
    return (
        value.replace("\\", "\\5c")
        .replace("*", "\\2a")
        .replace("(", "\\28")
        .replace(")", "\\29")
        .replace("\x00", "\\00")
    )


def _authenticate_sync(username: str, password: str) -> LdapResult | None:
    if not password:
        return None
    try:
        conn = _service_bind()
    except LDAPException as e:
        logger.warning("LDAP service bind failed: %s", e)
        return None
    try:
        found = _find_user_dn(conn, username)
    finally:
        conn.unbind()
    if not found:
        return None
    user_dn, attrs = found

    # Re-bind as the user with their password to verify credentials.
    try:
        user_conn = Connection(
            _server(), user=user_dn, password=password,
            authentication=SIMPLE, auto_bind=True,
        )
    except LDAPException:
        return None

    try:
        # Re-bind as service account to enumerate groups -- many directories
        # don't allow ordinary users to read the group tree.
        try:
            svc_conn = _service_bind()
            try:
                cns = _list_group_cns(svc_conn, user_dn)
            finally:
                svc_conn.unbind()
        except LDAPException:
            cns = []
    finally:
        user_conn.unbind()

    try:
        group_map: dict[str, str] = json.loads(settings.ldap_group_map or "{}")
    except json.JSONDecodeError:
        group_map = {}
    try:
        admin_groups: list[str] = json.loads(settings.ldap_admin_groups or "[]")
    except json.JSONDecodeError:
        admin_groups = []

    allowed_groups = sorted({group_map[c] for c in cns if c in group_map})
    is_admin = any(c in admin_groups for c in cns)

    return LdapResult(
        dn=user_dn,
        cn=str(attrs.get("cn") or username),
        email=str(attrs.get("mail") or ""),
        member_of_cns=cns,
        is_admin=is_admin,
        allowed_groups=allowed_groups,
    )


async def authenticate_ldap(username: str, password: str) -> LdapResult | None:
    """Async wrapper. Returns None on any failure (auth fail, network, etc.)."""
    if not settings.ldap_enabled or not settings.ldap_url:
        return None
    return await asyncio.to_thread(_authenticate_sync, username, password)
