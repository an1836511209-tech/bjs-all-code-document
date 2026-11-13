# Excel 提取溯源实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Excel 文件新增单元格级别的提取溯源能力，支持锚点定位 `(¶S-R-C)` 和高亮预览

**Architecture:** 新增两个工具模块（ExcelAnchorConverter、ExcelCellHighlighter），在 ExtractionService 中新增 Excel 分支接入现有 Anchor Markdown 流程，复用 UnifiedExtractionAgent 和 MinIO 上传逻辑

**Tech Stack:** openpyxl, Pillow (PIL), loguru（均为已有依赖，无需新增）

## Global Constraints

- 锚点格式: `(¶S-R-C)` S=sheet索引(0-based), R=行(0-based), C=列(0-based)
- 只给有值的单元格生成锚点，空单元格跳过
- 合并单元格整体作为一个锚点，bbox 覆盖整个合并区域
- 高亮样式与现有 PDFHighlighter 一致：黄色半透明(0.3) + 红色边框
- 旧的 Tika 文本提取路径完全保留，不删除任何现有代码
- SegmentInfo 复用现有类，segment_type 使用 `"excel_cell"`
- page_idx 字段复用为 sheet_idx

---

### Task 1: ExcelAnchorConverter — Excel 锚点转换器

**Files:**
- Create: `src/utils/excel_anchor_converter.py`
- Test: `tests/test_excel_anchor_converter.py`

**Interfaces:**
- Produces: `ExcelAnchorConverter.convert(file_bytes: bytes, file_name: str) -> Tuple[str, Dict[str, SegmentInfo], int]`
  - 返回: (带锚点的Markdown文本, segment_map, sheet数量)

- [ ] **Step 1: 创建 ExcelAnchorConverter 文件**

创建 `src/utils/excel_anchor_converter.py`：

