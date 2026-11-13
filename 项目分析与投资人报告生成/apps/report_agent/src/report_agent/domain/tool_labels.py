"""MCP 工具名 → 面向用户的中文名称。

``read_evidence`` 返回的 ``src`` 标记里带的是英文工具 id（``match_listed_peers``），
模型把它写进批注 note 时也照抄。批注是给业务同学看的，英文 id 没有可读性，
这里统一映射成中文；映射同时用于「note 为空时由工具名兜底」的分支。
"""

from __future__ import annotations

#: 工具 id → 中文名。新增 MCP 工具时同步登记，未登记的原样保留。
TOOL_LABELS: dict[str, str] = {
    "parse_materials": "材料解析",
    "export_parsed_md": "材料导出",
    "extract_project_profile": "项目画像",
    "query_track_labels": "赛道标签",
    "query_comparable_valuation": "可比估值",
    "match_listed_peers": "上市公司对标",
    "match_investors": "投资人匹配",
    "query_company_registry": "工商登记",
    "search_company_web": "公开网页搜索",
    "query_cbex_listing_financials": "北交所挂牌财务",
}

#: 按长度倒序，避免 ``match_investors`` 被 ``match`` 之类的短键先替换。
_SORTED_KEYS = sorted(TOOL_LABELS, key=len, reverse=True)


def humanize_tool(tool: str) -> str:
    """单值映射；未登记的工具名原样返回。"""
    key = str(tool or "").strip()
    return TOOL_LABELS.get(key, key)


def humanize_tools(text: str) -> str:
    """把一段文字里出现的所有工具 id 换成中文名。"""
    result = str(text or "")
    if not result:
        return result
    for key in _SORTED_KEYS:
        if key in result:
            result = result.replace(key, TOOL_LABELS[key])
    return result
