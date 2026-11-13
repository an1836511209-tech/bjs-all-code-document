from __future__ import annotations

from threading import BoundedSemaphore
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from data_mcp.features.cbex_financials import (
    query_cbex_listing_financials as call_query_cbex_listing_financials,
)
from data_mcp.features.company_registry import query_company_registry as call_query_company_registry
from data_mcp.features.historical_valuation import (
    query_comparable_valuation as call_query_comparable_valuation,
)
from data_mcp.features.investor_match import match_investors as call_match_investors
from data_mcp.features.listed_peer_match import match_listed_peers as call_match_listed_peers
from data_mcp.features.project_profile import (
    extract_project_profile as call_extract_project_profile,
)
from data_mcp.features.track_labels import query_track_labels as call_query_track_labels
from data_mcp.features.web_search import search_company_web as call_search_company_web
from data_mcp.mcp.agent_guidance import (
    EXTRACT_PROJECT_PROFILE_DESCRIPTION,
    MATCH_INVESTORS_DESCRIPTION,
    MATCH_LISTED_PEERS_DESCRIPTION,
    QUERY_CBEX_LISTING_FINANCIALS_DESCRIPTION,
    QUERY_COMPANY_REGISTRY_DESCRIPTION,
    QUERY_COMPARABLE_VALUATION_DESCRIPTION,
    QUERY_TRACK_LABELS_DESCRIPTION,
    SEARCH_COMPANY_WEB_DESCRIPTION,
    SERVER_INSTRUCTIONS,
)
from data_mcp.mcp.responses import (
    adapt_cbex_listing_financials,
    adapt_company_registry,
    adapt_company_web_search,
    adapt_comparable_valuation,
    adapt_investors,
    adapt_listed_peers,
    adapt_project_profile,
    adapt_track_labels,
)
from data_mcp.mcp.schemas import validate_tool_input, validate_tool_output
from data_mcp.mcp.tool_errors import guard_tool_errors

mcp = MCPServer("data_mcp", instructions=SERVER_INSTRUCTIONS)
_workbook_slots = BoundedSemaphore(1)


READ_ONLY_EXTERNAL = ToolAnnotations(
    read_only_hint=True,
    open_world_hint=True,
)

READ_ONLY_CLOSED_DOMAIN = ToolAnnotations(
    read_only_hint=True,
    open_world_hint=False,
)


@mcp.tool(name="export_matched_institutions", title="导出投资机构匹配表",
          description="独立查询 DMP 首批最多 200 家机构并导出四列 Excel；只接收最终精选标签。",
          annotations=READ_ONLY_EXTERNAL)
def export_matched_institutions(track_tags: str | list[str]) -> dict[str, Any]:
    # Never use guard_tool_errors: ValidationError chains can contain the entire file.
    from data_mcp.features.investor_match.workbook import (
        export_error_code,
        export_institution_workbook,
    )

    failed = {"schema_version": "1.0", "tool": "export_matched_institutions", "status": "failed",
              "summary": "投资机构匹配表生成失败，原报告不受影响。", "data": {}, "sources": [],
              "warnings": [{"code": "WORKBOOK_EXPORT_FAILED", "message": "请检查导出服务配置或稍后重试。", "retryable": True}]}
    if not _workbook_slots.acquire(blocking=False):
        failed["warnings"][0]["code"] = "WORKBOOK_EXPORT_BUSY"
        return failed
    try:
        validate_tool_input("export_matched_institutions", {"track_tags": track_tags})
        result = export_institution_workbook(track_tags)
        validate_tool_output("export_matched_institutions", result)
        return result
    except Exception as exc:
        failed["warnings"][0]["code"] = export_error_code(exc)
        return failed
    finally:
        _workbook_slots.release()