```python
"""
Excel 锚点 Markdown 转换器

将 Excel 文件转换为带锚点的 Markdown 格式
用于统一提取与溯源的 LLM 输入

锚点格式: (¶S-R-C)
- S: Sheet 索引 (0-based)
- R: 行号 (0-based)
- C: 列号 (0-based)

示例输出:
    | 资产名称 | 评估价值 |
    |---------|---------|
    | 办公楼A (¶0-0-0) | 1200万 (¶0-0-1) |
"""

import io
from typing import Dict, Any, List, Tuple, Optional
from loguru import logger

from src.utils.anchor_markdown_converter import SegmentInfo


class ExcelAnchorConverter:
    """Excel 锚点 Markdown 转换器"""

    ANCHOR_SYMBOL = "¶"

    # 默认列宽（字符单位）和行高（磅），当 openpyxl 读不到时使用
    DEFAULT_COL_WIDTH = 8.43
    DEFAULT_ROW_HEIGHT = 15.0

    # 列宽字符单位到像素的换算系数
    CHAR_WIDTH_PIXELS = 7
    # 行高磅到像素的换算系数 (1磅 = 96/72 像素)
    POINT_TO_PIXELS = 96 / 72

    @classmethod
    def convert(
        cls,
        file_bytes: bytes,
        file_name: str
    ) -> Tuple[str, Dict[str, SegmentInfo], int]:
        """
        解析 Excel 文件，生成带锚点的 Markdown 和 segment_map

        Args:
            file_bytes: Excel 文件字节内容
            file_name: 文件名

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
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
        except Exception as e:
            logger.error(f"Excel 文件打开失败: {e}")
            return "", {}, 0

        sheet_names = wb.sheetnames
        sheet_count = len(sheet_names)

        for sheet_idx, sheet_name in enumerate(sheet_names):
            sheet = wb[sheet_name]
            all_lines.append(f"\n# Sheet: {sheet_name}\n")

            # 收集合并单元格信息
            merged_map = cls._build_merged_map(sheet)

            # 收集所有有值的单元格，按行分组
            rows_data = cls._collect_cells(sheet, sheet_idx, merged_map, segment_map)

            # 生成 Markdown 表格
            if rows_data:
                table_md = cls._render_markdown_table(rows_data)
                all_lines.append(table_md)

        wb.close()

        markdown_text = "\n".join(all_lines)
        logger.info(
            f"Excel 锚点转换完成 | 文件: {file_name} | "
            f"Sheets: {sheet_count} | 锚点数: {len(segment_map)}"
        )

        return markdown_text, segment_map, sheet_count

    @classmethod
    def _build_merged_map(cls, sheet) -> Dict[Tuple[int, int], Tuple[int, int, int, int]]:
        """
        构建合并单元格映射表

        Returns:
            {(row, col): (min_row, min_col, max_row, max_col)} 坐标均为 0-based
        """
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
    def _collect_cells(
        cls,
        sheet,
        sheet_idx: int,
        merged_map: Dict[Tuple[int, int], Tuple[int, int, int, int]],
        segment_map: Dict[str, SegmentInfo]
    ) -> List[List[Optional[str]]]:
        """
        遍历 sheet 中有值的单元格，收集数据并构建 segment_map

        Returns:
            rows_data: 二维列表，每个元素是单元格文本（含锚点标记）或 None
        """
        rows_data: List[List[Optional[str]]] = []
        max_col = 0

        # 预计算每列的 x 偏移和每行的 y 偏移
        col_x_offsets = cls._precompute_col_offsets(sheet)
        row_y_offsets = cls._precompute_row_offsets(sheet)

        for row_idx, row in enumerate(sheet.iter_rows()):
            row_data: List[Optional[str]] = []
            has_value = False

            for col_idx, cell in enumerate(row):
                # 检查是否是合并单元格的非左上角
                if (row_idx, col_idx) in merged_map:
                    min_r, min_c, max_r, max_c = merged_map[(row_idx, col_idx)]
                    if (row_idx, col_idx) != (min_r, min_c):
                        row_data.append(None)
                        continue

                # 跳过空单元格
                cell_value = cell.value
                if cell_value is None or str(cell_value).strip() == "":
                    row_data.append(None)
                    continue

                has_value = True
                text = str(cell_value).strip()

                # 计算 bbox
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

                # 生成 anchor_id
                anchor_id = f"{sheet_idx}-{row_idx}-{col_idx}"

                # 创建 SegmentInfo
                segment_map[anchor_id] = SegmentInfo(
                    anchor_id=anchor_id,
                    page_idx=sheet_idx,  # 复用 page_idx 为 sheet_idx
                    bbox=bbox,
                    text=text,
                    segment_type="excel_cell"
                )

                # 在文本后追加锚点标记
                cell_text = f"{text} ({cls.ANCHOR_SYMBOL}{anchor_id})"
                row_data.append(cell_text)

            # 更新最大列数
            non_none = [c for c in row_data if c is not None]
            if non_none:
                max_col = max(max_col, len(row_data))
                rows_data.append(row_data)

        # 截断每行到 max_col
        if max_col > 0:
            rows_data = [row[:max_col] for row in rows_data]

        return rows_data

    @classmethod
    def _precompute_col_offsets(cls, sheet) -> List[float]:
        """预计算每列的 x 起始像素偏移"""
        from openpyxl.utils import get_column_letter
        offsets = [0.0]
        max_col = sheet.max_column or 1
        for c in range(max_col):
            try:
                w = sheet.column_dimensions[get_column_letter(c + 1)].width
            except Exception:
                w = None
            width_px = (w or cls.DEFAULT_COL_WIDTH) * cls.CHAR_WIDTH_PIXELS
            offsets.append(offsets[-1] + width_px)
        return offsets

    @classmethod
    def _precompute_row_offsets(cls, sheet) -> List[float]:
        """预计算每行的 y 起始像素偏移"""
        offsets = [0.0]
        max_row = sheet.max_row or 1
        for r in range(max_row):
            try:
                h = sheet.row_dimensions[r + 1].height
            except Exception:
                h = None
            height_px = (h or cls.DEFAULT_ROW_HEIGHT) * cls.POINT_TO_PIXELS
            offsets.append(offsets[-1] + height_px)
        return offsets

    @classmethod
    def _calc_cell_bbox(
        cls,
        row: int, col: int,
        col_x_offsets: List[float],
        row_y_offsets: List[float],
        sheet
    ) -> List[float]:
        """计算单个单元格的像素坐标 [x0, y0, x1, y1]"""
        x0 = col_x_offsets[col] if col < len(col_x_offsets) else 0
        x1 = col_x_offsets[col + 1] if col + 1 < len(col_x_offsets) else x0 + cls.DEFAULT_COL_WIDTH * cls.CHAR_WIDTH_PIXELS
        y0 = row_y_offsets[row] if row < len(row_y_offsets) else 0
        y1 = row_y_offsets[row + 1] if row + 1 < len(row_y_offsets) else y0 + cls.DEFAULT_ROW_HEIGHT * cls.POINT_TO_PIXELS
        return [x0, y0, x1, y1]

    @classmethod
    def _calc_merged_bbox(
        cls,
        min_r: int, min_c: int, max_r: int, max_c: int,
        col_x_offsets: List[float],
        row_y_offsets: List[float],
        sheet
    ) -> List[float]:
        """计算合并单元格的像素坐标 [x0, y0, x1, y1]"""
        x0 = col_x_offsets[min_c] if min_c < len(col_x_offsets) else 0
        x1 = col_x_offsets[max_c + 1] if max_c + 1 < len(col_x_offsets) else x0 + cls.DEFAULT_COL_WIDTH * cls.CHAR_WIDTH_PIXELS
        y0 = row_y_offsets[min_r] if min_r < len(row_y_offsets) else 0
        y1 = row_y_offsets[max_r + 1] if max_r + 1 < len(row_y_offsets) else y0 + cls.DEFAULT_ROW_HEIGHT * cls.POINT_TO_PIXELS
        return [x0, y0, x1, y1]

    @classmethod
    def _col_letter(cls, col_idx: int) -> str:
        """将 0-based 列索引转换为 Excel 列名（A, B, ..., Z, AA, AB, ...）"""
        result = ""
        while True:
            result = chr(65 + col_idx % 26) + result
            col_idx = col_idx // 26 - 1
            if col_idx < 0:
                break
        return result

    @classmethod
    def _render_markdown_table(cls, rows_data: List[List[Optional[str]]]) -> str:
        """将二维数据渲染为 Markdown 表格"""
        if not rows_data:
            return ""

        max_cols = max(len(row) for row in rows_data)
        lines = []

        # 第一行作为表头
        header = rows_data[0]
        header_cells = [(cell or "") for cell in header]
        # 补齐列数
        while len(header_cells) < max_cols:
            header_cells.append("")
        lines.append("| " + " | ".join(header_cells) + " |")
        lines.append("|" + "|".join(["---------"] * max_cols) + "|")

        # 数据行
        for row in rows_data[1:]:
            cells = [(cell or "") for cell in row]
            while len(cells) < max_cols:
                cells.append("")
            lines.append("| " + " | ".join(cells) + " |")

        return "\n".join(lines)
```

- [ ] **Step 2: 编写单元测试**

创建 `tests/test_excel_anchor_converter.py`：

