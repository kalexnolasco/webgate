"""Agent configuration, owned by the admin rather than the deployment.

A single row holds what the admin sets in the UI. Environment variables still work,
but only as the initial value for a fresh install (Docker, automated provisioning);
once a row exists it wins, so changing provider or model never needs a restart.

The API key is encrypted with the same Fernet key that protects server credentials.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from webgate.config import settings as env_settings
from webgate.db.engine import Base
from webgate.servers.crypto import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)

VALID_PROVIDERS = ("ollama", "openrouter")


class AgentSettings(Base):
    """Singleton row: there is one agent configuration per gateway."""

    __tablename__ = "agent_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(32), default="ollama")
    base_url: Mapped[str] = mapped_column(Text, default="")
    encrypted_api_key: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(255), default="")
    # Model rounds, not commands: one round may request several tools at once.
    max_steps: Mapped[int] = mapped_column(Integer, default=12)
    command_timeout: Mapped[int] = mapped_column(Integer, default=20)
    context_budget: Mapped[int] = mapped_column(Integer, default=24000)
    cache_ttl: Mapped[int] = mapped_column(Integer, default=60)
    findings_retention_days: Mapped[int] = mapped_column(Integer, default=90)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    updated_by: Mapped[str] = mapped_column(String(150), default="")


@dataclass
class ResolvedAgentConfig:
    """What the rest of the agent code reads. Never leaves the server with the key."""

    enabled: bool
    provider: str
    base_url: str
    api_key: str
    model: str
    max_steps: int
    command_timeout: int
    context_budget: int
    cache_ttl: int
    findings_retention_days: int
    configured: bool  # an admin has saved settings at least once
    source: str  # "database" or "environment"

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


def _from_env() -> ResolvedAgentConfig:
    return ResolvedAgentConfig(
        enabled=bool(env_settings.agent_enabled),
        provider=(env_settings.agent_provider or "ollama").lower(),
        base_url=env_settings.agent_base_url or "",
        api_key=env_settings.agent_api_key or "",
        model=env_settings.agent_model or "",
        max_steps=env_settings.agent_max_steps,
        command_timeout=env_settings.agent_command_timeout,
        context_budget=env_settings.agent_context_budget,
        cache_ttl=env_settings.agent_cache_ttl,
        findings_retention_days=env_settings.agent_findings_retention_days,
        configured=bool(env_settings.agent_enabled),
        source="environment",
    )


async def load_config(session: AsyncSession) -> ResolvedAgentConfig:
    row = (await session.execute(select(AgentSettings).limit(1))).scalar_one_or_none()
    if row is None:
        return _from_env()
    return ResolvedAgentConfig(
        enabled=bool(row.enabled),
        provider=(row.provider or "ollama").lower(),
        base_url=row.base_url or "",
        api_key=decrypt_value(row.encrypted_api_key) if row.encrypted_api_key else "",
        model=row.model or "",
        max_steps=row.max_steps or 12,
        command_timeout=row.command_timeout or 20,
        context_budget=row.context_budget or 24000,
        cache_ttl=row.cache_ttl if row.cache_ttl is not None else 60,
        findings_retention_days=(
            row.findings_retention_days if row.findings_retention_days is not None else 90
        ),
        configured=True,
        source="database",
    )


async def save_config(
    session: AsyncSession,
    *,
    enabled: bool,
    provider: str,
    base_url: str,
    model: str,
    api_key: str | None,
    max_steps: int,
    command_timeout: int,
    context_budget: int,
    cache_ttl: int,
    findings_retention_days: int,
    updated_by: str,
) -> ResolvedAgentConfig:
    """Persist what the admin submitted.

    ``api_key=None`` means "leave the stored key alone" — the UI never receives the
    key back, so it cannot echo it, and an empty string is a deliberate clearing.
    """
    provider = (provider or "ollama").lower()
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}.")

    row = (await session.execute(select(AgentSettings).limit(1))).scalar_one_or_none()
    if row is None:
        row = AgentSettings(id=1)
        session.add(row)

    row.enabled = enabled
    row.provider = provider
    row.base_url = (base_url or "").strip().rstrip("/")
    row.model = (model or "").strip()
    row.max_steps = max(1, min(int(max_steps or 12), 40))
    row.command_timeout = max(5, min(int(command_timeout or 20), 120))
    row.context_budget = max(4000, min(int(context_budget or 24000), 400000))
    # Zero disables reuse; the ceiling keeps a stale reading from ever looking fresh.
    row.cache_ttl = max(0, min(int(cache_ttl if cache_ttl is not None else 60), 900))
    row.findings_retention_days = max(0, min(int(findings_retention_days or 90), 3650))
    row.updated_by = updated_by
    row.updated_at = datetime.now()
    if api_key is not None:
        row.encrypted_api_key = encrypt_value(api_key) if api_key else ""

    await session.commit()
    await session.refresh(row)
    return await load_config(session)