@mcp.tool(
    name="query_comparable_valuation",
    title="历史成交可比估值查询",
    description=QUERY_COMPARABLE_VALUATION_DESCRIPTION,
    annotations=READ_ONLY_EXTERNAL,
)
@guard_tool_errors("query_comparable_valuation")
def query_comparable_valuation(
    tags: str | list[str],
    company_name: str = "",
) -> dict[str, Any]:

    payload: dict[str, Any] = {"tags": tags}
    if company_name:
        payload["company_name"] = company_name

    validate_tool_input("query_comparable_valuation", payload)

    result = adapt_comparable_valuation(
        call_query_comparable_valuation(
            tags=tags,
            company_name=company_name or "",
            env=None,
        )
    )

    validate_tool_output("query_comparable_valuation", result)

    return result


@mcp.tool(
    name="extract_project_profile",
    title="项目商业模式画像提取",
    description=EXTRACT_PROJECT_PROFILE_DESCRIPTION,
    annotations=READ_ONLY_EXTERNAL,
)
@guard_tool_errors("extract_project_profile")
def extract_project_profile(
    company_name: str,
    file_info: str = "",
    material_url: str = "",
    user_chat_input: str = "",
    search_keywords: str | list[str] = "",
) -> dict[str, Any]:

    payload: dict[str, Any] = {
        "company_name": company_name,
        "file_info": file_info or "",
        "material_url": material_url or "",
        "user_chat_input": user_chat_input or "",
    }

    if search_keywords:
        payload["search_keywords"] = search_keywords

    validate_tool_input("extract_project_profile", payload)

    raw_result = call_extract_project_profile(
        company_name=company_name,
        file_info=file_info or "",
        material_url=material_url or "",
        user_chat_input=user_chat_input or "",
        search_keywords=search_keywords or None,
        env=None,
    )

    result = adapt_project_profile(raw_result)
    validate_tool_output("extract_project_profile", result)

    return result


@mcp.tool(
    name="match_listed_peers",
    title="上市公司可比标的匹配",
    description=MATCH_LISTED_PEERS_DESCRIPTION,
    annotations=READ_ONLY_CLOSED_DOMAIN,
)
@guard_tool_errors("match_listed_peers")
def match_listed_peers(
    tags: str | list[str],
    summary: str = "",
    top_n: int = 0,
    field_weights: dict[str, float] | None = None,
) -> dict[str, Any]:

    payload: dict[str, Any] = {"tags": tags, "summary": summary or ""}

    if top_n and top_n > 0:
        payload["top_n"] = top_n

    if field_weights:
        payload["field_weights"] = field_weights

    validate_tool_input("match_listed_peers", payload)

    raw_result = call_match_listed_peers(
        tags=tags,
        summary=summary or "",
        top_n=top_n if top_n and top_n > 0 else None,
        field_weights=field_weights,
        env=None,
    )

    result = adapt_listed_peers(raw_result)
    validate_tool_output("match_listed_peers", result)

    return result


@mcp.tool(
    name="match_investors",
    title="潜在投资人匹配",
    description=MATCH_INVESTORS_DESCRIPTION,
    annotations=READ_ONLY_EXTERNAL,
)
@guard_tool_errors("match_investors")
def match_investors(
    company_name: str,
    track_tags: str | list[str],
    project_profile: str | dict[str, Any],
    label_type: str = "",
) -> dict[str, Any]:

    payload: dict[str, Any] = {
        "company_name": company_name,
        "track_tags": track_tags,
        "project_profile": project_profile,
    }

    if label_type:
        payload["label_type"] = label_type

    validate_tool_input("match_investors", payload)

    raw_result = call_match_investors(
        company_name=company_name,
        track_tags=track_tags,
        project_profile=project_profile,
        label_type=label_type or "",
        env=None,
    )

    result = adapt_investors(raw_result)
    validate_tool_output("match_investors", result)

    return result


