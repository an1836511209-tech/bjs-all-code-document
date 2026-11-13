"""Document artifact and validation contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DocumentIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(pattern=r"^[A-Z0-9_]{1,64}$")
    message: str


class DocumentArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str = Field(pattern=r"^artifact_[a-f0-9]{32}$")
    path: str = Field(pattern=r"^/workspace/(output|staging)/")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    skill_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    comment_count: int = Field(ge=0)
    valid: bool
    issues: tuple[DocumentIssue, ...] = ()
