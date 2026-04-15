from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.auth.models import UserOut
from webgate.auth.routes import get_current_user
from webgate.db.engine import get_session
from webgate.snippets.models import Snippet, SnippetCreate, SnippetOut

router = APIRouter(prefix="/api/snippets", tags=["snippets"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[UserOut, Depends(get_current_user)]


@router.get("", response_model=list[SnippetOut])
async def list_snippets(session: SessionDep, user: CurrentUserDep) -> list[Snippet]:
    stmt = select(Snippet).where(Snippet.user_id == user.id).order_by(Snippet.name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=SnippetOut, status_code=status.HTTP_201_CREATED)
async def create_snippet(
    body: SnippetCreate, session: SessionDep, user: CurrentUserDep
) -> Snippet:
    snippet = Snippet(
        name=body.name, command=body.command, description=body.description, user_id=user.id
    )
    session.add(snippet)
    await session.commit()
    await session.refresh(snippet)
    return snippet


@router.delete("/{snippet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_snippet(snippet_id: int, session: SessionDep, user: CurrentUserDep) -> None:
    stmt = select(Snippet).where(Snippet.id == snippet_id, Snippet.user_id == user.id)
    snippet = (await session.execute(stmt)).scalar_one_or_none()
    if snippet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snippet not found")
    await session.delete(snippet)
    await session.commit()