@mcp.tool(
    name="query_track_labels",
    title="查询企业赛道标签",
    description=QUERY_TRACK_LABELS_DESCRIPTION,
    annotations=READ_ONLY_EXTERNAL,
)
@guard_tool_errors("query_track_labels")
def query_track_labels(
    company_name: str,
    project_profile: str | dict[str, Any],
) -> dict[str, Any]:

    payload: dict[str, Any] = {
        "company_name": company_name,
        "project_profile": project_profile,
    }

    validate_tool_input("query_track_labels", payload)

    raw_result = call_query_track_labels(
        company_name=company_name,
        project_profile=project_profile,
        env=None,
    )

    result = adapt_track_labels(raw_result)
    validate_tool_output("query_track_labels", result)

    return result


@mcp.tool(
    name="query_company_registry",
    title="企业工商信息查询",
    description=QUERY_COMPANY_REGISTRY_DESCRIPTION,
    annotations=READ_ONLY_EXTERNAL,
)
@guard_tool_errors("query_company_registry")
def query_company_registry(company_name: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"company_name": company_name}
    validate_tool_input("query_company_registry", payload)
    result = adapt_company_registry(call_query_company_registry(company_name=company_name, env=None))
    validate_tool_output("query_company_registry", result)
    return result


@mcp.tool(
    name="search_company_web",
    title="企业公开网页搜索",
    description=SEARCH_COMPANY_WEB_DESCRIPTION,
    annotations=READ_ONLY_EXTERNAL,
)
@guard_tool_errors("search_company_web")
def search_company_web(
    company_name: str,
    search_keywords: str | list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"company_name": company_name}
    if search_keywords:
        payload["search_keywords"] = search_keywords
    validate_tool_input("search_company_web", payload)
    result = adapt_company_web_search(
        call_search_company_web(
            company_name=company_name,
            search_keywords=search_keywords,
            env=None,
        )
    )
    validate_tool_output("search_company_web", result)
    return result


@mcp.tool(
    name="query_cbex_listing_financials",
    title="北交互联挂牌财务查询",
    description=QUERY_CBEX_LISTING_FINANCIALS_DESCRIPTION,
    annotations=READ_ONLY_EXTERNAL,
)
@guard_tool_errors("query_cbex_listing_financials")
def query_cbex_listing_financials(
    project_name: str,
    detail_url: str = "",
    category: str = "all",
) -> dict[str, Any]:
    payload: dict[str, Any] = {"project_name": project_name}
    if detail_url:
        payload["detail_url"] = detail_url
    if category:
        payload["category"] = category
    validate_tool_input("query_cbex_listing_financials", payload)
    result = adapt_cbex_listing_financials(
        call_query_cbex_listing_financials(
            project_name=project_name,
            detail_url=detail_url,
            category=category or "all",
        )
    )
    validate_tool_output("query_cbex_listing_financials", result)
    return result


def run_server(
    transport: str = "stdio",
    *,
    host: str = "127.0.0.1",
    port: int = 8001,
) -> None:
    """Run Data MCP using one of the official MCP transports."""
    import threading

    from data_mcp.features.listed_peer_match.service import warmup_listed_peer_index

    # Warm the listed-peer embedding index in the background.
    #
    # A full rebuild embeds ~30k slots over HTTP and can take many minutes.
    # Running it inline meant a cold/missing index kept the MCP port closed,
    # which Report Agent treats as a hard readiness failure — every tool
    # became unavailable even though only `match_listed_peers` needs the
    # index. `open_or_build_index` holds a lock, so a concurrent call still
    # waits for the rebuild instead of starting a second one.
    threading.Thread(
        target=warmup_listed_peer_index,
        name="listed-peer-index-warmup",
        daemon=True,
    ).start()

    if transport == "stdio":
        mcp.run(transport="stdio")
        return
    if transport == "streamable-http":
        mcp.run(
            transport="streamable-http",
            host=host,
            port=port,
            streamable_http_path="/mcp",
        )
        return
    raise ValueError(f"unsupported transport: {transport}")


def run_stdio() -> None:
    """Backward-compatible stdio entrypoint."""
    run_server("stdio")
