"""read_evidence_pack returns multiple pointers + src in one call."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from report_agent.harness.evidence_tools import DEFAULT_EVIDENCE_PACKS, build_evidence_tools
from report_agent.infrastructure.evidence import WorkspaceEvidenceStore
from report_agent.runtime.workspace import TaskWorkspace


@pytest.fixture()
def workspace(tmp_path: Path):
    ws = TaskWorkspace(tmp_path / "ws")
    ws.initialize()
    return ws


def _store_evidence(workspace: TaskWorkspace, tool: str, data: dict) -> str:
    store = WorkspaceEvidenceStore(workspace)
    record = store.put(
        tool,
        {
            "status": "success",
            "summary": "ok",
            "warnings": [],
            "data": data,
            "sources": [],
        },
    )
    index = {
        "evidence": {
            record.evidence_id: {
                "tool": tool,
                "status": "success",
                "summary": "ok",
                "path": record.path,
                "sha256": record.sha256,
                "size_bytes": record.size,
            }
        }
    }
    workspace.import_artifact(
        "evidence",
        "index.json",
        json.dumps(index, ensure_ascii=False).encode("utf-8"),
    )
    return record.evidence_id


def _pack_tool(workspace: TaskWorkspace):
    tools = {tool.name: tool for tool in build_evidence_tools(WorkspaceEvidenceStore(workspace))}
    return tools["read_evidence_pack"]


def test_default_pack_for_match_investors(workspace: TaskWorkspace):
    eid = _store_evidence(
        workspace,
        "match_investors",
        {
            "candidates": [{"name": "甲资本", "investor_type": "机构"}],
            "counts": {"internal_institutions": 1, "internal_individuals_excluded": 9},
        },
    )
    result = json.loads(_pack_tool(workspace).invoke({"evidence_id": eid, "pointers": ""}))
    assert result["tool"] == "match_investors"
    pointers = [item["json_pointer"] for item in result["items"]]
    assert pointers == list(DEFAULT_EVIDENCE_PACKS["match_investors"])
    assert result["missing"] == []
    assert all("src" in item and "cite" in item for item in result["items"])
    assert "甲资本" in json.dumps(result["items"][0]["value"], ensure_ascii=False)


def test_pack_emits_per_row_src_for_peers(workspace: TaskWorkspace):
    eid = _store_evidence(
        workspace,
        "match_listed_peers",
        {
            "peers": [
                {"证券代码": "000001.SZ", "证券名称": "平安银行", "PE": 5.13},
                {"证券代码": "600036.SH", "证券名称": "招商银行", "PE": 7.31},
            ]
        },
    )
    result = json.loads(_pack_tool(workspace).invoke({"evidence_id": eid, "pointers": ""}))
    peers = result["items"][0]
    assert peers["json_pointer"] == "/data/peers"
    assert [row["json_pointer"] for row in peers["row_srcs"]] == [
        "/data/peers/0",
        "/data/peers/1",
    ]
    assert "招商银行" in peers["row_srcs"][1]["src"]
    assert "7.31" in peers["row_srcs"][1]["src"]
    assert "平安银行" not in peers["row_srcs"][1]["src"]


def test_pack_reports_missing_pointer(workspace: TaskWorkspace):
    eid = _store_evidence(workspace, "query_track_labels", {"tags": ["银行"]})
    result = json.loads(
        _pack_tool(workspace).invoke(
            {"evidence_id": eid, "pointers": ["/data/tags", "/data/absent"]}
        )
    )
    assert [item["json_pointer"] for item in result["items"]] == ["/data/tags"]
    assert result["missing"][0]["json_pointer"] == "/data/absent"


def test_skill_lists_new_tools():
    skill = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "investment-report"
        / "SKILL.md"
    )
    text = skill.read_text(encoding="utf-8")
    assert "read_evidence_pack" in text
    assert "run_writing_review" in text
    assert "第 2 次 `edit_file`" in text
    assert "第 4 次 `edit_file`" not in text
    assert "row_srcs" in text
    assert 'check_report(checks=["quality","ai_tells"])' in text
