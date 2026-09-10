from typing import Any, Literal

from pydantic import BaseModel, Field


class ModelOption(BaseModel):
    """One entry in the model picker."""

    id: str
    label: str


class ProviderStatus(BaseModel):
    provider: Literal["ollama", "openrouter"]
    reachable: bool
    base_url: str
    detail: str = ""
    models: list[ModelOption] = []
    selected: str = ""


class DiagnoseRequest(BaseModel):
    server_id: int
    question: str = Field(default="", max_length=2000)
    model: str = ""  # overrides the configured default for this run


class AgentStep(BaseModel):
    command: str
    exit_status: int | None = None
    output: str = ""
    error: str = ""
    cached_age: int | None = None  # seconds, when the result was reused


class ConversationTurn(BaseModel):
    role: str  # "user" or "agent"
    text: str
    commands: list[str] = []


class ConversationOut(BaseModel):
    server: str
    turns: list[ConversationTurn] = []
    exchanges: int = 0


class DiagnoseResult(BaseModel):
    server: str
    model: str
    provider: str
    answer: str
    steps: list[AgentStep]
    truncated: bool = False
    usage: dict[str, Any] = {}
    turns: list[ConversationTurn] = []
