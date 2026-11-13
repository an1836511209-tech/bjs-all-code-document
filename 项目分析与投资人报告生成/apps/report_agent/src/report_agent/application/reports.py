"""Persistent ReportContent lifecycle."""

from __future__ import annotations

import re

from report_agent.application.report_evidence import validate_report_evidence
from report_agent.domain.report_content import ReportContent, ReportSection, ReportStatus
from report_agent.infrastructure.evidence import WorkspaceEvidenceStore
from report_agent.runtime.workspace import TaskWorkspace

REPORT_ID = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class ReportContentService:
    def __init__(self, workspace: TaskWorkspace, evidence_store: WorkspaceEvidenceStore) -> None:
        self.workspace = workspace
        self.evidence_store = evidence_store

    def save(self, content: ReportContent) -> ReportContent:
        self.workspace.write_text(self._path(content.report_id), content.model_dump_json(indent=2))
        return content

    def get(self, report_id: str) -> ReportContent:
        return ReportContent.model_validate_json(self.workspace.read_text(self._path(report_id)))

    def upsert_section(self, report_id: str, section: ReportSection) -> ReportContent:
        content = self.get(report_id)
        sections = list(content.sections)
        index = next(
            (i for i, current in enumerate(sections) if current.section_id == section.section_id),
            None,
        )
        if index is None:
            sections.append(section)
        else:
            sections[index] = section
        candidate = ReportContent.model_validate(content.model_dump() | {"sections": sections})
        # Validate evidence_id existence for the upserted section immediately so
        # the model gets early feedback instead of discovering bad citations at
        # validate_report_content time (after potentially writing many sections).
        validate_report_evidence(candidate, self.evidence_store)
        return self.save(candidate)

    def validate(self, report_id: str) -> ReportContent:
        content = self.get(report_id)
        candidate = ReportContent.model_validate(
            content.model_dump() | {"status": ReportStatus.READY}
        )
        validate_report_evidence(candidate, self.evidence_store)
        return self.save(candidate)

    @staticmethod
    def _path(report_id: str) -> str:
        if not REPORT_ID.fullmatch(report_id):
            raise ValueError("invalid report_id")
        return f"/workspace/report/{report_id}.json"
