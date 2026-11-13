"""Inject deterministic workspace recovery state and phase instructions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest
from langchain_core.messages import SystemMessage

from report_agent.application.context_store import WorkspaceContextStore
from report_agent.runtime.workspace import TaskWorkspace
from report_agent.skills.catalog import SkillCatalog

PHASE_REFERENCES = {
    "ingested": ("material-ingestion",),
    "materials_ready": ("material-ingestion",),
    "collecting_data": ("evidence-and-missing-data",),
    "data_ready": ("report-outline", "evidence-and-missing-data"),
    "writing": ("report-outline", "evidence-and-missing-data"),
    "report_ready": ("word-production", "template-layout", "evidence-and-missing-data"),
    "word_created": ("word-production", "template-layout", "evidence-and-missing-data"),
    "docx_rendered": ("word-production", "template-layout", "evidence-and-missing-data"),
    "validated": ("word-production", "template-layout"),
    "staged": ("word-production", "template-layout"),
}


class WorkspaceContextMiddleware(AgentMiddleware[Any, Any, Any]):
    def __init__(
        self,
        store: WorkspaceContextStore,
        workspace: TaskWorkspace,
        reference_names: tuple[str, ...],
    ) -> None:
        self._store = store
        self._workspace = workspace
        self._reference_names = frozenset(reference_names)

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelCallResult[Any]]],
    ) -> ModelCallResult[Any]:
        phase = self._store.phase()
        active_references: list[tuple[str, str]] = []
        for name in PHASE_REFERENCES.get(phase, ()):
            if name in self._reference_names:
                active_references.append(
                    (name, SkillCatalog.read_staged_reference(self._workspace, name))
                )
                self._store.mark_reference_loaded(name)
        references = "".join(
            f"\n\n# Active Skill reference: {name}\n{content}"
            for name, content in active_references
        )
        addition = (
            "\n\n# Program-maintained workspace context\n"
            + self._store.working_memory()
            + references
        )
        current = request.system_prompt or ""
        return await handler(
            request.override(system_message=SystemMessage(content=current + addition))
        )
