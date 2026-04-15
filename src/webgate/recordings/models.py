from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from webgate.db.engine import Base


class Recording(Base):
    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    server_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("servers.id"), nullable=True
    )
    server_name: Mapped[str] = mapped_column(String(255), default="")
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    username: Mapped[str] = mapped_column(String(255), default="")
    file_path: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_s: Mapped[float] = mapped_column(default=0.0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)


class RecordingOut(BaseModel):
    id: int
    server_id: int | None
    server_name: str
    username: str
    started_at: datetime
    ended_at: datetime | None
    duration_s: float
    size_bytes: int

    model_config = {"from_attributes": True}
