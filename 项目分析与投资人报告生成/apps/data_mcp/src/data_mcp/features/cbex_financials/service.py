"""查询北交互联挂牌项目披露的主要财务指标。"""

from __future__ import annotations

from typing import Any

from data_mcp.features.cbex_financials.collector import collect_listing_financials


def query_cbex_listing_financials(
    project_name: str,
    detail_url: str = "",
    category: str = "all",
) -> dict[str, Any]:
    """按挂牌项目全称检索北交互联，并提取详情页主要财务指标。"""
    return collect_listing_financials(
        project_name,
        detail_url=detail_url,
        category=category or "all",
    )
