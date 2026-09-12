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
    sftp_read_only: Mapped[bool] = mapped_column(Boolean, default=False)
    # Opt-in per server: the diagnostic agent sends this host's command output
    # to the Anthropic API, so it is never on implicitly.
    agent_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    record_sessions: Mapped[bool] = mapped_column(Boolean, default=False)
    # OpenSSH public key line learned on first contact and checked from then on.
    host_key: Mapped[str] = mapped_column(Text, default="")
    jump_via_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("servers.id"), nullable=True
    )
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
    sftp_read_only: bool = False
    agent_enabled: bool = False
    record_sessions: bool = False
    jump_via_id: int | None = None


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
    sftp_read_only: bool | None = None
    agent_enabled: bool | None = None
    record_sessions: bool | None = None
    jump_via_id: int | None = None


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
    sftp_read_only: bool
    agent_enabled: bool = False
    record_sessions: bool = False
    host_key_fingerprint: str = ""
    jump_via_id: int | None = None
    last_connected_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ServerImportItem(ServerCreate):
    """A row from an export file.

    Carries the SOURCE database's ``id`` so the importer can rebuild jump-host
    links by name; ids themselves are never reused, since the target database
    assigns its own. ``jump_via_name`` lets a hand-written or backup file express
    the hop directly, without relying on ids at all.
    """

    id: int | None = None
    jump_via_name: str | None = None


class ServerImport(BaseModel):
    servers: list[ServerImportItem]
