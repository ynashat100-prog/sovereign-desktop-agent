"""Pydantic schemas shared by the HTTP and WebSocket interfaces."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class PermissionLevel(StrEnum):
    SAFE = "safe"
    CONFIRM = "confirm"
    DANGEROUS = "dangerous"


class RunState(StrEnum):
    IDLE = "idle"
    ROUTING = "routing"
    PLANNING = "planning"
    AWAITING_PERMISSION = "awaiting_permission"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class ProviderStatus(BaseModel):
    id: str
    name: str
    kind: Literal["local", "cloud", "vision"]
    available: bool
    detail: str
    models: list[str] = Field(default_factory=list)


class RuntimeStatus(BaseModel):
    runtime_available: bool = True
    demo_mode: bool = False
    ollama: ProviderStatus
    cloud: list[ProviderStatus] = Field(default_factory=list)
    vision: list[ProviderStatus] = Field(default_factory=list)


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    selected_provider: str | None = None
    privacy_mode: Literal["local_only", "hybrid"] = "local_only"
    cloud_consent: bool = False
    allow_screenshot: bool = False
    demo_mode: bool = False


class ProviderUpsertRequest(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str | None = Field(default=None, min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=160)
    fallback_enabled: bool = False
    preset: str | None = None


class OllamaPullRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9._:/-]+$")


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    permission: PermissionLevel
    rationale: str


class PermissionDecision(BaseModel):
    run_id: str
    decision: Literal["allow_once", "allow_always", "deny"]


class AgentResponse(BaseModel):
    run_id: str
    session_id: str
    state: RunState
    message: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    latency_ms: int


class TraceEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    category: Literal[
        "request", "router", "provider", "tool", "permission", "state", "result", "error"
    ]
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SetupCheck(BaseModel):
    key: str
    label: str
    status: Literal["ready", "warning", "unavailable"]
    detail: str


class SetupReport(BaseModel):
    checks: list[SetupCheck]
    recommendations: list[str]
