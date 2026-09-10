"""Talking to Ollama or OpenRouter through one OpenAI-compatible surface.

Both expose `/v1/chat/completions` with the same request and tool-call shapes, so the
only differences worth abstracting are the base URL, the auth header, and how each
lists its models.

Every function takes the resolved configuration explicitly: the admin can change
provider or model at runtime, so nothing here reads global state.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from webgate.agent.models import ModelOption
from webgate.agent.store import ResolvedAgentConfig
from webgate.config import settings as env_settings

logger = logging.getLogger(__name__)

OLLAMA_DEFAULT = "http://localhost:11434"
OPENROUTER_DEFAULT = "https://openrouter.ai/api"


class ProviderError(RuntimeError):
    """Raised with a message meant to be shown to the operator."""


def base_url(config: ResolvedAgentConfig) -> str:
    if config.base_url:
        return config.base_url.rstrip("/")
    return OLLAMA_DEFAULT if config.provider == "ollama" else OPENROUTER_DEFAULT


def _headers(config: ResolvedAgentConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.provider == "openrouter":
        if not config.api_key:
            raise ProviderError("OpenRouter needs an API key. Add one in Admin -> AI agent.")
        headers["Authorization"] = f"Bearer {config.api_key}"
        headers["X-Title"] = "webgate"  # OpenRouter asks callers to identify themselves
    elif config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    return headers


def _client(config: ResolvedAgentConfig, timeout: float | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout or env_settings.agent_request_timeout,
        proxy=env_settings.agent_proxy_url or None,
        headers=_headers(config),
    )


async def list_models(config: ResolvedAgentConfig) -> list[ModelOption]:
    """Models the configured provider currently offers, for the picker."""
    root = base_url(config)
    if config.provider == "ollama":
        # Ollama's native endpoint reports what is actually pulled on that box.
        async with _client(config, timeout=10) as client:
            resp = await client.get(f"{root}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        out: list[ModelOption] = []
        for entry in data.get("models", []):
            name = entry.get("name") or entry.get("model") or ""
            if not name:
                continue
            size = entry.get("size")
            label = f"{name} ({size / 1e9:.1f} GB)" if isinstance(size, int | float) else name
            out.append(ModelOption(id=name, label=label))
        return sorted(out, key=lambda m: m.id)

    async with _client(config, timeout=20) as client:
        resp = await client.get(f"{root}/v1/models")
        resp.raise_for_status()
        data = resp.json()
    out = []
    for entry in data.get("data", []):
        mid = entry.get("id")
        if not mid:
            continue
        # Surface only models that advertise tool support; the agent is useless without it.
        params = entry.get("supported_parameters") or []
        if params and "tools" not in params:
            continue
        out.append(ModelOption(id=mid, label=entry.get("name") or mid))
    return sorted(out, key=lambda m: m.id)


async def probe(config: ResolvedAgentConfig) -> tuple[bool, str]:
    """Cheap reachability check, so the UI can explain itself instead of hanging."""
    try:
        await list_models(config)
    except ProviderError as exc:
        return False, str(exc)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in (401, 403):
            return False, f"{base_url(config)} rejected the API key ({code})."
        return False, f"{base_url(config)} returned {code}."
    except httpx.RequestError as exc:
        return False, (
            f"Cannot reach {base_url(config)} ({type(exc).__name__}). "
            "The gateway needs this route, not the inspected host."
        )
    return True, ""


async def chat(
    config: ResolvedAgentConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str,
) -> dict[str, Any]:
    """One completion round. Returns the raw assistant message plus usage."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "stream": False,
        # Diagnosis should be reproducible and literal, not creative.
        "temperature": 0.1,
    }
    try:
        async with _client(config) as client:
            resp = await client.post(f"{base_url(config)}/v1/chat/completions", json=payload)
    except httpx.RequestError as exc:
        raise ProviderError(
            f"Cannot reach the model at {base_url(config)} ({type(exc).__name__})."
        ) from exc

    if resp.status_code >= 400:
        raise ProviderError(f"Model API returned {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise ProviderError("Model returned no choices.")
    return {"message": choices[0].get("message") or {}, "usage": data.get("usage") or {}}
