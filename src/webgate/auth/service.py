from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.auth.models import User
from webgate.config import settings

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(data: dict[str, Any]) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
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
