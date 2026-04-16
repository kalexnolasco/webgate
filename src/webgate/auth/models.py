import json
from datetime import datetime

from pydantic import BaseModel, field_validator
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from webgate.db.engine import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    allowed_groups: Mapped[str] = mapped_column(Text, default="[]")  # JSON array of group names
    totp_secret: Mapped[str] = mapped_column(String(255), default="")
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255))
    key_hash: Mapped[str] = mapped_column(String(255))
    key_prefix: Mapped[str] = mapped_column(String(10))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserCreate(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str
    totp_code: str = ""


class UserOut(BaseModel):
    id: int
    username: str
    is_admin: bool
    must_change_password: bool = False
    totp_enabled: bool = False
    allowed_groups: list[str] = []

    model_config = {"from_attributes": True}

    @field_validator("allowed_groups", mode="before")
    @classmethod
    def parse_groups(cls, v: object) -> list[str]:
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                return []
        return v if isinstance(v, list) else []


class UserManage(BaseModel):
    username: str
    password: str = ""
    allowed_groups: list[str] = []


class UserUpdateGroups(BaseModel):
    allowed_groups: list[str]


class ChangePassword(BaseModel):
    new_password: str


class TotpSetupOut(BaseModel):
    secret: str
    qr_uri: str
    qr_base64: str


class TotpVerifyIn(BaseModel):
    code: str


class TotpStatusOut(BaseModel):
    enabled: bool


class LoginOut(BaseModel):
    access_token: str = ""
    token_type: str = "bearer"
    requires_2fa: bool = False
    temp_token: str = ""


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ApiKeyCreate(BaseModel):
    name: str


class ApiKeyOut(BaseModel):
    id: int
    name: str
    key_prefix: str
    last_used_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreated(BaseModel):
    id: int
    name: str
    key: str
    key_prefix: str