```python
"""ExcelAnchorConverter 单元测试"""

import io
import pytest
import openpyxl


def create_test_excel(sheets=None, merged_cells=None):
    """创建测试用 Excel 文件字节"""
    wb = openpyxl.Workbook()
    if sheets:
        # 删除默认 sheet
        wb.remove(wb.active)
        for sheet_name, rows in sheets.items():
            ws = wb.create_sheet(sheet_name)
            for r, row_data in enumerate(rows, 1):
                for c, value in enumerate(row_data, 1):
                    ws.cell(row=r, column=c, value=value)
        # 处理合并单元格
        if merged_cells:
            for sheet_name, ranges in merged_cells.items():
                ws = wb[sheet_name]
                for range_str in ranges:
                    ws.merge_cells(range_str)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestExcelAnchorConverter:
    """ExcelAnchorConverter 测试"""

    def test_basic_single_sheet(self):
        """测试基本的单 sheet 转换"""
        from src.utils.excel_anchor_converter import ExcelAnchorConverter

        file_bytes = create_test_excel(sheets={
            "Sheet1": [
                ["资产名称", "评估价值", "备注"],
                ["办公楼A", "1200万", "已抵押"],
                ["厂房B", "800万", "无"],
            ]
        })

        markdown, segment_map, sheet_count = ExcelAnchorConverter.convert(file_bytes, "test.xlsx")

        assert sheet_count == 1
        assert "¶0-0-0" in markdown  # 资产名称
        assert "¶0-1-0" in markdown  # 办公楼A
        assert "¶0-1-1" in markdown  # 1200万
        assert "¶0-2-0" in markdown  # 厂房B
        assert "0-0-0" in segment_map
        assert "0-1-0" in segment_map
        assert segment_map["0-1-0"].text == "办公楼A"
        assert segment_map["0-1-0"].page_idx == 0
        assert segment_map["0-1-0"].segment_type == "excel_cell"

    def test_multi_sheet(self):
        """测试多 sheet 转换"""
        from src.utils.excel_anchor_converter import ExcelAnchorConverter

        file_bytes = create_test_excel(sheets={
            "资产明细": [["名称", "价值"], ["办公楼", "1000万"]],
            "汇总表": [["项目", "合计"], ["总价值", "1000万"]],
        })

        markdown, segment_map, sheet_count = ExcelAnchorConverter.convert(file_bytes, "test.xlsx")

        assert sheet_count == 2
        assert "# Sheet: 资产明细" in markdown
        assert "# Sheet: 汇总表" in markdown
        assert "¶0-0-0" in segment_map  # 资产明细 sheet
        assert "¶1-0-0" in segment_map  # 汇总表 sheet

    def test_empty_cells_skipped(self):
        """测试空单元格被跳过"""
        from src.utils.excel_anchor_converter import ExcelAnchorConverter

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(row=1, column=1, value="有值")
        ws.cell(row=1, column=3, value="也有值")
        # row=1, col=2 是空的
        buf = io.BytesIO()
        wb.save(buf)
        file_bytes = buf.getvalue()

        markdown, segment_map, _ = ExcelAnchorConverter.convert(file_bytes, "test.xlsx")

        assert "¶0-0-0" in segment_map  # 有值
        assert "¶0-0-2" in segment_map  # 也有值
        assert "0-0-1" not in segment_map  # 空单元格无锚点

    def test_merged_cells(self):
        """测试合并单元格处理"""
        from src.utils.excel_anchor_converter import ExcelAnchorConverter

        file_bytes = create_test_excel(
            sheets={
                "Sheet1": [
                    ["合并标题", None, "备注"],
                    ["A", "B", "C"],
                ]
            },
            merged_cells={
                "Sheet1": ["A1:C1"]
            }
        )

        markdown, segment_map, _ = ExcelAnchorConverter.convert(file_bytes, "test.xlsx")

        # 合并单元格只有左上角有锚点
        assert "0-0-0" in segment_map
        # 合并区域的其他位置不应有锚点
        assert "0-0-1" not in segment_map
        assert "0-0-2" not in segment_map
        # bbox 应覆盖整个合并区域
        bbox = segment_map["0-0-0"].bbox
        assert bbox[2] > bbox[0]  # x1 > x0（宽度 > 0）
        assert bbox[3] > bbox[1]  # y1 > y0（高度 > 0）

    def test_segment_info_structure(self):
        """测试 SegmentInfo 结构正确"""
        from src.utils.excel_anchor_converter import ExcelAnchorConverter

        file_bytes = create_test_excel(sheets={
            "Sheet1": [["Hello"]]
        })

        _, segment_map, _ = ExcelAnchorConverter.convert(file_bytes, "test.xlsx")
        info = segment_map["0-0-0"]

        assert info.anchor_id == "0-0-0"
        assert info.page_idx == 0
        assert len(info.bbox) == 4
        assert info.text == "Hello"
        assert info.segment_type == "excel_cell"
        assert info.score is None
        assert info.cells is None

    def test_chinese_content(self):
        """测试中文内容正确处理"""
        from src.utils.excel_anchor_converter import ExcelAnchorConverter

        file_bytes = create_test_excel(sheets={
            "数据表": [
                ["资产名称", "评估价值"],
                ["办公楼A栋", "壹仟贰佰万元整"],
            ]
        })

        markdown, segment_map, _ = ExcelAnchorConverter.convert(file_bytes, "测试.xlsx")

        assert "¶0-1-0" in segment_map
        assert segment_map["0-1-0"].text == "办公楼A栋"
        assert "办公楼A栋" in markdown
```

- [ ] **Step 3: 运行测试验证**

Run: `cd d:/Project/bjs_luruzhushen && python -m pytest tests/test_excel_anchor_converter.py -v`
Expected: 全部 PASS

- [ ] **Step 4: 提交**

```bash
git add src/utils/excel_anchor_converter.py tests/test_excel_anchor_converter.py
git commit -m "feat: 新增 ExcelAnchorConverter — Excel 锚点转换器"
```

---

### Task 2: ExcelCellHighlighter — Excel 单元格高亮渲染器

**Files:**
- Create: `src/utils/excel_cell_highlighter.py`
- Test: `tests/test_excel_cell_highlighter.py`

**Interfaces:**
- Produces: `ExcelCellHighlighter.render_highlight(file_bytes: bytes, sheet_idx: int, target_bboxes: List[List[float]]) -> bytes`
  - 返回: PNG 图片字节

- [ ] **Step 1: 创建 ExcelCellHighlighter 文件**

创建 `src/utils/excel_cell_highlighter.py`：

