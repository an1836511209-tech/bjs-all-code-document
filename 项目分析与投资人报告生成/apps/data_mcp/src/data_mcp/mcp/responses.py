"""Agent-oriented MCP response envelopes and feature result adapters."""

from __future__ import annotations

from typing import Any, cast

SCHEMA_VERSION = "1.0"
_NO_RESULT_PHRASES = ("未找到", "未查询到", "未检索到", "没有可比", "暂无可比")


def _warnings(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [
        {"code": "DATA_INCOMPLETE", "message": str(item).strip(), "retryable": False}
        for item in items
        if str(item).strip()
    ]


def envelope(
    tool: str,
    *,
    data: dict[str, Any],
    summary: str,
    sources: list[dict[str, str]],
    warnings: Any = None,
    empty: bool = False,
) -> dict[str, Any]:
    warning_items = _warnings(warnings)
    status = "empty" if empty else ("partial" if warning_items else "success")
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": tool,
        "status": status,
        "summary": summary,
        "data": data,
        "sources": sources,
        "warnings": warning_items,
    }


def failed_envelope(tool: str, *, message: str, code: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": tool,
        "status": "failed",
        "summary": message,
        "data": {},
        "sources": [],
        "warnings": [{"code": code, "message": message, "retryable": False}],
    }


def adapt_project_profile(result: dict[str, Any]) -> dict[str, Any]:
    profile = result.get("profile")
    warnings = result.get("warnings")
    qichacha_ok = result.get("qichacha_info") is not None
    zhipu_ok = result.get("zhipu_info") is not None
    data = {
        "profile": profile,
        "field_details": result.get("field_details", {}),
        "conflicts": result.get("conflicts", []),
    }
    empty = profile is None
    summary = "已生成带字段证据的项目画像" if not empty else "本次未生成可用项目画像"
    return envelope(
        "extract_project_profile",
        data=data,
        summary=summary,
        sources=[
            {"name": "project_document", "status": "used"},
            {"name": "qichacha", "status": "used" if qichacha_ok else "unavailable"},
            {"name": "zhipu", "status": "used" if zhipu_ok else "unavailable"},
            {"name": "hiagent", "status": "used"},
        ],
        warnings=warnings,
        empty=empty,
    )


def adapt_track_labels(result: dict[str, Any]) -> dict[str, Any]:
    tags = result.get("tags") if isinstance(result.get("tags"), list) else []
    source = str(result.get("source") or "")
    raw_meta = result.get("meta")
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    local_recall = bool(meta.get("local_recall_used")) or source == "local_recall"
    return envelope(
        "query_track_labels",
        # Only business data belongs here; provenance lives in sources.
        data={"tags": tags},
        summary=f"本次获得 {len(tags)} 个赛道标签" if tags else "本次未获得合适的赛道标签",
        sources=[
            {"name": "lms", "status": "used" if source == "api" else "unavailable"},
            {"name": "hiagent", "status": "used" if source == "fallback" else "not_used"},
            {
                "name": "taxonomy",
                "status": "used" if source in {"fallback", "local_recall"} else "not_used",
            },
            {"name": "local_recall", "status": "used" if local_recall else "not_used"},
        ],
        warnings=result.get("warnings"),
        empty=not tags,
    )


def adapt_listed_peers(result: dict[str, Any]) -> dict[str, Any]:
    peers = cast(list[Any], result.get("peers")) if isinstance(result.get("peers"), list) else []
    meta = cast(dict[str, Any], result.get("meta")) if isinstance(result.get("meta"), dict) else {}
    public_meta = {
        key: meta.get(key)
        for key in (
            "matching_version",
            "assessment_status",
            "score_kind",
            "corpus_size",
            "recall_k",
            "rerank_enabled",
            "embedding_backend",
        )
        if key in meta
    }
    return envelope(
        "match_listed_peers",
        data={
            "query": result.get("query", {}),
            "weights_used": result.get("weights_used", {}),
            "peers": peers,
            "meta": public_meta,
        },
        summary=f"本次获得 {len(peers)} 个上市公司候选" if peers else "本次未获得合适的上市公司候选",
        sources=[{"name": "listed_peer_corpus", "status": "used"}],
        empty=not peers,
    )


def adapt_comparable_valuation(result: dict[str, Any]) -> dict[str, Any]:
    choices = cast(list[Any], result.get("choice")) if isinstance(result.get("choice"), list) else []
    contents = [
        str(item.get("content") or item.get("text") or "").strip()
        for item in choices
        if isinstance(item, dict) and str(item.get("content") or item.get("text") or "").strip()
    ]
    content = "\n\n".join(contents)
    no_result = not content or any(phrase in content for phrase in _NO_RESULT_PHRASES)
    return envelope(
        "query_comparable_valuation",
        data={"content": content},
        summary="本次未获得合适的历史成交可比估值数据" if no_result else "已获得历史成交可比估值分析",
        sources=[{"name": "hiagent", "status": "used"}],
        empty=no_result,
    )


