"""Persistent task, session and run read models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from report_agent.domain.artifacts import PublishedArtifact


class StoredRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    session_id: str
    run_id: str
    workspace_id: str
    status: str
    user_message: str
    assistant_text: str = ""
    trace: list[dict] = Field(default_factory=list)
    artifacts: list[PublishedArtifact] = Field(default_factory=list)
    error_type: str | None = None
    skill_name: str | None = None
    skill_route: str | None = None
    created_at: datetime
    updated_at: datetime


class StoredTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    workspace_id: str
    status: str
    session_ids: list[str] = Field(default_factory=list)
    run_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
