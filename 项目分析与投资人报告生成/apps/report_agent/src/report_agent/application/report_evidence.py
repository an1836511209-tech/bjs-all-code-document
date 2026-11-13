"""Evidence validation for simple ReportContent."""

from __future__ import annotations

from report_agent.domain.report_content import EvidenceCitation, ReportContent
from report_agent.infrastructure.evidence import WorkspaceEvidenceStore


class EvidenceValidationError(ValueError):
    """Raised when ReportContent citations fail evidence validation.

    Carries the full ``issues`` list so the tool recovery middleware can route
    to the evidence-specific recovery branch (fix evidence_id / disclosure)
    instead of the generic "fix arguments and retry" path which is meaningless
    for ``validate_report_content`` (only takes ``report_id``).
    """

    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues[:8]))
        self.issues = issues


def validate_report_evidence(content: ReportContent, store: WorkspaceEvidenceStore) -> None:
    issues: list[str] = []
    targets: list[tuple[str, tuple[EvidenceCitation, ...], str | None]] = [
        ("title", content.title_citations, None)
    ]
    for section in content.sections:
        targets.extend(
            (f"paragraph:{section.section_id}", item.citations, item.disclosure)
            for item in section.paragraphs
        )
        targets.extend(
            (f"bullet:{section.section_id}", item.citations, item.disclosure)
            for item in section.bullet_items
        )
        for table in section.tables:
            for row in table.rows:
                targets.append((f"row:{row.row_id}", row.citations, row.disclosure))
                targets.extend(
                    (f"cell:{row.row_id}:{index}", citations, row.disclosure)
                    for index, citations in row.cell_citations.items()
                )
    for label, citations, disclosure in targets:
        for citation in citations:
            try:
                evidence = store.get(citation.evidence_id)
            except FileNotFoundError:
                issues.append(f"{label}: evidence not found")
                continue
            if evidence.get("status") in {"empty", "failed"}:
                issues.append(f"{label}: unusable {evidence.get('status')} evidence")
    if issues:
        raise EvidenceValidationError(issues)
