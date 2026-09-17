"""Single sign-on over OpenID Connect.

LDAP already existed, but no company running Entra ID, Okta or Google Workspace is
going to keep a second directory for one tool. This is the authorization code flow
with PKCE, which every one of those providers speaks.

Two things shape the implementation:

* **The gateway may be several workers.** The state, nonce and PKCE verifier are
  written to the database, not held in memory, because the browser can come back to a
  different worker than the one it left. The same table carries the one-time code the
  callback hands the page, so the session token never appears in a URL, in browser
  history or in a proxy log.
* **An ID token is only worth what its verification is worth.** The signature is
  checked against the provider's published keys, and the issuer, audience, expiry and
  nonce are all checked too. A token that merely decodes proves nothing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from jose import jwt
from sqlalchemy import DateTime, String, Text, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from webgate.db.engine import Base
from webgate.runtime_config import store as runtime

logger = logging.getLogger(__name__)

# A sign-in that takes longer than this was abandoned, and the row is a stale secret.
FLOW_TTL = timedelta(minutes=10)
# The handover code is used within a second of being issued; a minute is generous.
CODE_TTL = timedelta(minutes=1)
DISCOVERY_TTL = 3600.0


class OidcError(Exception):
    """Something the operator or the provider has to fix, phrased for whoever sees it."""


class OidcFlow(Base):
    """One sign-in attempt, in progress.

    In the database rather than in memory so the callback can land on any worker,
    which is the whole point of the stateless design.
    """

    __tablename__ = "oidc_flows"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(64))
    verifier: Mapped[str] = mapped_column(String(128))
    redirect_uri: Mapped[str] = mapped_column(Text, default="")
    # Set once the provider has been believed: the page trades this for a session.
    handover: Mapped[str] = mapped_column(String(64), default="")
    user_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


_discovery: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks: dict[str, tuple[float, dict[str, Any]]] = {}


def enabled() -> bool:
    return bool(runtime.get("oidc_enabled") and runtime.get("oidc_issuer"))


def provider_name() -> str:
    """What the button on the sign-in screen should say."""
    return str(runtime.get("oidc_display_name") or "").strip() or "single sign-on"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


async def _fetch(url: str, cache: dict[str, tuple[float, dict[str, Any]]]) -> dict[str, Any]:
    hit = cache.get(url)
    if hit and time.monotonic() - hit[0] < DISCOVERY_TTL:
        return hit[1]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
    except Exception as exc:
        raise OidcError(f"Could not reach the identity provider at {url}: {exc}") from exc
    cache[url] = (time.monotonic(), data)
    return data


async def discover() -> dict[str, Any]:
    issuer = str(runtime.get("oidc_issuer")).rstrip("/")
    return await _fetch(f"{issuer}/.well-known/openid-configuration", _discovery)


async def begin(session: AsyncSession, redirect_uri: str) -> str:
    """Record a new sign-in attempt and return the URL to send the browser to."""
    if not enabled():
        raise OidcError("Single sign-on is not configured on this gateway")

    config = await discover()
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    flow = OidcFlow(
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(24),
        verifier=verifier,
        redirect_uri=redirect_uri,
    )
    session.add(flow)
    # Abandoned attempts are stale secrets; clear them out on the way past.
    await session.execute(
        delete(OidcFlow).where(OidcFlow.created_at < datetime.now(UTC) - FLOW_TTL)
    )
    await session.commit()

    query = {
        "response_type": "code",
        "client_id": str(runtime.get("oidc_client_id")),
        "redirect_uri": redirect_uri,
        "scope": str(runtime.get("oidc_scopes")) or "openid profile email",
        "state": flow.state,
        "nonce": flow.nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{config['authorization_endpoint']}?{urlencode(query)}"


async def _claims(code: str, flow: OidcFlow) -> dict[str, Any]:
    """Trade the code for an ID token, and believe it only once it checks out."""
    config = await discover()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": flow.redirect_uri,
        "client_id": str(runtime.get("oidc_client_id")),
        "code_verifier": flow.verifier,
    }
    secret = str(runtime.get("oidc_client_secret"))
    if secret:
        data["client_secret"] = secret

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(config["token_endpoint"], data=data)
    except Exception as exc:
        raise OidcError(f"Could not reach the provider's token endpoint: {exc}") from exc
    if resp.status_code >= 400:
        detail = resp.text[:200]
        raise OidcError(f"The provider rejected the sign-in ({resp.status_code}): {detail}")

    id_token = resp.json().get("id_token")
    if not id_token:
        raise OidcError("The provider returned no id_token; check that the scope includes openid")

    jwks = await _fetch(config["jwks_uri"], _jwks)
    try:
        claims: dict[str, Any] = jwt.decode(
            id_token,
            jwks,
            algorithms=config.get("id_token_signing_alg_values_supported") or ["RS256"],
            audience=str(runtime.get("oidc_client_id")),
            issuer=config.get("issuer") or str(runtime.get("oidc_issuer")).rstrip("/"),
        )
    except Exception as exc:
        raise OidcError(f"The provider's token did not verify: {exc}") from exc

    # Without this a token minted for another sign-in could be replayed into this one.
    if claims.get("nonce") != flow.nonce:
        raise OidcError("The provider's token was issued for a different sign-in")
    return claims


def _as_list(raw: object) -> list[str]:
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(x) for x in raw]  # pyright: ignore[reportUnknownArgumentType]
    return []


def identity(claims: dict[str, Any]) -> tuple[str, list[str], bool]:
    """Username, webgate groups, and whether they are an admin.

    Group names come from the provider and mean nothing here until an admin maps
    them, exactly as LDAP works -- so a new directory group cannot silently grant
    access to a server group of the same name.
    """
    username = str(
        claims.get(str(runtime.get("oidc_username_claim")))
        or claims.get("preferred_username")
        or claims.get("email")
        or claims.get("sub")
        or ""
    ).strip()
    if not username:
        raise OidcError(
            "The provider's token carried no username. Set the username claim in "
            "Admin -> Settings -> Single sign-on to one your provider sends."
        )

    from_provider = _as_list(claims.get(str(runtime.get("oidc_groups_claim"))))
    try:
        mapping: dict[str, str] = json.loads(str(runtime.get("oidc_group_map")) or "{}")
    except json.JSONDecodeError:
        logger.warning("The SSO group mapping is not valid JSON; treating it as empty")
        mapping = {}
    try:
        admin_groups = set(json.loads(str(runtime.get("oidc_admin_groups")) or "[]"))
    except json.JSONDecodeError:
        admin_groups = set()

    groups = sorted({mapping[g] for g in from_provider if g in mapping})
    return username, groups, bool(admin_groups & set(from_provider))


async def take_flow(session: AsyncSession, state: str) -> OidcFlow:
    """The recorded attempt for this state, consumed so it cannot be replayed."""
    flow = (
        await session.execute(select(OidcFlow).where(OidcFlow.state == state))
    ).scalar_one_or_none()
    if flow is None:
        raise OidcError(
            "This sign-in is no longer valid. It may have been completed already, or "
            "taken too long. Start again."
        )
    if datetime.now(UTC) - flow.created_at.replace(tzinfo=UTC) > FLOW_TTL:
        await session.delete(flow)
        await session.commit()
        raise OidcError("This sign-in took too long. Start again.")
    return flow


async def complete(session: AsyncSession, code: str, flow: OidcFlow) -> dict[str, Any]:
    return await _claims(code, flow)


async def issue_handover(session: AsyncSession, flow: OidcFlow, user_id: int) -> str:
    """A one-time code the page trades for a session token.

    Redirecting with the session token in the URL would put it in browser history and
    in every proxy log on the way. This is single-use and lives about a minute.
    """
    flow.handover = secrets.token_urlsafe(32)
    flow.user_id = user_id
    flow.created_at = datetime.now(UTC)
    await session.commit()
    return flow.handover


async def redeem_handover(session: AsyncSession, handover: str) -> int:
    """The user behind a handover code, which is destroyed in the process."""
    flow = (
        await session.execute(select(OidcFlow).where(OidcFlow.handover == handover))
    ).scalar_one_or_none()
    if flow is None or flow.user_id is None:
        raise OidcError("This sign-in code is not valid")
    expired = datetime.now(UTC) - flow.created_at.replace(tzinfo=UTC) > CODE_TTL
    user_id = flow.user_id
    await session.delete(flow)
    await session.commit()
    if expired:
        raise OidcError("This sign-in code has expired. Start again.")
    return user_id
