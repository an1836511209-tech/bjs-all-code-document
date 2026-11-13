"""四项快赢的回归：遥测不被脱敏、MCP 字段中文化、一页纸字体统一、推理标签强制。"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from report_agent.domain.one_pager import BusinessType
from report_agent.harness.evidence_tools import _summarize
from report_agent.harness.middleware.agent_logger import _redact
from report_agent.harness.word_tools import ReportComment, validate_report_comments
from report_agent.infrastructure.word import one_pager_authoring

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _tag(name: str) -> str:
    return f"{{{W}}}{name}"


# --------------------------------------------------------------------------- #
# 遥测键不被当成密钥
# --------------------------------------------------------------------------- #

def test_token_counts_survive_redaction():
    """``input_tokens`` is telemetry; redacting it blinded the usage gauge."""
    redacted = _redact(
        {
            "usage_metadata": {
                "input_tokens": 1200,
                "output_tokens": 340,
                "total_tokens": 1540,
                "output_token_details": {"reasoning": 210},
            }
        }
    )
    usage = redacted["usage_metadata"]
    assert usage["input_tokens"] == 1200
    assert usage["output_tokens"] == 340
    assert usage["total_tokens"] == 1540
    assert usage["output_token_details"] == {"reasoning": 210}


def test_real_secrets_are_still_redacted():
    redacted = _redact(
        {
            "api_key": "sk-1",
            "Authorization": "Bearer x",
            "access_token": "t",
            "password": "p",
            "nested": {"secret_value": "s"},
        }
    )
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["access_token"] == "[REDACTED]"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["nested"]["secret_value"] == "[REDACTED]"


# --------------------------------------------------------------------------- #
# MCP 字段名中文化
# --------------------------------------------------------------------------- #

def test_mcp_field_names_are_translated_for_the_reader():
    note = _summarize({"insured_count": 127, "staff_range": "100-199人"})
    assert "参保人数=127" in note
    assert "员工规模=100-199人" in note
    assert "insured_count" not in note


def test_unknown_field_names_survive_instead_of_disappearing():
    note = _summarize({"brand_new_field": 7})
    assert "brand_new_field=7" in note


# --------------------------------------------------------------------------- #
# 一页纸字体统一
# --------------------------------------------------------------------------- #

def _fonts_of_paragraph(paragraph: ET.Element) -> set[str]:
    fonts = set()
    for run in paragraph.iter(_tag("r")):
        element = run.find(f"{_tag('rPr')}/{_tag('rFonts')}")
        if element is not None:
            fonts.add(element.get(_tag("eastAsia")) or element.get(_tag("ascii")) or "")
    return fonts


def _template_paragraph(placeholder: str) -> ET.Element:
    """Find the textbox paragraph that carries ``placeholder`` in the real template."""
    template = one_pager_authoring.resolve_template(BusinessType.PROPERTY)
    with zipfile.ZipFile(template) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    for textbox in root.iter(_tag("txbxContent")):
        for paragraph in textbox.iter(_tag("p")):
            merged = "".join(node.text or "" for node in paragraph.iter(_tag("t")))
            if placeholder in merged:
                return paragraph
    raise AssertionError(f"template has no paragraph for {placeholder}")


def test_body_placeholder_is_pinned_to_the_body_font():
    """``{{项目亮点正文3}}`` was authored in 仿宋 while its neighbours use 仿宋_GB2312."""
    paragraph = _template_paragraph("{{项目亮点正文3}}")
    filled, unresolved = one_pager_authoring._rewrite_paragraph(
        paragraph, {"项目亮点正文3": "第三段亮点正文"}
    )
    assert filled == ("项目亮点正文3",) and unresolved == ()
    assert _fonts_of_paragraph(paragraph) == {one_pager_authoring.BODY_FONT}


def test_contact_placeholder_is_pinned_to_the_body_font():
    paragraph = _template_paragraph("{{联系人名称}}")
    one_pager_authoring._rewrite_paragraph(paragraph, {"联系人名称": "张三"})
    assert _fonts_of_paragraph(paragraph) == {one_pager_authoring.BODY_FONT}


def test_heading_placeholder_is_pinned_to_the_heading_font():
    paragraph = _template_paragraph("{{项目亮点标题1}}")
    one_pager_authoring._rewrite_paragraph(paragraph, {"项目亮点标题1": "业绩高增长"})
    assert _fonts_of_paragraph(paragraph) == {one_pager_authoring.HEADING_FONT}


# --------------------------------------------------------------------------- #
# 推理标签：必须说清依据在哪 / 有没有依据
# --------------------------------------------------------------------------- #

def _comment(**kwargs) -> ReportComment:
    base = {"match_text": "公司2024年营收2.3亿元。", "comment_text": "", "kind": "material"}
    base.update(kwargs)
    return ReportComment(**base)


def test_reasoned_comment_needs_both_basis_and_inference():
    problems = validate_report_comments(
        [_comment(kind="reasoned", comment_text="基于材料推理，团队壁垒高")]
    )
    assert [p["problem"] for p in problems] == ["reasoned_comment_missing_basis"]


def test_reasoned_comment_passes_with_basis_and_inference():
    problems = validate_report_comments([
        _comment(
            kind="reasoned",
            comment_text="依据：材料第 6 页（创始团队来自AMAT）+ 第 7 页（平均从业12年）；推理：团队具备量产经验，交付风险低",
        )
    ])
    assert problems == []


def test_unreasoned_comment_must_admit_it_has_no_material_basis():
    problems = validate_report_comments(
        [_comment(kind="unreasoned", comment_text="该赛道估值中枢在 15-20x PE")]
    )
    assert [p["problem"] for p in problems] == ["unreasoned_comment_not_labelled"]


def test_unreasoned_comment_passes_when_labelled():
    problems = validate_report_comments([
        _comment(kind="unreasoned", comment_text="无材料依据，属经验判断：该赛道估值中枢在 15-20x PE")
    ])
    assert problems == []


def test_document_wide_font_normalization_removes_aliases():
    """模板里 25 个 run 写的是「方正仿宋_GB2312」，用户机器上没装 → 缺失字体回退。

    只按精确名字匹配挡不住这类变体，所以按家族收敛：名字含"仿宋"归到
    `仿宋_GB2312`，含"黑体"归到 `黑体`。
    """
    from xml.etree import ElementTree as ET

    from report_agent.infrastructure.word.one_pager_authoring import (
        BODY_FONT,
        HEADING_FONT,
        _normalize_document_fonts,
    )

    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = (
        f'<w:document xmlns:w="{w}"><w:body>'
        '<w:p><w:r><w:rPr><w:rFonts w:eastAsia="方正仿宋_GB2312"/></w:rPr>'
        "<w:t>面议</w:t></w:r></w:p>"
        '<w:p><w:r><w:rPr><w:rFonts w:eastAsia="仿宋"/></w:rPr><w:t>文字</w:t></w:r></w:p>'
        '<w:p><w:r><w:rPr><w:rFonts w:eastAsia="黑体"/></w:rPr><w:t>标题</w:t></w:r></w:p>'
        "<w:p><w:r><w:t>继承样式</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    root = ET.fromstring(xml)
    changed = _normalize_document_fonts(root)

    fonts = [
        run.find(f"{{{w}}}rPr/{{{w}}}rFonts").get(f"{{{w}}}eastAsia")
        for run in root.iter(f"{{{w}}}r")
        if run.find(f"{{{w}}}rPr/{{{w}}}rFonts") is not None
    ]
    assert changed == 3
    assert fonts == [BODY_FONT, BODY_FONT, HEADING_FONT]
    first = root.find(f"{{{w}}}body/{{{w}}}p/{{{w}}}r/{{{w}}}rPr/{{{w}}}rFonts")
    for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
        assert first.get(f"{{{w}}}{attribute}") == BODY_FONT, "数字/英文也要用同一个字体名"


def test_normalization_leaves_runs_without_explicit_fonts():
    from xml.etree import ElementTree as ET

    from report_agent.infrastructure.word.one_pager_authoring import (
        _normalize_document_fonts,
    )

    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    root = ET.fromstring(
        f'<w:document xmlns:w="{w}"><w:body>'
        "<w:p><w:r><w:t>继承</w:t></w:r></w:p></w:body></w:document>"
    )
    assert _normalize_document_fonts(root) == 0