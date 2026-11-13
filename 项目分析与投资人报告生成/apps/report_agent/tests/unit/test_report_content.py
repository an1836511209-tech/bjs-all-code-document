from pathlib import Path
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from report_agent.application.reports import ReportContentService
from report_agent.application.word_reports import WordReportService
from report_agent.domain.report_content import (
    EvidenceCitation,
    ReportContent,
    ReportSection,
    ReportStatus,
    ReportTable,
    ReportTableRow,
    ReportText,
)
from report_agent.harness.word_tools import ReportComment, build_word_tools
from report_agent.infrastructure.evidence import WorkspaceEvidenceStore
from report_agent.runtime.workspace import TaskWorkspace


def setup_content(tmp_path: Path):
    workspace = TaskWorkspace(tmp_path / "task")
    workspace.initialize()
    store = WorkspaceEvidenceStore(workspace)
    evidence = store.put(
        "extract_project_profile",
        {
            "schema_version": "1.0",
            "tool": "extract_project_profile",
            "status": "success",
            "summary": "ok",
            "data": {"company": "某企业", "peers": [{"name": "同行甲", "business": "装备"}]},
            "sources": [{"name": "project_document", "status": "available"}],
            "warnings": [],
        },
    )
    title = EvidenceCitation(evidence_id=evidence.evidence_id)
    row = EvidenceCitation(evidence_id=evidence.evidence_id)
    content = ReportContent(
        report_id="report",
        title="某企业投资人匹配报告",
        title_citations=(title,),
        company_name="某企业",
        status=ReportStatus.READY,
        sections=(
            ReportSection(
                section_id="peers",
                title="对标企业",
                paragraphs=(ReportText(text="标的企业为某企业。", citations=(title,)),),
                tables=(
                    ReportTable(
                        table_id="peers",
                        headers=("公司名称", "主营业务"),
                        rows=(
                            ReportTableRow(
                                row_id="peer_0", values=("同行甲", "装备"), citations=(row,)
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    return workspace, store, content


def test_table_rows_are_strings_with_row_level_citations(tmp_path: Path) -> None:
    _, _, content = setup_content(tmp_path)
    assert content.sections[0].tables[0].rows[0].values == ("同行甲", "装备")
    with pytest.raises(ValidationError, match="header width"):
        ReportTable(
            table_id="bad",
            headers=("a", "b"),
            rows=(ReportTableRow(row_id="r", values=("one",), citations=content.title_citations),),
        )


def test_report_validation_is_idempotent(tmp_path: Path) -> None:
    workspace, store, content = setup_content(tmp_path)
    service = ReportContentService(workspace, store)
    service.save(content.model_copy(update={"status": ReportStatus.DRAFT}))
    assert service.validate("report").status == ReportStatus.READY
    assert service.validate("report").status == ReportStatus.READY


def test_word_document_has_no_inline_comments(tmp_path: Path) -> None:
    """create_word_document generates a DOCX without comments; comments are added later."""
    workspace, store, content = setup_content(tmp_path)
    service = WordReportService(workspace, store, visual_review_required=False)
    artifact = service.create(content, filename="report.docx", skill_version="a" * 64)
    assert artifact.comment_count == 0
    with ZipFile(workspace.resolve(artifact.path)) as archive:
        assert "word/comments.xml" not in archive.namelist()


def test_add_report_comments_attaches_by_substring(tmp_path: Path) -> None:
    """add_report_comments finds paragraphs by match_text and attaches comments."""
    workspace, store, content = setup_content(tmp_path)
    service = WordReportService(workspace, store, visual_review_required=False)
    artifact = service.create(content, filename="report.docx", skill_version="a" * 64)
    assert artifact.comment_count == 0

    commented = service.manage_comments(
        artifact.artifact_id,
        [
            {"action": "add", "contains": "某企业。", "text": "出处说明：项目资料\n来源：项目材料"},
            {"action": "add", "contains": "同行甲", "text": "出处说明：同行资料\n来源：企查查"},
        ],
    )
    assert commented.comment_count == 2
    with ZipFile(workspace.resolve(commented.path)) as archive:
        comments = archive.read("word/comments.xml").decode()
    assert "出处说明" in comments
    assert "evidence_" not in comments


def test_word_surface_has_five_tools(tmp_path: Path) -> None:
    workspace, store, _ = setup_content(tmp_path)
    tools = build_word_tools(
        WordReportService(workspace, store, visual_review_required=False),
        skill_version="a" * 64,
        report_service=ReportContentService(workspace, store),
        publish=lambda path: None,
        workspace=workspace,
    )
    assert {tool.name for tool in tools} == {
        "create_word_document",
        "create_word_from_md",
        "edit_word_document",
        "add_report_comments",
        "manage_word_comments",
        "validate_and_publish_word",
    }


def test_comment_scripts_are_reused_behind_artifact_ids(tmp_path: Path) -> None:
    workspace, store, content = setup_content(tmp_path)
    service = WordReportService(workspace, store, visual_review_required=False)
    artifact = service.create(content, filename="report.docx", skill_version="a" * 64)

    # Add comments first (create_word_document produces 0 comments now).
    commented = service.manage_comments(
        artifact.artifact_id,
        [{"action": "add", "contains": "某企业", "text": "出处说明：项目资料"}],
    )
    extracted = service.manage_comments(commented.artifact_id, [{"action": "extract"}])
    stripped = service.manage_comments(commented.artifact_id, [{"action": "remove_all"}])

    assert isinstance(extracted, dict)
    assert len(extracted["comments"]) == 1
    assert stripped.comment_count == 0
    assert stripped.artifact_id != commented.artifact_id


def _setup_material_evidence(tmp_path: Path):
    """Build a workspace whose title citation points at a parse_materials evidence."""
    workspace = TaskWorkspace(tmp_path / "task_mat")
    workspace.initialize()
    store = WorkspaceEvidenceStore(workspace)
    evidence = store.put(
        "parse_materials",
        {
            "schema_version": "1.0",
            "tool": "parse_materials",
            "status": "success",
            "summary": "用户上传材料：项目材料.docx",
            "data": {
                "source_kind": "material",
                "material_id": "material_" + "a" * 32,
                "source_name": "项目材料.docx",
                "source_sha256": "a" * 64,
                "format": "docx",
                "blocks": [
                    {
                        "block_id": "p1",
                        "kind": "paragraph",
                        "text": "标的企业为某企业，注册资本1亿元。",
                        "locator": {"page": 1, "paragraph": 1},
                        "recognition_method": "embedded_text",
                        "confidence": 0.95,
                    },
                ],
            },
            "sources": [{"name": "项目材料.docx", "status": "available"}],
            "warnings": [],
        },
    )
    title = EvidenceCitation(evidence_id=evidence.evidence_id)
    content = ReportContent(
        report_id="report_mat",
        title="某企业投资人匹配报告",
        title_citations=(title,),
        company_name="某企业",
        status=ReportStatus.READY,
        sections=(
            ReportSection(
                section_id="overview",
                title="项目概况",
                paragraphs=(
                    ReportText(text="标的企业为某企业。", citations=(title,)),
                ),
            ),
        ),
    )
    return workspace, store, content


def test_material_evidence_validates_and_comments_added(tmp_path: Path) -> None:
    """Material evidence validates (evidence_id only, no locator) and comments are added via add_report_comments."""
    workspace, store, content = _setup_material_evidence(tmp_path)
    service = ReportContentService(workspace, store)
    service.save(content.model_copy(update={"status": ReportStatus.DRAFT}))
    assert service.validate("report_mat").status == ReportStatus.READY

    word_service = WordReportService(workspace, store, visual_review_required=False)
    artifact = word_service.create(content, filename="report_mat.docx", skill_version="b" * 64)
    assert artifact.comment_count == 0

    # Add a comment matching the paragraph text.
    commented = word_service.manage_comments(
        artifact.artifact_id,
        [{"action": "add", "contains": "某企业。", "text": "出处说明：项目概况\n来源：项目材料.docx\n原文：标的企业为某企业，注册资本1亿元。"}],
    )
    assert commented.comment_count == 1
    with ZipFile(workspace.resolve(commented.path)) as archive:
        comments = archive.read("word/comments.xml").decode()
    assert "项目材料.docx" in comments
    assert "标的企业为某企业，注册资本1亿元。" in comments
    assert "evidence_" not in comments


def test_material_id_rejected_as_evidence_id(tmp_path: Path) -> None:
    """Regression guard: model must not pass material_ prefix into evidence_id."""
    with pytest.raises(ValidationError, match="evidence_id"):
        EvidenceCitation(evidence_id="material_" + "a" * 32)


def test_report_comment_model_exposes_match_and_comment_fields() -> None:
    """ReportComment Pydantic model exposes match_text and comment_text to the model."""
    comment = ReportComment(match_text="某企业", comment_text="出处说明：项目资料")
    assert comment.match_text == "某企业"
    assert comment.comment_text == "出处说明：项目资料"
    with pytest.raises(ValidationError):
        ReportComment(match_text="", comment_text="valid")
