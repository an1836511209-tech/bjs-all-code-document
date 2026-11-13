from __future__ import annotations

import hashlib
import json
import secrets
import string
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from data_mcp.features.investor_match.tag_normalize import strip_wrapping_quotes
from data_mcp.shared.http.errors import (
    ExternalServiceError,
    public_message_for_exception,
    raise_from_http_error,
    raise_invalid_json_response,
)
from data_mcp.shared.http.retry_client import http_request
from data_mcp.shared.integrations.jgfw_gateway import build_jgfw_gateway_headers
from data_mcp.shared.settings import load_http_retry_config, load_investor_match_config

# DMP 业务固定品类；agent 无需填写。
FIXED_LABEL_TYPE = "股权转让/增资"
INVESTOR_TYPE_INSTITUTION = "机构"
INVESTOR_TYPE_INDIVIDUAL = "个人"
_NONCE_ALPHABET = string.ascii_letters + string.digits


def _is_dmp_configured(cfg: dict[str, Any]) -> bool:
    return bool(
        str(cfg.get("base_url") or "").strip()
        and str(cfg.get("path") or "").strip()
        and str(cfg.get("x_gw_token") or "").strip()
        and str(cfg.get("app_key") or "").strip()
        and str(cfg.get("app_secret") or "").strip()
    )


def dmp_signature(app_key: str, app_secret: str, timestamp: str, nonce: str) -> str:
    """SHA1(appKey + appSecret + timestamp + nonce)，小写十六进制。"""
    raw = f"{app_key}{app_secret}{timestamp}{nonce}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def build_dmp_auth_headers(
    cfg: dict[str, Any],
    *,
    nonce: str | None = None,
    timestamp_ms: int | None = None,
) -> dict[str, str]:
    app_key = str(cfg.get("app_key") or "").strip()
    app_secret = str(cfg.get("app_secret") or "").strip()
    if not app_key or not app_secret:
        raise RuntimeError("DMP 未配置 app_key/app_secret")
    nonce_value = nonce or "".join(secrets.choice(_NONCE_ALPHABET) for _ in range(10))
    if len(nonce_value) != 10:
        raise ValueError("DMP nonce 必须是 10 位")
    timestamp = str(int(time.time() * 1000) if timestamp_ms is None else timestamp_ms)
    return {
        "appKey": app_key,
        "nonce": nonce_value,
        "timestamp": timestamp,
        "signature": dmp_signature(app_key, app_secret, timestamp, nonce_value),
    }


def _join_label_names(label_names: list[str]) -> str:
    return ",".join(
        stripped
        for x in label_names
        if (stripped := strip_wrapping_quotes(str(x)))
    )


def _unwrap_payload(data: Any) -> dict[str, Any]:
    """兼容网关包装 {body: {...}} 与直接业务 JSON。"""
    if not isinstance(data, dict):
        raise ExternalServiceError("DMP", "DMP 返回格式无效")
    body = data.get("body")
    if isinstance(body, dict) and (
        "items" in body or "count" in body or "totalResults" in body or "total" in body
    ):
        return body
    nested = data.get("data")
    if isinstance(nested, dict) and (
        "items" in nested or "count" in nested or "totalResults" in nested
    ):
        return nested
    return data


# 机构名单只把这三项交给后续流程，避免整包 items 撑爆 Agent 上下文。
_INSTITUTION_ITEM_KEYS = ("investor_name", "match_label_num", "match_label_weight_sum")
AGENT_INSTITUTION_LIMIT = 30


def _parse_count(payload: dict[str, Any]) -> int:
    """个人投资人只统计响应 body.count，不读 items 或其他总数字段。"""
    raw = payload.get("count")
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _page_param(cfg: dict[str, Any], name: str, default: int, *, minimum: int) -> int:
    try:
        value = int(cfg.get(name, default))
    except (TypeError, ValueError):
        value = default
    return value if value >= minimum else default


def _page_params(cfg: dict[str, Any], kind: str) -> tuple[int, int]:
    """机构、个人各自读取 offset/limit。kind 为 institution 或 individual。"""
    if kind == "institution":
        default_limit = AGENT_INSTITUTION_LIMIT
    else:
        default_limit = 1
    offset = _page_param(cfg, f"{kind}_offset", 0, minimum=0)
    limit = _page_param(cfg, f"{kind}_limit", default_limit, minimum=1)
    return offset, limit


def _map_institution_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise ExternalServiceError("DMP", "DMP 返回格式无效")
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        slim = {key: item.get(key) for key in _INSTITUTION_ITEM_KEYS}
        name = str(slim.get("investor_name") or "").strip()
        if not name:
            continue
        try:
            score = float(slim.get("match_label_weight_sum") or 0)
        except (TypeError, ValueError):
            score = 0.0
        match_num = slim.get("match_label_num")
        out.append(
            {
                "name": name,
                "score": score,
                "match_reason": f"DMP 匹配标签数 {match_num}; 权重和 {score}",
                "usr_cgy_cd_dsc": "机构",
            }
        )
    out.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    return out[:AGENT_INSTITUTION_LIMIT]


