from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

limiter = Limiter(key_func=get_remote_address)

from webgate.audit.models import AuditOut
from webgate.audit.service import get_audit_log, log_action
from webgate.webhooks.dispatcher import fire as fire_webhook
from webgate.auth.models import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    ChangePassword,
    LoginOut,
    TotpSetupOut,
    TotpStatusOut,
    TotpVerifyIn,
    UserLogin,
    UserManage,
    UserOut,
    UserUpdateGroups,
)
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

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer()

SessionDep = Annotated[AsyncSession, Depends(get_session)]
AuthDep = Annotated[HTTPAuthorizationCredentials, Depends(security)]


async def get_current_user(credentials: AuthDep, session: SessionDep) -> UserOut:
    token = credentials.credentials

    # Check if it's an API key (starts with "wg_")
    if token.startswith("wg_"):
        user = await authenticate_api_key(session, token)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
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
    return UserOut.model_validate(user)


CurrentUserDep = Annotated[UserOut, Depends(get_current_user)]


def _require_admin(user: UserOut) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


@router.post("/login", response_model=LoginOut)
@limiter.limit("10/minute")
async def login(request: Request, body: UserLogin, session: SessionDep) -> LoginOut:
    user = await get_user_by_username(session, body.username)
    if not user or not verify_password(body.password, user.hashed_password):
        await fire_webhook("user_login_failed", {
            "username": body.username,
            "ip": request.client.host if request.client else "",
        })
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    # Check if 2FA is enabled
    if user.totp_enabled and user.totp_secret:
        if not body.totp_code:
            # Issue a short-lived temp token for 2FA verification
            temp_token = create_access_token(
                {"sub": str(user.id), "pending_2fa": True, "exp_minutes": 2}
            )
            return LoginOut(requires_2fa=True, temp_token=temp_token)
        # Verify the TOTP code
        if not verify_totp(user.totp_secret, body.totp_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid 2FA code"
            )
    token = create_access_token({"sub": str(user.id), "username": user.username})
    await log_action(
        user.id,
        user.username,
        "login",
        ip_address=request.client.host if request.client else "",
    )
    await fire_webhook("user_login", {
        "username": user.username,
        "user_id": user.id,
        "ip": request.client.host if request.client else "",
    })
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
    body: UserManage, session: SessionDep, current_user: CurrentUserDep
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
    return UserOut.model_validate(user)


@router.put("/users/{user_id}/groups", response_model=UserOut)
async def set_user_groups(
    user_id: int, body: UserUpdateGroups, session: SessionDep, current_user: CurrentUserDep
) -> UserOut:
    _require_admin(current_user)
    user = await get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.is_admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify admin")
    updated = await update_user_groups(session, user, body.allowed_groups)
    return UserOut.model_validate(updated)


@router.put("/users/{user_id}/password", response_model=UserOut)
async def reset_user_password(
    user_id: int, body: UserLogin, session: SessionDep, current_user: CurrentUserDep
) -> UserOut:
    _require_admin(current_user)
    user = await get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    updated = await update_user_password(session, user, body.password)
    return UserOut.model_validate(updated)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user(
    user_id: int, session: SessionDep, current_user: CurrentUserDep
) -> None:
    _require_admin(current_user)
    user = await get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.is_admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete admin")
    await delete_user(session, user)


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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Run TOTP setup first"
        )
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Name is required"
        )
    key_obj, plaintext_key = await create_api_key(session, current_user.id, body.name.strip())
    return ApiKeyCreated(
        id=key_obj.id,
        name=key_obj.name,
        key=plaintext_key,
        key_prefix=key_obj.key_prefix,
    )


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: int, session: SessionDep, current_user: CurrentUserDep
) -> None:
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
) -> list[AuditOut]:
    _require_admin(current_user)
    return await get_audit_log(session, limit=limit, offset=offset, username=username, action=action)
