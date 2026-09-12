from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from webgate.db.engine import Base


class Snippet(Base):
    __tablename__ = "snippets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    command: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    # Published by an admin for everyone. A team's standard checks should not be
    # something each person retypes from memory.
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    # Ask before sending. A snippet runs the moment it is clicked, and there is
    # no undo on `systemctl restart` against production.
    confirm: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SnippetCreate(BaseModel):
    name: str
    command: str
    description: str = ""
    shared: bool = False
    confirm: bool = False


class SnippetOut(BaseModel):
    id: int
    name: str
    command: str
    description: str
    shared: bool = False
    confirm: bool = False
    owned: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}
