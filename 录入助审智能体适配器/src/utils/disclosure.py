"""产权转让、企业增资辅助录入的申请书校验与中台值转换。"""

import json
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.utils.anchor_markdown_converter import SegmentInfo
from src.schemas.extraction import FieldExtractionResult, FieldExtractionStatus
from src.schemas.file import FileType
from src.schemas.rule_config import BusinessType, DisclosureField, ExtractionRule

APPLICATION_TITLES = {
    "产权转让信息预披露申请书": BusinessType.PROPERTY_TRANSFER_PRE,
    "产权转让信息披露申请书": BusinessType.PROPERTY_TRANSFER_FORMAL,
    "增资信息预披露申请书": BusinessType.CAPITAL_INCREASE_PRE,
    "增资信息披露申请书": BusinessType.CAPITAL_INCREASE_FORMAL,
}
DISCLOSURE_TYPES = frozenset(APPLICATION_TITLES.values())


def identify_application(content: str) -> BusinessType | None:
    """仅识别封面标题，不用文件名或正文中引用的其他申请书作判据。"""
    for line in content[:1800].splitlines()[:24]:
        title = re.sub(r"\s+|<[^>]*>|[#*《》]", "", line)
        title = title.removeprefix("企业")
        title = title.replace("信息正式披露", "信息披露")
        if title in APPLICATION_TITLES:
            return APPLICATION_TITLES[title]
    return None


def validate_application(expected: str, application_names: list[str], parsed_applications: list[tuple[str, str]]) -> None:
    if len(application_names) != 1 or len(parsed_applications) != 1:
        raise ValueError(f"{expected}需要一份可解析的披露申请书")
    name, content = parsed_applications[0]
    detected = identify_application(content)
    if detected is None:
        raise ValueError(f"无法从申请书《{name}》的封面确认业务类型，预期为{expected}")
    if detected != expected:
        raise ValueError(f"申请书《{name}》为{detected.value}，与请求业务类型{expected}不一致")


@lru_cache(maxsize=1)
def disclosure_dictionaries() -> dict[str, dict[str, str]]:
    path = Path(__file__).resolve().parents[2] / "data" / "disclosure_dictionaries.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def region_entries() -> tuple[tuple[str, str, str], ...]:
    path = Path(__file__).resolve().parents[2] / "data" / "region_data.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        entry
        for province in data["provinces"]
        for city in province.get("cities", [])
        for entry in [
            ("city", str(city["id"]), city["name"]),
            *(("district", str(item["id"]), item["name"]) for item in city.get("districts", [])),
        ]
    )


def options_for(field: DisclosureField) -> dict[str, str]:
    if field.options:
        return field.options
    if field.dictionary:
        return disclosure_dictionaries().get(field.dictionary, {})
    return {}


def match_cover_field(rule: ExtractionRule, segments: dict[str, SegmentInfo]) -> tuple[str, list[str]] | None:
    if len(rule.disclosure_fields) != 1 or rule.disclosure_rows:
        return None
    field = rule.disclosure_fields[0]
    if not field.cover_label:
        return None

    pattern = re.compile(rf"{re.escape(field.cover_label)}[：:]\s*([^\r\n]+)")
    matches = {}
    for anchor, segment in segments.items():
        if segment.page_idx != 0 or segment.segment_type != "text" or not segment.bbox:
            continue
        match = pattern.fullmatch(segment.text.strip())
        if match and (value := match[1].strip()):
            matches.setdefault(value, []).append(anchor)
    return next(iter(matches.items())) if len(matches) == 1 else None


def disclosure_prompt(rule: ExtractionRule) -> str:
    parts = [rule.extraction_logic]
    for field in rule.disclosure_fields:
        options = options_for(field)
        parts.append(f"{field.code}（{field.label}，{field.platform_type}）：{field.logic}")
        if options:
            if rule.platform_interface is None:
                parts.append("候选值用中文名称：" + "、".join(options.values()))
            else:
                parts.append("中台可选值（编码=名称）：" + "、".join(f"{code}={name}" for code, name in options.items()))
        if field.unconfirmed_options:
            parts.append("以下选项编码待确认，有原文依据时保留中文：" + "、".join(field.unconfirmed_options))
    return "\n".join(parts)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def _dictionary_code(value: str, options: dict[str, str]) -> str | None:
    if value in options:
        return value
    codes = [code for code, label in options.items() if _compact(label) == _compact(value)]
    return codes[0] if len(codes) == 1 else None


def _region_code(level: str, value: str, province: str | None) -> str | None:
    matching_codes = {
        code for kind, code, name in region_entries()
        if kind == level and (not province or code[:2] == province[:2])
        and (value == code or _compact(value) == _compact(name))
    }
    return next(iter(matching_codes)) if len(matching_codes) == 1 else None


