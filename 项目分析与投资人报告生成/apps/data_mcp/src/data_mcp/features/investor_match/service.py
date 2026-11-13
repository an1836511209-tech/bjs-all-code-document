from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from data_mcp.features.investor_match.dmp_client import FIXED_LABEL_TYPE
from data_mcp.features.investor_match.rules import (
    classify_investor_type,
    dedupe_network_against_internal,
    filter_out_shareholders,
)
from data_mcp.features.investor_match.tag_normalize import strip_wrapping_quotes
from data_mcp.shared.http.errors import public_message_for_exception

# DMP 首选：返回 institutions + individual_count；失败再走内部库 list。
FetchDmpFn = Callable[..., dict[str, Any]]
FetchDbFn = Callable[..., list[dict[str, Any]]]
FetchShareholdersFn = Callable[..., list[str]]
FetchNetworkFn = Callable[..., list[dict[str, Any]]]

logger = logging.getLogger(__name__)


def _normalize_tags(track_tags: str | list[Any] | None) -> list[str]:
    if track_tags is None:
        return []
    if isinstance(track_tags, list):
        return [
            strip_wrapping_quotes(str(t))
            for t in track_tags
            if strip_wrapping_quotes(str(t))
        ]
    text = str(track_tags).strip()
    if not text:
        return []
    cleaned = text.strip("[]")
    parts = []
    for sep in ("，", ",", ";", "；", "|"):
        if sep in cleaned:
            parts = [p.strip() for p in cleaned.split(sep)]
            break
    if not parts:
        parts = [cleaned]
    return [stripped for p in parts if (stripped := strip_wrapping_quotes(p))]


def _ensure_profile(project_profile: str | dict[str, Any] | None) -> str | dict[str, Any]:
    if project_profile is None:
        raise ValueError("project_profile 不能为空")
    if isinstance(project_profile, dict):
        if not project_profile:
            raise ValueError("project_profile 不能为空")
        return project_profile
    text = str(project_profile).strip()
    if not text:
        raise ValueError("project_profile 不能为空")
    return text


def _make_citation(
    *,
    source_type: str,
    source_name: str,
    quote: str,
    source_url: str = "",
) -> dict[str, str]:
    return {
        "source_type": str(source_type or "").strip(),
        "source_name": str(source_name or "").strip(),
        "source_url": str(source_url or "").strip(),
        "quote": str(quote or "").strip(),
    }


def _annotate_candidate(
    item: dict[str, Any],
    *,
    source: str,
    citation_source_type: str,
    citation_source_name: str,
    default_institution: bool = False,
) -> dict[str, Any]:
    name = str(item.get("name") or "").strip()
    investor_type = classify_investor_type(
        name,
        item.get("usr_cgy_cd_dsc"),
        default_institution=default_institution,
    )
    match_reason = str(item.get("match_reason") or "")
    source_name = str(item.get("source_name") or "").strip() or citation_source_name
    return {
        "name": name,
        "investor_type": investor_type,
        "source": source,
        "score": item.get("score"),
        "match_reason": match_reason,
        "citations": [
            _make_citation(
                source_type=citation_source_type,
                source_name=source_name,
                source_url=str(item.get("source_url") or ""),
                quote=match_reason,
            )
        ],
    }


def _public_candidate(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item["name"],
        "investor_type": item["investor_type"],
        "source": item["source"],
        "score": item.get("score"),
        "match_reason": item.get("match_reason"),
        "citations": list(item.get("citations") or []),
    }


