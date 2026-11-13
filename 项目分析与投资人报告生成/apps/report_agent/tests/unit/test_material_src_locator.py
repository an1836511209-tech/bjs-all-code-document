"""材料引用标记必须带出处：幻灯片按页、文档按段。"""

from __future__ import annotations

import json

from report_agent.harness.material_tools import _locator_label


def test_slide_block_points_at_a_page():
    assert _locator_label({"page": 5, "paragraph": None}) == "材料第 5 页"


def test_document_block_points_at_a_paragraph():
    assert _locator_label({"page": None, "paragraph": 12}) == "材料第 12 段"


def test_page_wins_when_both_are_present():
    assert _locator_label({"page": 3, "paragraph": 9}) == "材料第 3 页"


def test_no_locator_means_no_invented_reference():
    """没有定位信息时宁可不写，也不要编一个页号。"""
    assert _locator_label({}) == ""
    assert _locator_label({"page": None, "paragraph": None}) == ""
    assert _locator_label({"page": 0}) == ""


def test_src_marker_carries_the_locator(monkeypatch):
    """``read_material_chunk`` 生成的 src 标记里,出处要在原文之前。"""
    from report_agent.harness import material_tools

    class _Service:
        def read_chunk(self, material_id, offset, limit):  # noqa: ANN001
            return {
                "material_id": material_id,
                "offset": 0,
                "next_offset": None,
                "blocks": [
                    {
                        "block_id": "page.5",
                        "kind": "page",
                        "text": "每年中国进口100亿人民币。",
                        "locator": {"page": 5, "paragraph": None},
                    }
                ],
            }

    tools = material_tools.build_material_tools(_Service())
    read_chunk = next(t for t in tools if t.name == "read_material_chunk")
    payload = json.loads(read_chunk.invoke({"material_id": "material_x", "limit": 20}))

    src = payload["blocks"][0]["src"]
    assert "出处：材料第 5 页" in src
    assert "原文：每年中国进口100亿人民币。" in src
    assert src.startswith("<!-- src: material parse_materials /data/blocks/0/text ;")
