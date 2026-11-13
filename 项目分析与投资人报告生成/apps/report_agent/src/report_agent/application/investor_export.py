"""Export the full investor-matching list to an Excel workbook.

The report shows a curated slice; this module renders *every* candidate the
Data MCP returned so the deal team can work the long tail themselves. It lives
in the application layer because it needs no agent context — it is a pure
transform over the ``/data/candidates`` payload.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterable, Mapping
from typing import Any

from langchain_core.tools import StructuredTool
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from report_agent.infrastructure.evidence import WorkspaceEvidenceStore
from report_agent.runtime.workspace import TaskWorkspace

#: How many investor rows the report body itself shows.
DISPLAY_LIMIT = 30
#: Upper bound on the Excel sheet; matches what the MCP layer is asked to fetch.
EXPORT_LIMIT = 500

HEADERS = (
    "序号",
    "投资人名称",
    "类型",
    "来源",
    "匹配标签",
    "权重分数",
    "标签权重",
    "偏好权重",
    "简介权重",
    "匹配理由",
)
COLUMN_WIDTHS = (6, 34, 8, 10, 26, 10, 10, 10, 10, 46)

SOURCE_LABELS = {"internal": "内部库", "network": "网络", "web": "网络"}


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten one MCP candidate into the workbook row shape."""
    tags = candidate.get("matched_tags") or []
    breakdown = candidate.get("weight_breakdown") or {}
    if not isinstance(breakdown, Mapping):
        breakdown = {}
    tag_label = ""
    tag_weight = _as_float(tags[0].get("weight")) if tags and isinstance(tags[0], Mapping) else None
    if tags and isinstance(tags[0], Mapping):
        tag_label = str(tags[0].get("tag") or "").strip()
    return {
        "name": str(candidate.get("name") or "").strip(),
        "investor_type": str(candidate.get("investor_type") or "").strip(),
        "source": SOURCE_LABELS.get(str(candidate.get("source") or ""), str(candidate.get("source") or "")),
        "tag": tag_label,
        "score": _as_float(candidate.get("score")),
        "label_weight": tag_weight,
        "preference_weight": _as_float(breakdown.get("preference_weight")),
        "summary_weight": _as_float(breakdown.get("summary_weight")),
        "reason": str(candidate.get("match_reason") or "").strip(),
    }


def select_display_rows(candidates: Iterable[Mapping[str, Any]], limit: int = DISPLAY_LIMIT) -> list[dict[str, Any]]:
    """Rows the report should show: institutions first, highest score first."""
    rows = [r for r in (_normalize(c) for c in candidates) if r["name"]]
    institutions = [r for r in rows if r["investor_type"] in ("机构", "institution")]
    networks = [r for r in rows if r not in institutions]
    institutions.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0)))
    networks.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0)))
    return (institutions + networks)[:limit]


def export_investors_xlsx(
    candidates: Iterable[Mapping[str, Any]],
    *,
    project: str,
    limit: int = EXPORT_LIMIT,
) -> bytes:
    """Render the full candidate list as an ``.xlsx`` payload."""
    rows = [r for r in (_normalize(c) for c in candidates) if r["name"]][:limit]
    rows.sort(key=lambda r: (r["source"] != "内部库", r["score"] is None, -(r["score"] or 0.0)))

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "投资人清单"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="155EEF")
    sheet.append(list(HEADERS))
    for cell in sheet[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for index, row in enumerate(rows, start=1):
        sheet.append(
            [
                index,
                row["name"],
                row["investor_type"],
                row["source"],
                row["tag"],
                row["score"],
                row["label_weight"],
                row["preference_weight"],
                row["summary_weight"],
                row["reason"],
            ]
        )

    for position, width in enumerate(COLUMN_WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(position)].width = width
    sheet.freeze_panes = "A2"

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def export_filename(project: str) -> str:
    safe = "".join(ch for ch in project if ch.isalnum() or ch in "-_（）()一-鿿").strip()
    return f"{safe or '项目'}-投资人清单.xlsx"


def _extract_candidates(payload: Any) -> list[Mapping[str, Any]]:
    """Pull the candidate list out of a ``match_investors`` evidence payload."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    if isinstance(data, Mapping):
        for key in ("candidates", "investors", "items", "results", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
    for key in ("candidates", "investors", "items", "results", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def build_investor_export_tools(
    workspace: TaskWorkspace, evidence_store: WorkspaceEvidenceStore
) -> tuple[StructuredTool, ...]:
    """Expose the full-list Excel export as an agent tool."""

    def export_investor_list(evidence_id: str, project: str) -> str:
        payload = evidence_store.get(evidence_id)
        candidates = _extract_candidates(payload)
        if not candidates:
            raise ValueError("该 evidence 中没有投资人候选列表")
        content = export_investors_xlsx(candidates, project=project)
        filename = export_filename(project)
        record = workspace.write_bytes(f"/workspace/report/{filename}", content)
        return json.dumps(
            {
                "path": record.path,
                "filename": filename,
                "count": min(len(candidates), EXPORT_LIMIT),
                "display_limit": DISPLAY_LIMIT,
            },
            ensure_ascii=False,
        )

    return (
        StructuredTool.from_function(
            export_investor_list,
            name="export_investor_list",
            description=(
                "把 match_investors 返回的全量投资人候选导出为 Excel。"
                "evidence_id 为 match_investors 返回的 evidence_id，project 为项目名。"
                "报告正文只展示前 30 家，全量（最多 500 家）写入 /workspace/report/ 下的 xlsx。"
            ),
        ),
    )