```python
"""
Excel 单元格高亮渲染器

将 Excel sheet 渲染为 PNG 图片，并在指定单元格画高亮区域
用于溯源预览（与现有 PDFHighlighter 输出格式兼容）
"""

import io
from typing import List, Tuple, Optional
from loguru import logger

from PIL import Image, ImageDraw, ImageFont


class ExcelCellHighlighter:
    """Excel 单元格高亮渲染器"""

    # 高亮样式（与 PDFHighlighter 一致）
    HIGHLIGHT_COLOR = (255, 255, 0)   # 黄色 (RGB)
    HIGHLIGHT_ALPHA = 77              # 0.3 * 255 ≈ 77
    BORDER_COLOR = (255, 0, 0)        # 红色 (RGB)
    BORDER_WIDTH = 2

    # 渲染参数
    PADDING = 10                      # 画布边距（像素）
    GRID_COLOR = (200, 200, 200)      # 网格线颜色（浅灰）
    TEXT_COLOR = (0, 0, 0)            # 文本颜色（黑色）
    BG_COLOR = (255, 255, 255)        # 背景色（白色）
    FONT_SIZE = 12                    # 字体大小

    # 裁剪范围：目标单元格周围 ±N 行/列
    ROW_MARGIN = 5
    COL_MARGIN = 3

    # 最大渲染尺寸
    MAX_WIDTH = 2000
    MAX_HEIGHT = 3000

    # 默认列宽/行高（与 ExcelAnchorConverter 一致）
    DEFAULT_COL_WIDTH = 8.43
    DEFAULT_ROW_HEIGHT = 15.0
    CHAR_WIDTH_PIXELS = 7
    POINT_TO_PIXELS = 96 / 72

    @classmethod
    def render_highlight(
        cls,
        file_bytes: bytes,
        sheet_idx: int,
        target_bboxes: List[List[float]],
    ) -> bytes:
        """
        渲染指定 sheet 为 PNG 图片，并在 target_bboxes 位置画高亮

        Args:
            file_bytes: Excel 文件字节内容
            sheet_idx: Sheet 索引（0-based）
            target_bboxes: 需要高亮的单元格坐标列表 [[x0,y0,x1,y1], ...]

        Returns:
            PNG 图片字节
        """
        import openpyxl

        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
        except Exception as e:
            logger.error(f"Excel 高亮渲染失败 - 文件打开错误: {e}")
            return cls._render_error_image(f"Excel 打开失败: {e}")

        try:
            sheet_names = wb.sheetnames
            if sheet_idx >= len(sheet_names):
                logger.error(f"Sheet 索引 {sheet_idx} 超出范围（共 {len(sheet_names)} 个 sheet）")
                return cls._render_error_image(f"Sheet 索引 {sheet_idx} 超出范围")

            sheet = wb[sheet_names[sheet_idx]]

            # 计算裁剪范围
            crop_info = cls._calc_crop_range(sheet, target_bboxes)

            # 渲染
            img_bytes = cls._render_sheet(sheet, target_bboxes, crop_info)

            logger.info(
                f"Excel 高亮渲染完成 | Sheet: {sheet_names[sheet_idx]} | "
                f"高亮区域数: {len(target_bboxes)} | 图片大小: {len(img_bytes)} 字节"
            )
            return img_bytes

        except Exception as e:
            logger.error(f"Excel 高亮渲染失败: {e}")
            return cls._render_error_image(f"渲染失败: {e}")
        finally:
            wb.close()

    @classmethod
    def _calc_crop_range(cls, sheet, target_bboxes: List[List[float]]) -> dict:
        """
        计算裁剪范围：目标单元格周围 ±ROW_MARGIN 行 / ±COL_MARGIN 列

        Returns:
            {
                "x_offset": float, "y_offset": float,
                "width": float, "height": float,
                "col_start": int, "col_end": int,
                "row_start": int, "row_end": int,
            }
        """
        if not target_bboxes:
            return {"x_offset": 0, "y_offset": 0, "width": 800, "height": 600,
                    "col_start": 0, "col_end": 10, "row_start": 0, "row_end": 20}

        # 从 target_bboxes 反推行列范围
        min_x = min(b[0] for b in target_bboxes)
        min_y = min(b[1] for b in target_bboxes)
        max_x = max(b[2] for b in target_bboxes)
        max_y = max(b[3] for b in target_bboxes)

        # 计算每列/每行的偏移，找到目标所在的行列
        col_offsets = cls._get_col_offsets(sheet)
        row_offsets = cls._get_row_offsets(sheet)

        # 找到目标列范围
        col_start = 0
        for i, x in enumerate(col_offsets):
            if x <= min_x:
                col_start = i
        col_end = len(col_offsets) - 1
        for i, x in enumerate(col_offsets):
            if x >= max_x:
                col_end = i
                break

        # 找到目标行范围
        row_start = 0
        for i, y in enumerate(row_offsets):
            if y <= min_y:
                row_start = i
        row_end = len(row_offsets) - 1
        for i, y in enumerate(row_offsets):
            if y >= max_y:
                row_end = i
                break

        # 扩展边距
        col_start = max(0, col_start - cls.COL_MARGIN)
        col_end = min(len(col_offsets) - 1, col_end + cls.COL_MARGIN)
        row_start = max(0, row_start - cls.ROW_MARGIN)
        row_end = min(len(row_offsets) - 1, row_end + cls.ROW_MARGIN)

        x_offset = col_offsets[col_start] if col_start < len(col_offsets) else 0
        y_offset = row_offsets[row_start] if row_start < len(row_offsets) else 0
        x_end = col_offsets[col_end] if col_end < len(col_offsets) else 800
        y_end = row_offsets[row_end] if row_end < len(row_offsets) else 600

        return {
            "x_offset": x_offset,
            "y_offset": y_offset,
            "width": x_end - x_offset,
            "height": y_end - y_offset,
            "col_start": col_start,
            "col_end": col_end,
            "row_start": row_start,
            "row_end": row_end,
        }

    @classmethod
    def _get_col_offsets(cls, sheet) -> List[float]:
        """获取每列的 x 起始偏移"""
        offsets = [0.0]
        max_col = sheet.max_column or 1
        for c in range(max_col):
            try:
                from openpyxl.utils import get_column_letter
                w = sheet.column_dimensions[get_column_letter(c + 1)].width
            except Exception:
                w = None
            width_px = (w or cls.DEFAULT_COL_WIDTH) * cls.CHAR_WIDTH_PIXELS
            offsets.append(offsets[-1] + width_px)
        return offsets

    @classmethod
    def _get_row_offsets(cls, sheet) -> List[float]:
        """获取每行的 y 起始偏移"""
        offsets = [0.0]
        max_row = sheet.max_row or 1
        for r in range(max_row):
            try:
                h = sheet.row_dimensions[r + 1].height
            except Exception:
                h = None
            height_px = (h or cls.DEFAULT_ROW_HEIGHT) * cls.POINT_TO_PIXELS
            offsets.append(offsets[-1] + height_px)
        return offsets

    @classmethod
    def _render_sheet(
        cls,
        sheet,
        target_bboxes: List[List[float]],
        crop_info: dict
    ) -> bytes:
        """渲染 sheet 为 PNG 图片"""
        x_off = crop_info["x_offset"]
        y_off = crop_info["y_offset"]
        width = int(crop_info["width"]) + cls.PADDING * 2
        height = int(crop_info["height"]) + cls.PADDING * 2

        # 限制最大尺寸
        if width > cls.MAX_WIDTH:
            width = cls.MAX_WIDTH
        if height > cls.MAX_HEIGHT:
            height = cls.MAX_HEIGHT

        # 创建画布
        img = Image.new("RGB", (width, height), cls.BG_COLOR)
        draw = ImageDraw.Draw(img)

        # 尝试加载中文字体
        font = cls._load_font()

        # 获取偏移表
        col_offsets = cls._get_col_offsets(sheet)
        row_offsets = cls._get_row_offsets(sheet)

        # 绘制网格线
        for c in range(crop_info["col_start"], crop_info["col_end"] + 1):
            if c < len(col_offsets):
                x = int(col_offsets[c] - x_off) + cls.PADDING
                if 0 <= x <= width:
                    draw.line([(x, 0), (x, height)], fill=cls.GRID_COLOR, width=1)

        for r in range(crop_info["row_start"], crop_info["row_end"] + 1):
            if r < len(row_offsets):
                y = int(row_offsets[r] - y_off) + cls.PADDING
                if 0 <= y <= height:
                    draw.line([(0, y), (width, y)], fill=cls.GRID_COLOR, width=1)

        # 绘制单元格文本（只渲染裁剪范围内的单元格）
        for row in sheet.iter_rows(
            min_row=crop_info["row_start"] + 1,
            max_row=crop_info["row_end"] + 1,
            min_col=crop_info["col_start"] + 1,
            max_col=crop_info["col_end"] + 1,
        ):
            for cell in row:
                if cell.value is not None:
                    r_idx = cell.row - 1
                    c_idx = cell.column - 1
                    if r_idx < len(row_offsets) and c_idx < len(col_offsets):
                        x = int(col_offsets[c_idx] - x_off) + cls.PADDING + 3
                        y = int(row_offsets[r_idx] - y_off) + cls.PADDING + 3
                        text = str(cell.value)
                        # 截断过长文本
                        if len(text) > 30:
                            text = text[:27] + "..."
                        draw.text((x, y), text, fill=cls.TEXT_COLOR, font=font)

        # 绘制高亮区域（alpha 混合）
        highlight_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        hl_draw = ImageDraw.Draw(highlight_layer)

        for bbox in target_bboxes:
            bx0 = int(bbox[0] - x_off) + cls.PADDING
            by0 = int(bbox[1] - y_off) + cls.PADDING
            bx1 = int(bbox[2] - x_off) + cls.PADDING
            by1 = int(bbox[3] - y_off) + cls.PADDING

            # 半透明黄色填充
            hl_draw.rectangle([bx0, by0, bx1, by1], fill=(255, 255, 0, cls.HIGHLIGHT_ALPHA))
            # 红色边框
            hl_draw.rectangle([bx0, by0, bx1, by1], outline=cls.BORDER_COLOR, width=cls.BORDER_WIDTH)

        # 合并高亮层
        img = Image.alpha_composite(img.convert("RGBA"), highlight_layer)
        img = img.convert("RGB")

        # 输出 PNG
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    @classmethod
    def _load_font(cls, size: int = None) -> ImageFont.FreeTypeFont:
        """加载中文字体，回退到默认字体"""
        size = size or cls.FONT_SIZE
        font_paths = [
            "C:/Windows/Fonts/msyh.ttc",      # Microsoft YaHei
            "C:/Windows/Fonts/simhei.ttf",     # SimHei
            "C:/Windows/Fonts/simsun.ttc",     # SimSun
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",  # Linux
        ]
        for path in font_paths:
            try:
                return ImageFont.truetype(path, size)
            except (IOError, OSError):
                continue
        return ImageFont.load_default()

    @classmethod
    def _render_error_image(cls, error_msg: str) -> bytes:
        """渲染错误提示图片"""
        img = Image.new("RGB", (400, 100), (255, 240, 240))
        draw = ImageDraw.Draw(img)
        font = cls._load_font()
        draw.text((10, 30), f"高亮渲染失败: {error_msg}", fill=(200, 0, 0), font=font)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
```

