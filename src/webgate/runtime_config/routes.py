"""The admin settings panel.

The panel is rendered from what GET returns, so a new setting appears in the UI as
soon as it is added to the registry.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.audit.service import log_action
from webgate.auth.models import UserOut
from webgate.auth.routes import get_current_user
from webgate.config import settings as env_settings
from webgate.db.engine import get_session
from webgate.runtime_config import store
from webgate.runtime_config.registry import BY_KEY, SECTIONS, SPECS, InvalidSetting

router = APIRouter(prefix="/api/settings", tags=["settings"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[UserOut, Depends(get_current_user)]

# Shown so an admin can see what is fixed by the deployment and why, rather than
# hunting for a knob that is not there.
FIXED = (
    ("WEBGATE_DB_URL", "Where the database is. Cannot live inside it."),
    ("WEBGATE_SECRET_KEY", "Decrypts stored credentials. Cannot live in what it encrypts."),
    ("WEBGATE_HOST", "Bind address, read before the app can serve a request."),
    ("WEBGATE_PORT", "Bind port, read before the app can serve a request."),
    ("WEBGATE_ROOT_PATH", "Sub-path for a reverse proxy; routes are mounted at startup."),
    ("WEBGATE_LOG_LEVEL", "Read once by the server process."),
    ("WEBGATE_DEMO_MODE", "A deployment posture. Enabling it here would block turning it off."),
    ("WEBGATE_JWT_ALGORITHM", "One typo away from accepting unsigned tokens."),
)


class SettingsIn(BaseModel):
    values: dict[str, Any] = {}


class ResetIn(BaseModel):
    # None resets everything; a list resets just those.
    keys: list[str] | None = None


def _require_admin(user: UserOut) -> None:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required"
        )


def _render(key: str) -> Any:
    """A secret is never returned; the panel only needs to know whether one is set."""
    spec = BY_KEY[key]
    if spec.kind == "secret":
        return "********" if store.get(key) else ""
    return store.get(key)


@router.get("")
async def read_settings(current_user: CurrentUserDep) -> dict[str, object]:
    _require_admin(current_user)
    return {
        "locked": store.is_locked(),
        "sections": [
            {
                "name": section,
                "settings": [
                    {
                        "key": s.key,
                        "label": s.label,
                        "help": s.help,
                        "kind": s.kind,
                        "value": _render(s.key),
                        "source": store.source(s.key),
                        "minimum": s.minimum,
                        "maximum": s.maximum,
                        "choices": list(s.choices),
                        "placeholder": s.placeholder,
                        "warning": s.warning,
                        "env_var": f"WEBGATE_{s.key.upper()}",
                    }
                    for s in SPECS
                    if s.section == section
                ],
            }
            for section in SECTIONS
        ],
        "fixed": [{"env_var": name, "reason": reason} for name, reason in FIXED],
    }


@router.put("")
async def write_settings(
    body: SettingsIn,
    request: Request,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> dict[str, object]:
    _require_admin(current_user)
    if env_settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Settings are read-only in demo mode"
        )
    try:
        changed = await store.apply(session, body.values, actor=current_user.username)
    except InvalidSetting as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    if changed:
        # The values themselves are not logged: one of them is a bind password.
        await log_action(
            current_user.id,
            current_user.username,
            "settings_update",
            detail=", ".join(sorted(changed)),
            ip_address=request.client.host if request.client else "",
        )
    return {"changed": changed}


@router.post("/reset")
async def reset_settings(
    body: ResetIn,
    request: Request,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> dict[str, object]:
    _require_admin(current_user)
    if env_settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Settings are read-only in demo mode"
        )
    try:
        cleared = await store.reset(session, body.keys)
    except InvalidSetting as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    if cleared:
        await log_action(
            current_user.id,
            current_user.username,
            "settings_reset",
            detail=", ".join(sorted(cleared)),
            ip_address=request.client.host if request.client else "",
        )
    return {"cleared": cleared}
