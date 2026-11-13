"""Persistence ports owned by the Report Agent application layer."""

from __future__ import annotations

from typing import Protocol

from report_agent.domain.artifacts import PublishedArtifact
from report_agent.domain.identifiers import RunIdentity
from report_agent.domain.tasks import StoredRun, StoredTask


class RunRepository(Protocol):
    def create(self, identity: RunIdentity, user_message: str) -> None: ...

    def finish(
        self,
        identity: RunIdentity,
        *,
        status: str,
        assistant_text: str,
        trace: list[dict],
        artifacts: list[PublishedArtifact],
        skill_name: str | None = None,
        skill_route: str | None = None,
    ) -> None: ...

    def fail(self, identity: RunIdentity, error_type: str) -> None: ...

    def get_run(self, run_id: str) -> StoredRun | None: ...

    def get_task(self, task_id: str) -> StoredTask | None: ...

    def get_artifact(self, artifact_id: str) -> PublishedArtifact | None: ...
