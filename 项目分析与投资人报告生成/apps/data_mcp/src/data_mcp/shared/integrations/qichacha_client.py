from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from urllib.parse import urlencode

from data_mcp.shared.http.errors import (
    ExternalServiceError,
    public_message_for_exception,
    raise_from_http_error,
    raise_invalid_json_response,
)
from data_mcp.shared.http.retry_client import http_request
from data_mcp.shared.settings import (
    load_http_retry_config,
    load_investor_match_config,
    load_project_profile_qichacha_config,
)

PORTRAIT_PARTNER_LIMIT = 10
PORTRAIT_EMPLOYEE_LIMIT = 10

_FACE_FIELDS = (
    "Name",
    "CreditCode",
    "OperName",
    "StartDate",
    "Status",
    "RegistCapi",
    "RegisteredCapital",
    "RegisteredCapitalUnit",
    "RegisteredCapitalCCY",
    "RecCap",
    "PaidUpCapital",
    "PaidUpCapitalUnit",
    "PaidUpCapitalCCY",
    "EconKind",
    "Address",
    "Scope",
    "PersonScope",
    "InsuredCount",
    "IsOnStock",
    "StockNumber",
    "StockType",
)


def _is_qichacha_configured(cfg: dict[str, Any]) -> bool:
    return bool(
        str(cfg.get("key") or "").strip()
        and str(cfg.get("secret_key") or "").strip()
        and str(cfg.get("base_url") or "").strip()
        and str(cfg.get("path") or "").strip()
    )


def _auth_headers(cfg: dict[str, Any]) -> dict[str, str]:
    key = str(cfg["key"])
    secret = str(cfg["secret_key"])
    timespan = str(int(time.time()))
    token = hashlib.md5(f"{key}{timespan}{secret}".encode()).hexdigest().upper()
    return {"Token": token, "Timespan": timespan}


