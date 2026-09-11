import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from webgate.agent import conversation, memory, provider
from webgate.agent.models import (
    ConversationOut,
    DiagnoseRequest,
    DiagnoseResult,
    ModelOption,
    ProviderStatus,
)
from webgate.agent.service import run_turn
from webgate.agent.store import ResolvedAgentConfig, load_config, save_config
from webgate.audit.service import log_action
from webgate.auth.models import UserOut
from webgate.auth.routes import get_current_user
from webgate.config import settings
from webgate.db.engine import get_session
from webgate.servers.service import get_server, list_servers

router = APIRouter(prefix="/api/agent", tags=["agent"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[UserOut, Depends(get_current_user)]


class AgentSettingsIn(BaseModel):
    enabled: bool = False
    provider: Literal["ollama", "openrouter"] = "ollama"
    base_url: str = ""
    model: str = ""
    # Omitted entirely -> keep whatever is stored. "" -> deliberately clear it.
    api_key: str | None = None
    max_steps: int = Field(default=12, ge=1, le=40)
    command_timeout: int = Field(default=20, ge=5, le=120)
    context_budget: int = Field(default=24000, ge=4000, le=400000)
    cache_ttl: int = Field(default=60, ge=0, le=900)
    findings_retention_days: int = Field(default=90, ge=0, le=3650)


class AgentSettingsOut(BaseModel):
    """Never carries the API key back out — only whether one is stored."""

    enabled: bool
    provider: str
    base_url: str
    effective_base_url: str
    model: str
    has_api_key: bool
    max_steps: int
    command_timeout: int
    context_budget: int
    cache_ttl: int
    findings_retention_days: int
    configured: bool
    source: str
    editable: bool


def _require_admin(user: UserOut) -> None:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required"
        )


def _deny_in_demo() -> None:
    if settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The diagnostic agent is disabled in demo mode",
        )


def _as_out(config: ResolvedAgentConfig) -> AgentSettingsOut:
    return AgentSettingsOut(
        enabled=config.enabled,
        provider=config.provider,
        base_url=config.base_url,
        effective_base_url=provider.base_url(config),
        model=config.model,
        has_api_key=config.has_api_key,
        max_steps=config.max_steps,
        command_timeout=config.command_timeout,
        context_budget=config.context_budget,
        cache_ttl=config.cache_ttl,
        findings_retention_days=config.findings_retention_days,
        configured=config.configured,
        source=config.source,
        editable=not settings.demo_mode,
    )


# ----------------------------------------------------------------- configuration


@router.get("/settings", response_model=AgentSettingsOut)
async def read_settings(session: SessionDep, current_user: CurrentUserDep) -> AgentSettingsOut:
    _require_admin(current_user)
    return _as_out(await load_config(session))


@router.put("/settings", response_model=AgentSettingsOut)
async def write_settings(
    body: AgentSettingsIn,
    request: Request,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> AgentSettingsOut:
    _require_admin(current_user)
    _deny_in_demo()
    try:
        config = await save_config(
            session,
            enabled=body.enabled,
            provider=body.provider,
            base_url=body.base_url,
            model=body.model,
            api_key=body.api_key,
            max_steps=body.max_steps,
            command_timeout=body.command_timeout,
            context_budget=body.context_budget,
            cache_ttl=body.cache_ttl,
            findings_retention_days=body.findings_retention_days,
            updated_by=current_user.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await log_action(
        current_user.id,
        current_user.username,
        "agent_settings_update",
        detail=(
            f"provider={config.provider} enabled={config.enabled} "
            f"model={config.model or 'unset'} key={'set' if config.has_api_key else 'none'}"
        ),
        ip_address=request.client.host if request.client else "",
    )
    return _as_out(config)


@router.post("/settings/test", response_model=ProviderStatus)
async def test_settings(
    body: AgentSettingsIn, session: SessionDep, current_user: CurrentUserDep
) -> ProviderStatus:
    """Try the submitted settings without saving them, so the picker can fill in."""
    _require_admin(current_user)
    _deny_in_demo()

    stored = await load_config(session)
    # A blank key in the form means "use the one already stored", not "no key".
    api_key = body.api_key if body.api_key is not None else stored.api_key
    candidate = ResolvedAgentConfig(
        enabled=True,
        provider=body.provider,
        base_url=body.base_url,
        api_key=api_key or "",
        model=body.model,
        max_steps=body.max_steps,
        command_timeout=body.command_timeout,
        context_budget=body.context_budget,
        cache_ttl=body.cache_ttl,
        findings_retention_days=body.findings_retention_days,
        configured=True,
        source=stored.source,
    )
    reachable, detail = await provider.probe(candidate)
    models: list[ModelOption] = await provider.list_models(candidate) if reachable else []
    return ProviderStatus(
        provider=candidate.provider,  # type: ignore[arg-type]
        reachable=reachable,
        base_url=provider.base_url(candidate),
        detail=detail,
        models=models,
        selected=body.model or (models[0].id if models else ""),
    )


# --------------------------------------------------------------------- diagnosis


async def _active_config(session: AsyncSession) -> ResolvedAgentConfig:
    _deny_in_demo()
    config = await load_config(session)
    if not config.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "The AI agent is not set up on this gateway. An admin can configure it "
                "in Admin -> AI agent."
            ),
        )
    return config


