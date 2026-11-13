"""
Excel 锚点 Markdown 转换器

将 Excel 文件转换为带锚点的 Markdown 格式
用于统一提取与溯源的 LLM 输入

锚点格式: (¶F-S-R-C)
- F: 文件索引 (0-based)
- S: Sheet 索引 (0-based)
- R: 行号 (0-based，对应 Excel 实际行号)
- C: 列号 (0-based)

示例输出:
    | 资产名称 | 评估价值 |
    |---------|---------|
    | 办公楼A (¶0-0-1-0) | 1200万 (¶0-0-1-1) |
"""

import io
from datetime import date, datetime
from typing import Dict, List, Tuple, Optional
from loguru import logger

from src.utils.anchor_markdown_converter import SegmentInfo
from src.utils.excel_anchor_context import make_cell_ref
from src.utils.excel_offset_utils import (
    DEFAULT_COL_WIDTH, DEFAULT_ROW_HEIGHT, CHAR_WIDTH_PIXELS, POINT_TO_PIXELS,
    compute_col_offsets, compute_row_offsets,
)


class ExcelAnchorConverter:
    """Excel 锚点 Markdown 转换器"""

    ANCHOR_SYMBOL = "¶"

    @classmethod
    def convert(
        cls,
        file_bytes: bytes,
        file_name: str,
        file_index: int = 0,
    ) -> Tuple[str, Dict[str, SegmentInfo], int]:
        """
        解析 Excel 文件，生成带锚点的 Markdown 和 segment_map

        Args:
            file_bytes: Excel 文件字节内容
            file_name: 文件名
            file_index: 文件索引（多文件合并时由上层传入，默认 0）

        Returns:
            Tuple[str, Dict[str, SegmentInfo], int]:
                - 带锚点的 Markdown 文本（给 LLM）
                - segment_map {anchor_id: SegmentInfo}
                - sheet_count（sheet 数量）
        """
        import openpyxl

        segment_map: Dict[str, SegmentInfo] = {}
        all_lines: List[str] = []

        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        except Exception as e:
            logger.error(f"Excel 文件打开失败: {e}")
            return "", {}, 0

        try:
            sheet_names = wb.sheetnames
            sheet_count = len(sheet_names)

            for sheet_idx, sheet_name in enumerate(sheet_names):
                sheet = wb[sheet_name]
                all_lines.append(f"\n# Sheet: {sheet_name}\n")

                merged_map = cls._build_merged_map(sheet)
                rows_data = cls._collect_cells(
                    sheet,
                    sheet_idx,
                    sheet_name,
                    file_index,
                    merged_map,
                    segment_map,
                )

                if rows_data:
                    table_md = cls._render_markdown_table(rows_data)
                    all_lines.append(table_md)
        finally:
            wb.close()

        markdown_text = "\n".join(all_lines)
        logger.info(
            f"Excel 锚点转换完成 | 文件: {file_name} | "
            f"Sheets: {sheet_count} | 锚点数: {len(segment_map)}"
        )

        return markdown_text, segment_map, sheet_count

    @classmethod
    def _format_cell_value(cls, value) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d") if value.hour == value.minute == 0 else value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()

    @classmethod
    def _build_merged_map(cls, sheet) -> Dict[Tuple[int, int], Tuple[int, int, int, int]]:
        merged_map = {}
        try:
            for merged_range in sheet.merged_cells.ranges:
                min_row = merged_range.min_row - 1
                min_col = merged_range.min_col - 1
                max_row = merged_range.max_row - 1
                max_col = merged_range.max_col - 1
                for r in range(min_row, max_row + 1):
                    for c in range(min_col, max_col + 1):
                        merged_map[(r, c)] = (min_row, min_col, max_row, max_col)
        except Exception as e:
            logger.warning(f"读取合并单元格失败: {e}")
        return merged_map

    @classmethod
    def _make_anchor_id(cls, file_index: int, sheet_idx: int, row_idx: int, col_idx: int) -> str:
        return f"{file_index}-{sheet_idx}-{row_idx}-{col_idx}"

    @classmethod
    def _collect_cells(
        cls,
        sheet,
        sheet_idx: int,
        sheet_name: str,
        file_index: int,
        merged_map: Dict[Tuple[int, int], Tuple[int, int, int, int]],
        segment_map: Dict[str, SegmentInfo],
    ) -> List[List[Optional[str]]]:
        rows_data: List[List[Optional[str]]] = []
        max_col = 0

        col_x_offsets = compute_col_offsets(sheet)
        row_y_offsets = compute_row_offsets(sheet)

        min_row = sheet.min_row or 1
        max_row = sheet.max_row or 1
        min_col = sheet.min_column or 1
        max_col_idx = sheet.max_column or 1

        for row_idx in range(min_row - 1, max_row):
            row_data: List[Optional[str]] = []
            has_value = False

            for col_idx in range(min_col - 1, max_col_idx):
                if (row_idx, col_idx) in merged_map:
                    min_r, min_c, max_r, max_c = merged_map[(row_idx, col_idx)]
                    if (row_idx, col_idx) != (min_r, min_c):
                        row_data.append(None)
                        continue

                cell = sheet.cell(row=row_idx + 1, column=col_idx + 1)
                text = cls._format_cell_value(cell.value)
                if not text:
                    row_data.append(None)
                    continue

                has_value = True
                if (row_idx, col_idx) in merged_map:
                    min_r, min_c, max_r, max_c = merged_map[(row_idx, col_idx)]
                    bbox = cls._calc_merged_bbox(
                        min_r, min_c, max_r, max_c,
                        col_x_offsets, row_y_offsets, sheet
                    )
                else:
                    bbox = cls._calc_cell_bbox(
                        row_idx, col_idx,
                        col_x_offsets, row_y_offsets, sheet
                    )

                anchor_id = cls._make_anchor_id(file_index, sheet_idx, row_idx, col_idx)
                cell_ref = make_cell_ref(sheet_name, row_idx, col_idx)

                segment_map[anchor_id] = SegmentInfo(
                    anchor_id=anchor_id,
                    page_idx=sheet_idx,
                    bbox=bbox,
                    text=text,
                    segment_type="excel_cell",
                    file_index=file_index,
                    sheet_name=sheet_name,
                    row=row_idx,
                    col=col_idx,
                    cell_ref=cell_ref,
                )

                cell_text = f"{text} ({cls.ANCHOR_SYMBOL}{anchor_id})"
                row_data.append(cell_text)

            if has_value:
                max_col = max(max_col, len(row_data))
                rows_data.append(row_data)

        if max_col > 0:
            rows_data = [row[:max_col] for row in rows_data]

        return rows_data

    @classmethod
    def _calc_cell_bbox(
        cls,
        row: int, col: int,
        col_x_offsets: List[float],
        row_y_offsets: List[float],
        sheet
    ) -> List[float]:
        x0 = col_x_offsets[col] if col < len(col_x_offsets) else 0
        x1 = col_x_offsets[col + 1] if col + 1 < len(col_x_offsets) else x0 + DEFAULT_COL_WIDTH * CHAR_WIDTH_PIXELS
        y0 = row_y_offsets[row] if row < len(row_y_offsets) else 0
        y1 = row_y_offsets[row + 1] if row + 1 < len(row_y_offsets) else y0 + DEFAULT_ROW_HEIGHT * POINT_TO_PIXELS
        return [x0, y0, x1, y1]

    @classmethod
    def _calc_merged_bbox(
        cls,
        min_r: int, min_c: int, max_r: int, max_c: int,
        col_x_offsets: List[float],
        row_y_offsets: List[float],
        sheet
    ) -> List[float]:
        x0 = col_x_offsets[min_c] if min_c < len(col_x_offsets) else 0
        x1 = col_x_offsets[max_c + 1] if max_c + 1 < len(col_x_offsets) else x0 + DEFAULT_COL_WIDTH * CHAR_WIDTH_PIXELS
        y0 = row_y_offsets[min_r] if min_r < len(row_y_offsets) else 0
        y1 = row_y_offsets[max_r + 1] if max_r + 1 < len(row_y_offsets) else y0 + DEFAULT_ROW_HEIGHT * POINT_TO_PIXELS
        return [x0, y0, x1, y1]

    @classmethod
    def _render_markdown_table(cls, rows_data: List[List[Optional[str]]]) -> str:
        if not rows_data:
            return ""

        max_cols = max(len(row) for row in rows_data)
        lines = []

        header = rows_data[0]
        header_cells = [(cell or "") for cell in header]
        while len(header_cells) < max_cols:
            header_cells.append("")
        lines.append("| " + " | ".join(header_cells) + " |")
        lines.append("|" + "|".join(["---------"] * max_cols) + "|")

        for row in rows_data[1:]:
            cells = [(cell or "") for cell in row]
            while len(cells) < max_cols:
                cells.append("")
            lines.append("| " + " | ".join(cells) + " |")

        return "\n".join(lines)