- [ ] **Step 2: 编写单元测试**

创建 `tests/test_excel_cell_highlighter.py`：

```python
"""ExcelCellHighlighter 单元测试"""

import io
import pytest
import openpyxl
from PIL import Image


def create_test_excel():
    """创建测试用 Excel 文件"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.cell(row=1, column=1, value="资产名称")
    ws.cell(row=1, column=2, value="评估价值")
    ws.cell(row=2, column=1, value="办公楼A")
    ws.cell(row=2, column=2, value="1200万")
    ws.cell(row=3, column=1, value="厂房B")
    ws.cell(row=3, column=2, value="800万")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestExcelCellHighlighter:
    """ExcelCellHighlighter 测试"""

    def test_render_returns_png(self):
        """测试渲染返回有效的 PNG 字节"""
        from src.utils.excel_cell_highlighter import ExcelCellHighlighter

        file_bytes = create_test_excel()
        result = ExcelCellHighlighter.render_highlight(
            file_bytes=file_bytes,
            sheet_idx=0,
            target_bboxes=[[0, 0, 100, 30]]
        )

        # 验证是有效的 PNG
        assert len(result) > 0
        img = Image.open(io.BytesIO(result))
        assert img.format == "PNG"

    def test_render_with_multiple_bboxes(self):
        """测试多个高亮区域"""
        from src.utils.excel_cell_highlighter import ExcelCellHighlighter

        file_bytes = create_test_excel()
        result = ExcelCellHighlighter.render_highlight(
            file_bytes=file_bytes,
            sheet_idx=0,
            target_bboxes=[[0, 0, 100, 30], [100, 30, 200, 60]]
        )

        img = Image.open(io.BytesIO(result))
        assert img.size[0] > 0
        assert img.size[1] > 0

    def test_invalid_sheet_idx(self):
        """测试无效 sheet 索引返回错误图片"""
        from src.utils.excel_cell_highlighter import ExcelCellHighlighter

        file_bytes = create_test_excel()
        result = ExcelCellHighlighter.render_highlight(
            file_bytes=file_bytes,
            sheet_idx=99,
            target_bboxes=[[0, 0, 100, 30]]
        )

        # 应返回错误提示图片而非抛异常
        assert len(result) > 0
        img = Image.open(io.BytesIO(result))
        assert img.format == "PNG"
```

