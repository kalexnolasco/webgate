"""Saved commands: a button that runs a command in the open terminal.

Three things the first version could not do, and each of them mattered:

* **Share.** A snippet belonged to one user, so a team's standard checks were
  something every member retyped from memory. An admin can now publish one.
* **Take a parameter.** `tail -n 200 /var/log/nginx/error.log` is a different snippet
  from the same command with a different path. Placeholders make it one.
* **Ask first.** A snippet runs the moment it is clicked, and nothing asks before
  `systemctl restart nginx` reaches production.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.auth.models import UserOut
from webgate.auth.routes import get_current_user
from webgate.db.engine import get_session
from webgate.snippets.models import Snippet, SnippetCreate, SnippetOut

router = APIRouter(prefix="/api/snippets", tags=["snippets"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[UserOut, Depends(get_current_user)]

# `{name}`, the same shape the LDAP filters already use, so there is one convention.
PLACEHOLDER = re.compile(r"\{([a-zA-Z][a-zA-Z0-9_]*)\}")


def placeholders(command: str) -> list[str]:
    """The parameters a command asks for, in the order they first appear."""
    return list(dict.fromkeys(PLACEHOLDER.findall(command)))


def _out(snippet: Snippet, user: UserOut) -> SnippetOut:
    return SnippetOut(
        id=snippet.id,
        name=snippet.name,
        command=snippet.command,
        description=snippet.description,
        shared=snippet.shared,
        confirm=snippet.confirm,
        # Drives whether the UI offers to delete it: a shared snippet is not yours
        # to remove unless you are an admin.
        owned=snippet.user_id == user.id or user.is_admin,
        created_at=snippet.created_at,
    )


@router.get("", response_model=list[SnippetOut])
async def list_snippets(session: SessionDep, user: CurrentUserDep) -> list[SnippetOut]:
    """Your own snippets, plus everything an admin has published."""
    stmt = (
        select(Snippet)
        .where(or_(Snippet.user_id == user.id, Snippet.shared.is_(True)))
        # Shared ones first: they are the team's agreed set, and a personal snippet
        # with the same name should read as the variation it is.
        .order_by(Snippet.shared.desc(), Snippet.name)
    )
    return [_out(s, user) for s in (await session.execute(stmt)).scalars().all()]


@router.post("", response_model=SnippetOut, status_code=status.HTTP_201_CREATED)
async def create_snippet(
    body: SnippetCreate, session: SessionDep, user: CurrentUserDep
) -> SnippetOut:
    if body.shared and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin can publish a snippet to everyone",
        )
    snippet = Snippet(
        name=body.name,
        command=body.command,
        description=body.description,
        shared=body.shared,
        confirm=body.confirm,
        user_id=user.id,
    )
    session.add(snippet)
    await session.commit()
    await session.refresh(snippet)
    return _out(snippet, user)


@router.put("/{snippet_id}", response_model=SnippetOut)
async def update_snippet(
    snippet_id: int, body: SnippetCreate, session: SessionDep, user: CurrentUserDep
) -> SnippetOut:
    snippet = await _own_or_admin(session, snippet_id, user)
    if body.shared and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin can publish a snippet to everyone",
        )
    snippet.name = body.name
    snippet.command = body.command
    snippet.description = body.description
    snippet.shared = body.shared
    snippet.confirm = body.confirm
    await session.commit()
    await session.refresh(snippet)
    return _out(snippet, user)


@router.delete("/{snippet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_snippet(snippet_id: int, session: SessionDep, user: CurrentUserDep) -> None:
    snippet = await _own_or_admin(session, snippet_id, user)
    await session.delete(snippet)
    await session.commit()


async def _own_or_admin(session: AsyncSession, snippet_id: int, user: UserOut) -> Snippet:
    """Yours to change, or you are an admin. A shared snippet is nobody else's to edit."""
    stmt = select(Snippet).where(Snippet.id == snippet_id)
    if not user.is_admin:
        stmt = stmt.where(Snippet.user_id == user.id)
    snippet = (await session.execute(stmt)).scalar_one_or_none()
    if snippet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snippet not found")
    return snippet
