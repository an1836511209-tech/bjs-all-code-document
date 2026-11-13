"""企查查工商摘要，供报告事实不足时单独查询。"""

from __future__ import annotations

import logging
import unicodedata
from typing import Any

from data_mcp.shared.http.errors import ExternalServiceError
from data_mcp.shared.integrations.qichacha_client import (
    fetch_eci_info,
    summarize_eci_for_portrait,
)
from data_mcp.shared.settings import load_project_profile_qichacha_config

logger = logging.getLogger(__name__)

_NO_RESULT_STATUSES = frozenset({"201"})
_LISTED_YES = frozenset({"1", "Y", "y", "是", "true", "True"})
_LISTED_NO = frozenset({"0", "N", "n", "否", "false", "False"})


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _listed_label(value: Any) -> str:
    raw = _text(value)
    if raw in _LISTED_YES:
        return "是"
    if raw in _LISTED_NO:
        return "否"
    return raw


def _public_company(summary: dict[str, Any]) -> dict[str, Any]:
    """把画像用企查查摘要收成稳定字段，不带供应商原始包。"""
    company: dict[str, Any] = {}
    fields = {
        "name": summary.get("Name"),
        "credit_code": summary.get("CreditCode"),
        "legal_representative": summary.get("OperName"),
        "established_on": summary.get("StartDate"),
        "registration_status": summary.get("Status"),
        "registered_capital": summary.get("RegistCapi"),
        "paid_in_capital": summary.get("RecCap"),
        "company_type": summary.get("EconKind"),
        "address": summary.get("Address"),
        "business_scope": summary.get("Scope"),
        "staff_range": summary.get("PersonScope"),
        "insured_count": summary.get("InsuredCount"),
        "stock_code": summary.get("StockNumber"),
        "listing_type": summary.get("StockType"),
    }
    for key, value in fields.items():
        text = _text(value)
        if text:
            company[key] = text

    listed = _listed_label(summary.get("IsOnStock"))
    if listed:
        company["listed"] = listed

    industry_raw = summary.get("Industry")
    if isinstance(industry_raw, dict):
        industry = {
            "industry": _text(industry_raw.get("Industry")),
            "sub_industry": _text(industry_raw.get("SubIndustry")),
            "middle_category": _text(industry_raw.get("MiddleCategory")),
            "small_category": _text(industry_raw.get("SmallCategory")),
        }
        industry = {key: value for key, value in industry.items() if value}
        if industry:
            company["industry"] = industry

    tags = [_text(item) for item in summary.get("Tags") or [] if _text(item)]
    if tags:
        company["tags"] = tags

    shareholders: list[dict[str, str]] = []
    for item in summary.get("Partners") or []:
        if not isinstance(item, dict):
            continue
        holder = {
            "name": _text(item.get("StockName")),
            "percent": _text(item.get("StockPercent")),
            "holder_type": _text(item.get("StockType")),
        }
        holder = {key: value for key, value in holder.items() if value}
        if holder.get("name"):
            shareholders.append(holder)
    if shareholders:
        company["shareholders"] = shareholders

    executives: list[dict[str, str]] = []
    for item in summary.get("Employees") or []:
        if not isinstance(item, dict):
            continue
        person = {
            "name": _text(item.get("Name")),
            "title": _text(item.get("Job")),
        }
        person = {key: value for key, value in person.items() if value}
        if person.get("name"):
            executives.append(person)
    if executives:
        company["executives"] = executives

    return company


def query_company_registry(company_name: str, env: str | None = None) -> dict[str, Any]:
    """调用企查查 ECIInfoVerify/GetInfo，返回工商、行业、股东和主要人员摘要。"""
    name = _text(company_name)
    if not name:
        raise ValueError("company_name 不能为空")

    cfg = load_project_profile_qichacha_config(env)
    data = fetch_eci_info(name, cfg)
    status = _text(data.get("Status"))
    if status in _NO_RESULT_STATUSES:
        return {"company": None, "warnings": ["当前公司名称无法获取企查查数据，请提供精确名称。"],
                "warning_code": "COMPANY_NOT_FOUND"}
    if status != "200":
        logger.warning("qichacha company lookup failed status=%s", status or "<empty>")
        raise ExternalServiceError("企查查", "企查查查询失败")

    summary = summarize_eci_for_portrait(data)
    if not summary:
        return {"company": None, "warnings": ["当前公司名称无法获取企查查数据，请提供精确名称。"],
                "warning_code": "COMPANY_NOT_FOUND"}
    company = _public_company(summary)
    registered_name = _text(company.get("name"))
    # Full-width punctuation is equivalent; abbreviations and similar names are not.
    if not registered_name or unicodedata.normalize("NFKC", registered_name) != unicodedata.normalize("NFKC", name):
        return {"company": None, "warnings": ["查询名称未精确匹配企业登记名称，请提供精确名称或跳过工商查询。"],
                "warning_code": "COMPANY_NAME_NOT_EXACT"}
    return {"company": company, "warnings": []}
