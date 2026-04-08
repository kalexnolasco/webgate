from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

limiter = Limiter(key_func=get_remote_address)

from webgate.audit.models import AuditOut
from webgate.audit.service import get_audit_log, log_action
from webgate.auth.models import (
    ChangePassword,
    TokenOut,
    UserLogin,
    UserManage,
    UserOut,
    UserUpdateGroups,
)
from webgate.auth.service import (
    create_access_token,
    create_user,
    decode_access_token,
    delete_user,
    get_user_by_id,
    get_user_by_username,
    list_users,
    update_user_groups,
    update_user_password,
    verify_password,
)
from webgate.db.engine import get_session

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer()

SessionDep = Annotated[AsyncSession, Depends(get_session)]
AuthDep = Annotated[HTTPAuthorizationCredentials, Depends(security)]


async def get_current_user(credentials: AuthDep, session: SessionDep) -> UserOut:
    payload = decode_access_token(credentials.credentials)
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


@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
async def login(request: Request, body: UserLogin, session: SessionDep) -> TokenOut:
    user = await get_user_by_username(session, body.username)
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    token = create_access_token({"sub": str(user.id), "username": user.username})
    await log_action(user.id, user.username, "login", ip_address=request.client.host if request.client else "")
    return TokenOut(access_token=token)


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
