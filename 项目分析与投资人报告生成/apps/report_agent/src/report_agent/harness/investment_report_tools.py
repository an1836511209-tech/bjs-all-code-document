"""Assemble and enforce the complete Investment Report Skill toolset."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from report_agent.application.context_store import WorkspaceContextStore
from report_agent.application.data_gateway import DataMcpGateway
from report_agent.application.investor_export import build_investor_export_tools
from report_agent.application.materials import MaterialIngestionService
from report_agent.application.reports import ReportContentService
from report_agent.application.review_checker import QualityChecker
from report_agent.application.word_reports import WordReportService
from report_agent.domain.outline import outline_loader
from report_agent.harness.context_tools import build_context_tools
from report_agent.harness.data_tools import build_data_mcp_tools
from report_agent.harness.evidence_tools import build_evidence_tools
from report_agent.harness.filesystem_tools import build_filesystem_tools
from report_agent.harness.ask_user_tools import build_ask_user_tools
from report_agent.harness.ideology_tools import build_ideology_tools
from report_agent.harness.material_tools import build_material_tools
from report_agent.harness.report_tools import build_report_tools
from report_agent.harness.review_tools import build_review_tools
from report_agent.harness.word_tools import build_word_tools
from report_agent.infrastructure.evidence import WorkspaceEvidenceStore
from report_agent.infrastructure.materials.parser import MaterialParser
from report_agent.runtime.workspace import TaskWorkspace
from report_agent.settings.ideology_settings import resolve_ideology_dictionary_path
from report_agent.skills import SkillCatalog, SkillDescriptor, ToolPolicy


def build_investment_report_tools(
    *,
    skill: SkillDescriptor,
    gateway: DataMcpGateway,
    workspace: TaskWorkspace,
    backend: Any = None,
    publisher_tools: Iterable[BaseTool] = (),
    publish=None,
    word_service: WordReportService | None = None,
    context_store: WorkspaceContextStore | None = None,
    skill_reference_names: tuple[str, ...] = (),
    visual_review_required: bool = True,
    word_workspace: TaskWorkspace | None = None,
    ideology_dictionary_path: Path | None = None,
    quality_checker: QualityChecker | None = None,
    material_parser: MaterialParser | None = None,
    upload_material_md=None,
    task_id: str = "",
) -> tuple[BaseTool, ...]:
    evidence_store = WorkspaceEvidenceStore(workspace)
    report_service = ReportContentService(workspace, evidence_store)
    tool_context_store = context_store or WorkspaceContextStore(workspace)
    reference_names = skill_reference_names or SkillCatalog.stage_references(skill, workspace)
    if material_parser is None:
        raise ValueError("material_parser is required")
    resolved_ideology_path = resolve_ideology_dictionary_path(
        explicit=ideology_dictionary_path,
    )
    if quality_checker is None:
        outline_path = str(
            Path("apps/report_agent/skills/investment-report/references/report-outline.md")
        )
        quality_checker = QualityChecker(
            required_sections=outline_loader(outline_path) or None,
            outline_path=outline_path,
            workspace=workspace,
        )
    available = (
        *build_context_tools(tool_context_store, workspace, reference_names),
        *build_material_tools(
            MaterialIngestionService(
                workspace, parser=material_parser, evidence_store=evidence_store
            ),
            context_store,
            upload_markdown=upload_material_md,
            task_id=task_id,
        ),
        *build_data_mcp_tools(gateway),
        *build_evidence_tools(evidence_store),
        *build_ask_user_tools(),
        *build_report_tools(report_service, context_store),
        *build_ideology_tools(resolved_ideology_path),
        *build_review_tools(quality_checker, workspace=workspace),
        *build_word_tools(
            word_service
            or WordReportService(
                workspace,
                evidence_store,
                visual_review_required=visual_review_required,
            ),
            skill_version=skill.version,
            report_service=report_service,
            publish=publish,
            context_store=context_store,
            workspace=word_workspace or workspace,
        ),
        *build_investor_export_tools(workspace, evidence_store),
        *publisher_tools,
    )
    if backend is not None:
        available = (*available, *build_filesystem_tools(backend=backend))
    by_name = {tool.name: tool for tool in available}
    if len(by_name) != len(available):
        raise ValueError("duplicate tool names in Investment Report toolset")
    selected_names = ToolPolicy().select(skill, by_name)
    return tuple(by_name[name] for name in selected_names)
