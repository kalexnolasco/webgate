from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from webgate.db.engine import Base

# Known event names. Stored in `events` as a JSON array of strings; "*" means all.
EVENT_NAMES = [
    "user_login",
    "user_login_failed",
    "ssh_connect",
    "sftp_upload",
    "sftp_delete",
    "server_added",
    "server_deleted",
]


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    events: Mapped[str] = mapped_column(Text, default='["*"]')  # JSON array
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    secret: Mapped[str] = mapped_column(String(255), default="")  # HMAC signing key
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WebhookCreate(BaseModel):
    name: str
    url: str
    events: list[str] = Field(default_factory=lambda: ["*"])
    enabled: bool = True
    secret: str = ""


class WebhookUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    events: list[str] | None = None
    enabled: bool | None = None
    secret: str | None = None


class WebhookOut(BaseModel):
    id: int
    name: str
    url: str
    events: list[str]
    enabled: bool
    has_secret: bool
    last_fired_at: datetime | None
    last_status: int | None
    created_at: datetime
