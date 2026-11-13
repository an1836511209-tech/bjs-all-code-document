from __future__ import annotations

import re
from typing import Any

_SUFFIXES = (
    "有限责任公司",
    "股份有限公司",
    "有限公司",
    "有限合伙",
    "集团",
    "控股",
)

_WHITESPACE_RE = re.compile(r"\s+")
_INSTITUTION_HINTS = (
    "基金",
    "资本",
    "投资",
    "合伙",
    "有限公司",
    "有限合伙",
    "集团",
    "控股",
    "证券",
    "资产",
    "创投",
    "私募",
)


def normalize_investor_name(name: str | None) -> str:
    """生成用于去重/剔股东的比较键；展示仍用原始名称。"""
    if name is None:
        return ""
    text = str(name).replace("\u3000", " ").strip().lower()
    text = _WHITESPACE_RE.sub("", text)
    changed = True
    while changed and text:
        changed = False
        for suffix in _SUFFIXES:
            if text.endswith(suffix.lower()):
                text = text[: -len(suffix)]
                changed = True
                break
    return text


def compute_weight_score(
    lbl_wgt: Any,
    pref_wgt: Any,
    smy_wgt: Any,
    weight_ratio: dict[str, float] | None = None,
) -> float:
    ratio = weight_ratio or {"lbl_wgt": 1.0, "pref_wgt": 1.0, "smy_wgt": 1.0}
    r1 = float(ratio.get("lbl_wgt", 1) or 0)
    r2 = float(ratio.get("pref_wgt", 1) or 0)
    r3 = float(ratio.get("smy_wgt", 1) or 0)
    denom = r1 + r2 + r3
    if denom <= 0:
        return 0.0

    def _f(v: Any) -> float:
        if v is None or v == "":
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    return (_f(lbl_wgt) * r1 + _f(pref_wgt) * r2 + _f(smy_wgt) * r3) / denom


def classify_investor_type(
    name: str | None,
    usr_cgy_cd_dsc: str | None = None,
    *,
    default_institution: bool = False,
) -> str:
    """返回「机构」或「个人」。"""
    category = "" if usr_cgy_cd_dsc is None else str(usr_cgy_cd_dsc)
    if "机构" in category:
        return "机构"
    if "个人" in category:
        return "个人"

    display = "" if name is None else str(name)
    if any(hint in display for hint in _INSTITUTION_HINTS):
        return "机构"
    if default_institution:
        return "机构"
    return "个人"


def is_shareholder(name: str | None, shareholder_keys: set[str]) -> bool:
    key = normalize_investor_name(name)
    if not key:
        return False
    return key in shareholder_keys


def build_shareholder_keys(names: list[str] | None) -> set[str]:
    return {normalize_investor_name(n) for n in (names or []) if normalize_investor_name(n)}


def filter_out_shareholders(
    candidates: list[dict[str, Any]],
    shareholder_names: list[str] | None,
) -> list[dict[str, Any]]:
    keys = build_shareholder_keys(shareholder_names)
    if not keys:
        return list(candidates)
    return [c for c in candidates if not is_shareholder(c.get("name"), keys)]


def dedupe_network_against_internal(
    network: list[dict[str, Any]],
    internal: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    internal_keys = {
        normalize_investor_name(c.get("name"))
        for c in internal
        if normalize_investor_name(c.get("name"))
    }
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in network:
        key = normalize_investor_name(item.get("name"))
        if not key or key in internal_keys or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
