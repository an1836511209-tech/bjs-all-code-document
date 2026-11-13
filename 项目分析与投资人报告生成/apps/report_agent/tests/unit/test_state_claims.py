"""A status word in the report must be supported by the evidence it cites.

The failure this prevents: a material draws a progress matrix as shapes, the
text layer carries no status, and the report writes "整机验证中" where the
material's own annotation says "整机已完成".
"""

from __future__ import annotations

import pytest

from report_agent.application.review_checker import QualityChecker
from report_agent.infrastructure.evidence import WorkspaceEvidenceStore
from report_agent.runtime.workspace import TaskWorkspace

EVIDENCE_ID = "evidence_" + "a" * 32


@pytest.fixture()
def workspace(tmp_path):
    workspace = TaskWorkspace(tmp_path)
    workspace.initialize()
    store = WorkspaceEvidenceStore(workspace)
    store.put(
        "parse_materials",
        {
            "schema_version": "1.0",
            "tool": "parse_materials",
            "status": "success",
            "summary": "用户上传材料：bp.pdf",
            "data": {
                "source_kind": "material",
                "blocks": [
                    {
                        "block_id": "page.11",
                        "kind": "page",
                        "text": "三一（工程机械）送样完成、台架完成、整机已完成。",
                        "locator": {"page": 11},
                        "recognition_method": "multimodal",
                        "chart_heavy": True,
                    }
                ],
            },
            "sources": [{"name": "bp.pdf", "status": "available"}],
            "warnings": [],
        },
    )
    return workspace


def _checker(workspace):
    return QualityChecker(required_sections=[], required_fields=[], workspace=workspace)


def _issues(workspace, md):
    return [i for i in _checker(workspace).check(md) if i.kind == "state_claim_without_source"]


def test_status_backed_by_the_cited_block_passes(workspace):
    md = (
        "## 二、项目分析\n\n"
        "三一整机已完成。<!-- src: material parse_materials /data/blocks/0/text ; "
        "原文：三一整机已完成 -->\n"
    )
    assert _issues(workspace, md) == []


def test_status_contradicting_the_cited_block_is_reported(workspace):
    md = (
        "## 二、项目分析\n\n"
        "三一整机处于验证阶段。<!-- src: material parse_materials /data/blocks/0/text ; "
        "原文：三一整机已完成 -->\n"
    )
    issues = _issues(workspace, md)
    assert len(issues) == 1
    assert "验证" in issues[0].terms


def test_status_without_any_source_is_reported(workspace):
    md = "## 二、项目分析\n\n三一整机验证阶段尚未结束。\n"
    issues = _issues(workspace, md)
    assert len(issues) == 1
    assert "没有任何来源标注" in issues[0].message


def test_paragraphs_without_status_words_are_ignored(workspace):
    md = "## 二、项目分析\n\n公司注册资本 13,180 万元。\n"
    assert _issues(workspace, md) == []


def test_check_is_skipped_without_a_workspace():
    checker = QualityChecker(required_sections=[], required_fields=[])
    md = "## 二、项目分析\n\n三一整机验证阶段。\n"
    assert not [i for i in checker.check(md) if i.kind == "state_claim_without_source"]
