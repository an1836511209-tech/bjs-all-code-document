"""In-memory repository for deterministic unit and API tests."""

from __future__ import annotations

from datetime import UTC, datetime

from report_agent.domain.artifacts import PublishedArtifact
from report_agent.domain.identifiers import RunIdentity
from report_agent.domain.tasks import StoredRun, StoredTask


class InMemoryRunRepository:
    def __init__(self) -> None:
        self._runs: dict[str, StoredRun] = {}

    def create(self, identity: RunIdentity, user_message: str) -> None:
        now = datetime.now(UTC)
        self._runs[identity.run_id] = StoredRun(
            task_id=identity.task_id,
            session_id=identity.session_id,
            run_id=identity.run_id,
            workspace_id=identity.workspace_id,
            status="running",
            user_message=user_message,
            created_at=now,
            updated_at=now,
        )

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
    ) -> None:
        current = self._runs[identity.run_id]
        self._runs[identity.run_id] = current.model_copy(
            update={
                "status": status,
                "assistant_text": assistant_text,
                "trace": trace,
                "artifacts": artifacts,
                "skill_name": skill_name,
                "skill_route": skill_route,
                "updated_at": datetime.now(UTC),
            }
        )

    def fail(self, identity: RunIdentity, error_type: str) -> None:
        current = self._runs[identity.run_id]
        self._runs[identity.run_id] = current.model_copy(
            update={"status": "failed", "error_type": error_type, "updated_at": datetime.now(UTC)}
        )

    def get_run(self, run_id: str) -> StoredRun | None:
        return self._runs.get(run_id)

    def get_task(self, task_id: str) -> StoredTask | None:
        runs = [run for run in self._runs.values() if run.task_id == task_id]
        if not runs:
            return None
        return StoredTask(
            task_id=task_id,
            workspace_id=runs[0].workspace_id,
            status=runs[-1].status,
            session_ids=list(dict.fromkeys(run.session_id for run in runs)),
            run_ids=[run.run_id for run in runs],
            artifact_ids=[artifact.artifact_id for run in runs for artifact in run.artifacts],
            created_at=runs[0].created_at,
            updated_at=runs[-1].updated_at,
        )

    def get_artifact(self, artifact_id: str) -> PublishedArtifact | None:
        for run in self._runs.values():
            for artifact in run.artifacts:
                if artifact.artifact_id == artifact_id:
                    return artifact
        return None