def _request_dmp(
    *,
    cfg: dict[str, Any],
    label_name: str,
    investor_type: str,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    url = f"{cfg['base_url'].rstrip('/')}{cfg['path']}"
    headers = {"Content-Type": "application/json"}
    headers.update(build_jgfw_gateway_headers(cfg))
    headers.update(build_dmp_auth_headers(cfg))
    if cfg.get("mode") == "mock":
        headers["X-DMP-Mock-Caller"] = "report_match"
    body = {
        "label_type": FIXED_LABEL_TYPE,
        "label_name": label_name,
        "investor_type": investor_type,
        "offset": offset,
        "limit": limit,
    }
    method = str(cfg.get("method") or "POST").upper()
    timeout = float(cfg.get("timeout_seconds") or 30)
    retry_cfg = load_http_retry_config()
    try:
        if method == "GET":
            response = http_request(
                "GET",
                url,
                headers=headers,
                params=body,
                timeout=timeout,
                service_name="dmp",
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
                service_name="dmp",
                max_retries=retry_cfg["max_retries"],
                backoff_base_seconds=retry_cfg["backoff_base_seconds"],
                backoff_max_seconds=retry_cfg["backoff_max_seconds"],
            )
    except Exception as exc:
        raise_from_http_error("DMP", exc)

    try:
        data = response.json()
    except Exception:
        raise_invalid_json_response(
            "DMP",
            status_code=response.status_code,
            body=response.text if isinstance(response.text, str) else None,
        )
    return _unwrap_payload(data)


def query_dmp_investors(
    label_names: list[str],
    env: str | None = None,
) -> dict[str, Any]:
    """调用 DMP：机构返回候选列表，个人只取总数。

    label_type 固定为「股权转让/增资」；label_name 为赛道标签（英文逗号拼接）。
    机构调用失败则抛错（由上层改走内部库）；个人统计失败时保留机构结果并写入 warnings。

    返回 ``{"institutions": [...], "individual_count": int, "warnings": [...]}``。
    """
    full = load_investor_match_config(env)
    cfg = full["dmp"]
    if not _is_dmp_configured(cfg):
        raise RuntimeError("DMP 未配置 base_url/path/x_gw_token/app_key/app_secret，跳过调用")

    label_name = _join_label_names(label_names)
    if not label_name:
        raise ValueError("label_name 不能为空")

    institution_offset, institution_limit = _page_params(cfg, "institution")
    individual_offset, individual_limit = _page_params(cfg, "individual")

    # 机构列表与个人总数互不依赖，并行请求；机构失败仍向上抛，个人失败软降级。
    with ThreadPoolExecutor(max_workers=2) as pool:
        institution_future = pool.submit(
            _request_dmp,
            cfg=cfg,
            label_name=label_name,
            investor_type=INVESTOR_TYPE_INSTITUTION,
            offset=institution_offset,
            limit=institution_limit,
        )
        individual_future = pool.submit(
            _request_dmp,
            cfg=cfg,
            label_name=label_name,
            investor_type=INVESTOR_TYPE_INDIVIDUAL,
            offset=individual_offset,
            limit=individual_limit,
        )

        institution_error: Exception | None = None
        institutions: list[dict[str, Any]] = []
        try:
            institution_payload = institution_future.result()
            institutions = _map_institution_items(institution_payload.get("items"))
        except Exception as exc:  # noqa: BLE001 - 先收齐个人 future，再抛机构错误
            institution_error = exc

        warnings: list[str] = []
        individual_count = 0
        try:
            individual_payload = individual_future.result()
            if institution_error is None:
                individual_count = _parse_count(individual_payload)
        except Exception as exc:  # noqa: BLE001 - 个人统计软失败
            if institution_error is None:
                warnings.append(
                    f"DMP 个人投资人统计暂不可用: {public_message_for_exception(exc)}"
                )

    if institution_error is not None:
        raise institution_error

    return {
        "institutions": institutions,
        "individual_count": individual_count,
        "warnings": warnings,
    }


def query_dmp_institutions_for_export(selected_tags: list[str], env: str | None = None):
    """One bounded request; deliberately bypass the report request/retry/mapping path."""
    import httpx

    from data_mcp.features.investor_match.workbook import slim_institution_rows
    from data_mcp.shared.settings import load_workbook_export_config

    cfg = load_investor_match_config(env)["dmp"]
    limits = load_workbook_export_config()
    if not _is_dmp_configured(cfg):
        raise ValueError("DMP_EXPORT_NOT_CONFIGURED")
    method = str(cfg.get("method") or "POST").upper()
    if method not in {"GET", "POST"}:
        raise ValueError("INVALID_DMP_METHOD")
    headers = {"Content-Type": "application/json"}
    headers.update(build_jgfw_gateway_headers(cfg))
    headers.update(build_dmp_auth_headers(cfg))
    if cfg.get("mode") == "mock":
        headers["X-DMP-Mock-Caller"] = "workbook_export"
    body = dict(
        label_type=FIXED_LABEL_TYPE,
        label_name=_join_label_names(selected_tags),
        investor_type=INVESTOR_TYPE_INSTITUTION,
        offset=0,
        limit=200,
    )
    deadline = time.monotonic() + limits["request_timeout_seconds"]
    kwargs: dict[str, Any] = {"params" if method == "GET" else "json": body}
    with httpx.Client(timeout=limits["request_timeout_seconds"], follow_redirects=False) as client:
        with client.stream(
            method, f"{cfg['base_url'].rstrip('/')}{cfg['path']}", headers=headers, **kwargs
        ) as response:
            if response.status_code != 200:
                raise ValueError("DMP_EXPORT_HTTP_ERROR")
            content = bytearray()
            for chunk in response.iter_bytes(chunk_size=65536):
                if time.monotonic() > deadline:
                    raise TimeoutError("DMP_EXPORT_TIMEOUT")
                if len(content) + len(chunk) > limits["max_response_bytes"]:
                    raise ValueError("DMP_EXPORT_RESPONSE_TOO_LARGE")
                content.extend(chunk)
    try:
        payload = _unwrap_payload(json.loads(content))
    except Exception:
        raise ValueError("INVALID_DMP_EXPORT_JSON") from None
    return slim_institution_rows(payload.get("items"), selected_tags)