def match_investors(
    company_name: str,
    track_tags: str | list[Any],
    project_profile: str | dict[str, Any],
    label_type: str = "",
    env: str | None = None,
    *,
    fetch_dmp: FetchDmpFn | None = None,
    fetch_db: FetchDbFn | None = None,
    fetch_shareholders: FetchShareholdersFn | None = None,
    fetch_network: FetchNetworkFn | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """编排内部库 + 企查查 + 网络搜索，返回结构化投资人匹配结果。

    内部候选优先 DMP（机构列表 + 个人总数）；DMP 不通再走原有内部投资人库。
    网络候选仍走 HiAgent。
    """
    company = str(company_name or "").strip()
    if not company:
        raise ValueError("company_name 不能为空")

    tags = _normalize_tags(track_tags)
    if not tags:
        raise ValueError("track_tags 不能为空")

    profile = _ensure_profile(project_profile)
    # label_type 保留兼容入参；DMP 侧已固定为「股权转让/增资」，不再依赖 agent 填写。
    _ = str(label_type or "").strip()

    from data_mcp.shared.settings import load_investor_match_config, resolve_env

    cfg = config or load_investor_match_config(env)
    selected_env = resolve_env(env)
    internal_top_n = int(cfg.get("internal_top_n") or 100)
    network_top_n = int(cfg.get("network_top_n") or 10)

    warnings: list[str] = []

    # --- internal ---
    if fetch_dmp is None:
        from data_mcp.features.investor_match.dmp_client import query_dmp_investors as fetch_dmp
    if fetch_db is None:
        from data_mcp.features.investor_match.repository import query_touziren_investors as fetch_db
    if fetch_shareholders is None:
        from data_mcp.shared.integrations.qichacha_client import (
            fetch_shareholders as fetch_shareholders,
        )
    if fetch_network is None:
        from data_mcp.features.investor_match.network_client import (
            invoke_network_investor_agent as fetch_network,
        )

    assert fetch_dmp is not None
    assert fetch_db is not None
    assert fetch_shareholders is not None
    assert fetch_network is not None

    def _load_internal() -> tuple[list[dict[str, Any]], str, int | None, list[str]]:
        local_warnings: list[str] = []
        try:
            dmp_result = fetch_dmp(tags, env)
            if not isinstance(dmp_result, dict):
                raise TypeError("DMP 返回必须是对象")
            raw = list(dmp_result.get("institutions") or [])
            try:
                individual_count = int(dmp_result.get("individual_count") or 0)
            except (TypeError, ValueError):
                individual_count = 0
            for w in dmp_result.get("warnings") or []:
                text = str(w or "").strip()
                if text:
                    local_warnings.append(text)
            return raw, "dmp", individual_count, local_warnings
        except Exception as exc:  # noqa: BLE001 - soft fail to DB
            logger.warning("DMP investor lookup failed: %s", public_message_for_exception(exc))
            local_warnings.append("DMP 数据暂不可用，已改用内部投资人库")
            try:
                raw = fetch_db(tags, env, weight_ratio=cfg.get("weight_ratio"))
                return raw, "db_fallback", None, local_warnings
            except Exception as db_exc:  # noqa: BLE001
                logger.warning(
                    "investor database fallback failed: %s",
                    public_message_for_exception(db_exc),
                )
                local_warnings.append("内部投资人数据暂不可用，本次未获得内部候选")
                return [], "none", None, local_warnings

    def _load_shareholders() -> tuple[list[str], bool, Exception | None]:
        try:
            return fetch_shareholders(company, env), True, None
        except Exception as exc:  # noqa: BLE001
            return [], False, exc

    def _load_network() -> tuple[list[dict[str, Any]], Exception | None]:
        try:
            return fetch_network(profile, tags, env), None
        except Exception as exc:  # noqa: BLE001
            return [], exc

    # DMP/内部库、企查查股东、网络 HiAgent 无数据依赖，并行拉取后再本地合并过滤。
    with ThreadPoolExecutor(max_workers=3) as pool:
        internal_future = pool.submit(_load_internal)
        shareholders_future = pool.submit(_load_shareholders)
        network_future = pool.submit(_load_network)
        internal_raw, internal_source, dmp_individual_count, internal_warnings = (
            internal_future.result()
        )
        shareholders, shareholders_filtered, shareholders_error = shareholders_future.result()
        network_raw, network_error = network_future.result()

    warnings.extend(internal_warnings)
    if shareholders_error is not None:
        logger.warning(
            "qichacha shareholder lookup failed: %s",
            public_message_for_exception(shareholders_error),
        )
        warnings.append("企查查股东数据暂不可用，候选名单可能包含现有股东")
    if network_error is not None:
        logger.warning(
            "network investor lookup failed: %s",
            public_message_for_exception(network_error),
        )
        warnings.append("网络投资人数据暂不可用，本次未获得网络候选")

    if internal_source == "dmp":
        internal_citation_type = "dmp"
        internal_citation_name = "DMP 标签库"
        # DMP 机构结果默认按机构标注
        default_institution = True
    else:
        internal_citation_type = "investor_db"
        internal_citation_name = "内部投资人库"
        default_institution = False

    internal_annotated = [
        _annotate_candidate(
            item,
            source="internal",
            citation_source_type=internal_citation_type,
            citation_source_name=internal_citation_name,
            default_institution=default_institution,
        )
        for item in internal_raw
        if str(item.get("name") or "").strip()
    ]
    internal_filtered = filter_out_shareholders(internal_annotated, shareholders)

    institutions = [c for c in internal_filtered if c["investor_type"] == "机构"]
    individuals = [c for c in internal_filtered if c["investor_type"] == "个人"]
    institutions.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    institutions = institutions[:internal_top_n]

    if dmp_individual_count is not None:
        individual_count = dmp_individual_count
    else:
        individual_count = len(individuals)

    network_annotated = [
        _annotate_candidate(
            item,
            source="network",
            citation_source_type="network",
            citation_source_name="公开网络信息",
            default_institution=True,
        )
        for item in network_raw
        if str(item.get("name") or "").strip()
    ]
    network_filtered = filter_out_shareholders(network_annotated, shareholders)
    network_deduped = dedupe_network_against_internal(network_filtered, institutions)
    network_deduped = network_deduped[:network_top_n]

    merged = [_public_candidate(c) for c in institutions] + [
        _public_candidate(c) for c in network_deduped
    ]

    return {
        "internal": {
            "institutions": institutions,
            "institution_count": len(institutions),
            "individual_count": individual_count,
            "total_after_filter": len(institutions) + individual_count,
        },
        "network": {
            "institutions": network_deduped,
            "institution_count": len(network_deduped),
        },
        "merged": merged,
        "warnings": warnings,
        "meta": {
            "env": selected_env,
            "internal_source": internal_source,
            "shareholders_filtered": shareholders_filtered,
            "shareholder_count": len(shareholders),
            "internal_top_n": internal_top_n,
            "network_top_n": network_top_n,
            "track_tags": tags,
            "label_type": FIXED_LABEL_TYPE if internal_source == "dmp" else None,
            "company_name": company,
            "project_profile_kind": "object" if isinstance(profile, dict) else "string",
        },
    }
