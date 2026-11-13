"""Unit tests for QualityChecker."""

from __future__ import annotations

REQUIRED_SECTIONS = [
    "一、报告头部", "二、项目分析", "三、市场分析",
    "四、对标与估值参考", "五、投资匹配分析", "六、匹配投资人明细",
]
REQUIRED_FIELDS = ["注册资本", "股权", "营业收入", "赛道标签", "投资人"]


def _checker():
    from report_agent.application.review_checker import QualityChecker

    return QualityChecker(
        required_sections=list(REQUIRED_SECTIONS),
        required_fields=list(REQUIRED_FIELDS),
    )


def test_missing_section_detected():
    md = "## 二、项目分析\n" + ("内容" * 50) + "\n"
    issues = _checker().check(md)
    assert any(i.kind == "missing_section" and "一、" in i.message for i in issues)


def test_all_sections_present_passes():
    md = "\n".join(f"## {s}\nbody\n" for s in REQUIRED_SECTIONS)
    issues = _checker().check(md)
    assert not any(i.kind == "missing_section" for i in issues)


def test_long_analysis_without_numbers_does_not_require_citation():
    md = "## 一、报告头部\n\n" + ("这是一段超过一百字的测试段落内容。" * 8) + "\n"
    issues = _checker().check(md)
    assert not any(i.kind == "missing_citation" for i in issues)


def test_short_paragraph_no_citation_passes():
    md = "## 一、报告头部\n\n一段短文。\n"
    issues = _checker().check(md)
    assert not any(i.kind == "missing_citation" for i in issues)


def test_long_paragraph_with_cite_passes():
    md = "## 一、报告头部\n\n" + ("长内容。" * 30) + " <!-- cite: evidence_abc1234567890def1234567890abcdef -->\n"
    issues = _checker().check(md)
    assert not any(i.kind == "missing_citation" for i in issues)


def test_missing_data_field_detected():
    md = "## 一、报告头部\n" + ("内容" * 50) + "\n报告内容无关键字段\n"
    issues = _checker().check(md)
    assert any(
        i.kind == "missing_data_field" and i.severity == "warn" and "注册资本" in i.message
        for i in issues
    )


def test_required_fields_present_passes():
    md = "## 一、报告头部\n" + " ".join(REQUIRED_FIELDS) + "\n"
    issues = _checker().check(md)
    assert not any(i.kind == "missing_data_field" for i in issues)


def test_placeholder_text_block():
    md = "## 一、报告头部\n这里有 TODO 占位符\n"
    issues = _checker().check(md)
    assert any(i.kind == "placeholder_text" and i.severity == "block" for i in issues)


def test_fabricated_number_block():
    md = "## 一、报告头部\n公司预计增长约 30% 收入。\n"
    issues = _checker().check(md)
    assert any(i.kind == "fabricated_number" and i.severity == "block" for i in issues)


def test_truncated_section_warn():
    md = "\n".join(
        [f"## {s}\n短\n" for s in REQUIRED_SECTIONS]
    )
    issues = _checker().check(md)
    assert any(i.kind == "truncated_section" and i.severity == "warn" for i in issues)


def test_imbalanced_chapters_warn():
    s1 = "## 一、报告头部\n短\n"
    s2 = "## 二、主体\n中等长内容。" * 10 + "\n"
    s3 = "## 三、附记\n" + ("大量内容。" * 1000) + "\n"
    issues = _checker().check(s1 + s2 + s3)
    assert any(i.kind == "imbalanced_chapters" for i in issues)


def test_inconsistent_number_format_warn():
    md = "## 一、报告头部\n公司营收 5.13 亿元，去年 51,300,000,000 元。\n"
    issues = _checker().check(md)
    assert any(i.kind == "inconsistent_number_format" for i in issues)


def test_abbreviation_undefined_warn():
    md = "## 一、报告头部\n我们使用 MCP 协议。\n"
    issues = _checker().check(md)
    assert any(i.kind == "abbreviation_undefined" for i in issues)


def test_clean_report_quality_pass():
    md = "\n".join(
        f"## {s}\n正常章节内容 {i}，注册资本 X，股权 Y，营业收入 Z，赛道标签 A，投资人 B。\n"
        + " <!-- cite: evidence_abc -->"
        for i, s in enumerate(REQUIRED_SECTIONS, 1)
    )
    issues = _checker().check(md)
    block_issues = [i for i in issues if i.severity == "block"]
    assert len(block_issues) == 0
