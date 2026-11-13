"""
PDF 文本层坐标检索（与 Paddle 144 DPI 像素坐标对齐）

Paddle OCR 在遗漏表格字段时通常不会产生对应 layout_block，故无 bbox。
本模块从 PDF 内置文本层用 PyMuPDF 定位文字，并转换为 PaddlePDFHighlighter 使用的
144 DPI 像素坐标，使文本层补全片段的高亮与 OCR 块级高亮同一套坐标系。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Union

from loguru import logger

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None  # type: ignore

# 与 PaddlePDFHighlighter.PADDLE_DPI 一致：144 DPI 相对 PDF 点（72 DPI）缩放
PADDLE_DPI_SCALE = 144.0 / 72.0


@dataclass(frozen=True)
class TextLayerBBoxHit:
    """文本层检索命中"""

    page_idx: int
    bbox: List[float]  # [x0, y0, x1, y1] @ 144 DPI 像素
    matched_query: str


def pdf_rect_to_paddle_bbox(rect: "fitz.Rect") -> List[float]:
    """PDF 点坐标 -> Paddle 144 DPI 像素坐标"""
    return [
        float(rect.x0) * PADDLE_DPI_SCALE,
        float(rect.y0) * PADDLE_DPI_SCALE,
        float(rect.x1) * PADDLE_DPI_SCALE,
        float(rect.y1) * PADDLE_DPI_SCALE,
    ]


def get_page_paddle_bbox(doc: "fitz.Document", page_idx: int) -> Optional[List[float]]:
    """
    返回 PDF 指定页的整页 bbox（144 DPI 像素，与 Paddle 高亮坐标系一致）

    用于文本层补全溯源：补全内容来自 OCR 遗漏的文本层，精确字级 bbox 易偏，
    整页高亮更符合「请用户在 PDF 该页核对」的交互预期。
    """
    if fitz is None or doc is None:
        return None
    if page_idx < 0 or page_idx >= doc.page_count:
        return None
    try:
        return pdf_rect_to_paddle_bbox(doc[page_idx].rect)
    except Exception as e:
        logger.warning(f"获取页 {page_idx} 整页 bbox 失败: {e}")
        return None


def merge_paddle_bboxes(bboxes: Sequence[List[float]]) -> Optional[List[float]]:
    """合并多个 Paddle 像素 bbox"""
    valid = [b for b in bboxes if b and len(b) == 4]
    if not valid:
        return None
    x0 = min(b[0] for b in valid)
    y0 = min(b[1] for b in valid)
    x1 = max(b[2] for b in valid)
    y1 = max(b[3] for b in valid)
    if x1 <= x0 or y1 <= y0:
        return None
    return [x0, y0, x1, y1]


def _search_queries_for_line(line: str) -> List[str]:
    """生成用于 page.search_for 的候选串（从长到短）"""
    stripped = re.sub(r"\s+", " ", line.strip())
    if not stripped:
        return []

    queries: List[str] = []
    seen: set = set()

    def add(q: str) -> None:
        q = q.strip()
        if len(q) < 2 or q in seen:
            return
        seen.add(q)
        queries.append(q)

    add(stripped)

    # 字段行「标签：值」优先搜值
    if "：" in stripped:
        add(stripped.split("：", 1)[-1].strip())
    if ":" in stripped:
        add(stripped.split(":", 1)[-1].strip())

    # 标的基本信息-机械设备名称：... 取后半段
    if stripped.startswith("标的基本信息-"):
        body = stripped[len("标的基本信息-") :]
        add(body)
        if "：" in body:
            add(body.split("：", 1)[-1].strip())

    # 较长文本增加子串，提高拆行 PDF 命中率
    for q in list(queries):
        if len(q) > 24:
            add(q[:24])
        if len(q) > 12:
            add(q[:12])

    queries.sort(key=len, reverse=True)
    return queries


def find_text_bbox_on_page(
    page: "fitz.Page",
    text: str,
) -> Optional[List[float]]:
    """在单页内搜索文本，返回 Paddle 像素 bbox"""
    if fitz is None or not text:
        return None

    for query in _search_queries_for_line(text):
        try:
            rects = page.search_for(query)
        except Exception:
            rects = []
        if not rects:
            continue
        paddle_boxes = [pdf_rect_to_paddle_bbox(r) for r in rects]
        merged = merge_paddle_bboxes(paddle_boxes)
        if merged:
            return merged
    return None


def find_text_bbox_in_document(
    doc: "fitz.Document",
    text: str,
    preferred_page_idx: Optional[int] = None,
    page_range: Optional[Sequence[int]] = None,
) -> Optional[TextLayerBBoxHit]:
    """
    在文档中定位文本，优先 preferred_page_idx，再搜索 page_range 或全文
    """
    if fitz is None or not text:
        return None

    indices: List[int]
    if page_range is not None:
        indices = list(page_range)
    else:
        indices = list(range(doc.page_count))

    if preferred_page_idx is not None and preferred_page_idx in indices:
        ordered = [preferred_page_idx] + [i for i in indices if i != preferred_page_idx]
    else:
        ordered = indices

    queries = _search_queries_for_line(text)
    for page_idx in ordered:
        if page_idx < 0 or page_idx >= doc.page_count:
            continue
        page = doc[page_idx]
        for query in queries:
            try:
                rects = page.search_for(query)
            except Exception:
                rects = []
            if not rects:
                continue
            merged = merge_paddle_bboxes([pdf_rect_to_paddle_bbox(r) for r in rects])
            if merged:
                return TextLayerBBoxHit(
                    page_idx=page_idx,
                    bbox=merged,
                    matched_query=query,
                )
    return None


def open_pdf_document(pdf_bytes: bytes) -> Optional["fitz.Document"]:
    if fitz is None or not pdf_bytes:
        return None
    try:
        return fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.warning(f"打开 PDF 用于文本层坐标检索失败: {e}")
        return None
