"""测试：一页纸正文里的分点换行要渲染成真正的换行。"""

from __future__ import annotations

from lxml import etree as ET

from report_agent.infrastructure.word.one_pager_authoring import (
    _tag,
    _write_text_with_breaks,
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _run(text: str = "") -> ET.Element:
    root = ET.fromstring(f'<w:r xmlns:w="{W}"><w:t>{text}</w:t></w:r>')
    return root


def test_newlines_become_real_breaks():
    run = _run()
    node = run.find(_tag("t"))
    _write_text_with_breaks(
        node,
        "1.平台型定位。公司总部位于上海，成立于2015年2月；\n"
        "2.四大业务板块。智慧交易覆盖144家钢厂；\n"
        "3.国资背景。国资委首批员工持股试点。",
    )

    assert len(run.findall(_tag("br"))) == 2, "三个分点之间要有两个换行"
    texts = [t.text for t in run.findall(_tag("t"))]
    assert texts[0].startswith("1.平台型定位")
    assert texts[1].startswith("2.四大业务板块")
    assert texts[2].startswith("3.国资背景")


def test_single_line_text_is_untouched():
    run = _run()
    node = run.find(_tag("t"))
    _write_text_with_breaks(node, "就一句话，没有分点。")

    assert run.findall(_tag("br")) == []
    assert run.find(_tag("t")).text == "就一句话，没有分点。"


def test_break_order_is_text_then_break_then_text():
    run = _run()
    node = run.find(_tag("t"))
    _write_text_with_breaks(node, "第一点\n第二点")

    order = [child.tag for child in run]
    assert order == [_tag("t"), _tag("br"), _tag("t")]
