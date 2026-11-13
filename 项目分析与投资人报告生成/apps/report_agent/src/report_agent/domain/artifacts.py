"""Published artifact contract returned by service-owned object storage."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


def artifact_download_path(artifact_id: str) -> str:
    """Stable public download entry; object-storage signatures stay internal."""
    return f"/api/artifacts/{artifact_id}/content"


class PublishedArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_id: str = Field(pattern=r"^artifact_[a-f0-9]{32}$")
    filename: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int = Field(ge=1)
    bucket: str
    object_key: str
    download_url: str
    expires_at: datetime
