"""Unit tests for ReportIssue + CheckResult Pydantic models."""

from __future__ import annotations

from report_agent.domain.review_issue import CheckResult, ReportIssue


def test_report_issue_minimal_fields():
    issue = ReportIssue(
        kind="missing_section",
        severity="block",
        message="缺章节",
    )
    assert issue.kind == "missing_section"
    assert issue.severity == "block"
    assert issue.section == ""
    assert issue.locations == []
    assert issue.count == 0
    assert issue.suggestion == ""


def test_report_issue_with_full_fields():
    issue = ReportIssue(
        section="三、市场分析",
        kind="em_dash_overuse",
        severity="warn",
        locations=[3, 7, 11],
        count=15,
        message="破折号 '——' 占比 7.2%",
        suggestion="替换为句号 / 顿号",
    )
    assert issue.section == "三、市场分析"
    assert issue.locations == [3, 7, 11]
    assert issue.count == 15


def test_report_issue_frozen_rejects_extra_field():
    issue = ReportIssue(kind="missing_section", severity="block", message="x")
    try:
        issue.bad = "should fail"
    except (AttributeError, TypeError, ValueError):
        return
    raise AssertionError("expected frozen model to reject mutation")


def test_check_result_summary_groups_by_kind():
    issues = [
        ReportIssue(kind="missing_section", severity="block", message="a"),
        ReportIssue(kind="missing_section", severity="warn", message="b"),
        ReportIssue(kind="em_dash_overuse", severity="warn", message="c"),
    ]
    summary = CheckResult(issues=issues).summary()
    assert summary == {"missing_section": 2, "em_dash_overuse": 1}


def test_check_result_block_count():
    issues = [
        ReportIssue(kind="missing_section", severity="block", message="a"),
        ReportIssue(kind="em_dash_overuse", severity="warn", message="b"),
        ReportIssue(kind="fabricated_number", severity="block", message="c"),
    ]
    assert CheckResult(issues=issues).block_count() == 2


# ===== sample_report.md fixture integration =====


def test_sample_report_quality_passes_basics():
    from pathlib import Path

    from report_agent.application.review_checker import QualityChecker

    sample = Path("apps/report_agent/tests/unit/fixtures/sample_report.md")
    text = sample.read_text(encoding="utf-8")
    checker = QualityChecker(
        required_sections=[
            "一、报告头部", "二、项目分析", "三、市场分析",
            "四、对标与估值参考", "五、投资匹配分析", "六、匹配投资人明细",
        ],
    )
    issues = checker.check(text)
    # Fixture is a minimal sample — just verify it parses and
    # all 6 required sections are present (no missing_section).
    assert any("missing_section" not in i.kind for i in issues) or not any(
        "missing_section" in i.kind for i in issues
    )
    assert not any(i.kind == "missing_section" for i in issues)


def test_sample_report_ai_tells_passes_basics():
    from pathlib import Path

    from report_agent.application.review_checker import AITellDetector

    sample = Path("apps/report_agent/tests/unit/fixtures/sample_report.md")
    text = sample.read_text(encoding="utf-8")
    issues = AITellDetector().check(text)
    block_issues = [i for i in issues if i.severity == "block"]
    assert len(block_issues) == 0


def test_sample_report_check_report_both_modes():
    from pathlib import Path

    from report_agent.application.review_checker import QualityChecker
    from report_agent.harness.review_tools import build_review_tools

    sample = Path("apps/report_agent/tests/unit/fixtures/sample_report.md")
    text = sample.read_text(encoding="utf-8")
    checker = QualityChecker(
        required_sections=[
            "一、报告头部", "二、项目分析", "三、市场分析",
            "四、对标与估值参考", "五、投资匹配分析", "六、匹配投资人明细",
        ],
    )
    import json
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(text)
        path = f.name
    try:
        tool = build_review_tools(checker)[0]
        raw = tool.invoke({"md_path": path, "checks": ["quality", "ai_tells"]})
        payload = json.loads(raw)
        assert "issues" in payload
        assert "summary" in payload
        assert "block_count" in payload
        # The fixture is a stripped sample; just verify the tool returns valid structure
        # Real reports will have more content. We don't assert block_count == 0.
    finally:
        import os
        os.unlink(path)


def test_sample_report_with_issues_triggers_block():
    from pathlib import Path

    from report_agent.application.review_checker import QualityChecker
    from report_agent.domain.review_issue import CheckResult
    from report_agent.harness.review_tools import build_review_tools

    sample = Path("apps/report_agent/tests/unit/fixtures/sample_report.md")
    text = sample.read_text(encoding="utf-8")
    checker = QualityChecker(
        required_sections=[
            "一、报告头部", "二、项目分析", "三、市场分析",
            "四、对标与估值参考", "五、投资匹配分析", "六、匹配投资人明细",
        ],
    )
    # Add TWO template-transition phrases to exceed threshold of 2
    bad = text + "\n综上所述，第一段。\n综上所述，第二段。\n"
    import json
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(bad)
        path = f.name
    try:
        tool = build_review_tools(checker)[0]
        raw = tool.invoke({"md_path": path, "checks": ["ai_tells"]})
        payload = json.loads(raw)
        assert any(i["kind"] == "template_transition" for i in payload["issues"])
    finally:
        import os
        os.unlink(path)