- [ ] **Step 3: 运行测试验证**

Run: `cd d:/Project/bjs_luruzhushen && python -m pytest tests/test_excel_cell_highlighter.py -v`
Expected: 全部 PASS

- [ ] **Step 4: 提交**

```bash
git add src/utils/excel_cell_highlighter.py tests/test_excel_cell_highlighter.py
git commit -m "feat: 新增 ExcelCellHighlighter — Excel 单元格高亮渲染器"
```

---

### Task 3: ExtractionService 集成 — Excel 解析分支

**Files:**
- Modify: `src/services/extraction/service.py:1426` — 在 `is_text_document_format` 之前插入 Excel 分支
- Modify: `src/services/extraction/service.py` — 新增 `_create_excel_parse_result()` 方法

**Interfaces:**
- Consumes: `ExcelAnchorConverter.convert()` (Task 1)
- Produces: `parse_result` with `is_text_only=False`, `is_excel=True`, `excel_segment_map`

- [ ] **Step 1: 在 _parse_files() 中插入 Excel 分支**

在 `src/services/extraction/service.py` 第 1426 行（`# 2. 检查是否为文本文档格式` 注释之前），插入以下代码：

```python
        # 1.5. 检查是否为 Excel 格式（使用 openpyxl，支持溯源）
        elif file_extension in FileHandler.SUPPORTED_EXCEL_FORMATS:
            logger.info(f"检测到 Excel 格式: {file_extension}，使用 openpyxl 提取（支持溯源）")

            try:
                # 获取文件内容
                file_content = await get_file_content()

                # 用 ExcelAnchorConverter 生成 Anchor Markdown + segment_map
                from src.utils.excel_anchor_converter import ExcelAnchorConverter
                anchor_markdown, segment_map, sheet_count = ExcelAnchorConverter.convert(
                    file_content, file_input.file_name
                )

                if not anchor_markdown:
                    logger.warning(f"Excel 锚点转换结果为空，降级到 Tika 文本提取")
                    # 降级到 Tika
                    tika_result = await self.tika_client.extract_text(
                        file_content=file_content,
                        file_name=file_input.file_name
                    )
                    parse_result = self._create_text_parse_result(
                        text_content=tika_result["text"],
                        file_name=file_input.file_name
                    )
                    return parse_result, None

                # 构建模拟的 parse_result（兼容现有流程）
                parse_result = self._create_excel_parse_result(
                    anchor_markdown=anchor_markdown,
                    segment_map=segment_map,
                    file_name=file_input.file_name,
                    sheet_count=sheet_count,
                )

                # Excel 需要 file_bytes 用于高亮渲染，存入 parse_result
                parse_result.file_bytes = file_content

                return parse_result, None  # Excel 不需要 PDF 文件

            except Exception as e:
                logger.error(f"Excel 提取失败: {e}")
                raise
```

- [ ] **Step 2: 新增 _create_excel_parse_result() 方法**

在 `_create_text_parse_result()` 方法之后（约第 1659 行之后），新增：

```python
    def _create_excel_parse_result(
        self,
        anchor_markdown: str,
        segment_map: Dict[str, Any],
        file_name: str,
        sheet_count: int,
    ) -> Any:
        """
        为 Excel 文件创建解析结果对象（支持溯源）

        与 _create_text_parse_result 的区别：
        - is_text_only=False（启用溯源）
        - is_excel=True（标记为 Excel，高亮时路由到 Excel 高亮器）
        - excel_segment_map 存储单元格级 segment_map

        Args:
            anchor_markdown: 带锚点的 Markdown 文本
            segment_map: 单元格级 segment_map
            file_name: 文件名
            sheet_count: Sheet 数量

        Returns:
            模拟 MinerU 的 ParseResult 对象
        """
        from types import SimpleNamespace

        # 创建模拟的 layout_block
        mock_layout_block = SimpleNamespace(
            bbox=SimpleNamespace(x0=0, y0=0, x1=100, y1=100),
            category_type="text",
            lines=[SimpleNamespace(spans=[SimpleNamespace(text=anchor_markdown)])]
        )

        # 创建模拟的 page
        mock_page = SimpleNamespace(
            page_num=0,
            text=anchor_markdown,
            width=0,
            height=0,
            contents=[SimpleNamespace(type="text", text=anchor_markdown)],
            layout_blocks=[mock_layout_block],
        )

        # 创建 parse_result
        parse_result = SimpleNamespace(
            pages=[mock_page],
            file_name=file_name,
            total_pages=sheet_count,
            # 关键：不标记为 text_only，这样会走溯源流程
            is_text_only=False,
            # 标记为 Excel，高亮时路由到 Excel 高亮器
            is_excel=True,
            # 存储 segment_map 供后续查表
            excel_segment_map=segment_map,
            raw_text=anchor_markdown,
            md_content=anchor_markdown,
        )

        return parse_result
```

- [ ] **Step 3: 修改 _parse_single_file 返回值处理**

在 `parse_with_metadata` 函数中（约第 922 行），`parse_result` 从 `_parse_single_file` 返回后，需要将 Excel 的 `file_bytes` 传递到 `result` dict 中。

在约第 926-933 行的返回 dict 中，新增 `file_bytes` 字段：

