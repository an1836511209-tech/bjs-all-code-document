"""智谱网页搜索，供报告事实不足时按企业名称补充公开信息。"""

from __future__ import annotations

from typing import Any

from data_mcp.features.project_profile.zhipu_client import (
    build_search_queries,
    fetch_web_search,
    summarize_search_response,
)
from data_mcp.shared.http.errors import ExternalServiceError, public_message_for_exception
from data_mcp.shared.settings import load_project_profile_zhipu_config

MAX_SUPPLEMENT_QUERIES = 5


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _keyword_list(search_keywords: str | list[str] | None) -> list[str]:
    if isinstance(search_keywords, str):
        return [part.strip() for part in search_keywords.split(",") if part.strip()]
    if isinstance(search_keywords, list):
        return [_text(part) for part in search_keywords if _text(part)]
    return []


def _queries_for_company(
    company_name: str,
    search_keywords: str | list[str] | None,
    query_templates: list[str] | None,
) -> list[str]:
    keywords = _keyword_list(search_keywords)[:MAX_SUPPLEMENT_QUERIES]
    if keywords:
        queries: list[str] = []
        for keyword in keywords:
            scoped = keyword if company_name in keyword else f"{company_name} {keyword}".strip()
            if scoped and scoped not in queries:
                queries.append(scoped)
        return queries
    return build_search_queries(company_name, None, query_templates=query_templates)


def search_company_web(
    company_name: str,
    search_keywords: str | list[str] | None = None,
    env: str | None = None,
) -> dict[str, Any]:
    """调用智谱 Web Search。未给关键词时使用配置模板；给定时只查这些补充词。"""
    name = _text(company_name)
    if not name:
        raise ValueError("company_name 不能为空")

    cfg = load_project_profile_zhipu_config(env)
    templates = cfg.get("query_templates")
    template_list = templates if isinstance(templates, list) else None
    queries = _queries_for_company(name, search_keywords, template_list)
    if not queries:
        raise ValueError("搜索关键词为空")

    searches: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_urls: set[str] = set()
    upstream_failures = 0

    for query in queries:
        try:
            payload = fetch_web_search(query, cfg)
        except Exception as exc:
            upstream_failures += 1
            warnings.append(f"智谱搜索失败({query}): {public_message_for_exception(exc)}")
            continue

        summary = summarize_search_response(query, payload)
        deduped: list[dict[str, str]] = []
        for item in summary.get("results") or []:
            if not isinstance(item, dict):
                continue
            url = _text(item.get("url"))
            if url:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
            deduped.append(
                {
                    "title": _text(item.get("title")),
                    "url": url,
                    "summary": _text(item.get("summary")),
                    "site_name": _text(item.get("site_name")),
                }
            )
        deduped = [item for item in deduped if item["title"] or item["summary"]]
        if deduped:
            searches.append({"query": query, "results": deduped})
        else:
            warnings.append(f"智谱搜索无结果: {query}")

    if not searches and upstream_failures == len(queries):
        raise ExternalServiceError("智谱搜索", "智谱搜索暂不可用")

    return {"company_name": name, "searches": searches, "warnings": warnings}
