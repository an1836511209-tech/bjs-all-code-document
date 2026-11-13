"""Agent tools for incremental ReportContent authoring."""

from __future__ import annotations

import json

from langchain_core.tools import StructuredTool

from report_agent.application.context_store import WorkspaceContextStore
from report_agent.application.reports import ReportContentService
from report_agent.domain.report_content import ReportContent, ReportSection


def build_report_tools(
    service: ReportContentService, context_store: WorkspaceContextStore | None = None
):
    def create_report_content(content: ReportContent) -> str:
        saved = service.save(content)
        if context_store:
            context_store.record_report("create_report_content", saved)
        return _ack("created", saved)

    def upsert_report_section(report_id: str, section: ReportSection) -> str:
        saved = service.upsert_section(report_id, section)
        if context_store:
            context_store.record_report("upsert_report_section", saved)
        return _ack("section_upserted", saved)

    def get_report_content(report_id: str) -> str:
        return service.get(report_id).model_dump_json()

    def validate_report_content(report_id: str) -> str:
        saved = service.validate(report_id)
        if context_store:
            context_store.record_report("validate_report_content", saved)
        return _ack("validated", saved)

    defs = (
        (
            create_report_content,
            "create_report_content",
            "Create simple report content. Paragraphs and bullet items carry citations; table rows contain string values and one row-level citations array.",
        ),
        (
            upsert_report_section,
            "upsert_report_section",
            "Add or replace one section. Table rows use {row_id, values: string[], citations}; never wrap cells in claim objects.",
        ),
        (
            get_report_content,
            "get_report_content",
            "Read authoritative saved ReportContent by report_id.",
        ),
        (
            validate_report_content,
            "validate_report_content",
            "Validate all citations and mark ReportContent ready. Repeated calls are idempotent.",
        ),
    )
    return tuple(
        StructuredTool.from_function(fn, name=name, description=description)
        for fn, name, description in defs
    )


def _ack(action: str, content: ReportContent) -> str:
    return json.dumps(
        {
            "action": action,
            "report_id": content.report_id,
            "status": content.status.value,
            "section_count": len(content.sections),
            "next_action": "create_word_document"
            if content.status.value == "ready"
            else "upsert_next_section_or_validate",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
