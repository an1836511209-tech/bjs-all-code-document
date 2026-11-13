"""``batch_edit`` must behave like ``edit_file``, but for many edits at once."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from report_agent.harness.filesystem_tools import (
    MAX_EDITS_PER_CALL,
    build_filesystem_tools,
)
from report_agent.runtime.sandbox import build_workspace_backend
from report_agent.runtime.workspace import TaskWorkspace


@pytest.fixture()
def workspace(tmp_path):
    workspace = TaskWorkspace(tmp_path)
    workspace.initialize()
    return workspace


@pytest.fixture()
def tool(workspace):
    backend = build_workspace_backend("sbx", workspace, backend="filesystem")
    (tool, ) = build_filesystem_tools(backend=backend)
    return tool


def _write(workspace, text: str) -> None:
    # ``/workspace/report/report.md`` maps to ``<root>/report/report.md`` in
    # both TaskWorkspace and the deepagents virtual filesystem backend.
    target = workspace.root / "report"
    target.mkdir(parents=True, exist_ok=True)
    (target / "report.md").write_text(text, encoding="utf-8")


def _read(workspace) -> str:
    return (workspace.root / "report" / "report.md").read_text(encoding="utf-8")


def test_multiple_edits_are_applied_in_one_call(tool, workspace):
    _write(workspace, "第一段\n第二段\n第三段\n")

    result = json.loads(
        tool.invoke(
            {
                "file_path": "/workspace/report/report.md",
                "edits": [
                    {"old_string": "第一段", "new_string": "第一段<!-- cite: e1 -->"},
                    {"old_string": "第二段", "new_string": "第二段<!-- cite: e2 -->"},
                    {"old_string": "第三段", "new_string": "第三段<!-- cite: e3 -->"},
                ],
            }
        )
    )

    assert result["status"] == "ok"
    assert result["replaced"] == 3
    assert result["failed"] == 0
    assert result["requested"] == 3
    text = _read(workspace)
    assert "第一段<!-- cite: e1 -->" in text
    assert "第三段<!-- cite: e3 -->" in text


def test_a_failing_edit_does_not_abort_the_others(tool, workspace):
    _write(workspace, "保留原文\n")

    result = json.loads(
        tool.invoke(
            {
                "file_path": "/workspace/report/report.md",
                "edits": [
                    {"old_string": "根本不存在", "new_string": "x"},
                    {"old_string": "保留原文", "new_string": "改过了"},
                ],
            }
        )
    )

    assert result["replaced"] == 1
    assert result["failed"] == 1
    assert result["results"][0]["status"] == "failed"
    assert result["results"][1]["status"] == "ok"
    assert "改过了" in _read(workspace)
    assert "hint" in result


def test_edits_are_applied_against_the_evolving_content(tool, workspace):
    _write(workspace, "原始\n")

    result = json.loads(
        tool.invoke(
            {
                "file_path": "/workspace/report/report.md",
                "edits": [
                    {"old_string": "原始", "new_string": "中间"},
                    {"old_string": "中间", "new_string": "最终"},
                ],
            }
        )
    )

    assert result["replaced"] == 2
    assert _read(workspace) == "最终\n"


def test_replace_all_is_supported(tool, workspace):
    _write(workspace, "同词出现\n同词出现\n")

    result = json.loads(
        tool.invoke(
            {
                "file_path": "/workspace/report/report.md",
                "edits": [
                    {"old_string": "同词", "new_string": "异词", "replace_all": True},
                ],
            }
        )
    )

    assert result["replaced"] == 1
    assert result["results"][0]["occurrences"] == 2
    assert _read(workspace) == "异词出现\n异词出现\n"


def test_empty_edit_list_is_rejected(tool):
    result = json.loads(
        tool.invoke({"file_path": "/workspace/report/report.md", "edits": []})
    )
    assert result["status"] == "error"
    assert "non-empty" in result["error"]


def test_too_many_edits_is_rejected(tool):
    edits = [{"old_string": f"a{i}", "new_string": f"b{i}"} for i in range(MAX_EDITS_PER_CALL + 1)]
    result = json.loads(
        tool.invoke({"file_path": "/workspace/report/report.md", "edits": edits})
    )
    assert result["status"] == "error"
    assert "too many edits" in result["error"]


def test_relative_path_is_rejected(tool):
    result = json.loads(
        tool.invoke(
            {
                "file_path": "report/report.md",
                "edits": [{"old_string": "a", "new_string": "b"}],
            }
        )
    )
    assert result["status"] == "error"


def test_missing_file_reports_failure_without_aborting(tool):
    result = json.loads(
        tool.invoke(
            {
                "file_path": "/workspace/report/does-not-exist.md",
                "edits": [{"old_string": "a", "new_string": "b"}],
            }
        )
    )
    assert result["status"] == "error"
    assert result["failed"] == 1
    assert "not found" in result["results"][0]["error"]


def _allowed_tools(skill_md: Path) -> list[str]:
    text = skill_md.read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    tools: list[str] = []
    in_list = False
    for line in frontmatter.splitlines():
        if line.startswith("allowed-tools:"):
            in_list = True
            continue
        if in_list:
            stripped = line.strip()
            if stripped.startswith("- "):
                tools.append(stripped[2:].strip())
            elif stripped:
                break
    return tools


@pytest.mark.parametrize("skill", ["investment-report", "one-pager"])
def test_skill_allows_batch_edit(skill):
    """``ToolPolicy`` filters by allowed-tools, so an unlisted tool is invisible."""
    repo_root = Path(__file__).resolve().parents[4]
    skill_md = repo_root / "apps" / "report_agent" / "skills" / skill / "SKILL.md"
    assert "batch_edit" in _allowed_tools(skill_md), (
        f"{skill} must list batch_edit in allowed-tools or the model cannot call it"
    )

