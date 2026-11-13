"""
Excel 偏移量计算工具

提供单元格像素偏移量的预计算，供锚点转换器和高亮渲染器共用，
避免两处各自维护一套相同的常量和计算逻辑。
"""

from typing import List
from openpyxl.utils import get_column_letter

# 默认列宽（字符单位）和行高（磅），当 openpyxl 读不到时使用
DEFAULT_COL_WIDTH = 8.43
DEFAULT_ROW_HEIGHT = 15.0

# 列宽字符单位到像素的换算系数
CHAR_WIDTH_PIXELS = 7
# 行高磅到像素的换算系数 (1磅 = 96/72 像素)
POINT_TO_PIXELS = 96 / 72


def compute_col_offsets(sheet) -> List[float]:
    """计算每列的 x 起始像素偏移"""
    offsets = [0.0]
    max_col = sheet.max_column or 1
    for c in range(max_col):
        try:
            w = sheet.column_dimensions[get_column_letter(c + 1)].width
        except Exception:
            w = None
        width_px = (w or DEFAULT_COL_WIDTH) * CHAR_WIDTH_PIXELS
        offsets.append(offsets[-1] + width_px)
    return offsets


def compute_row_offsets(sheet) -> List[float]:
    """计算每行的 y 起始像素偏移"""
    offsets = [0.0]
    max_row = sheet.max_row or 1
    for r in range(max_row):
        try:
            h = sheet.row_dimensions[r + 1].height
        except Exception:
            h = None
        height_px = (h or DEFAULT_ROW_HEIGHT) * POINT_TO_PIXELS
        offsets.append(offsets[-1] + height_px)
    return offsets