def _normalize_value(field: DisclosureField, value: Any, context: dict) -> str | None:
    if field.approval_field and _dictionary_code(
        str(context.get(field.approval_field, "")), {"0": "否", "1": "是"}
    ) != "1":
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        return None
    value = str(value).strip()
    if not value:
        return None
    if field.dictionary in ("city", "district"):
        province_code = "JGDQS" if field.code == "JGDQSHI" else next(
            (key for key in ("PROVINCE", "SZDQS") if key in context), None
        )
        province = _dictionary_code(str(context.get(province_code, "")), disclosure_dictionaries()["province"])
        return _region_code(field.dictionary, value, province)
    options = options_for(field)
    if options:
        if field.multiple:
            codes = [_dictionary_code(item.strip(), options) for item in re.split(r"[;；]", value)]
            return ";".join(dict.fromkeys(codes)) if all(codes) else None
        return _dictionary_code(value, options)
    if field.dictionary:
        return None
    if field.platform_type == "DATE" or (field.code == "PZRQ" and field.platform_type == "C10"):
        match = re.fullmatch(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?", value)
        if match:
            try:
                return date(*(int(part) for part in match.groups())).isoformat()
            except ValueError:
                pass
        return None
    if re.fullmatch(r"N\d+(?:\.\d+)?", field.platform_type):
        value = _compact(value).replace(",", "").removesuffix("%")
        if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
            return None
        try:
            number = Decimal(value)
            return format(number, "f") if number.is_finite() else None
        except InvalidOperation:
            return None
    max_length = re.fullmatch(r"C(?:LOB)?(\d+)", field.platform_type)
    if max_length and len(value) > int(max_length[1]):
        return None
    return value


def _normalize_rows(rule: ExtractionRule, value: str) -> tuple[list[dict] | None, bool]:
    try:
        raw_rows = json.loads(value, parse_float=Decimal)
    except (TypeError, ValueError):
        return None, False
    if not isinstance(raw_rows, list) or any(not isinstance(row, dict) for row in raw_rows):
        return None, False

    rows = []
    valid = True
    for raw in raw_rows:
        row = {}
        for field in rule.disclosure_fields:
            candidate = raw.get(field.code)
            if candidate is None or candidate == "":
                if field.missing_flag and field.code in raw:
                    row[field.code] = None
                    row[field.missing_flag] = "1"
                continue
            normalized = _normalize_value(field, candidate, raw)
            if normalized is None:
                valid = False
                if not isinstance(candidate, str) or candidate.strip() not in field.unconfirmed_options:
                    continue
                normalized = candidate.strip()
            row[field.code] = normalized
        if row:
            if rule.disclosure_row_keys and not any(row.get(key) for key in rule.disclosure_row_keys):
                valid = False
                continue
            rows.append(row)
    return rows or None, valid


def format_disclosure_results(rules: list[ExtractionRule], results: list[FieldExtractionResult]) -> None:
    """保留一期来源结构，在结果中标明中台接口和字段。"""
    rules_by_name = {rule.field_name: rule for rule in rules}
    raw_values = {
        result.field_name: result.values[0].extracted_value
        for result in results
        if result.values and result.values[0].sources and result.field_status == FieldExtractionStatus.SUCCESS
    }
    for result in results:
        rule = rules_by_name[result.field_name]
        fields = rule.disclosure_fields
        if not fields:
            continue
        result.extraction_rule = {
            **(result.extraction_rule or {}),
            "platform_interface": rule.platform_interface,
            "platform_fields": [
                field.model_dump(exclude_defaults=True, exclude={"logic", "options"}) for field in fields
            ],
        }
        mapping_pending = rule.platform_interface is None
        for value in result.values:
            raw = value.extracted_value
            if raw is None or raw == "":
                continue
            if rule.disclosure_rows:
                normalized, valid = _normalize_rows(rule, raw)
            else:
                normalized = _normalize_value(fields[0], raw, raw_values)
                valid = normalized is not None
                if mapping_pending and normalized is not None:
                    normalized = options_for(fields[0]).get(normalized, normalized)
            value.extracted_value = normalized if value.sources else None
            if not valid or value.extracted_value is None:
                if result.field_status != FieldExtractionStatus.FAILED:
                    result.field_status = FieldExtractionStatus.PENDING
                    result.error_message = "提取值未通过中台格式、字典或来源校验"
        if mapping_pending and result.field_status != FieldExtractionStatus.FAILED:
            result.field_status = FieldExtractionStatus.PENDING
            result.error_message = "中台字段编码待确认"