def fetch_eci_info(search_key: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """调用企查查 ECIInfoVerify/GetInfo，返回完整 JSON 对象。"""
    name = str(search_key or "").strip()
    if not name:
        raise ValueError("searchKey 不能为空")
    if not _is_qichacha_configured(cfg):
        raise RuntimeError("企查查未配置 key/secret_key")

    key = str(cfg["key"])
    base = str(cfg["base_url"]).rstrip("/")
    path = str(cfg["path"])
    query = urlencode({"key": key, "searchKey": name})
    url = f"{base}{path}?{query}"
    headers = _auth_headers(cfg)
    timeout = float(cfg.get("timeout_seconds") or 30)

    retry_cfg = load_http_retry_config()
    try:
        response = http_request(
            "GET",
            url,
            headers=headers,
            timeout=timeout,
            service_name="qichacha",
            max_retries=retry_cfg["max_retries"],
            backoff_base_seconds=retry_cfg["backoff_base_seconds"],
            backoff_max_seconds=retry_cfg["backoff_max_seconds"],
        )
    except Exception as exc:
        raise_from_http_error("企查查", exc)

    try:
        data = response.json()
    except Exception:
        raise_invalid_json_response(
            "企查查",
            status_code=response.status_code,
            body=response.text if isinstance(response.text, str) else None,
        )

    if not isinstance(data, dict):
        raise ExternalServiceError("企查查", "企查查返回格式无效")
    return data


def summarize_eci_for_portrait(payload: dict[str, Any]) -> dict[str, Any] | None:
    """将企查查 GetInfo 响应精简为画像用对象；无 Result 返回 None。"""
    result = payload.get("Result") if isinstance(payload, dict) else None
    if not isinstance(result, dict) or not result:
        return None

    out: dict[str, Any] = {}
    for field in _FACE_FIELDS:
        if field in result and result[field] is not None:
            out[field] = result[field]

    industry = result.get("Industry")
    if isinstance(industry, dict):
        out["Industry"] = {
            "Industry": industry.get("Industry") or "",
            "SubIndustry": industry.get("SubIndustry") or "",
            "MiddleCategory": industry.get("MiddleCategory") or "",
            "SmallCategory": industry.get("SmallCategory") or "",
        }

    tags: list[str] = []
    tag_list = result.get("TagList")
    if isinstance(tag_list, list):
        for item in tag_list:
            if isinstance(item, dict):
                name = str(item.get("Name") or "").strip()
                if name and name not in tags:
                    tags.append(name)
    if tags:
        out["Tags"] = tags

    partners_out: list[dict[str, str]] = []
    partners = result.get("Partners")
    if isinstance(partners, list):
        for item in partners[:PORTRAIT_PARTNER_LIMIT]:
            if not isinstance(item, dict):
                continue
            partners_out.append(
                {
                    "StockName": str(item.get("StockName") or ""),
                    "StockPercent": str(item.get("StockPercent") or ""),
                    "StockType": str(item.get("StockType") or ""),
                }
            )
    if partners_out:
        out["Partners"] = partners_out

    employees_out: list[dict[str, str]] = []
    employees = result.get("Employees")
    if isinstance(employees, list):
        for item in employees[:PORTRAIT_EMPLOYEE_LIMIT]:
            if not isinstance(item, dict):
                continue
            employees_out.append(
                {
                    "Name": str(item.get("Name") or ""),
                    "Job": str(item.get("Job") or ""),
                }
            )
    if employees_out:
        out["Employees"] = employees_out

    return out if out else None


def resolve_qichacha_info_for_portrait(
    company_name: str,
    env: str | None = None,
) -> tuple[str, list[str]]:
    """
    拉取并精简企查查信息，供画像 state.qichacha_info 使用。
    返回 (json_string_or_empty, warnings)。失败不抛给调用方业务层。
    """
    name = str(company_name or "").strip()
    if not name:
        return "", ["company_name 不能为空"]

    try:
        cfg = load_project_profile_qichacha_config(env)
    except Exception:
        return "", ["企查查配置加载失败"]

    if not _is_qichacha_configured(cfg):
        return "", ["企查查未配置 key/secret_key"]

    try:
        data = fetch_eci_info(name, cfg)
    except Exception as exc:
        return "", [f"企查查调用失败: {public_message_for_exception(exc)}"]

    status = str(data.get("Status") or "").strip()
    if status != "200":
        msg = str(data.get("Message") or "").strip()
        detail = f"Status={status}" + (f" {msg}" if msg else "")
        return "", [f"企查查查询无结果或失败: {detail}"]

    summary = summarize_eci_for_portrait(data)
    if summary is None:
        return "", ["企查查查询无结果"]

    return json.dumps(summary, ensure_ascii=False), []


def _extract_shareholder_names(payload: Any) -> list[str]:
    """尽量兼容企查查常见返回结构，抽取股东名称。"""
    names: list[str] = []

    def add(value: Any) -> None:
        if value is None:
            return
        text = str(value).strip()
        if text and text not in names:
            names.append(text)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                key_l = str(key).lower()
                if key_l in {
                    "stockname",
                    "shareholdername",
                    "partnername",
                    "name",
                    "investorname",
                    "opername",
                }:
                    if isinstance(val, str):
                        add(val)
                if key_l in {"partners", "shareholders", "stockholders", "investorlist"}:
                    walk(val)
                elif isinstance(val, (dict, list)):
                    walk(val)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, str):
                    add(item)
                else:
                    walk(item)

    walk(payload)

    if isinstance(payload, dict):
        result = payload.get("Result") or payload.get("result") or payload.get("data")
        if isinstance(result, dict):
            partners = result.get("Partners") or result.get("partners") or result.get("Shareholders")
            if isinstance(partners, list):
                for p in partners:
                    if isinstance(p, dict):
                        add(p.get("StockName") or p.get("stockName") or p.get("Name") or p.get("name"))

    return names


def fetch_shareholders(
    company_name: str,
    env: str | None = None,
) -> list[str]:
    """调用企查查 GetInfo，返回股东名称列表；配置不全或失败抛 RuntimeError。"""
    name = str(company_name or "").strip()
    if not name:
        raise ValueError("company_name 不能为空")

    full = load_investor_match_config(env)
    cfg = full["qichacha"]
    data = fetch_eci_info(name, cfg)
    names = _extract_shareholder_names(data)
    if not names:
        return []
    return names