def adapt_company_registry(result: dict[str, Any]) -> dict[str, Any]:
    company = result.get("company") if isinstance(result.get("company"), dict) else None
    found = bool(company)
    response = envelope(
        "query_company_registry",
        data={"company": company},
        summary="已获得企业工商摘要" if found else "本次未查询到该企业的工商信息",
        sources=[{"name": "qichacha", "status": "used" if found else "no_result"}],
        warnings=result.get("warnings"),
        empty=not found,
    )
    code = result.get("warning_code")
    if code in {"COMPANY_NAME_NOT_EXACT", "COMPANY_NOT_FOUND"}:
        for warning in response["warnings"]:
            warning.update(code=code, retryable=True)
    return response


def adapt_cbex_listing_financials(result: dict[str, Any]) -> dict[str, Any]:
    annual = result.get("annual") if isinstance(result.get("annual"), list) else []
    latest = result.get("latest") if isinstance(result.get("latest"), list) else []
    candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
    issue_source = result.get("issues")
    issue_list: list[Any] = issue_source if isinstance(issue_source, list) else []
    stage = str(result.get("stage") or "")
    has_financials = bool(annual or latest)
    warnings = [text for text in (str(item).strip() for item in issue_list) if text]
    if stage == "selection_required":
        warnings.append("存在多个同名或相似项目，请选定 detail_url 后重试")
    elif stage == "search_incomplete":
        warnings.append("北交互联搜索未完成，本次没有可用财务数据")
    if has_financials and stage == "done":
        summary = (
            "已提取北交互联多年度财务数据，金额单位为万元"
            if not warnings
            else "已提取部分北交互联财务数据，金额单位为万元，使用前需核对质量问题"
        )
        empty = False
    elif stage == "selection_required" and candidates:
        summary = f"找到 {len(candidates)} 个相似挂牌项目，需要选定详情页后再提取财务数据"
        empty = False
    elif stage == "not_found":
        summary = "没有找到名称匹配的北交互联挂牌项目"
        empty = True
    else:
        summary = "本次未获得可用的北交互联财务数据"
        empty = True
    match_score = result.get("match_score")
    return envelope(
        "query_cbex_listing_financials",
        data={
            "project_name": str(result.get("project_name") or ""),
            "matched_project_name": str(result.get("matched_project_name") or ""),
            "detail_url": str(result.get("detail_url") or ""),
            "project_type": str(result.get("project_type") or ""),
            "match_score": match_score if isinstance(match_score, int) else None,
            "quality_status": str(result.get("quality_status") or ""),
            "unit": "万元",
            "annual": annual,
            "latest": latest,
            "candidates": candidates,
        },
        summary=summary,
        sources=[{"name": "cbex_otc", "status": "used" if has_financials or candidates else "no_result"}],
        warnings=warnings,
        empty=empty,
    )


def adapt_company_web_search(result: dict[str, Any]) -> dict[str, Any]:
    raw_searches = result.get("searches")
    searches = raw_searches if isinstance(raw_searches, list) else []
    result_count = 0
    for item in searches:
        if not isinstance(item, dict):
            continue
        results = item.get("results")
        if isinstance(results, list):
            result_count += len(results)
    found = result_count > 0
    return envelope(
        "search_company_web",
        data={
            "company_name": str(result.get("company_name") or ""),
            "searches": searches,
        },
        summary=f"本次获得 {result_count} 条公开网页结果" if found else "本次未获得可用的公开网页结果",
        sources=[{"name": "zhipu", "status": "used" if found else "no_result"}],
        warnings=result.get("warnings"),
        empty=not found,
    )


def adapt_investors(result: dict[str, Any]) -> dict[str, Any]:
    candidates = cast(list[Any], result.get("merged")) if isinstance(result.get("merged"), list) else []
    internal = cast(dict[str, Any], result.get("internal")) if isinstance(result.get("internal"), dict) else {}
    network = cast(dict[str, Any], result.get("network")) if isinstance(result.get("network"), dict) else {}
    meta = cast(dict[str, Any], result.get("meta")) if isinstance(result.get("meta"), dict) else {}
    return envelope(
        "match_investors",
        data={
            "candidates": candidates,
            "counts": {
                "internal_institutions": internal.get("institution_count", 0),
                "internal_individuals_excluded": internal.get("individual_count", 0),
                "network_institutions": network.get("institution_count", 0),
            },
            "shareholder_filter_applied": bool(meta.get("shareholders_filtered")),
        },
        summary=f"本次获得 {len(candidates)} 个潜在投资机构候选" if candidates else "本次未获得合适的潜在投资机构候选",
        sources=[
            {"name": str(meta.get("internal_source") or "internal"), "status": "used"},
            {"name": "qichacha", "status": "used" if meta.get("shareholders_filtered") else "unavailable"},
            {"name": "hiagent_network", "status": "used" if network.get("institution_count") else "no_result"},
        ],
        warnings=result.get("warnings"),
        empty=not candidates,
    )
