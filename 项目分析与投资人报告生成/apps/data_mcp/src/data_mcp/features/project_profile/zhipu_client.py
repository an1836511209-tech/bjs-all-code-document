from __future__ import annotations

import json
from typing import Any

from data_mcp.shared.http.errors import (
    public_message_for_exception,
    raise_from_http_error,
    raise_invalid_json_response,
)
from data_mcp.shared.http.retry_client import http_request
from data_mcp.shared.settings import load_http_retry_config, load_project_profile_zhipu_config

DEFAULT_QUERY_TEMPLATES: tuple[str, ...] = (
    "{company_name} 主营业务 产品",
    "{company_name} 行业 赛道",
    "{company_name} 证券代码 上市",
)

# 每个搜索词保留的结果条数（传给智能体与 MCP 返回一致）
MAX_RESULTS_PER_QUERY = 2


def _is_zhipu_configured(cfg: dict[str, Any]) -> bool:
    return bool(
        str(cfg.get("api_key") or "").strip()
        and str(cfg.get("base_url") or "").strip()
        and str(cfg.get("path") or "").strip()
    )


def build_search_queries(
    company_name: str,
    search_keywords: str | list[str] | None = None,
    *,
    query_templates: list[str] | None = None,
) -> list[str]:
    """根据企业名称模板与可选关键词生成去重后的搜索词列表。"""
    name = str(company_name or "").strip()
    templates = query_templates or list(DEFAULT_QUERY_TEMPLATES)
    queries: list[str] = []

    for template in templates:
        text = str(template or "").strip()
        if not text:
            continue
        query = text.format(company_name=name).strip()
        if query and query not in queries:
            queries.append(query)

    extra: list[str] = []
    if isinstance(search_keywords, str):
        extra = [part.strip() for part in search_keywords.split(",") if part.strip()]
    elif isinstance(search_keywords, list):
        extra = [str(part).strip() for part in search_keywords if str(part).strip()]

    for query in extra:
        if query not in queries:
            queries.append(query)
    return queries


def fetch_web_search(query: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """调用智谱 Web Search API，返回完整 JSON 对象。"""
    text = str(query or "").strip()
    if not text:
        raise ValueError("search_query 不能为空")
    if not _is_zhipu_configured(cfg):
        raise RuntimeError("智谱搜索未配置 api_key")

    base = str(cfg["base_url"]).rstrip("/")
    path = str(cfg["path"]).strip()
    if not path.startswith("/"):
        path = f"/{path}"
    url = f"{base}{path}"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "search_engine": str(cfg.get("search_engine") or "search_pro"),
        "search_query": text,
        "count": min(int(cfg.get("count") or MAX_RESULTS_PER_QUERY), MAX_RESULTS_PER_QUERY),
    }
    timeout = float(cfg.get("timeout_seconds") or 30)

    retry_cfg = load_http_retry_config()
    try:
        response = http_request(
            "POST",
            url,
            headers=headers,
            json=body,
            timeout=timeout,
            service_name="zhipu_search",
            max_retries=retry_cfg["max_retries"],
            backoff_base_seconds=retry_cfg["backoff_base_seconds"],
            backoff_max_seconds=retry_cfg["backoff_max_seconds"],
        )
    except Exception as exc:
        raise_from_http_error("智谱搜索", exc)

    try:
        data = response.json()
    except Exception:
        raise_invalid_json_response(
            "智谱搜索",
            status_code=response.status_code,
            body=response.text if isinstance(response.text, str) else None,
        )

    if not isinstance(data, dict):
        raise RuntimeError("智谱搜索返回格式无效")
    return data


def _normalize_result_item(item: dict[str, Any]) -> dict[str, str]:
    return {
        "title": str(item.get("title") or "").strip(),
        "url": str(item.get("link") or item.get("url") or "").strip(),
        "summary": str(item.get("content") or item.get("summary") or "").strip(),
        "site_name": str(item.get("media") or item.get("site_name") or "").strip(),
    }


def summarize_search_response(
    query: str,
    payload: dict[str, Any],
    *,
    max_results: int = MAX_RESULTS_PER_QUERY,
) -> dict[str, Any]:
    """将单次搜索响应精简为画像用结构，每个问题最多保留 max_results 条。"""
    results_raw = payload.get("search_result") or payload.get("searchResult") or []
    results: list[dict[str, str]] = []
    if isinstance(results_raw, list):
        for item in results_raw:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_result_item(item)
            if normalized["title"] or normalized["summary"]:
                results.append(normalized)
            if len(results) >= max_results:
                break
    return {"query": query, "results": results}


def summarize_zhipu_for_portrait(
    company_name: str,
    searches: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "company_name": str(company_name or "").strip(),
        "searches": searches,
    }


def resolve_zhipu_info_for_portrait(
    company_name: str,
    env: str | None = None,
    search_keywords: str | list[str] | None = None,
) -> tuple[str, list[str]]:
    """
    拉取并精简智谱搜索结果，供画像 state.zhipu_info 使用。
    返回 (json_string_or_empty, warnings)。失败不抛给调用方业务层。
    """
    name = str(company_name or "").strip()
    if not name:
        return "", ["company_name 不能为空"]

    try:
        cfg = load_project_profile_zhipu_config(env)
    except Exception:
        return "", ["智谱搜索配置加载失败"]

    if not _is_zhipu_configured(cfg):
        return "", ["智谱搜索未配置 api_key"]

    templates = cfg.get("query_templates")
    template_list = templates if isinstance(templates, list) else None
    queries = build_search_queries(name, search_keywords, query_templates=template_list)
    if not queries:
        return "", ["智谱搜索关键词为空"]

    searches: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_urls: set[str] = set()

    for query in queries:
        try:
            payload = fetch_web_search(query, cfg)
        except Exception as exc:
            warnings.append(f"智谱搜索失败({query}): {public_message_for_exception(exc)}")
            continue

        summary = summarize_search_response(query, payload)
        deduped_results: list[dict[str, str]] = []
        for item in summary.get("results") or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if url:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
            deduped_results.append(item)
            if len(deduped_results) >= MAX_RESULTS_PER_QUERY:
                break

        if deduped_results:
            searches.append({"query": query, "results": deduped_results})
        else:
            warnings.append(f"智谱搜索无结果: {query}")

    if not searches:
        detail = "; ".join(warnings) if warnings else "全部查询无结果"
        return "", [f"智谱搜索未返回可用结果: {detail}"]

    payload = summarize_zhipu_for_portrait(name, searches)
    return json.dumps(payload, ensure_ascii=False), warnings
