"""Versioned, typed events emitted by the Report Agent runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from report_agent.domain.identifiers import RunIdentity


class EventType(StrEnum):
    RUN_STARTED = "run.started"
    PLAN_UPDATED = "plan.updated"
    SKILL_ACTIVATED = "skill.activated"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    WORKSPACE_CHANGED = "workspace.changed"
    CONTEXT_COMPACTED = "context.compacted"
    APPROVAL_REQUIRED = "approval.required"
    APPROVAL_RESOLVED = "approval.resolved"
    ARTIFACT_CREATED = "artifact.created"
    ARTIFACT_VALIDATED = "artifact.validated"
    RUN_PAUSED = "run.paused"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"


class AgentEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    event_id: str = Field(default_factory=lambda: f"event_{uuid4().hex}")
    type: EventType
    task_id: str
    session_id: str
    run_id: str
    workspace_id: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create(
        cls, event_type: EventType, identity: RunIdentity, payload: dict[str, Any] | None = None
    ) -> AgentEvent:
        return cls(
            type=event_type,
            task_id=identity.task_id,
            session_id=identity.session_id,
            run_id=identity.run_id,
            workspace_id=identity.workspace_id,
            payload=payload or {},
        )
