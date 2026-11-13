"""Bounded, institution-only export. Raw DMP label lists never leave this module."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from data_mcp.features.investor_match.tag_normalize import strip_wrapping_quotes

HEADERS = ("投资机构名称", "权重分数", "匹配标签数（接口）", "匹配到的标签")
FILENAME = "投资机构匹配.xlsx"
_SEPARATORS = re.compile(r"[,，;；|\n\r、]+")
_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def export_error_code(exc: Exception) -> str:
    """Only expose allowlisted failure codes, never upstream bodies or file contents."""
    import httpx

    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return "DMP_EXPORT_TIMEOUT"
    if isinstance(exc, httpx.RequestError):
        return "DMP_EXPORT_UNAVAILABLE"
    if isinstance(exc, ValueError):
        code = str(exc)
        if code in {
            "DMP_EXPORT_NOT_CONFIGURED",
            "DMP_EXPORT_HTTP_ERROR",
            "DMP_EXPORT_RESPONSE_TOO_LARGE",
        }:
            return code
        if code in {"INVALID_DMP_EXPORT_JSON", "INVALID_DMP_ITEMS"}:
            return "DMP_EXPORT_INVALID_RESPONSE"
    return "WORKBOOK_EXPORT_FAILED"


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def normalize_track_tags(value: str | list[str]) -> list[str]:
    raw = _SEPARATORS.split(value) if isinstance(value, str) else value
    if not isinstance(raw, list) or not raw or any(not isinstance(t, str) for t in raw):
        raise ValueError("INVALID_TAGS")
    tags: dict[str, str] = {}
    for tag in raw:
        tag = strip_wrapping_quotes(" ".join(unicodedata.normalize("NFKC", tag).split()))
        if tag:
            if len(tag) > 160 or _SEPARATORS.search(tag) or _ILLEGAL.search(tag):
                raise ValueError("INVALID_TAGS")
            tags.setdefault(normalized(tag), tag)
    if not 1 <= len(tags) <= 10:
        raise ValueError("INVALID_TAG_COUNT")
    return list(tags.values())


@dataclass(frozen=True)
class LabelMatch:
    labels: list[str]
    unverified: bool


def match_requested_labels(requested_tags: list[str], raw_labels: object) -> LabelMatch:
    invalid = False
    if isinstance(raw_labels, str):
        invalid = "..." in raw_labels or "…" in raw_labels
        if raw_labels.strip().startswith("["):
            try:
                raw_labels = json.loads(raw_labels)
            except ValueError:
                return LabelMatch([], True)
        else:
            raw_labels = _SEPARATORS.split(raw_labels)
    if not isinstance(raw_labels, list):
        return LabelMatch([], True)
    labels = set()
    for value in raw_labels:
        if not isinstance(value, str):
            invalid = True
            continue
        if "..." in value or "…" in value:
            invalid = True
            continue
        label = normalized(value)
        if label:
            labels.add(label)
    return LabelMatch([q for q in requested_tags if normalized(q) in labels], invalid)


def _score(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        number = float(value)
        return number if math.isfinite(number) else 0.0
    except (ValueError, TypeError, OverflowError):
        return 0.0


def _weight_as_text(value: float) -> str:
    """Excel text cell for weight scores — avoids numeric format trailing dots like ``5.``."""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return format(number, ".10g")


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
        if number.is_finite() and 0 <= number <= 2**31 - 1 and number == number.to_integral_value():
            return int(number)
    except (InvalidOperation, ValueError, TypeError):
        pass
    return None


@dataclass
class SlimResult:
    rows: list[dict[str, Any]]
    diagnostics: list[tuple[bool, bool]]
    query_tags: list[str]


def slim_institution_rows(
    items: object, requested_tags: list[str], *, limit: int = 200
) -> SlimResult:
    if not isinstance(items, list):
        raise ValueError("INVALID_DMP_ITEMS")
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("investor_name")
        if not isinstance(name, str) or not name.strip():
            continue
        match = match_requested_labels(requested_tags, item.get("label_name_list"))
        count = _count(item.get("match_label_num"))
        name = _ILLEGAL.sub("", name).strip()[:1000]
        if not name:
            continue
        row = dict(
            investor_name=name,
            match_label_weight_sum=_score(item.get("match_label_weight_sum")),
            match_label_num=count,
            matched_labels=match.labels,
        )
        rows.append((row, (match.unverified, count is not None and count != len(match.labels))))
    rows.sort(key=lambda pair: pair[0]["match_label_weight_sum"], reverse=True)
    rows = rows[: min(limit, 200)]
    return SlimResult([r for r, _ in rows], [d for _, d in rows], requested_tags)


def build_institution_workbook(result: SlimResult) -> bytes:
    # Optional export must not make openpyxl a server startup dependency.
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill

    book = Workbook()
    sheet = book.active
    sheet.title = "投资机构"
    sheet.append(HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="155EEF")
    sheet["C1"].comment = Comment("接口统计值；可能与可核验的标签名称数量不同。", "投研 Agent")
    sheet["D1"].comment = Comment("本次查询标签与机构标签列表的完整名称交集。", "投研 Agent")
    for index, (row, diagnostic) in enumerate(zip(result.rows, result.diagnostics, strict=True), 2):
        sheet.append(
            [
                row["investor_name"],
                _weight_as_text(row["match_label_weight_sum"]),
                row["match_label_num"],
                "、".join(row["matched_labels"]),
            ]
        )
        for column in (1, 2, 4):
            sheet.cell(index, column).data_type = "s"
        sheet.cell(index, 4).alignment = Alignment(wrap_text=True, vertical="top")
        notes = []
        if diagnostic[0]:
            notes.append("机构标签列表缺失、异常或被截断，仅展示已核验项。")
        if diagnostic[1]:
            notes.append("接口匹配数量与可核验名称数量不同，保留接口原值。")
        if notes:
            sheet.cell(index, 4).comment = Comment("\n".join(notes), "投研 Agent")
    for col, width in zip("ABCD", (42, 14, 24, 70), strict=True):
        sheet.column_dimensions[col].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:D{len(result.rows) + 1}"
    stream = io.BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


def export_institution_workbook(track_tags: str | list[str], env: str | None = None) -> dict:
    from data_mcp.features.investor_match.dmp_client import query_dmp_institutions_for_export

    tags = normalize_track_tags(track_tags)
    result = query_dmp_institutions_for_export(tags, env)
    content = build_institution_workbook(result)
    if len(content) > 2 * 1024 * 1024:
        raise ValueError("WORKBOOK_TOO_LARGE")
    unverified = sum(d[0] for d in result.diagnostics)
    mismatch = sum(d[1] for d in result.diagnostics)
    status = "empty" if not result.rows else "partial" if unverified or mismatch else "success"
    return {
        "schema_version": "1.0",
        "tool": "export_matched_institutions",
        "status": status,
        "summary": f"首批 {len(result.rows)} 家投资机构（最多 200 家）",
        "data": {
            "filename": FILENAME,
            "content_base64": base64.b64encode(content).decode("ascii"),
            "row_count": len(result.rows),
            "sha256": hashlib.sha256(content).hexdigest(),
            "query_tags": tags,
            "unverified_row_count": unverified,
            "count_mismatch_row_count": mismatch,
        },
        "sources": [{"name": "dmp", "status": "available"}],
        "warnings": (
            [
                {
                    "code": "LABELS_PARTIALLY_VERIFIED",
                    "message": "部分标签不能完整核验，详见单元格注释。",
                    "retryable": False,
                }
            ]
            if unverified or mismatch
            else []
        ),
    }
