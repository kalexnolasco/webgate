import json
import secrets
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.audit.models import AuditOut
from webgate.audit.service import audit_actions, get_audit_log, log_action
from webgate.auth import oidc
from webgate.auth.ldap import authenticate_ldap
from webgate.auth.models import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    ChangePassword,
    LoginOut,
    SsoExchange,
    TotpSetupOut,
    TotpStatusOut,
    TotpVerifyIn,
    UserLogin,
    UserManage,
    UserOut,
    UserUpdateGroups,
)
from webgate.auth.oidc import OidcError
from webgate.auth.service import (
    authenticate_api_key,
    create_access_token,
    create_api_key,
    create_user,
    decode_access_token,
    delete_api_key,
    delete_user,
    generate_totp_secret,
    get_api_keys,
    get_totp_uri,
    get_user_by_id,
    get_user_by_username,
    list_users,
    update_user_groups,
    update_user_password,
    verify_password,
    verify_totp,
)
from webgate.db.engine import get_session
from webgate.runtime_config import store as runtime
from webgate.webhooks.dispatcher import fire as fire_webhook

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer()

SessionDep = Annotated[AsyncSession, Depends(get_session)]
AuthDep = Annotated[HTTPAuthorizationCredentials, Depends(security)]


async def get_current_user(request: Request, credentials: AuthDep, session: SessionDep) -> UserOut:
    """Resolve the user from JWT or API key and enforce account-level gates
    (pending 2FA, forced password change). Only a short allowlist of endpoints
    can be hit while a user is in one of those states."""
    token = credentials.credentials

    # Check if it's an API key (starts with "wg_")
    if token.startswith("wg_"):
        user = await authenticate_api_key(session, token)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        if user.must_change_password:
            # API keys cannot bypass a forced password change.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Password change required before using API keys",
            )
        return UserOut.model_validate(user)

    # Otherwise treat as JWT
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = await get_user_by_id(session, int(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    path = request.url.path
    # Pre-2FA temp token: only /api/auth/login is allowed (for the code step).
    if payload.get("pending_2fa") and path != "/api/auth/login":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Pending 2FA: submit totp_code via /api/auth/login to obtain a session token"),
        )
    # Forced password change: only /api/auth/me and /api/auth/change-password are allowed.
    if user.must_change_password and path not in {
        "/api/auth/me",
        "/api/auth/change-password",
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required",
        )
    return UserOut.model_validate(user)


CurrentUserDep = Annotated[UserOut, Depends(get_current_user)]


def _require_admin(user: UserOut) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


@router.post("/login", response_model=LoginOut)
@limiter.limit("10/minute")
async def login(request: Request, body: UserLogin, session: SessionDep) -> LoginOut:
    user = await get_user_by_username(session, body.username)
    local_ok = bool(user and verify_password(body.password, user.hashed_password))

    if not local_ok:
        # Fall through to LDAP if it's enabled. On success we auto-provision
        # or refresh the local row so the rest of the app keeps working
        # against the User table (audit, allowed_groups, JWT subject, ...).
        ldap_result = await authenticate_ldap(body.username, body.password)
        if ldap_result is None:
            # Strip any control characters and truncate to 64 chars before
            # emitting the attacker-controlled username into the webhook
            # payload. Receivers (Slack, Discord, custom handlers) often
            # render it verbatim, and we don't want payloads that contain
            # terminal escapes, HTML, or 10 MB strings.
            safe_username = "".join(c for c in (body.username or "") if c.isprintable())[:64]
            await fire_webhook(
                "user_login_failed",
                {
                    "username": safe_username,
                    "ip": request.client.host if request.client else "",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )
        # LDAP passed -- create or refresh the local user row.
        if user is None:
            user = await create_user(
                session, body.username, secrets.token_urlsafe(32), is_admin=ldap_result.is_admin
            )
            user.must_change_password = False
        else:
            user.is_admin = ldap_result.is_admin
        user.allowed_groups = json.dumps(ldap_result.allowed_groups)
        await session.commit()
        await session.refresh(user)

    if user is None:
        # Unreachable: local_ok requires a row, and the LDAP path creates one. Stated
        # rather than assumed, so the invariant is enforced instead of being something
        # every line below quietly relies on -- and it fails closed if it ever breaks.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Check if 2FA is enabled
    if user.totp_enabled and user.totp_secret:
        if not body.totp_code:
            # Short-lived pre-2FA token: only accepted by /api/auth/login
            # itself (gated in get_current_user) and expires in 2 minutes.
            temp_token = create_access_token(
                {"sub": str(user.id), "pending_2fa": True},
                expires_minutes=2,
            )
            return LoginOut(requires_2fa=True, temp_token=temp_token)
        # Verify the TOTP code
        if not verify_totp(user.totp_secret, body.totp_code):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid 2FA code")
    token = create_access_token({"sub": str(user.id), "username": user.username})
    await log_action(
        user.id,
        user.username,
        "login",
        ip_address=request.client.host if request.client else "",
    )
    await fire_webhook(
        "user_login",
        {
            "username": user.username,
            "user_id": user.id,
            "ip": request.client.host if request.client else "",
        },
    )
    return LoginOut(access_token=token)


async def _record(request: Request, actor: UserOut, action: str, detail: str) -> None:
    """Who changed whose access, and from where.

    Only sign-ins were recorded. Creating an account, moving someone between groups,
    resetting a password or clearing a 2FA secret are all changes to who can reach the
    fleet, and none of them left a trace.
    """
    await log_action(
        actor.id,
        actor.username,
        action,
        detail=detail,
        ip_address=request.client.host if request.client else "",
    )


def _redirect_base(request: Request) -> str:
    """Where the provider should send the browser back to.

    A configured value wins: behind a proxy that rewrites the host, the app's own view
    of its address is whatever the proxy forwarded, which may not be reachable.
    """
    configured = str(runtime.get("oidc_redirect_base")).strip().rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


@router.get("/sso/start")
async def sso_start(request: Request, session: SessionDep) -> RedirectResponse:
    """Send the browser to the identity provider."""
    try:
        url = await oidc.begin(session, f"{_redirect_base(request)}/api/auth/sso/callback")
    except OidcError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get("/sso/callback")
async def sso_callback(
    request: Request,
    session: SessionDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    """Where the provider sends the browser back.

    Ends in a redirect either way, because the person is looking at a browser tab and
    a JSON error body would be the last thing they see.
    """
    root = str(request.base_url).rstrip("/")

    def back(message: str) -> RedirectResponse:
        return RedirectResponse(
            f"{root}/?sso_error={quote(message[:300])}", status_code=status.HTTP_302_FOUND
        )

    if error:
        return back(error_description or f"The provider refused the sign-in: {error}")
    if not code or not state:
        return back("The provider did not send a code. Start again.")

    try:
        flow = await oidc.take_flow(session, state)
        claims = await oidc.complete(session, code, flow)
        username, groups, is_admin = oidc.identity(claims)
    except OidcError as exc:
        return back(str(exc))

    user = await get_user_by_username(session, username)
    if user is None:
        user = await create_user(session, username, secrets.token_urlsafe(32), is_admin=is_admin)
        # There is no local password to change: the provider is the password.
        user.must_change_password = False
    else:
        user.is_admin = is_admin
    user.allowed_groups = json.dumps(groups)
    await session.commit()
    await session.refresh(user)

    handover = await oidc.issue_handover(session, flow, user.id)
    await log_action(
        user.id,
        user.username,
        "sso_login",
        detail=f"groups: {', '.join(groups) or 'none'}{'; admin' if is_admin else ''}",
        ip_address=request.client.host if request.client else "",
    )
    return RedirectResponse(f"{root}/?sso={handover}", status_code=status.HTTP_302_FOUND)


@router.post("/sso/exchange", response_model=LoginOut)
async def sso_exchange(body: SsoExchange, request: Request, session: SessionDep) -> LoginOut:
    """Trade the one-time code for a session token.

    The token is never put in a URL: it would end up in browser history and in every
    proxy log between here and the person.
    """
    try:
        user_id = await oidc.redeem_handover(session, body.code)
    except OidcError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="That account no longer exists"
        )
    token = create_access_token({"sub": str(user.id), "username": user.username})
    await fire_webhook(
        "user_login",
        {
            "username": user.username,
            "user_id": user.id,
            "via": "sso",
            "ip": request.client.host if request.client else "",
        },
    )
    return LoginOut(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUserDep) -> UserOut:
    return current_user


@router.post("/change-password", response_model=UserOut)
@limiter.limit("5/minute")
async def change_password(
    request: Request, body: ChangePassword, session: SessionDep, current_user: CurrentUserDep
) -> UserOut:
    if len(body.new_password) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Password too short (min 4 chars)"
        )
    user = await get_user_by_id(session, current_user.id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    updated = await update_user_password(session, user, body.new_password)
    updated.must_change_password = False
    await session.commit()
    await session.refresh(updated)
    return UserOut.model_validate(updated)


# ---- Admin: user management ----


@router.get("/users", response_model=list[UserOut])
async def get_users(session: SessionDep, current_user: CurrentUserDep) -> list[UserOut]:
    _require_admin(current_user)
    users = await list_users(session)
    return [UserOut.model_validate(u) for u in users]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_new_user(
    body: UserManage, request: Request, session: SessionDep, current_user: CurrentUserDep
) -> UserOut:
    _require_admin(current_user)
    existing = await get_user_by_username(session, body.username)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")
    if not body.password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password required")
    user = await create_user(
        session, body.username, body.password, allowed_groups=body.allowed_groups
    )
    await _record(
        request,
        current_user,
        "user_created",
        f"{user.username}; groups: {', '.join(body.allowed_groups) or 'none'}",
    )
    return UserOut.model_validate(user)


@router.put("/users/{user_id}/groups", response_model=UserOut)
async def set_user_groups(
    user_id: int,
    body: UserUpdateGroups,
    request: Request,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> UserOut:
    _require_admin(current_user)
    user = await get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.is_admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify admin")
    was = ", ".join(json.loads(user.allowed_groups or "[]")) or "none"
    now = ", ".join(body.allowed_groups) or "none"
    updated = await update_user_groups(session, user, body.allowed_groups)
    await _record(request, current_user, "user_groups_changed", f"{user.username}: {was} -> {now}")
    return UserOut.model_validate(updated)


@router.put("/users/{user_id}/password", response_model=UserOut)
async def reset_user_password(
    user_id: int,
    body: UserLogin,
    request: Request,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> UserOut:
    _require_admin(current_user)
    user = await get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    updated = await update_user_password(session, user, body.password)
    await _record(request, current_user, "user_password_reset", user.username)
    return UserOut.model_validate(updated)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user(
    user_id: int, request: Request, session: SessionDep, current_user: CurrentUserDep
) -> None:
    _require_admin(current_user)
    user = await get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.is_admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete admin")
    name = user.username
    await delete_user(session, user)
    await _record(request, current_user, "user_deleted", name)


@router.post("/totp/setup", response_model=TotpSetupOut)
async def totp_setup(session: SessionDep, current_user: CurrentUserDep) -> TotpSetupOut:
    import base64
    import io

    import qrcode

    user = await get_user_by_id(session, current_user.id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    secret = generate_totp_secret()
    user.totp_secret = secret
    await session.commit()
    uri = get_totp_uri(secret, user.username)
    qr = qrcode.make(uri)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    return TotpSetupOut(secret=secret, qr_uri=uri, qr_base64=f"data:image/png;base64,{qr_b64}")


@router.post("/totp/verify", response_model=TotpStatusOut)
async def totp_verify(
    body: TotpVerifyIn, session: SessionDep, current_user: CurrentUserDep
) -> TotpStatusOut:
    user = await get_user_by_id(session, current_user.id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not user.totp_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Run TOTP setup first")
    if not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")
    user.totp_enabled = True
    await session.commit()
    return TotpStatusOut(enabled=True)


@router.post("/totp/disable", response_model=TotpStatusOut)
async def totp_disable(
    body: TotpVerifyIn, session: SessionDep, current_user: CurrentUserDep
) -> TotpStatusOut:
    user = await get_user_by_id(session, current_user.id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not user.totp_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is not enabled")
    if not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")
    user.totp_secret = ""
    user.totp_enabled = False
    await session.commit()
    return TotpStatusOut(enabled=False)


@router.put("/users/{user_id}/totp-reset", response_model=UserOut)
async def reset_user_totp(
    user_id: int, session: SessionDep, current_user: CurrentUserDep
) -> UserOut:
    _require_admin(current_user)
    user = await get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.totp_secret = ""
    user.totp_enabled = False
    await session.commit()
    await session.refresh(user)
    return UserOut.model_validate(user)


# ---- API Keys ----


@router.get("/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(session: SessionDep, current_user: CurrentUserDep) -> list[ApiKeyOut]:
    keys = await get_api_keys(session, current_user.id)
    return [ApiKeyOut.model_validate(k) for k in keys]


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key_endpoint(
    body: ApiKeyCreate, session: SessionDep, current_user: CurrentUserDep
) -> ApiKeyCreated:
    if not body.name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name is required")
    key_obj, plaintext_key = await create_api_key(session, current_user.id, body.name.strip())
    return ApiKeyCreated(
        id=key_obj.id,
        name=key_obj.name,
        key=plaintext_key,
        key_prefix=key_obj.key_prefix,
    )


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: int, session: SessionDep, current_user: CurrentUserDep) -> None:
    deleted = await delete_api_key(session, key_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")


@router.get("/audit", response_model=list[AuditOut])
async def audit_log_endpoint(
    session: SessionDep,
    current_user: CurrentUserDep,
    limit: int = 100,
    offset: int = 0,
    username: str | None = None,
    action: str | None = None,
    search: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[AuditOut]:
    _require_admin(current_user)
    return await get_audit_log(
        session,
        limit=limit,
        offset=offset,
        username=username,
        action=action,
        search=search,
        since=since,
        until=until,
    )


@router.get("/audit/actions", response_model=list[str])
async def audit_actions_endpoint(session: SessionDep, current_user: CurrentUserDep) -> list[str]:
    """The action kinds actually present, so the filter is a list rather than guesswork."""
    _require_admin(current_user)
    return await audit_actions(session)
