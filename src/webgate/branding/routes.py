from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.audit.service import log_action
from webgate.auth.models import UserOut
from webgate.auth.routes import get_current_user
from webgate.branding import store
from webgate.config import settings
from webgate.db.engine import get_session

router = APIRouter(prefix="/api/branding", tags=["branding"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[UserOut, Depends(get_current_user)]


class BrandingIn(BaseModel):
    app_name: str = ""
    tagline: str = ""
    favicon_emoji: str = ""
    colors: dict[str, str] = {}
    colors_dark: dict[str, str] = {}
    # None means "leave the stored image alone"; "" removes it.
    logo: str | None = None
    login_image: str | None = None
    favicon: str | None = None


def _require_admin(user: UserOut) -> None:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required"
        )


def _deny_in_demo() -> None:
    if settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Branding is read-only in demo mode"
        )


@router.get("")
async def read_branding(session: SessionDep) -> dict[str, object]:
    """Public: the sign-in screen is branded before anyone has logged in."""
    return (await store.load(session)).as_dict()


@router.put("")
async def write_branding(
    body: BrandingIn,
    request: Request,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> dict[str, object]:
    _require_admin(current_user)
    _deny_in_demo()
    try:
        view = await store.save(
            session,
            app_name=body.app_name,
            tagline=body.tagline,
            favicon_emoji=body.favicon_emoji,
            colors=body.colors,
            colors_dark=body.colors_dark,
            logo=body.logo,
            login_image=body.login_image,
            favicon=body.favicon,
            updated_by=current_user.username,
        )
    except store.BrandingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await log_action(
        current_user.id,
        current_user.username,
        "branding_update",
        detail=f"name={view.app_name or 'default'} colours={len(view.colors or {})}",
        ip_address=request.client.host if request.client else "",
    )
    return view.as_dict()


@router.delete("")
async def reset_branding(
    request: Request, session: SessionDep, current_user: CurrentUserDep
) -> dict[str, object]:
    _require_admin(current_user)
    _deny_in_demo()
    view = await store.reset(session)
    await log_action(
        current_user.id,
        current_user.username,
        "branding_reset",
        detail="restored the shipped look",
        ip_address=request.client.host if request.client else "",
    )
    return view.as_dict()