```python
                if parse_result:
                    logger.info(f"文件解析成功: {file_input.file_name}")
                    return {
                        "success": True,
                        "file_type": file_type,
                        "file_name": file_input.file_name,
                        "file_path": file_url,
                        "parse_result": parse_result,
                        "pdf_content": pdf_content,
                        "file_bytes": getattr(parse_result, 'file_bytes', None),  # Excel 高亮用
                        "from_cache": False
                    }
```

同样在缓存命中的返回 dict 中（约第 899-907 行），也加上：

```python
                    return {
                        "success": True,
                        "file_type": file_type,
                        "file_name": file_input.file_name,
                        "file_path": file_url,
                        "parse_result": parse_result,
                        "pdf_content": pdf_content,
                        "file_bytes": getattr(parse_result, 'file_bytes', None),  # Excel 高亮用
                        "from_cache": True
                    }
```

- [ ] **Step 4: 在 parsed_data 中存储 file_bytes**

在 `_parse_files()` 构建 `parsed_data` 的位置（约第 844-852 行），新增 `file_bytes` 字段：

```python
            parsed_data = {
                "file_type": file_type,
                "file_names": file_names,
                "file_paths": file_paths,
                "pdf_contents": pdf_contents,
                "file_bytes_list": [r.get("file_bytes") for r in type_results],  # Excel 高亮用
                "parse_results": parse_results,
                "md_content": self._merge_md_content(parse_results),
                "middle_json": self._merge_middle_json(parse_results)
            }
```

- [ ] **Step 5: 运行现有测试确认无回归**

Run: `cd d:/Project/bjs_luruzhushen && python -m pytest tests/ -v --timeout=60 -x`
Expected: 现有测试全部通过（无回归）

- [ ] **Step 6: 提交**

```bash
git add src/services/extraction/service.py
git commit -m "feat: ExtractionService 集成 Excel 锚点提取路径"
```

---

### Task 4: Anchor Markdown 查表 — Excel 分支

**Files:**
- Modify: `src/services/extraction/service.py:2614-2623` — `_extract_batch_fields()` 中检测 Excel 并使用预构建的 segment_map

**Interfaces:**
- Consumes: `parse_result.excel_segment_map` (Task 3), `AnchorMarkdownConverter.lookup_bboxes_by_anchors()` (已有)
- Produces: `regions: List[Region]` 供高亮使用

- [ ] **Step 1: 修改 _extract_batch_fields() 的 Anchor Markdown 获取逻辑**

在 `src/services/extraction/service.py` 第 2614-2623 行，将：

```python
        # 获取或生成 Anchor Markdown
        if anchor_markdown_cache and file_type in anchor_markdown_cache:
            tagged_markdown, segment_map = anchor_markdown_cache[file_type]
            logger.debug(f"使用缓存的 Anchor Markdown | 文件类型: {file_type}")
        else:
            tagged_markdown, segment_map = AnchorMarkdownConverter.convert(file_data)
            if not tagged_markdown:
                logger.warning(f"转换 Anchor Markdown 失败")
                tagged_markdown = file_data.get("md_content", "")
                segment_map = {}
```

改为：

```python
        # 获取或生成 Anchor Markdown
        # 优先检查是否为 Excel（已有预构建的 anchor_markdown 和 segment_map）
        parse_results = file_data.get("parse_results", [])
        is_excel = any(getattr(pr, 'is_excel', False) for pr in parse_results)

        if is_excel:
            # Excel 文件：使用预构建的 anchor_markdown 和 segment_map
            excel_pr = next(pr for pr in parse_results if getattr(pr, 'is_excel', False))
            tagged_markdown = getattr(excel_pr, 'md_content', '')
            segment_map = getattr(excel_pr, 'excel_segment_map', {})
            logger.debug(f"使用 Excel 预构建的 Anchor Markdown | 锚点数: {len(segment_map)}")
        elif anchor_markdown_cache and file_type in anchor_markdown_cache:
            tagged_markdown, segment_map = anchor_markdown_cache[file_type]
            logger.debug(f"使用缓存的 Anchor Markdown | 文件类型: {file_type}")
        else:
            tagged_markdown, segment_map = AnchorMarkdownConverter.convert(file_data)
            if not tagged_markdown:
                logger.warning(f"转换 Anchor Markdown 失败")
                tagged_markdown = file_data.get("md_content", "")
                segment_map = {}
```

- [ ] **Step 2: 运行现有测试确认无回归**

Run: `cd d:/Project/bjs_luruzhushen && python -m pytest tests/ -v --timeout=60 -x`
Expected: 现有测试全部通过

- [ ] **Step 3: 提交**

```bash
git add src/services/extraction/service.py
git commit -m "feat: _extract_batch_fields 支持 Excel 预构建 segment_map 查表"
```

---

### Task 5: 高亮生成 — Excel 路由

**Files:**
- Modify: `src/services/extraction/service.py:4426-4507` — `_batch_generate_highlights()` 中检测 Excel 并路由到 ExcelCellHighlighter

**Interfaces:**
- Consumes: `ExcelCellHighlighter.render_highlight()` (Task 2), `file_data['file_bytes_list']` (Task 3)
- Produces: `image_bytes` 供上传 MinIO

- [ ] **Step 1: 修改 generate_highlight_image_only() 支持 Excel**

在 `src/services/extraction/service.py` 的 `generate_highlight_image_only()` 函数内部（约第 4438 行之后），在获取 `parse_results` 之后、进入 regions 处理之前，插入 Excel 高亮分支：

```python
                    parse_results = file_data.get("parse_results", [])
                    file_paths = file_data.get("file_paths", [])
                    pdf_contents = file_data.get("pdf_contents", [])
                    file_bytes_list = file_data.get("file_bytes_list", [])  # Excel 用

                    # 检测是否为 Excel 文件
                    is_excel = any(getattr(pr, 'is_excel', False) for pr in parse_results)

                    if is_excel and regions:
                        # Excel 高亮：使用 ExcelCellHighlighter
                        from src.utils.excel_cell_highlighter import ExcelCellHighlighter

                        # 获取 file_bytes（取第一个非 None 的）
                        file_bytes = next((fb for fb in file_bytes_list if fb is not None), None)
                        if file_bytes is None:
                            logger.warning("Excel 高亮失败: 未找到 file_bytes")
                            return None

                        # sheet_idx = page_idx（复用字段）
                        sheet_idx = regions[0].page_idx
                        target_bboxes = [r.bbox for r in regions]

                        img_bytes = await asyncio.get_event_loop().run_in_executor(
                            None,
                            ExcelCellHighlighter.render_highlight,
                            file_bytes,
                            sheet_idx,
                            target_bboxes,
                        )
                        return img_bytes

                    # 以下是现有的 PDF 高亮逻辑（不变）
```

