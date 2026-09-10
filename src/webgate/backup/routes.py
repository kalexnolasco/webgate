from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.audit.service import log_action
from webgate.auth.models import UserOut
from webgate.auth.routes import get_current_user
from webgate.backup.models import BackupRequest, RestoreReport, RestoreRequest
from webgate.backup.service import build_backup, read_payload, restore_backup
from webgate.config import settings
from webgate.db.engine import get_session

router = APIRouter(prefix="/api/backup", tags=["backup"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[UserOut, Depends(get_current_user)]


def _require_admin(user: UserOut) -> None:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required"
        )


def _deny_in_demo(what: str) -> None:
    if settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=f"{what} is disabled in demo mode"
        )


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("webgate")
    except Exception:  # pragma: no cover - packaging metadata missing in odd installs
        return "unknown"


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@router.post("/export")
async def export_backup(
    body: BackupRequest,
    request: Request,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> dict:
    _require_admin(current_user)
    _deny_in_demo("Backup")

    data = await build_backup(
        session,
        passphrase=body.passphrase,
        include_audit=body.include_audit,
        version=_version(),
    )
    counts = data["counts"]
    await log_action(
        current_user.id,
        current_user.username,
        "backup_export",
        detail=(
            f"{counts['servers']} servers, {counts['users']} users, "
            f"credentials={'yes' if data['includes_credentials'] else 'no'}"
        ),
        ip_address=_client_ip(request),
    )
    return data


@router.post("/restore", response_model=RestoreReport)
async def restore(
    body: RestoreRequest,
    request: Request,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> RestoreReport:
    _require_admin(current_user)
    _deny_in_demo("Restore")

    try:
        payload = read_payload(body.data, body.passphrase)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    report = await restore_backup(session, payload, mode=body.mode, actor_id=current_user.id)

    made = ", ".join(f"{v} {k}" for k, v in report["created"].items() if v) or "nothing"
    await log_action(
        current_user.id,
        current_user.username,
        "backup_restore",
        detail=f"mode={body.mode}, created {made}",
        ip_address=_client_ip(request),
    )
    return RestoreReport(**report)
