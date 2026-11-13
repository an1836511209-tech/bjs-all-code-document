"""Unit tests for AITellDetector (LLM writing pattern detection)."""

from __future__ import annotations


def _detector():
    from report_agent.application.review_checker import AITellDetector

    return AITellDetector()


def test_em_dash_overuse_block():
    md = "## 一、报告头部\n" + ("其——结果" * 30) + "\n"
    issues = _detector().check(md)
    assert any(i.kind == "em_dash_overuse" for i in issues)


def test_em_dash_under_threshold():
    md = "## 一、报告头部\n偶尔——出现\n" + ("长内容" * 100) + "\n"
    issues = _detector().check(md)
    assert not any(i.kind == "em_dash_overuse" for i in issues)


def test_template_transition_block():
    md = "## 一、报告头部\n" + ("综上所述，" * 3) + "结论。\n"
    issues = _detector().check(md)
    assert any(i.kind == "template_transition" for i in issues)


def test_template_transition_under_threshold():
    md = "## 一、报告头部\n综上所述，结论是 X。\n"
    issues = _detector().check(md)
    assert not any(i.kind == "template_transition" for i in issues)


def test_bureaucratic_phrase_block():
    md = "## 一、报告头部\n" + ("具有重要意义" * 4) + "\n"
    issues = _detector().check(md)
    assert any(i.kind == "bureaucratic_phrase" for i in issues)


def test_bureaucratic_phrase_under_threshold():
    md = "## 一、报告头部\n该项目具有重要意义。\n"
    issues = _detector().check(md)
    assert not any(i.kind == "bureaucratic_phrase" for i in issues)


def test_ai_vocabulary_block():
    md = "## 一、报告头部\n" + ("至关重要" * 4) + "\n"
    issues = _detector().check(md)
    assert any(i.kind == "ai_vocabulary" for i in issues)


def test_ai_vocabulary_under_threshold():
    md = "## 一、报告头部\n该项目至关重要。\n"
    issues = _detector().check(md)
    assert not any(i.kind == "ai_vocabulary" for i in issues)


def test_conclusion_cliche_block():
    md = "## 一、报告头部\n综上所述，\n"
    issues = _detector().check(md)
    assert any(i.kind == "conclusion_cliche" for i in issues)


def test_list_overuse_warn():
    md = "## 一、报告头部\n1. 收入\n2. 利润\n3. 增长\n4. 估值\n5. 风险\n"
    issues = _detector().check(md)
    assert any(i.kind == "list_overuse" for i in issues)


def test_list_overuse_under_threshold():
    md = "## 一、报告头部\n1. 第一\n2. 第二\n"
    issues = _detector().check(md)
    assert not any(i.kind == "list_overuse" for i in issues)


def test_fake_specificity_warn():
    md = "## 一、报告头部\n" + ("约 30%" * 4) + "\n"
    issues = _detector().check(md)
    assert any(i.kind == "fake_specificity" for i in issues)


def test_uniform_paragraph_warn():
    md = "## 一、报告头部\n" + ("同一段长内容。" * 30 + "\n\n") * 5 + "\n"
    issues = _detector().check(md)
    assert any(i.kind == "uniform_paragraph" for i in issues)


def test_clean_report_no_ai_tells():
    md = "## 一、报告头部\n公司主营业务为 X。\n\n营收 5.13 亿元，同比增长 12.3%。\n"
    issues = _detector().check(md)
    block_issues = [i for i in issues if i.severity == "block"]
    assert len(block_issues) == 0
