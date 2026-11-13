"""Append-only workspace audit event sink."""

from __future__ import annotations

from report_agent.domain.events import AgentEvent
from report_agent.runtime.workspace import TaskWorkspace


class WorkspaceAuditLog:
    def __init__(self, workspace: TaskWorkspace) -> None:
        self._workspace = workspace

    def append(self, event: AgentEvent) -> None:
        payload = event.model_dump_json(exclude_none=True)
        self._workspace.append_text("/workspace/logs/audit.ndjson", payload + "\n")
