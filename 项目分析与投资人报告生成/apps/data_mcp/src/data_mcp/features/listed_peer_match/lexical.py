"""轻量中文关键词证据。只验证文本重合，不声称商业模式完全可比。"""

from __future__ import annotations

import re

from data_mcp.features.listed_peer_match.corpus import ListedCompany

# 这些通用修饰语不应单独构成业务匹配证据。
_GENERIC = (
    "数字化",
    "智能化",
    "一体化",
    "面向",
    "提供",
    "服务",
    "客户",
    "企业",
    "公司",
    "业务",
    "产品",
    "平台",
    "技术",
    "解决方案",
    "开发",
    "研发",
    "生产",
    "销售",
    "从事",
    "主要",
    "该公司",
)


def query_terms(text: str) -> set[str]:
    text = text.lower()
    for word in _GENERIC:
        text = text.replace(word, " ")
    terms: set[str] = set()
    for part in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", text):
        if re.fullmatch(r"[a-z0-9]+", part):
            if len(part) > 1:
                terms.add(part)
        else:
            terms.update(part[i : i + 2] for i in range(len(part) - 1))
    return terms


def business_hits(company: ListedCompany, terms: set[str]) -> set[str]:
    # 标签本身不能证明主营业务；客户/产品/行业中的事实才算证据。
    text = company.matching_profile().lower()
    return {term for term in terms if term in text}
