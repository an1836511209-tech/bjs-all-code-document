"""
Excel 锚点上下文工具

统一 Excel 文件的锚点 Markdown / segment_map 合并、RAG 过滤与溯源信息构建，
供 ExtractionService 批量/单字段提取、缓存预生成与高亮路由共用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger
from openpyxl.utils import get_column_letter

from src.utils.anchor_markdown_converter import AnchorMarkdownConverter, SegmentInfo


@dataclass
class ExcelAnchorContext:
    """Excel 文件类型的统一锚点上下文"""

    is_excel: bool
    trace_supported: bool
    tagged_markdown: str
    segment_map: Dict[str, SegmentInfo]

    @classmethod
    def empty(cls) -> "ExcelAnchorContext":
        return cls(is_excel=False, trace_supported=False, tagged_markdown="", segment_map={})

    @classmethod
    def from_file_data(cls, file_data: Optional[Dict[str, Any]]) -> "ExcelAnchorContext":
        if not file_data:
            return cls.empty()

        if file_data.get("is_excel") and file_data.get("excel_segment_map"):
            return cls(
                is_excel=True,
                trace_supported=bool(file_data.get("excel_trace_supported", True)),
                tagged_markdown=file_data.get("md_content", "") or "",
                segment_map=file_data["excel_segment_map"],
            )

        parse_results = file_data.get("parse_results") or []
        if not any(getattr(pr, "is_excel", False) for pr in parse_results):
            return cls.empty()

        return cls.build_from_parse_results(
            parse_results,
            file_names=file_data.get("file_names") or [],
        )

    @classmethod
    def build_from_type_results(cls, type_results: List[Dict[str, Any]]) -> "ExcelAnchorContext":
        """合并同一 file_type 下多个文件的 Excel 解析结果"""
        if not type_results:
            return cls.empty()

        sorted_results = sorted(
            type_results,
            key=lambda r: (r.get("file_name") or "", r.get("file_path") or ""),
        )
        parse_results = [r["parse_result"] for r in sorted_results if r.get("parse_result")]
        file_names = [r.get("file_name", "") for r in sorted_results if r.get("parse_result")]
        return cls.build_from_parse_results(parse_results, file_names=file_names)

    @classmethod
    def build_from_parse_results(
        cls,
        parse_results: List[Any],
        file_names: Optional[List[str]] = None,
    ) -> "ExcelAnchorContext":
        excel_results = [pr for pr in parse_results if getattr(pr, "is_excel", False)]
        if not excel_results:
            return cls.empty()

        multi_file = len(excel_results) > 1
        merged_map: Dict[str, SegmentInfo] = {}
        md_parts: List[str] = []
        trace_supported = True

        for file_idx, pr in enumerate(excel_results):
            local_map: Dict[str, SegmentInfo] = getattr(pr, "excel_segment_map", {}) or {}
            local_md: str = getattr(pr, "md_content", "") or ""
            file_name = (
                (file_names[file_idx] if file_names and file_idx < len(file_names) else None)
                or getattr(pr, "file_name", f"文件{file_idx + 1}")
            )

            if getattr(pr, "is_text_only", False) or not local_map:
                trace_supported = False

            prefixed_md, prefixed_map = cls._prefix_file_anchors(
                local_md, local_map, file_idx=file_idx, multi_file=multi_file
            )
            merged_map.update(prefixed_map)

            if multi_file:
                md_parts.append(f"# === {file_name} ===\n\n{prefixed_md}")
            else:
                md_parts.append(prefixed_md)

        tagged_markdown = "\n\n---\n\n".join(part for part in md_parts if part.strip())
        return cls(
            is_excel=True,
            trace_supported=trace_supported and bool(merged_map),
            tagged_markdown=tagged_markdown,
            segment_map=merged_map,
        )

    @classmethod
    def _rekey_anchor_id(cls, anchor_id: str, file_index: int) -> str:
        parts = anchor_id.split("-")
        if len(parts) == 4:
            return f"{file_index}-{parts[1]}-{parts[2]}-{parts[3]}"
        if len(parts) == 3:
            return f"{file_index}-{parts[0]}-{parts[1]}-{parts[2]}"
        return f"{file_index}-{anchor_id}"

    @classmethod
    def _prefix_file_anchors(
        cls,
        markdown: str,
        segment_map: Dict[str, SegmentInfo],
        file_idx: int,
        multi_file: bool,
    ) -> Tuple[str, Dict[str, SegmentInfo]]:
        symbol = AnchorMarkdownConverter.ANCHOR_SYMBOL
        prefixed_map: Dict[str, SegmentInfo] = {}

        if not multi_file:
            for aid, seg in segment_map.items():
                prefixed_map[aid] = cls._clone_segment(seg, anchor_id=aid, file_index=file_idx)
            return markdown, prefixed_map

        new_md = markdown
        for old_id, seg in segment_map.items():
            new_id = cls._rekey_anchor_id(old_id, file_idx)
            prefixed_map[new_id] = cls._clone_segment(seg, anchor_id=new_id, file_index=file_idx)
            new_md = new_md.replace(f"({symbol}{old_id})", f"({symbol}{new_id})")

        return new_md, prefixed_map

    @staticmethod
    def _clone_segment(seg: SegmentInfo, anchor_id: str, file_index: int) -> SegmentInfo:
        return SegmentInfo(
            anchor_id=anchor_id,
            page_idx=seg.page_idx,
            bbox=list(seg.bbox) if seg.bbox else seg.bbox,
            text=seg.text,
            segment_type=seg.segment_type,
            score=seg.score,
            cells=seg.cells,
            file_index=file_index,
            sheet_name=getattr(seg, "sheet_name", None),
            row=getattr(seg, "row", None),
            col=getattr(seg, "col", None),
            cell_ref=getattr(seg, "cell_ref", None),
        )

    def filter_by_sheet_indices(self, sheet_indices: Set[int]) -> "ExcelAnchorContext":
        """RAG 命中 sheet 后，保留对应 segment 并重建 Markdown"""
        if not sheet_indices:
            return self

        filtered_map = {
            aid: seg for aid, seg in self.segment_map.items() if seg.page_idx in sheet_indices
        }
        if not filtered_map:
            return self

        tagged_markdown = self._rebuild_markdown_from_segments(filtered_map)
        return ExcelAnchorContext(
            is_excel=True,
            trace_supported=self.trace_supported,
            tagged_markdown=tagged_markdown,
            segment_map=filtered_map,
        )

    @staticmethod
    def _rebuild_markdown_from_segments(segment_map: Dict[str, SegmentInfo]) -> str:
        """按 sheet 分组重建简化 Markdown（供 RAG 过滤后使用）"""
        by_sheet: Dict[int, List[SegmentInfo]] = {}
        sheet_names: Dict[int, str] = {}
        for seg in segment_map.values():
            by_sheet.setdefault(seg.page_idx, []).append(seg)
            if getattr(seg, "sheet_name", None):
                sheet_names[seg.page_idx] = seg.sheet_name

        lines: List[str] = []
        symbol = AnchorMarkdownConverter.ANCHOR_SYMBOL
        for sheet_idx in sorted(by_sheet.keys()):
            sheet_name = sheet_names.get(sheet_idx, f"Sheet{sheet_idx + 1}")
            lines.append(f"\n# Sheet: {sheet_name}\n")
            segments = sorted(
                by_sheet[sheet_idx],
                key=lambda s: (getattr(s, "row", 0) or 0, getattr(s, "col", 0) or 0),
            )
            for seg in segments:
                cell_ref = getattr(seg, "cell_ref", None) or seg.anchor_id
                lines.append(f"- {cell_ref}: {seg.text} ({symbol}{seg.anchor_id})")
        return "\n".join(lines)


def make_cell_ref(sheet_name: str, row: int, col: int) -> str:
    """生成 Excel 单元格引用，如 Sheet1!B5"""
    col_letter = get_column_letter(col + 1)
    return f"{sheet_name}!{col_letter}{row + 1}"


def build_excel_source_fields(
    regions: List[Any],
    segment_map: Dict[str, SegmentInfo],
) -> Dict[str, Any]:
    """
    从 regions / segment_map 提取 Excel 溯源展示字段

    Returns:
        dict with sheet_name, cell_ref, cell_refs, sheet_index, trace_supported
    """
    cell_refs: List[str] = []
    sheet_names: List[str] = []
    sheet_indices: List[int] = []

    for region in regions:
        file_index = getattr(region, "file_index", None)
        sheet_name = getattr(region, "sheet_name", None)
        cell_ref = getattr(region, "cell_ref", None)
        page_idx = getattr(region, "page_idx", None)

        if not cell_ref and page_idx is not None:
            for seg in segment_map.values():
                if seg.page_idx == page_idx and seg.bbox == getattr(region, "bbox", None):
                    cell_ref = getattr(seg, "cell_ref", None)
                    sheet_name = sheet_name or getattr(seg, "sheet_name", None)
                    file_index = file_index if file_index is not None else getattr(seg, "file_index", None)
                    break

        if cell_ref:
            cell_refs.append(cell_ref)
        if sheet_name:
            sheet_names.append(sheet_name)
        if page_idx is not None:
            sheet_indices.append(page_idx)

    primary_sheet = sheet_names[0] if sheet_names else None
    primary_ref = cell_refs[0] if cell_refs else None
    primary_sheet_index = sheet_indices[0] if sheet_indices else None

    return {
        "sheet_name": primary_sheet,
        "cell_ref": primary_ref,
        "cell_refs": cell_refs or None,
        "sheet_index": primary_sheet_index,
        "trace_supported": bool(cell_refs),
        "document_type": "excel",
    }


def resolve_anchor_context(
    file_data: Dict[str, Any],
    anchor_markdown_cache: Optional[Dict[str, Tuple[str, Dict[str, SegmentInfo]]]] = None,
) -> Tuple[str, Dict[str, SegmentInfo], bool]:
    """
    统一解析锚点上下文（Excel 优先，否则 PDF/Word 走 AnchorMarkdownConverter）

    Returns:
        (tagged_markdown, segment_map, is_excel)
    """
    file_type = file_data.get("file_type", "")
    excel_ctx = ExcelAnchorContext.from_file_data(file_data)
    if excel_ctx.is_excel:
        return excel_ctx.tagged_markdown, excel_ctx.segment_map, True

    if anchor_markdown_cache and file_type in anchor_markdown_cache:
        tagged_markdown, segment_map = anchor_markdown_cache[file_type]
        return tagged_markdown, segment_map, False

    tagged_markdown, segment_map = AnchorMarkdownConverter.convert(file_data)
    if not tagged_markdown:
        tagged_markdown = file_data.get("md_content", "") or ""
        segment_map = {}
    return tagged_markdown, segment_map, False
