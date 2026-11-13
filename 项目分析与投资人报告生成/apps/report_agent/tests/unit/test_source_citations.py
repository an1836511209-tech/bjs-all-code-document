"""Web citations and Word comments must carry what a reader needs."""

from __future__ import annotations

from report_agent.application.review_checker import QualityChecker
from report_agent.harness.word_tools import ReportComment, validate_report_comments


def _checker():
    return QualityChecker(required_sections=[], required_fields=[])


def _web_issues(md: str):
    return [i for i in _checker().check(md) if i.kind == "web_source_incomplete"]


# --------------------------------------------------------------------------- #
# web source completeness
# --------------------------------------------------------------------------- #

def test_complete_web_source_passes():
    md = (
        "## 三、市场分析\n\n"
        "市场规模持续扩大。<!-- src: web search_company_web /data/searches/0 ; "
        "搜狐新闻｜液压行业白皮书｜https://example.com/report；检索日期：2026-11-03 -->\n"
    )
    assert _web_issues(md) == []


def test_web_source_without_link_is_reported():
    md = (
        "## 三、市场分析\n\n"
        "市场规模持续扩大。<!-- src: web search_company_web /data/searches/0 ; "
        "搜狐新闻｜液压行业白皮书；检索日期：2026-11-03 -->\n"
    )
    issues = _web_issues(md)
    assert len(issues) == 1
    assert "链接" in issues[0].message


def test_web_source_without_date_is_reported():
    md = (
        "## 三、市场分析\n\n"
        "市场规模持续扩大。<!-- src: web search_company_web /data/searches/0 ; "
        "搜狐新闻｜液压行业白皮书｜https://example.com/report -->\n"
    )
    issues = _web_issues(md)
    assert len(issues) == 1
    assert "检索日期" in issues[0].message


def test_material_source_is_not_judged_by_the_web_rule():
    md = (
        "## 三、市场分析\n\n"
        "市场规模持续扩大。<!-- src: material parse_materials /data/blocks/1/text ; "
        "原文：市场规模持续扩大 -->\n"
    )
    assert _web_issues(md) == []


# --------------------------------------------------------------------------- #
# comment validation
# --------------------------------------------------------------------------- #

def test_comment_naming_another_entity_is_rejected():
    comments = [
        ReportComment(
            match_text="湖北正洋森煜投资合伙企业（有限合伙）",
            comment_text="云南旅游股份有限公司为旅游类上市公司，与本公司形成产业链协同。",
            kind="mcp",
        )
    ]
    problems = validate_report_comments(comments)
    assert len(problems) == 1
    assert problems[0]["problem"] == "comment_names_a_different_entity"


def test_comment_about_its_own_entity_passes():
    comments = [
        ReportComment(
            match_text="湖北正洋森煜投资合伙企业（有限合伙）",
            comment_text="湖北正洋森煜投资合伙企业（有限合伙）为库内匹配分最高的机构候选。",
            kind="mcp",
        )
    ]
    assert validate_report_comments(comments) == []


def test_mcp_comment_cannot_present_an_api_field_as_original_text():
    comments = [
        ReportComment(
            match_text="招商银行",
            comment_text='原文："DMP 匹配标签数 1；权重 15.0"。',
            kind="mcp",
        )
    ]
    problems = validate_report_comments(comments)
    assert len(problems) == 1
    assert problems[0]["problem"] == "mcp_comment_claims_to_be_original_text"


def test_material_comment_may_quote_original_text():
    comments = [
        ReportComment(
            match_text="公司成立于2001年",
            comment_text="出处：材料第 12 页；原文：公司成立于2001年。",
            kind="material",
        )
    ]
    assert validate_report_comments(comments) == []
