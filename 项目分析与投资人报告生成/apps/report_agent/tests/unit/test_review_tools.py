"""Unit tests for check_report harness tool."""

from __future__ import annotations

import json


_REQUIRED_SECTIONS = [
    "一、报告头部", "二、项目分析", "三、市场分析",
    "四、对标与估值参考", "五、投资匹配分析", "六、匹配投资人明细",
]


def _tool():
    from report_agent.application.review_checker import QualityChecker
    from report_agent.harness.review_tools import build_review_tools

    return build_review_tools(
        QualityChecker(required_sections=list(_REQUIRED_SECTIONS))
    )[0]


def _run(md_text: str, checks: list[str]) -> dict:
    from pathlib import Path

    p = Path("tests/unit/fixtures/_tmp_check.md")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(md_text, encoding="utf-8")
    try:
        result = json.loads(_tool().invoke({"md_path": str(p), "checks": checks}))
        return result
    finally:
        p.unlink()


def test_check_report_quality_finds_missing_section():
    md = "## 二、项目分析\n" + ("内容" * 50) + "\n"
    result = _run(md, ["quality"])
    kinds = {i["kind"] for i in result["issues"]}
    assert "missing_section" in kinds
    assert result["block_count"] >= 1


def test_check_report_ai_tells_finds_template():
    md = "## 一、报告头部\n" + ("综上所述，" * 3) + "结论。\n"
    result = _run(md, ["ai_tells"])
    assert any(i["kind"] == "template_transition" for i in result["issues"])


def test_check_report_unknown_check_raises():
    import pytest

    with pytest.raises(ValueError, match="checks"):
        _run("## 一、报告头部\n", ["unknown"])


def test_check_report_both_modes():
    md = (
        "## 二、项目分析\n" + ("长内容。" * 50) + " 综上所述，\n"
    )
    result = _run(md, ["quality", "ai_tells"])
    kinds = {i["kind"] for i in result["issues"]}
    assert "missing_section" in kinds
    assert "conclusion_cliche" in kinds
    assert result["block_count"] >= 2


def test_check_report_missing_file_raises():
    import pytest

    with pytest.raises(ValueError, match="file not found"):
        _tool().invoke({"md_path": "/nonexistent.md", "checks": ["quality"]})


def test_check_report_empty_md():
    result = _run("", ["quality", "ai_tells"])
    assert result["issues"] == []
    assert result["block_count"] == 0
    assert result["summary"] == {}


def test_check_report_resolves_sandbox_path_via_workspace():
    """When built with a workspace, check_report resolves sandbox paths
    like '/workspace/report/report.md' via TaskWorkspace.resolve() —
    important because agent writes report.md at that sandbox path."""
    from pathlib import Path

    from report_agent.runtime.workspace import TaskWorkspace
    from report_agent.harness.review_tools import build_review_tools
    from report_agent.application.review_checker import QualityChecker

    ws = TaskWorkspace(Path(".runtime/test_ws_sandbox"))
    ws.initialize()
    target = ws.resolve("/workspace/report/report.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "## 一、报告头部\n" + ("x" * 200) + " <!-- cite: e -->\n\n## 二、注\n" + ("y" * 200),
        encoding="utf-8",
    )
    try:
        tool = build_review_tools(QualityChecker(), workspace=ws)[0]
        result = tool.invoke({"md_path": "/workspace/report/report.md", "checks": ["quality"]})
        assert "issues" in result
    finally:
        import shutil

        shutil.rmtree(ws.root, ignore_errors=True)


def test_run_writing_review_merges_non_blocking_checks():
    from pathlib import Path

    from report_agent.application.review_checker import QualityChecker
    from report_agent.harness.review_tools import build_review_tools

    tools = {tool.name: tool for tool in build_review_tools(
        QualityChecker(required_sections=list(_REQUIRED_SECTIONS))
    )}
    review = tools["run_writing_review"]
    path = Path("tests/unit/fixtures/_tmp_writing_review.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("## 二、项目分析\n" + ("内容" * 40) + "\n综上所述，\n", encoding="utf-8")
    try:
        result = json.loads(review.invoke({"md_path": str(path)}))
    finally:
        path.unlink(missing_ok=True)
    assert result["step"] == "writing_review"
    assert result["blocking"] is False
    assert result["by_step"]["data_field"] >= 1
    assert result["by_step"]["ai_tells"] >= 1
    kinds = {issue["kind"] for issue in result["issues"]}
    assert "missing_section" in kinds