注意：需要在函数开头确认 `regions` 变量已从 `task_info` 中获取。查看现有代码结构，`regions` 在约第 4434 行已获取：`regions = task_info.get('regions')`。

- [ ] **Step 2: 运行现有测试确认无回归**

Run: `cd d:/Project/bjs_luruzhushen && python -m pytest tests/ -v --timeout=60 -x`
Expected: 现有测试全部通过

- [ ] **Step 3: 提交**

```bash
git add src/services/extraction/service.py
git commit -m "feat: _batch_generate_highlights 支持 Excel 单元格高亮渲染"
```

---

### Task 6: 集成验证 — 端到端测试

**Files:**
- Create: `tests/test_excel_e2e.py`

- [ ] **Step 1: 编写端到端验证脚本**

创建 `tests/test_excel_e2e.py`：

```python
"""
Excel 提取溯源端到端验证

验证 ExcelAnchorConverter → segment_map → lookup_bboxes_by_anchors → ExcelCellHighlighter 完整链路
"""

import io
import pytest
import openpyxl


def create_test_excel():
    """创建测试用 Excel"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "资产明细"
    ws.cell(row=1, column=1, value="资产名称")
    ws.cell(row=1, column=2, value="评估价值")
    ws.cell(row=1, column=3, value="备注")
    ws.cell(row=2, column=1, value="办公楼A")
    ws.cell(row=2, column=2, value="1200万")
    ws.cell(row=2, column=3, value="已抵押")
    ws.cell(row=3, column=1, value="厂房B")
    ws.cell(row=3, column=2, value="800万")
    ws.cell(row=3, column=3, value="无")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestExcelE2E:
    """Excel 提取溯源端到端测试"""

    def test_full_chain(self):
        """测试完整链路：Excel → Anchor Markdown → segment_map → lookup → highlight"""
        from src.utils.excel_anchor_converter import ExcelAnchorConverter
        from src.utils.anchor_markdown_converter import AnchorMarkdownConverter
        from src.utils.excel_cell_highlighter import ExcelCellHighlighter

        file_bytes = create_test_excel()

        # Step 1: 转换
        markdown, segment_map, sheet_count = ExcelAnchorConverter.convert(file_bytes, "test.xlsx")
        assert sheet_count == 1
        assert len(segment_map) > 0

        # Step 2: 模拟 LLM 返回的 anchor_ids
        anchor_ids = ["0-1-1"]  # 1200万

        # Step 3: 查表
        bbox_infos = AnchorMarkdownConverter.lookup_bboxes_by_anchors(anchor_ids, segment_map)
        assert len(bbox_infos) == 1
        assert "page_idx" in bbox_infos[0]
        assert "bbox" in bbox_infos[0]

        # Step 4: 高亮渲染
        from src.services.llm.models import Region
        regions = [Region(
            page_idx=info["page_idx"],
            page_number=info["page_idx"] + 1,
            bbox=info["bbox"]
        ) for info in bbox_infos]

        img_bytes = ExcelCellHighlighter.render_highlight(
            file_bytes=file_bytes,
            sheet_idx=regions[0].page_idx,
            target_bboxes=[r.bbox for r in regions],
        )

        # 验证输出
        from PIL import Image
        img = Image.open(io.BytesIO(img_bytes))
        assert img.format == "PNG"
        assert img.size[0] > 0
        assert img.size[1] > 0

    def test_anchor_markdown_format(self):
        """验证生成的 Anchor Markdown 格式正确"""
        from src.utils.excel_anchor_converter import ExcelAnchorConverter

        file_bytes = create_test_excel()
        markdown, _, _ = ExcelAnchorConverter.convert(file_bytes, "test.xlsx")

        # 验证 Markdown 表格格式
        assert "| 资产名称" in markdown
        assert "|---------|" in markdown
        assert "(¶0-1-0)" in markdown  # 办公楼A
        assert "(¶0-1-1)" in markdown  # 1200万

    def test_segment_map_lookup(self):
        """验证 segment_map 查表正确"""
        from src.utils.excel_anchor_converter import ExcelAnchorConverter
        from src.utils.anchor_markdown_converter import AnchorMarkdownConverter

        file_bytes = create_test_excel()
        _, segment_map, _ = ExcelAnchorConverter.convert(file_bytes, "test.xlsx")

        # 查找 1200万
        bbox_infos = AnchorMarkdownConverter.lookup_bboxes_by_anchors(["0-1-1"], segment_map)
        assert len(bbox_infos) == 1
        info = bbox_infos[0]
        assert info["page_idx"] == 0
        assert len(info["bbox"]) == 4
        assert info["bbox"][2] > info["bbox"][0]  # 有效宽度
        assert info["bbox"][3] > info["bbox"][1]  # 有效高度
```

- [ ] **Step 2: 运行端到端测试**

Run: `cd d:/Project/bjs_luruzhushen && python -m pytest tests/test_excel_e2e.py -v`
Expected: 全部 PASS

- [ ] **Step 3: 提交**

```bash
git add tests/test_excel_e2e.py
git commit -m "test: Excel 提取溯源端到端验证测试"
```

---

### Task 7: 最终验证与清理

- [ ] **Step 1: 运行全部测试**

Run: `cd d:/Project/bjs_luruzhushen && python -m pytest tests/ -v --timeout=60`
Expected: 全部 PASS，无回归

- [ ] **Step 2: 检查 git 状态**

```bash
git status
git log --oneline -5
```

确认所有文件已提交，无遗漏。

- [ ] **Step 3: 更新设计文档状态**

将 `docs/superpowers/specs/2026-07-18-excel-extraction-tracing-design.md` 中的 `状态: 待审核` 改为 `状态: 已实现`。
