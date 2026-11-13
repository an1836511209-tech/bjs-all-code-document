"""
Excel 单元格高亮渲染器

将 Excel sheet 渲染为 PNG 图片，并在指定单元格画高亮区域
用于溯源预览（与现有 PDFHighlighter 输出格式兼容）
"""

import io
import os
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from loguru import logger
from PIL import Image, ImageDraw, ImageFont
from src.utils.excel_offset_utils import (
    DEFAULT_COL_WIDTH, DEFAULT_ROW_HEIGHT, CHAR_WIDTH_PIXELS, POINT_TO_PIXELS,
    compute_col_offsets, compute_row_offsets,
)


class ExcelCellHighlighter:
    """Excel 单元格高亮渲染器"""

    _FONT_CACHE: Dict[int, ImageFont.FreeTypeFont] = {}

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

    @classmethod
    def render_highlight(
        cls,
        file_bytes: bytes,
        sheet_idx: int,
        target_bboxes: List[List[float]],
    ) -> bytes:
        """渲染单个 sheet 的高亮图（兼容旧接口）"""
        return cls.render_sheet_highlight(file_bytes, sheet_idx, target_bboxes)

    @classmethod
    def render_regions(
        cls,
        file_bytes_list: List[Optional[bytes]],
        regions: List[Dict],
    ) -> bytes:
        """
        按 file_index / sheet_idx 分组渲染高亮，多 sheet 或多文件时纵向拼接

        Args:
            file_bytes_list: 各 Excel 文件字节列表
            regions: [{page_idx, bbox, file_index?}, ...]
        """
        if not regions:
            return cls._render_error_image("无高亮区域")

        by_file: Dict[int, List[Dict]] = defaultdict(list)
        for region in regions:
            file_index = region.get("file_index")
            if file_index is None:
                file_index = 0
            by_file[file_index].append(region)

        images: List[Image.Image] = []
        for file_index in sorted(by_file.keys()):
            file_bytes = (
                file_bytes_list[file_index]
                if file_index < len(file_bytes_list)
                else None
            )
            if not file_bytes:
                logger.warning(f"Excel 高亮失败: file_index={file_index} 无 file_bytes")
                continue

            by_sheet: Dict[int, List[List[float]]] = defaultdict(list)
            for region in by_file[file_index]:
                sheet_idx = region.get("page_idx", 0)
                bbox = region.get("bbox")
                if bbox:
                    by_sheet[sheet_idx].append(bbox)

            for sheet_idx in sorted(by_sheet.keys()):
                png_bytes = cls.render_sheet_highlight(
                    file_bytes, sheet_idx, by_sheet[sheet_idx]
                )
                images.append(Image.open(io.BytesIO(png_bytes)).convert("RGB"))

        if not images:
            return cls._render_error_image("无法渲染任何高亮区域")

        if len(images) == 1:
            return cls._image_to_bytes(images[0])

        return cls._image_to_bytes(cls._stack_images_vertically(images))

    @classmethod
    def render_sheet_highlight(
        cls,
        file_bytes: bytes,
        sheet_idx: int,
        target_bboxes: List[List[float]],
    ) -> bytes:
        """渲染指定 sheet 为 PNG 图片，并在 target_bboxes 位置画高亮"""
        import openpyxl

        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        except Exception as e:
            logger.error(f"Excel 高亮渲染失败 - 文件打开错误: {e}")
            return cls._render_error_image(f"Excel 打开失败: {e}")

        try:
            sheet_names = wb.sheetnames
            if sheet_idx < 0 or sheet_idx >= len(sheet_names):
                logger.error(f"Sheet 索引 {sheet_idx} 超出范围（共 {len(sheet_names)} 个 sheet）")
                return cls._render_error_image(f"Sheet 索引 {sheet_idx} 超出范围")

            sheet = wb[sheet_names[sheet_idx]]
            crop_info = cls._calc_crop_range(sheet, target_bboxes)
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
        col_offsets = compute_col_offsets(sheet)
        row_offsets = compute_row_offsets(sheet)

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
        col_offsets = compute_col_offsets(sheet)
        row_offsets = compute_row_offsets(sheet)

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
            hl_draw.rectangle([bx0, by0, bx1, by1], fill=cls.HIGHLIGHT_COLOR + (cls.HIGHLIGHT_ALPHA,))
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
    def _image_to_bytes(cls, img: Image.Image) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    @classmethod
    def _stack_images_vertically(cls, images: List[Image.Image]) -> Image.Image:
        width = max(img.width for img in images)
        height = sum(img.height for img in images) + 10 * (len(images) - 1)
        canvas = Image.new("RGB", (width, height), cls.BG_COLOR)
        y = 0
        for img in images:
            canvas.paste(img, (0, y))
            y += img.height + 10
        return canvas

    @classmethod
    def _load_font(cls, size: int = None) -> ImageFont.FreeTypeFont:
        """加载支持中文的字体，回退到默认字体"""
        size = size or cls.FONT_SIZE
        if size in cls._FONT_CACHE:
            return cls._FONT_CACHE[size]

        font = cls._try_load_cjk_font(size)
        cls._FONT_CACHE[size] = font
        return font

    @classmethod
    def _try_load_cjk_font(cls, size: int) -> ImageFont.FreeTypeFont:
        project_root = Path(__file__).resolve().parents[2]
        candidates = [
            project_root / "assets" / "fonts" / "NotoSansSC-Regular.otf",
            project_root / "assets" / "fonts" / "NotoSansSC-Regular.ttf",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/simsun.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/arphic/uming.ttc",
        ]

        for candidate in candidates:
            font = cls._load_font_from_path(str(candidate), size)
            if font is not None:
                return font

        fc_match_path = cls._find_font_via_fontconfig()
        if fc_match_path:
            font = cls._load_font_from_path(fc_match_path, size)
            if font is not None:
                return font

        logger.warning("未找到中文字体，Excel 溯源图中文可能显示为乱码")
        return ImageFont.load_default()

    @classmethod
    def _load_font_from_path(cls, path: str, size: int) -> Optional[ImageFont.FreeTypeFont]:
        if not path or not os.path.isfile(path):
            return None

        for index in (0, 1, None):
            try:
                if index is None:
                    font = ImageFont.truetype(path, size)
                else:
                    font = ImageFont.truetype(path, size, index=index)
                logger.debug(f"Excel 高亮使用字体: {path}" + (f" (index={index})" if index is not None else ""))
                return font
            except (IOError, OSError):
                continue
        return None

    @classmethod
    def _find_font_via_fontconfig(cls) -> Optional[str]:
        """通过 fontconfig 查找可用的中文字体"""
        try:
            result = subprocess.run(
                ["fc-match", "-f", "%{file}", ":lang=zh"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None

        path = (result.stdout or "").strip()
        if result.returncode == 0 and path and os.path.isfile(path):
            return path
        return None

    @classmethod
    def _render_error_image(cls, error_msg: str) -> bytes:
        """渲染错误提示图片"""
        img = Image.new("RGB", (400, 100), (255, 240, 240))
        draw = ImageDraw.Draw(img)
        font = cls._load_font()
        if len(error_msg) > 50:
            error_msg = error_msg[:50] + "..."
        draw.text((10, 30), f"高亮渲染失败: {error_msg}", fill=(200, 0, 0), font=font)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
