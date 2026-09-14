"""Validated public API payloads. No typed text or clipboard content is accepted."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

Visibility = Literal["visible", "hidden", "prerender", "unloaded", "unknown"]
EventType = Literal[
    "visibilitychange", "blur", "focus", "fullscreenchange", "beforeunload",
    "pagehide", "pageshow", "copy", "paste", "cut", "contextmenu", "keydown",
    "pointerleave", "pointerenter", "domcontentloaded", "fullscreen_error",
    "online", "offline", "fetch_failure", "editor_change",
]


class StrictModel(BaseModel):
    model_config = {"extra": "forbid"}


class SessionStart(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    started_at: datetime | None = None  # Client hint; server records its own start time.
    user_agent: str = Field(max_length=512)
    platform: str = Field(max_length=128)
    screen_width: int = Field(ge=0, le=100000)
    screen_height: int = Field(ge=0, le=100000)
    viewport_width: int | None = Field(default=None, ge=0, le=100000)
    viewport_height: int | None = Field(default=None, ge=0, le=100000)
    language: str | None = Field(default=None, max_length=64)
    hardware_concurrency: int | None = Field(default=None, ge=1, le=1024)
    device_memory: float | None = Field(default=None, ge=0, le=1024, allow_inf_nan=False)
    timezone: str | None = Field(default=None, max_length=128)
    duration_minutes: Literal[30, 45, 60, 90] = 60


class SessionEnd(StrictModel):
    session_id: UUID


class EventIn(StrictModel):
    event_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    event_type: EventType
    sequence: int | None = Field(default=None, ge=0, le=2_147_483_647)
    performance_ms: float | None = Field(default=None, ge=0, le=1_000_000_000_000, allow_inf_nan=False)
    timestamp_client: datetime
    visibility_state: Visibility
    document_has_focus: bool
    fullscreen: bool
    screen_width: int = Field(ge=0, le=100000)
    screen_height: int = Field(ge=0, le=100000)
    viewport_width: int = Field(ge=0, le=100000)
    viewport_height: int = Field(ge=0, le=100000)
    user_agent: str = Field(max_length=512)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def validate_safe_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False)) > 2048:
            raise ValueError("metadata exceeds 2048 characters")
        # Event-specific checks happen in the endpoint, once event_type is known.
        for key in value:
            if re.search(r"key|text|content|data", key, re.IGNORECASE) and key != "keyCategory":
                raise ValueError("metadata may not contain keystroke or clipboard content")
        return value


class HeartbeatIn(StrictModel):
    session_id: UUID
    sequence: int = Field(ge=0, le=2_147_483_647)
    client_timestamp: datetime
    performance_ms: float | None = Field(default=None, ge=0, le=1_000_000_000_000, allow_inf_nan=False)
    visibility_state: Visibility
    has_focus: bool
    fullscreen: bool


class MarkerIn(StrictModel):
    session_id: UUID
    label: str = Field(min_length=1, max_length=200)
    timestamp_client: datetime

    @field_validator("label")
    @classmethod
    def clean_label(cls, value: str) -> str:
        cleaned = " ".join("".join(ch for ch in value if ch.isprintable()).split())
        if not cleaned or len(cleaned) > 100:
            raise ValueError("marker label must contain 1 to 100 printable characters")
        return cleaned


class SubmissionIn(StrictModel):
    """A simulated judge request containing metadata only, never source code."""

    session_id: UUID
    question_id: Literal["q1", "q2", "q3"]
    language: Literal["C", "C++", "Java", "Python"]
    action: Literal["run", "submit"]
    code_length: int = Field(ge=0, le=1_000_000)
    timestamp_client: datetime
