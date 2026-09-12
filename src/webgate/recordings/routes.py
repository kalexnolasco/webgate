import contextlib
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.auth.models import UserOut
from webgate.auth.routes import get_current_user
from webgate.auth.service import authenticate_api_key, decode_access_token, get_user_by_id
from webgate.db.engine import get_session
from webgate.recordings.models import Recording, RecordingOut
from webgate.recordings.recorder import unpack


async def _user_from_query_token(token: str, session: AsyncSession) -> UserOut:
    """Resolve a user from a JWT or API key passed via ?token= query. Used by
    the play/download endpoints that open in a new browser tab where we can't
    set an Authorization header."""
    if token.startswith("wg_"):
        u = await authenticate_api_key(session, token)
    else:
        payload = decode_access_token(token)
        if not payload or not payload.get("sub"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        u = await get_user_by_id(session, int(str(payload["sub"])))
    if u is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return UserOut.model_validate(u)


router = APIRouter(prefix="/api/recordings", tags=["recordings"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[UserOut, Depends(get_current_user)]


@router.get("", response_model=list[RecordingOut])
async def list_recordings(session: SessionDep, user: CurrentUserDep) -> list[Recording]:
    stmt = select(Recording).order_by(Recording.started_at.desc())
    if not user.is_admin:
        stmt = stmt.where(Recording.user_id == user.id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _get_recording_for(session: AsyncSession, recording_id: int, user: UserOut) -> Recording:
    stmt = select(Recording).where(Recording.id == recording_id)
    if not user.is_admin:
        stmt = stmt.where(Recording.user_id == user.id)
    rec = (await session.execute(stmt)).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    return rec


def _cast_bytes(rec: Recording) -> bytes:
    """The cast, wherever this recording keeps it.

    Recordings made from v2.3.0 live in the database, so any worker can serve them.
    Older ones are a path on whichever worker happened to record the session -- which
    is exactly the bug: behind a load balancer, roughly half the replays landed on the
    worker that did not have the file.
    """
    if rec.data:
        return unpack(rec.data)
    if rec.file_path:
        path = Path(rec.file_path)
        if path.exists():
            return path.read_bytes()
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=(
            "This recording was stored on a single worker's disk and is not "
            "reachable from here. Recordings made from v2.3.0 onwards are not."
        ),
    )


@router.get("/{recording_id}/download")
async def download_recording(
    recording_id: int, session: SessionDep, token: Annotated[str, Query()]
) -> Response:
    user = await _user_from_query_token(token, session)
    rec = await _get_recording_for(session, recording_id, user)
    return Response(
        content=_cast_bytes(rec),
        media_type="application/x-asciicast",
        headers={
            "Content-Disposition": (
                f'attachment; filename="webgate-{rec.id}-{rec.server_name}.cast"'
            )
        },
    )


@router.get("/{recording_id}/play", response_class=HTMLResponse)
async def play_recording(
    recording_id: int, session: SessionDep, token: Annotated[str, Query()]
) -> HTMLResponse:
    user = await _user_from_query_token(token, session)
    rec = await _get_recording_for(session, recording_id, user)
    # Embed asciinema-player from CDN. The cast file is fetched via the
    # download endpoint so JWT auth is honored.
    started = rec.started_at.isoformat()
    # Referrer-Policy no-referrer prevents leaking the ?token= to any
    # external asset (CDN, browser history peeks, etc.). The meta refresh
    # is a belt-and-braces for older browsers.
    html = f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<meta name="referrer" content="no-referrer">
<title>webgate replay #{rec.id} &mdash; {rec.server_name}</title>
<link rel="stylesheet" referrerpolicy="no-referrer"
      href="https://cdn.jsdelivr.net/npm/asciinema-player@3.7.0/dist/bundle/asciinema-player.css">
<style>
  body {{ background:#1a1b26; color:#c0caf5; margin:0; padding:20px;
          font-family:system-ui,sans-serif; }}
  .meta {{ display:flex; gap:24px; font-size:13px; margin-bottom:16px; color:#9ba3c5; }}
  .meta b {{ color:#fff; }}
  #player {{ max-width:1100px; }}
</style>
</head><body>
<div class=\"meta\">
  <span>📹 <b>{rec.server_name}</b></span>
  <span>👤 {rec.username}</span>
  <span>🕒 {started}</span>
  <span>⏱ {rec.duration_s:.1f}s</span>
  <span>💾 {rec.size_bytes:,} bytes</span>
</div>
<div id=\"player\"></div>
<script referrerpolicy="no-referrer"
        src=\"https://cdn.jsdelivr.net/npm/asciinema-player@3.7.0/dist/bundle/asciinema-player.min.js\"></script>
<script>
  AsciinemaPlayer.create('cast?token={token}', document.getElementById('player'),
    {{ idleTimeLimit: 2, theme: 'tango', fit: 'width' }});
</script>
</body></html>"""
    return HTMLResponse(
        content=html,
        headers={"Referrer-Policy": "no-referrer", "Cache-Control": "private, no-store"},
    )


@router.get("/{recording_id}/cast")
async def cast_raw(
    recording_id: int, session: SessionDep, token: Annotated[str, Query()]
) -> Response:
    """Same as /download but returns the raw cast (no Content-Disposition) so
    the embedded player can fetch it via XHR."""
    user = await _user_from_query_token(token, session)
    rec = await _get_recording_for(session, recording_id, user)
    return Response(content=_cast_bytes(rec), media_type="application/x-asciicast")


@router.delete("/{recording_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recording(recording_id: int, session: SessionDep, user: CurrentUserDep) -> None:
    rec = await _get_recording_for(session, recording_id, user)
    p = Path(rec.file_path)
    if p.exists():
        with contextlib.suppress(OSError):
            p.unlink()
    await session.delete(rec)
    await session.commit()
