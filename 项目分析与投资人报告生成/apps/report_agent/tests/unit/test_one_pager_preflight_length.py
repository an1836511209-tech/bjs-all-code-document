"""Writing targets must not become an endless render/rewrite loop."""
from __future__ import annotations

import pytest

from report_agent.domain.one_pager import (
    HIGHLIGHT_BODY_HARD_LIMIT,
    HIGHLIGHT_BODY_RANGE,
    INTRO_BODY_HARD_LIMIT,
    INTRO_BODY_RANGE,
)
from report_agent.harness.one_pager_tools import preflight_one_pager_md


def _body(n: int, seed: str = "测") -> str:
    return (seed * n)[:n]


def _md(*, intro_len: int, highlight_len: int) -> str:
    intro = "\n\n".join(
        f"### {title}\n{_body(intro_len)}"
        for title in ("核心产品", "市场布局", "团队构成")
    )
    highlight = "\n\n".join(
        f"### {title}\n{_body(highlight_len)}"
        for title in ("技术壁垒强", "客户验证充分", "增长空间明确")
    )
    return f"""# 项目概览

## 基本信息

- 项目名称：示例项目
- 公司全称：示例科技有限公司
- 所属区域：北京市
- 所属行业：高端装备
- 原始简介：公司从事精密仪器研发与制造。
- 联系人名称：待补充
- 拟募集金额：面议
- 对应持股比例：待定

## 项目介绍

{intro}

## 项目亮点

{highlight}

## 投资人匹配

| 序号 | 来源 | 投资人类型 | 投资人名称 | 匹配理由 |
|------|------|-----------|-----------|---------|
| 1 | 内部库 | 机构 | 示例基金 | 赛道匹配 |
"""


def test_preflight_accepts_in_range_bodies() -> None:
    issues = preflight_one_pager_md(
        _md(intro_len=INTRO_BODY_RANGE[0], highlight_len=HIGHLIGHT_BODY_RANGE[0]),
        "增资",
    )
    assert issues == []


def test_preflight_accepts_small_deviations_from_writing_targets() -> None:
    assert preflight_one_pager_md(_md(intro_len=222, highlight_len=198), "增资") == []
    assert preflight_one_pager_md(_md(intro_len=198, highlight_len=190), "增资") == []


def test_preflight_reports_only_extreme_overflow_with_delta() -> None:
    issues = preflight_one_pager_md(
        _md(intro_len=INTRO_BODY_HARD_LIMIT + 20, highlight_len=HIGHLIGHT_BODY_HARD_LIMIT + 15),
        "增资",
    )
    messages = {item["field"]: item["message"] for item in issues}
    assert "项目介绍.核心产品" in messages
    assert f"正文字数 {INTRO_BODY_HARD_LIMIT + 20}" in messages["项目介绍.核心产品"]
    assert f"硬上限 {INTRO_BODY_HARD_LIMIT} 字" in messages["项目介绍.核心产品"]
    assert "超出 20 字" in messages["项目介绍.核心产品"]
    assert "项目亮点.技术壁垒强" in messages
    assert f"正文字数 {HIGHLIGHT_BODY_HARD_LIMIT + 15}" in messages["项目亮点.技术壁垒强"]
    assert "超出 15 字" in messages["项目亮点.技术壁垒强"]


def test_preflight_excludes_multiline_source_comments_and_quoted_headings() -> None:
    md = _md(intro_len=240, highlight_len=175)
    md = md.replace(
        _body(240),
        _body(240) + "\n<!-- src: material parse_materials\n/data/blocks/0/text ; 原文："
        + "这是材料中的引用，不属于正文。" * 8
        + "\n## 项目介绍\n### 材料原标题\n-->",
        1,
    )
    assert preflight_one_pager_md(md, "增资") == []


def test_preflight_still_rejects_empty_copy_with_long_source_comment() -> None:
    md = _md(intro_len=200, highlight_len=175)
    md = md.replace(_body(200), "\n<!-- src:\n" + "来源" * 30 + "\n-->", 1)
    issues = preflight_one_pager_md(md, "增资")
    assert "段正文为空" in issues[0]["message"]


@pytest.mark.parametrize(
    "table",
    [
        "| 指标 | 2024年度 |\n|---|---|\n| 营业收入（亿元） | 1.00 |",
        "指标 | 2024年度\n:--- | ---:\n营业收入（亿元） | 1.00",
        "<table><tr><td>营业收入1.00亿元</td></tr></table>",
    ],
)
def test_preflight_rejects_tables_in_financial_analysis(table: str) -> None:
    md = _md(intro_len=200, highlight_len=175).replace(
        f"### 市场布局\n{_body(200)}",
        f"### 经营分析\n2024年度财务指标如下。\n\n{table}",
    )

    issues = preflight_one_pager_md(md, "增资")

    assert [issue["field"] for issue in issues] == ["项目介绍.经营分析"]
    assert "禁止表格" in issues[0]["message"]


def test_preflight_accepts_financial_summary_with_a_table_in_its_source() -> None:
    md = _md(intro_len=200, highlight_len=175).replace(
        f"### 市场布局\n{_body(200)}",
        "### 经营分析\n2024年（快报数），营业收入1.00亿元，利润总额1.30亿元。\n"
        "<!-- src: 材料原文\n| 指标 | 2024年度 |\n|---|---|\n-->"
    )

    assert preflight_one_pager_md(md, "增资") == []
