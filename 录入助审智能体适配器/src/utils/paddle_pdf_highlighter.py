"""
Paddle OCR 专用 PDF 高亮工具

核心设计理念：
1. 使用与 Paddle OCR 完全相同的 144 DPI 渲染 PDF
2. 直接使用 Paddle 返回的像素坐标（经旋转逆变换后绘制）
3. PDF 以原生方向渲染（便于阅读），bbox 从 Paddle 矫正坐标系映射回直渲坐标系

坐标说明：
- Paddle OCR 返回：144 DPI 下、方向矫正后图像中的像素坐标
- 本高亮器：144 DPI 直渲 PDF；angle≠0 时对 bbox 做逆变换后再高亮

旋转说明：
- doc_preprocessor_res.angle：相对正常阅读方向逆时针偏转的角度
- Paddle 内部对输入图做 prerotate(-angle) 后 OCR，bbox 在矫正后坐标系
- 高亮时保持 PDF 直渲，将 bbox 从矫正坐标系逆映射到直渲像素坐标
"""

import io
import hashlib
import threading
from pathlib import Path
from typing import List, Tuple, Union, Optional, Dict

import fitz  # PyMuPDF
import cv2
import numpy as np
from PIL import Image
from loguru import logger

from src.utils.exceptions import PDFConversionError
from src.utils.minio.client import get_minio_client, MinIOClientError


# PDF 文档缓存（线程安全）
_pdf_cache: Dict[str, fitz.Document] = {}
_pdf_cache_lock = threading.Lock()
_MAX_CACHE_SIZE = 10  # 最多缓存 10 个 PDF 文档


def _get_pdf_cache_key(pdf_path: Union[str, Path, bytes]) -> str:
    """生成 PDF 缓存键"""
    if isinstance(pdf_path, bytes):
        return hashlib.md5(pdf_path[:1024]).hexdigest()
    return str(pdf_path)


def _get_cached_pdf(pdf_path: Union[str, Path, bytes]) -> fitz.Document:
    """获取缓存的 PDF 文档，如果不存在则打开并缓存"""
    cache_key = _get_pdf_cache_key(pdf_path)

    with _pdf_cache_lock:
        if cache_key in _pdf_cache:
            return _pdf_cache[cache_key]

        if len(_pdf_cache) >= _MAX_CACHE_SIZE:
            oldest_key = next(iter(_pdf_cache))
            try:
                _pdf_cache[oldest_key].close()
            except Exception:
                pass
            del _pdf_cache[oldest_key]

        if isinstance(pdf_path, (str, Path)):
            doc = fitz.open(str(pdf_path))
        elif isinstance(pdf_path, bytes):
            doc = fitz.open(stream=pdf_path, filetype="pdf")
        else:
            raise PDFConversionError(f"不支持的 PDF 输入类型: {type(pdf_path)}")

        _pdf_cache[cache_key] = doc
        return doc


def clear_pdf_cache():
    """清理 PDF 缓存"""
    with _pdf_cache_lock:
        for doc in _pdf_cache.values():
            try:
                doc.close()
            except Exception:
                pass
        _pdf_cache.clear()
        logger.debug("PDF 缓存已清理")