@router.get("/status", response_model=ProviderStatus)
async def agent_status(session: SessionDep, current_user: CurrentUserDep) -> ProviderStatus:
    config = await _active_config(session)
    reachable, detail = await provider.probe(config)
    models = await provider.list_models(config) if reachable else []
    return ProviderStatus(
        provider=config.provider,  # type: ignore[arg-type]
        reachable=reachable,
        base_url=provider.base_url(config),
        detail=detail,
        models=models,
        selected=config.model or (models[0].id if models else ""),
    )


# ----------------------------------------------------------------------- findings


async def _reachable_server_ids(session: AsyncSession, current_user: UserOut):
    """None for an admin (everything), otherwise the ids this user's groups allow."""
    if current_user.is_admin:
        return None
    groups = current_user.allowed_groups
    if isinstance(groups, str):
        groups = json.loads(groups or "[]")
    servers = await list_servers(
        session, current_user.id, is_admin=False, allowed_groups=groups or []
    )
    return [s.id for s in servers]


@router.get("/findings")
async def search_findings(
    session: SessionDep,
    current_user: CurrentUserDep,
    q: str = "",
    server_id: int | None = None,
) -> dict[str, Any]:
    """Past answers, searched by the words you type.

    Every word must appear somewhere in the finding, which is what people expect when
    they type two of them and keeps the result set small without ranking.
    """
    await _active_config(session)
    server_ids = await _reachable_server_ids(session, current_user)

    if not q.strip():
        rows = await memory.recent(
            session, user_id=current_user.id, server_ids=server_ids, server_id=server_id
        )
        return {"mode": "recent", "results": [memory.to_dict(r) for r in rows]}

    rows = await memory.search_keywords(
        session, q, user_id=current_user.id, server_ids=server_ids, server_id=server_id
    )
    return {"mode": "keywords", "results": [memory.to_dict(r) for r in rows]}


@router.delete("/findings/{finding_id}")
async def delete_finding(
    finding_id: int, session: SessionDep, current_user: CurrentUserDep
) -> dict[str, bool]:
    await _active_config(session)
    removed = await memory.forget(
        session, finding_id, user_id=current_user.id, is_admin=current_user.is_admin
    )
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")
    return {"deleted": True}


@router.post("/findings/purge")
async def purge_findings(session: SessionDep, current_user: CurrentUserDep) -> dict[str, int]:
    """Apply the retention window now. Findings hold production command output."""
    _require_admin(current_user)
    config = await _active_config(session)
    return {"deleted": await memory.purge_older_than(session, config.findings_retention_days)}


async def _resolve_server(session: AsyncSession, server_id: int, current_user: UserOut):
    """The caller's own ACL decides: the agent reaches nothing they could not."""
    groups = current_user.allowed_groups
    if isinstance(groups, str):
        groups = json.loads(groups or "[]")
    server = await get_server(
        session,
        server_id,
        current_user.id,
        is_admin=current_user.is_admin,
        allowed_groups=groups or [],
    )
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    if not server.agent_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"The agent is not enabled for {server.name}. An admin can turn it on in "
                "the server's settings."
            ),
        )
    if server.ssh_enabled is False and server.sftp_enabled is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(f"{server.name} has both SSH and SFTP disabled, so there is no way in."),
        )
    return server


@router.get("/chat/{server_id}", response_model=ConversationOut)
async def read_conversation(
    server_id: int, session: SessionDep, current_user: CurrentUserDep
) -> ConversationOut:
    """The transcript so far, so reopening the panel resumes where it left off."""
    await _active_config(session)
    server = await _resolve_server(session, server_id, current_user)
    messages = await conversation.load(session, current_user.id, server_id)
    return ConversationOut(
        server=server.name,
        turns=conversation.to_display(messages),
        exchanges=sum(1 for m in messages if m.get("role") == "user"),
    )


@router.delete("/chat/{server_id}", response_model=ConversationOut)
async def clear_conversation(
    server_id: int, session: SessionDep, current_user: CurrentUserDep
) -> ConversationOut:
    config = await _active_config(session)
    server = await _resolve_server(session, server_id, current_user)
    await conversation.clear(session, current_user.id, server_id)
    del config
    return ConversationOut(server=server.name, turns=[], exchanges=0)


@router.post("/diagnose", response_model=DiagnoseResult)
async def diagnose(
    body: DiagnoseRequest,
    request: Request,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> DiagnoseResult:
    config = await _active_config(session)
    server = await _resolve_server(session, body.server_id, current_user)

    model = (body.model or config.model or "").strip()
    if not model:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose a model first.")

    history = await conversation.load(session, current_user.id, server.id)
    try:
        result, messages = await run_turn(
            session,
            server,
            config=config,
            question=body.question,
            model=model,
            user_id=current_user.id,
            username=current_user.username,
            history=history,
            ip_address=request.client.host if request.client else "",
        )
    except provider.ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await conversation.save(session, current_user.id, server.id, messages)

    # Keep the answer so it can be found again.
    await memory.record(
        session,
        server_id=server.id,
        server_name=server.name,
        user_id=current_user.id,
        username=current_user.username,
        question=body.question,
        answer=result.answer,
        tools=[s.command for s in result.steps],
        model=model,
    )
    result.turns = conversation.to_display(messages)
    return result
