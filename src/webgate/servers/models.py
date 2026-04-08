from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from webgate.db.engine import Base


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    hostname: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=22)
    username: Mapped[str] = mapped_column(String(255))
    auth_method: Mapped[str] = mapped_column(String(20), default="password")
    encrypted_password: Mapped[str] = mapped_column(Text, default="")
    encrypted_private_key: Mapped[str] = mapped_column(Text, default="")
    group: Mapped[str] = mapped_column(String(255), default="")
    tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON array stored as text
    description: Mapped[str] = mapped_column(Text, default="")
    ssh_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sftp_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sftp_allowed_paths: Mapped[str] = mapped_column(Text, default="[]")  # JSON array of paths
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))


class ServerCreate(BaseModel):
    name: str
    hostname: str
    port: int = 22
    username: str
    auth_method: str = "password"
    password: str = ""
    private_key: str = ""
    group: str = ""
    tags: list[str] = []
    description: str = ""
    ssh_enabled: bool = True
    sftp_enabled: bool = True
    sftp_allowed_paths: list[str] = []


class ServerUpdate(BaseModel):
    name: str | None = None
    hostname: str | None = None
    port: int | None = None
    username: str | None = None
    auth_method: str | None = None
    password: str | None = None
    private_key: str | None = None
    group: str | None = None
    tags: list[str] | None = None
    description: str | None = None
    ssh_enabled: bool | None = None
    sftp_enabled: bool | None = None
    sftp_allowed_paths: list[str] | None = None


class ServerOut(BaseModel):
    id: int
    name: str
    hostname: str
    port: int
    username: str
    auth_method: str
    group: str
    tags: list[str]
    description: str
    ssh_enabled: bool
    sftp_enabled: bool
    sftp_allowed_paths: list[str]
    last_connected_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ServerImport(BaseModel):
    servers: list[ServerCreate]