class PaddlePDFHighlighter:
    """Paddle OCR 专用 PDF 高亮器（144 DPI，像素坐标）"""

    PADDLE_DPI = 144

    DEFAULT_HIGHLIGHT_COLOR = (0, 255, 255)
    DEFAULT_BORDER_COLOR = (0, 0, 255)
    DEFAULT_ALPHA = 0.3
    DEFAULT_BORDER_WIDTH = 2

    @staticmethod
    def normalize_rotation_angle(rotation_angle: int) -> int:
        """将 Paddle 返回的旋转角度规范到 [0, 360)。"""
        return int(rotation_angle or 0) % 360

    @classmethod
    def correction_angle_for_paddle(cls, rotation_angle: int) -> int:
        """PDF 直渲矩阵不叠加 OCR angle（保持原生阅读方向）。"""
        _ = cls.normalize_rotation_angle(rotation_angle)
        return 0

    @classmethod
    def build_render_matrix(cls, rotation_angle: int = 0) -> fitz.Matrix:
        """构建 144 DPI 直渲矩阵。"""
        zoom = cls.PADDLE_DPI / 72.0
        mat = fitz.Matrix(zoom, zoom)
        correction = cls.correction_angle_for_paddle(rotation_angle)
        if correction != 0:
            mat = mat.prerotate(correction)
        return mat

    @classmethod
    def transform_bbox_paddle_to_native(
        cls,
        bbox: List[float],
        native_width: int,
        native_height: int,
        rotation_angle: int,
    ) -> List[float]:
        """
        将 Paddle 矫正坐标系下的 bbox 映射到 PDF 144 DPI 直渲像素坐标。

        Paddle 对输入图做 prerotate(-angle) 后 OCR，逆变换公式（逐顶点）：
        - 180°: (xn, yn) = (W - xc, H - yc)
        -  90°: (xn, yn) = (W - yc, xc)
        - 270°: (xn, yn) = (yc, H - xc)
        """
        angle = cls.normalize_rotation_angle(rotation_angle)
        if angle == 0 or len(bbox) != 4:
            return list(bbox)

        x0, y0, x1, y1 = bbox
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        w, h = native_width, native_height
        mapped: List[Tuple[float, float]] = []

        for xc, yc in corners:
            if angle == 180:
                mapped.append((w - xc, h - yc))
            elif angle == 90:
                mapped.append((w - yc, xc))
            elif angle == 270:
                mapped.append((yc, h - xc))
            else:
                logger.warning(f"不支持的 Paddle 旋转角度: {angle}°，bbox 未变换")
                return list(bbox)

        xs = [p[0] for p in mapped]
        ys = [p[1] for p in mapped]
        return [min(xs), min(ys), max(xs), max(ys)]

    @classmethod
    def transform_bboxes_paddle_to_native(
        cls,
        bboxes: List[List[float]],
        native_width: int,
        native_height: int,
        rotation_angle: int,
    ) -> List[List[float]]:
        """批量将 bbox 从 Paddle 矫正坐标系映射到直渲坐标系。"""
        return [
            cls.transform_bbox_paddle_to_native(b, native_width, native_height, rotation_angle)
            for b in bboxes
        ]

    @classmethod
    def _render_page_bgr(
        cls, page: fitz.Page, rotation_angle: int = 0
    ) -> Tuple[np.ndarray, fitz.Pixmap]:
        """将 PDF 页渲染为 OpenCV BGR 图像（144 DPI 直渲）。"""
        mat = cls.build_render_matrix(rotation_angle)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_data = pix.tobytes("ppm")
        img_pil = Image.open(io.BytesIO(img_data))
        img_cv = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
        return img_cv, pix

    @classmethod
    def _log_rotation_correction(cls, page_num: int, rotation_angle: int) -> None:
        """记录旋转/bbox 变换信息。"""
        detected = cls.normalize_rotation_angle(rotation_angle)
        if detected == 0:
            logger.debug(f"[高亮器] PDF 直渲 | 页面: {page_num} | ocr_angle=0")
            return
        logger.info(
            f"[高亮器] PDF 直渲 + bbox 逆变换 | 页面: {page_num} | "
            f"ocr_angle={detected}° | prerotate=0°"
        )

    @classmethod
    def highlight_single_region(
        cls,
        pdf_path: Union[str, Path, bytes],
        page_num: int,
        bbox: List[float],
        rotation_angle: int = 0,
        **kwargs
    ) -> str:
        return cls.highlight_pdf_regions(
            pdf_path, page_num, [bbox], rotation_angle=rotation_angle, **kwargs
        )

    @classmethod
    def generate_highlight_image(
        cls,
        pdf_path: Union[str, Path, bytes],
        page_num: int,
        bboxes: List[List[float]],
        highlight_color: Tuple[int, int, int] = DEFAULT_HIGHLIGHT_COLOR,
        border_color: Tuple[int, int, int] = DEFAULT_BORDER_COLOR,
        alpha: float = DEFAULT_ALPHA,
        border_width: int = DEFAULT_BORDER_WIDTH,
        use_cache: bool = True,
        output_format: str = 'JPEG',
        jpeg_quality: int = 85,
        rotation_angle: int = 0
    ) -> Optional[bytes]:
        try:
            if use_cache:
                doc = _get_cached_pdf(pdf_path)
            else:
                doc = cls._open_pdf(pdf_path)

            if page_num < 0 or page_num >= len(doc):
                logger.error(f"页码 {page_num} 超出范围（PDF 共 {len(doc)} 页）")
                return None

            page = doc.load_page(page_num)
            cls._log_rotation_correction(page_num, rotation_angle)
            img_cv, pix = cls._render_page_bgr(page, rotation_angle)

            draw_bboxes = cls.transform_bboxes_paddle_to_native(
                bboxes, pix.width, pix.height, rotation_angle
            )
            logger.debug(
                f"[高亮器] 渲染: {pix.width}x{pix.height} px | "
                f"ocr_angle={rotation_angle}° | bbox 数: {len(bboxes)}"
            )

            highlighted_img = cls._draw_highlights(
                img_cv, draw_bboxes, highlight_color, border_color, alpha, border_width
            )

            if not use_cache:
                doc.close()

            img_rgb = cv2.cvtColor(highlighted_img, cv2.COLOR_BGR2RGB)
            img_pil = Image.fromarray(img_rgb)
            buffer = io.BytesIO()

            if output_format.upper() == 'JPEG':
                img_pil.save(buffer, format='JPEG', quality=jpeg_quality, optimize=False)
            else:
                img_pil.save(buffer, format='PNG', optimize=False)

            return buffer.getvalue()

        except Exception as e:
            logger.error(f"生成高亮图片失败: {e}")
            return None

    @classmethod
    def highlight_pdf_regions(
        cls,
        pdf_path: Union[str, Path, bytes],
        page_num: int,
        bboxes: List[List[float]],
        highlight_color: Tuple[int, int, int] = DEFAULT_HIGHLIGHT_COLOR,
        border_color: Tuple[int, int, int] = DEFAULT_BORDER_COLOR,
        alpha: float = DEFAULT_ALPHA,
        border_width: int = DEFAULT_BORDER_WIDTH,
        output_format: str = 'PNG',
        rotation_angle: int = 0
    ) -> str:
        try:
            doc = cls._open_pdf(pdf_path)

            if page_num < 0 or page_num >= len(doc):
                raise PDFConversionError(
                    f"页码 {page_num} 超出范围（PDF 共 {len(doc)} 页）"
                )

            page = doc.load_page(page_num)
            cls._log_rotation_correction(page_num, rotation_angle)
            img_cv, pix = cls._render_page_bgr(page, rotation_angle)

            draw_bboxes = cls.transform_bboxes_paddle_to_native(
                bboxes, pix.width, pix.height, rotation_angle
            )

            detected = cls.normalize_rotation_angle(rotation_angle)
            rotation_info = f" | ocr_angle: {detected}°" if detected != 0 else ""
            logger.info(
                f"Paddle 高亮 | 页面: {page_num} | "
                f"DPI: {cls.PADDLE_DPI} | "
                f"图像: {pix.width}x{pix.height} px | "
                f"区域: {len(bboxes)}{rotation_info}"
            )

            highlighted_img = cls._draw_highlights(
                img_cv, draw_bboxes, highlight_color, border_color, alpha, border_width
            )

            url = cls._upload_to_minio(highlighted_img, output_format)
            doc.close()

            logger.info(f"Paddle 高亮成功 | URL: {url[:60]}...")
            return url

        except fitz.FileDataError as e:
            raise PDFConversionError(f"PDF 文件损坏或格式不正确: {str(e)}")
        except MinIOClientError as e:
            raise PDFConversionError(f"上传图片到 MinIO 失败: {str(e)}")
        except Exception as e:
            logger.error(f"Paddle 高亮处理失败: {e}", exc_info=True)
            raise PDFConversionError(f"高亮处理失败: {str(e)}")

    @classmethod
    def _open_pdf(cls, pdf_path: Union[str, Path, bytes]) -> fitz.Document:
        if isinstance(pdf_path, (str, Path)):
            return fitz.open(str(pdf_path))
        if isinstance(pdf_path, bytes):
            return fitz.open(stream=pdf_path, filetype="pdf")
        raise PDFConversionError(f"不支持的 PDF 输入类型: {type(pdf_path)}")

    @classmethod
    def _draw_highlights(
        cls,
        img: np.ndarray,
        bboxes: List[List[float]],
        highlight_color: Tuple[int, int, int],
        border_color: Tuple[int, int, int],
        alpha: float,
        border_width: int
    ) -> np.ndarray:
        result = img.copy()
        overlay = img.copy()
        h, w = img.shape[:2]

        for idx, bbox in enumerate(bboxes):
            if len(bbox) != 4:
                logger.warning(f"跳过无效 bbox[{idx}]: {bbox}（长度应为 4）")
                continue

            x0_px = int(round(bbox[0]))
            y0_px = int(round(bbox[1]))
            x1_px = int(round(bbox[2]))
            y1_px = int(round(bbox[3]))

            x0_px = max(0, min(x0_px, w))
            y0_px = max(0, min(y0_px, h))
            x1_px = max(0, min(x1_px, w))
            y1_px = max(0, min(y1_px, h))

            if x1_px <= x0_px or y1_px <= y0_px:
                logger.warning(
                    f"跳过无效区域[{idx}]: [{x0_px}, {y0_px}, {x1_px}, {y1_px}]"
                )
                continue

            logger.debug(
                f"绘制高亮[{idx}] | 像素: [{x0_px}, {y0_px}, {x1_px}, {y1_px}] | "
                f"尺寸: {x1_px - x0_px}x{y1_px - y0_px} px"
            )

            cv2.rectangle(overlay, (x0_px, y0_px), (x1_px, y1_px), highlight_color, -1)
            cv2.rectangle(result, (x0_px, y0_px), (x1_px, y1_px), border_color, border_width)

        cv2.addWeighted(overlay, alpha, result, 1 - alpha, 0, result)
        return result

    @classmethod
    def _upload_to_minio(
        cls,
        img: np.ndarray,
        output_format: str = 'PNG',
        expires_days: int = 7
    ) -> str:
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img_pil = Image.fromarray(img_rgb)

        buffer = io.BytesIO()
        if output_format.upper() == 'JPEG':
            if img_pil.mode == 'RGBA':
                img_pil = img_pil.convert('RGB')
            img_pil.save(buffer, format='JPEG', quality=95)
            content_type = 'image/jpeg'
        else:
            img_pil.save(buffer, format='PNG')
            content_type = 'image/png'

        buffer.seek(0)
        minio_client = get_minio_client()
        return minio_client.upload_bytes(
            data=buffer.getvalue(),
            content_type=content_type,
            expires_days=expires_days
        )


def highlight_paddle_pdf(
    pdf_path: Union[str, Path, bytes],
    page_num: int,
    regions: List[List[float]],
    rotation_angle: int = 0,
    **kwargs
) -> str:
    return PaddlePDFHighlighter.highlight_pdf_regions(
        pdf_path, page_num, regions, rotation_angle=rotation_angle, **kwargs
    )
