from __future__ import annotations

from typing import Any

from data_mcp.shared.http.errors import (
    ExternalServiceError,
    raise_from_http_error,
    raise_invalid_json_response,
)
from data_mcp.shared.http.retry_client import http_request
from data_mcp.shared.integrations.jgfw_gateway import build_jgfw_gateway_headers
from data_mcp.shared.settings import load_track_labels_config


def _normalize_name(value: str) -> str:
    return "".join(str(value or "").split()).replace("（", "(").replace("）", ")")


def is_lms_track_labels_configured(cfg: dict[str, Any] | None = None) -> bool:
    block = cfg or {}
    api = block.get("api") if isinstance(block.get("api"), dict) else block
    if not isinstance(api, dict):
        return False
    return bool(
        str(api.get("base_url") or "").strip()
        and str(api.get("path") or "").strip()
        and str(api.get("secret_key") or "").strip()
        and str(api.get("x_gw_token") or "").strip()
    )


def _as_tag_list(raw_tags: Any) -> list[str]:
    items: list[Any]
    if isinstance(raw_tags, list):
        items = raw_tags
    elif isinstance(raw_tags, str):
        items = [part.strip() for part in raw_tags.replace("，", ",").split(",")]
    else:
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for item in items:
        tag = str(item or "").strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags


def parse_track_labels_response(payload: Any, *, company_name: str) -> list[str]:
    """解析 API 平台赛道标签响应。空列表返回 []，业务失败时抛 ExternalServiceError。"""
    if not isinstance(payload, dict):
        raise ExternalServiceError("API平台", "API平台返回格式无效")

    error_msg = str(payload.get("error_msg") or "").strip()
    if error_msg:
        raise ExternalServiceError("API平台", error_msg)

    status = payload.get("status")
    if status is not None:
        try:
            status_code = int(str(status))
        except (TypeError, ValueError):
            status_code = -1
        if status_code != 0:
            msg = str(payload.get("msg") or "API平台业务失败").strip() or "API平台业务失败"
            raise ExternalServiceError("API平台", msg)

    data = payload.get("data")
    records: list[Any]
    if isinstance(data, dict):
        nested = data.get("data")
        if isinstance(nested, list):
            records = nested
        elif isinstance(nested, dict):
            records = [nested]
        else:
            records = [data]
    elif isinstance(data, list):
        records = data
    else:
        raise ExternalServiceError("API平台", "赛道标签为空")
    if not records:
        return []

    target = _normalize_name(company_name)
    matched: dict[str, Any] | None = None
    for item in records:
        if not isinstance(item, dict):
            continue
        if _normalize_name(str(item.get("corpName") or "")) == target:
            matched = item
            break
    if matched is None and len(records) == 1 and isinstance(records[0], dict):
        matched = records[0]
    if matched is None:
        raise ExternalServiceError("API平台", "响应中未找到对应企业")

    return _as_tag_list(matched.get("class4Tag"))


def query_lms_track_labels(
    company_name: str,
    env: str | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """单次调用 API 平台查询企业赛道标签；未配置或失败时抛错。"""
    company = str(company_name or "").strip()
    if not company:
        raise ValueError("company_name 不能为空")

    full = config or load_track_labels_config(env)
    api = full.get("api") if isinstance(full.get("api"), dict) else full
    if not isinstance(api, dict) or not is_lms_track_labels_configured({"api": api}):
        raise RuntimeError("API平台赛道标签未配置，跳过调用")

    url = f"{str(api['base_url']).rstrip('/')}{api['path']}"
    headers = {"Content-Type": "application/json"}
    headers.update(build_jgfw_gateway_headers(api))

    body = {
        "secretKey": str(api.get("secret_key") or ""),
        "source": str(api.get("source") or "2").strip() or "2",
        "corpName": company,
    }
    method = str(api.get("method") or "POST").upper()
    timeout = float(api.get("timeout_seconds") or 90)
    # 传输层不重试。失败或空标签由 query_track_labels 间隔 20 秒再调用一次。
    retry_cfg = {"max_retries": 0, "backoff_base_seconds": 0.0, "backoff_max_seconds": 0.0}

    try:
        if method == "GET":
            response = http_request(
                "GET",
                url,
                headers=headers,
                params=body,
                timeout=timeout,
                service_name="api_platform_track_labels",
                max_retries=retry_cfg["max_retries"],
                backoff_base_seconds=retry_cfg["backoff_base_seconds"],
                backoff_max_seconds=retry_cfg["backoff_max_seconds"],
            )
        else:
            response = http_request(
                "POST",
                url,
                headers=headers,
                json=body,
                timeout=timeout,
                service_name="api_platform_track_labels",
                max_retries=retry_cfg["max_retries"],
                backoff_base_seconds=retry_cfg["backoff_base_seconds"],
                backoff_max_seconds=retry_cfg["backoff_max_seconds"],
            )
    except Exception as exc:
        raise_from_http_error("API平台", exc)

    try:
        data = response.json()
    except Exception:
        raise_invalid_json_response(
            "API平台",
            status_code=response.status_code,
            body=response.text if isinstance(response.text, str) else None,
        )

    return parse_track_labels_response(data, company_name=company)
