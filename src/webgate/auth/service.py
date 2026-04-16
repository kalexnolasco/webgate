from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.auth.models import ApiKey, User
from webgate.config import settings

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(data: dict[str, Any], expires_minutes: int | None = None) -> str:
    """Mint a signed JWT. `expires_minutes` overrides the default session TTL
    for short-lived tokens (e.g. the 2-minute pre-2FA token)."""
    to_encode = data.copy()
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    expire = datetime.now(UTC) + timedelta(minutes=minutes)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError:
        return None


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_count(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(User))
    count = result.scalar_one()
    return int(count)


async def create_user(
    session: AsyncSession,
    username: str,
    password: str,
    is_admin: bool = False,
    allowed_groups: list[str] | None = None,
) -> User:
    user = User(
        username=username,
        hashed_password=hash_password(password),
        is_admin=is_admin,
        allowed_groups=json.dumps(allowed_groups or []),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def seed_admin(session: AsyncSession) -> None:
    """Create default admin user if no users exist."""
    count = await get_user_count(session)
    if count > 0:
        return
    user = await create_user(session, "admin", "admin", is_admin=True)
    user.must_change_password = True
    await session.commit()
    logger.info("Created default admin user (admin/admin) — password change required on first login")


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.username))
    return list(result.scalars().all())


async def update_user_groups(
    session: AsyncSession, user: User, groups: list[str]
) -> User:
    user.allowed_groups = json.dumps(groups)
    await session.commit()
    await session.refresh(user)
    return user


async def update_user_password(
    session: AsyncSession, user: User, new_password: str
) -> User:
    user.hashed_password = hash_password(new_password)
    await session.commit()
    await session.refresh(user)
    return user


async def delete_user(session: AsyncSession, user: User) -> None:
    await session.delete(user)
    await session.commit()


def generate_api_key() -> str:
    """Generate a random API key like 'wg_xxxxxxxxxxxxxxxxxxxxxxxxxxxx'."""
    return "wg_" + secrets.token_hex(24)


async def create_api_key(session: AsyncSession, user_id: int, name: str) -> tuple[ApiKey, str]:
    """Create an API key. Returns (model, plaintext_key)."""
    key = generate_api_key()
    key_obj = ApiKey(
        user_id=user_id,
        name=name,
        key_hash=hash_password(key),
        key_prefix=key[:10],
    )
    session.add(key_obj)
    await session.commit()
    await session.refresh(key_obj)
    return key_obj, key


async def get_api_keys(session: AsyncSession, user_id: int) -> list[ApiKey]:
    """List all API keys for a user."""
    result = await session.execute(
        select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_api_key(session: AsyncSession, key_id: int, user_id: int) -> bool:
    """Delete an API key. Returns True if found and deleted."""
    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user_id)
    )
    key_obj = result.scalar_one_or_none()
    if not key_obj:
        return False
    await session.delete(key_obj)
    await session.commit()
    return True


async def authenticate_api_key(session: AsyncSession, key: str) -> User | None:
    """Look up API key by prefix, then verify hash. Update last_used_at."""
    prefix = key[:10]
    result = await session.execute(
        select(ApiKey).where(ApiKey.key_prefix == prefix)
    )
    for api_key in result.scalars().all():
        if verify_password(key, api_key.key_hash):
            api_key.last_used_at = datetime.now(UTC)
            user_result = await session.execute(
                select(User).where(User.id == api_key.user_id)
            )
            user = user_result.scalar_one_or_none()
            await session.commit()
            return user
    return None


def generate_totp_secret() -> str:
    import pyotp

    return pyotp.random_base32()


def get_totp_uri(secret: str, username: str) -> str:
    import pyotp

    return pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name="webgate")


def verify_totp(secret: str, code: str) -> bool:
    import pyotp

    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)
