"""批注按句子锚定：一个段落多个来源时，每条批注要落到各自那句上。"""

from __future__ import annotations

from report_agent.infrastructure.word.md_parser import parse_report_markdown

MARKDOWN = """# 测试报告

## 一、项目分析

股权结构：核心团队持股47.99%，早期投资者18.40%。<!-- src: material parse_materials /data/blocks/6/text ; 出处：材料第7页；原文：核心团队47.99% --> 公司下设三家全资子公司。<!-- src: material parse_materials /data/blocks/6/text ; 出处：材料第7页；原文：全资子公司——惠然科学仪器 -->
"""


def _paragraphs():
    content = parse_report_markdown(MARKDOWN, report_id="report_1", title="测试报告", company_name="测试公司", title_evidence_id="evidence_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    return [item for section in content.sections for item in section.paragraphs]


def test_each_src_marker_gets_its_own_sentence_anchor():
    from report_agent.infrastructure.word.authoring import WordReportAuthor

    paragraphs = _paragraphs()
    assert paragraphs, "应解析出段落"
    item = paragraphs[0]

    anchors = item.src_anchors
    assert len(anchors) == 2, "一个段落里的两个 src 都要被保留"

    first, second = anchors
    assert "核心团队持股47.99%" in first["anchor"]
    assert "全资子公司" in second["anchor"]
    assert first["anchor"] != second["anchor"], "两条批注不能共用同一个锚点"


def test_comments_are_queued_per_sentence():
    from report_agent.infrastructure.word.authoring import WordReportAuthor

    author = WordReportAuthor.__new__(WordReportAuthor)  # 只测批注队列，不渲染文档
    author._src_comments = []
    author._collect_src_comment(_paragraphs()[0])

    queued = author.take_src_comments()
    assert len(queued) == 2
    anchors = [anchor for anchor, _ in queued]
    assert "核心团队持股47.99%" in anchors[0]
    assert "全资子公司" in anchors[1]
    assert all(text.startswith("【原材料】") for _, text in queued)


def test_a_paragraph_without_markers_yields_no_comments():
    from report_agent.infrastructure.word.authoring import WordReportAuthor

    author = WordReportAuthor.__new__(WordReportAuthor)
    author._src_comments = []
    content = parse_report_markdown(
        "# 报告\n\n## 一、正文\n\n这句没有来源标记。\n", report_id="r", title="报告", company_name="测试公司", title_evidence_id="evidence_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    )
    for section in content.sections:
        for item in section.paragraphs:
            author._collect_src_comment(item)
    assert author.take_src_comments() == []


def test_two_sources_on_the_same_sentence_share_one_anchor():
    """一句话确实有两个来源时，允许两条批注锚在同一处。"""
    from report_agent.infrastructure.word.authoring import WordReportAuthor
    from report_agent.infrastructure.word.md_parser import parse_report_markdown

    md = (
        "# 报告\n\n## 一、正文\n\n"
        "公司注册资本17,270.695万元，实缴10,197.93万元。"
        "<!-- src: mcp query_company_registry /data/company ; 注册资本=17270.695万元 -->"
        "<!-- src: material parse_materials /data/blocks/1/text ; 原文：实缴资本10,197.93万元 -->\n"
    )
    content = parse_report_markdown(
        md, report_id="r", title="报告", company_name="测试公司",
        title_evidence_id="evidence_" + "c" * 32,
    )
    item = content.sections[0].paragraphs[0]
    assert len(item.src_anchors) == 2
    assert item.src_anchors[0]["anchor"] == item.src_anchors[1]["anchor"]

    author = WordReportAuthor.__new__(WordReportAuthor)
    author._src_comments = []
    author._collect_src_comment(item)
    queued = author.take_src_comments()
    assert len(queued) == 2, "两条批注都要保留，只是锚点相同"
    assert queued[0][0] == queued[1][0]
    assert queued[0][1].startswith("【MCP")
    assert queued[1][1].startswith("【原材")