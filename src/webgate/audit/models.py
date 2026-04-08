from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from webgate.db.engine import Base


class AuditEntry(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer)
    username: Mapped[str] = mapped_column(String(150))
    action: Mapped[str] = mapped_column(String(50))  # login, ssh_connect, sftp_ls, server_create, etc.
    detail: Mapped[str] = mapped_column(Text, default="")
    ip_address: Mapped[str] = mapped_column(String(45), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditOut(BaseModel):
    id: int
    user_id: int
    username: str
    action: str
    detail: str
    ip_address: str
    created_at: datetime

    model_config = {"from_attributes": True}
