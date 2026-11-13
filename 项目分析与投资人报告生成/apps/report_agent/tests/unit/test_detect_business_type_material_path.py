"""detect_one_pager_business_type must resolve PDF/input paths via parsed materials."""

from __future__ import annotations

import json

from report_agent.harness.one_pager_tools import build_one_pager_tools
from report_agent.runtime.workspace import TaskWorkspace

MATERIAL_ID = "material_" + "a" * 32
SOURCE_NAME = "01-【BP】惠然科技介绍-中投万方(1).pdf"
CAPITAL_TEXT = "本轮拟增资扩股，募集资金用于扩产，拟募集金额5000万元。"


def _workspace(tmp_path):
    workspace = TaskWorkspace(tmp_path)
    workspace.initialize()
    return workspace


def _tools(workspace):
    return {tool.name: tool for tool in build_one_pager_tools(workspace)}


def _write_parsed(workspace: TaskWorkspace, *, source_name: str = SOURCE_NAME, text: str = CAPITAL_TEXT):
    payload = {
        "schema_version": "1.0",
        "material_id": MATERIAL_ID,
        "source_name": source_name,
        "source_sha256": "0" * 64,
        "format": "pdf",
        "blocks": [
            {
                "block_id": "page.1",
                "kind": "page",
                "text": text,
                "locator": {"page": 1},
            }
        ],
    }
    workspace.write_text(
        f"/workspace/working/materials/{MATERIAL_ID}.json",
        json.dumps(payload, ensure_ascii=False),
    )


def test_detect_uses_parsed_material_when_given_input_pdf_path(tmp_path):
    workspace = _workspace(tmp_path)
    workspace.import_artifact("input", SOURCE_NAME, b"%PDF-1.4 binary \xe2 content")
    _write_parsed(workspace)
    tools = _tools(workspace)

    result = json.loads(
        tools["detect_one_pager_business_type"].invoke(
            {
                "material_path": f"/workspace/input/{SOURCE_NAME}",
                "filename": SOURCE_NAME,
            }
        )
    )

    assert result["status"] == "ok"
    assert result["business_type"] == "增资"
    assert result["confidence"] == "high"


def test_detect_accepts_material_id_directly(tmp_path):
    workspace = _workspace(tmp_path)
    _write_parsed(workspace)
    tools = _tools(workspace)

    result = json.loads(
        tools["detect_one_pager_business_type"].invoke({"material_path": MATERIAL_ID})
    )

    assert result["status"] == "ok"
    assert result["business_type"] == "增资"


def test_detect_fails_clearly_when_pdf_has_no_parsed_material(tmp_path):
    workspace = _workspace(tmp_path)
    workspace.import_artifact("input", SOURCE_NAME, b"%PDF-1.4 binary \xe2 content")
    tools = _tools(workspace)

    result = json.loads(
        tools["detect_one_pager_business_type"].invoke(
            {"material_path": f"/workspace/input/{SOURCE_NAME}", "filename": SOURCE_NAME}
        )
    )

    assert result["status"] == "failed"
    assert "question_request" not in result
    assert "parse_materials" in result["error"] or "material_id" in result["error"]


def test_detect_recovers_material_id_from_wrong_materials_area_path(tmp_path):
    workspace = _workspace(tmp_path)
    _write_parsed(workspace)
    tools = _tools(workspace)

    result = json.loads(
        tools["detect_one_pager_business_type"].invoke(
            {"material_path": f"/workspace/materials/{MATERIAL_ID}.pdf"}
        )
    )

    assert result["status"] == "ok"
    assert result["business_type"] == "增资"


def test_detect_prefers_newest_when_duplicate_parsed_materials_exist(tmp_path):
    """UAT: re-parse on resume left multiple material_*.json for one PDF."""
    workspace = _workspace(tmp_path)
    workspace.import_artifact("input", SOURCE_NAME, b"%PDF-1.4 binary \xe2 content")
    older_id = "material_" + "b" * 32
    newer_id = "material_" + "c" * 32
    for material_id, text in (
        (older_id, "普通公司介绍，无融资信息。"),
        (newer_id, CAPITAL_TEXT),
    ):
        payload = {
            "schema_version": "1.0",
            "material_id": material_id,
            "source_name": SOURCE_NAME,
            "source_sha256": "1" * 64,
            "format": "pdf",
            "blocks": [
                {
                    "block_id": "page.1",
                    "kind": "page",
                    "text": text,
                    "locator": {"page": 1},
                }
            ],
        }
        workspace.write_text(
            f"/workspace/working/materials/{material_id}.json",
            json.dumps(payload, ensure_ascii=False),
        )
    tools = _tools(workspace)

    result = json.loads(
        tools["detect_one_pager_business_type"].invoke(
            {
                "material_path": f"/workspace/input/{SOURCE_NAME}",
                "filename": SOURCE_NAME,
            }
        )
    )

    assert result["status"] == "ok"
    assert result["business_type"] == "增资"
    assert "question_request" not in result
