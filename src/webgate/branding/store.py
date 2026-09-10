"""Branding state and validation."""

from __future__ import annotations

import base64
import binascii
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from webgate.db.engine import Base

logger = logging.getLogger(__name__)

# Anything a browser will render as an <img>, plus SVG which companies usually have.
ALLOWED_IMAGE_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/gif": "gif",
    "image/x-icon": "ico",
    "image/vnd.microsoft.icon": "ico",
}
MAX_IMAGE_BYTES = 1024 * 1024  # a logo, not a photograph

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# A tab icon may be one or two emoji, matching how the rest of the product names things.
_MAX_EMOJI_LEN = 8

# Every colour the interface derives from. Blank means "keep the shipped default",
# so a company can set two and leave the rest alone.
COLOR_KEYS = (
    "accent",
    "accent_fg",
    "bg_primary",
    "bg_secondary",
    "text_primary",
    "danger",
    "warning",
    "info",
)


class Branding(Base):
    """Singleton row: one look per gateway."""

    __tablename__ = "branding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    app_name: Mapped[str] = mapped_column(String(80), default="")
    tagline: Mapped[str] = mapped_column(String(160), default="")
    favicon_emoji: Mapped[str] = mapped_column(String(16), default="")
    colors: Mapped[str] = mapped_column(Text, default="{}")  # JSON, hex per COLOR_KEYS
    colors_dark: Mapped[str] = mapped_column(Text, default="{}")
    logo: Mapped[str] = mapped_column(Text, default="")  # data: URI
    login_image: Mapped[str] = mapped_column(Text, default="")
    favicon: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    updated_by: Mapped[str] = mapped_column(String(150), default="")


@dataclass
class BrandingView:
    """What the frontend needs to paint itself, safe for anyone to read."""

    app_name: str = ""
    tagline: str = ""
    favicon_emoji: str = ""
    colors: dict[str, str] | None = None
    colors_dark: dict[str, str] | None = None
    logo: str = ""
    login_image: str = ""
    favicon: str = ""
    customised: bool = False

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["colors"] = self.colors or {}
        data["colors_dark"] = self.colors_dark or {}
        return data


class BrandingError(ValueError):
    """Rejected input, with a message meant for the admin."""


def validate_color(value: str, *, field: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if not _HEX.match(value):
        raise BrandingError(f"{field} must be a hex colour like #1a73e8, not {value!r}.")
    return value.lower()


def validate_colors(raw: dict[str, str] | None, *, label: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (raw or {}).items():
        if key not in COLOR_KEYS:
            raise BrandingError(f"{key!r} is not a colour this interface uses.")
        cleaned = validate_color(value, field=f"{label} {key}")
        if cleaned:
            out[key] = cleaned
    return out


def validate_image(data_uri: str, *, field: str) -> str:
    """Accept a data: URI of a known image type, within a sane size.

    The value is re-encoded from its decoded bytes rather than passed through, so a
    payload that merely *looks* like base64 cannot reach an ``<img src>`` intact.
    """
    value = (data_uri or "").strip()
    if not value:
        return ""
    if not value.startswith("data:"):
        raise BrandingError(f"{field} must be an uploaded image.")
    try:
        header, payload = value.split(",", 1)
        media_type = header[5:].split(";", 1)[0].strip().lower()
    except ValueError as exc:
        raise BrandingError(f"{field} is not a readable image.") from exc

    if media_type not in ALLOWED_IMAGE_TYPES:
        allowed = ", ".join(sorted({v for v in ALLOWED_IMAGE_TYPES.values()}))
        raise BrandingError(f"{field} must be one of: {allowed}.")
    if ";base64" not in header:
        raise BrandingError(f"{field} must be base64 encoded.")
    try:
        blob = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BrandingError(f"{field} is not valid base64.") from exc
    if not blob:
        raise BrandingError(f"{field} is empty.")
    if len(blob) > MAX_IMAGE_BYTES:
        raise BrandingError(
            f"{field} is {len(blob) // 1024} KB; the limit is {MAX_IMAGE_BYTES // 1024} KB."
        )
    return f"data:{media_type};base64,{base64.b64encode(blob).decode()}"


def validate_emoji(value: str) -> str:
    value = (value or "").strip()
    if len(value) > _MAX_EMOJI_LEN:
        raise BrandingError("The tab icon should be one or two characters.")
    return value


def _view(row: Branding | None) -> BrandingView:
    import json

    if row is None:
        return BrandingView()
    try:
        colors = json.loads(row.colors or "{}")
        colors_dark = json.loads(row.colors_dark or "{}")
    except json.JSONDecodeError:
        colors, colors_dark = {}, {}
    return BrandingView(
        app_name=row.app_name or "",
        tagline=row.tagline or "",
        favicon_emoji=row.favicon_emoji or "",
        colors=colors,
        colors_dark=colors_dark,
        logo=row.logo or "",
        login_image=row.login_image or "",
        favicon=row.favicon or "",
        customised=any(
            [row.app_name, row.tagline, row.favicon_emoji, colors, colors_dark,
             row.logo, row.login_image, row.favicon]
        ),
    )


async def load(session: AsyncSession) -> BrandingView:
    row = (await session.execute(select(Branding).limit(1))).scalar_one_or_none()
    return _view(row)


async def save(
    session: AsyncSession,
    *,
    app_name: str,
    tagline: str,
    favicon_emoji: str,
    colors: dict[str, str] | None,
    colors_dark: dict[str, str] | None,
    logo: str | None,
    login_image: str | None,
    favicon: str | None,
    updated_by: str,
) -> BrandingView:
    """Persist a look.

    An image field of ``None`` means "leave it alone", so saving colours does not
    silently drop a logo; an empty string is a deliberate removal.
    """
    import json

    row = (await session.execute(select(Branding).limit(1))).scalar_one_or_none()
    if row is None:
        row = Branding(id=1)
        session.add(row)

    row.app_name = (app_name or "").strip()[:80]
    row.tagline = (tagline or "").strip()[:160]
    row.favicon_emoji = validate_emoji(favicon_emoji)
    row.colors = json.dumps(validate_colors(colors, label="light"))
    row.colors_dark = json.dumps(validate_colors(colors_dark, label="dark"))
    if logo is not None:
        row.logo = validate_image(logo, field="The logo")
    if login_image is not None:
        row.login_image = validate_image(login_image, field="The sign-in image")
    if favicon is not None:
        row.favicon = validate_image(favicon, field="The tab icon")
    row.updated_by = updated_by
    row.updated_at = datetime.now()

    await session.commit()
    await session.refresh(row)
    return _view(row)


async def reset(session: AsyncSession) -> BrandingView:
    row = (await session.execute(select(Branding).limit(1))).scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.commit()
    return BrandingView()
