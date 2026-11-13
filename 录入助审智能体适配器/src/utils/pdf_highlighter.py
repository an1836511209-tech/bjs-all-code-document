"""
PDF高亮工具模块

提供PDF页面区域高亮功能，支持：
1. 根据坐标在PDF页面上绘制高亮区域
2. 支持多个区域高亮
3. 上传到MinIO并返回URL
"""

import base64
import io
from pathlib import Path
from typing import List, Tuple, Union, Optional
from dataclasses import dataclass

import fitz  # PyMuPDF
import cv2
import numpy as np
from PIL import Image

from src.utils.exceptions import PDFConversionError
from src.utils.minio.client import get_minio_client, MinIOClientError


@dataclass
class BBox:
    """
    边界框坐标类
    
    Attributes:
        x0: 左上角X坐标
        y0: 左上角Y坐标
        x1: 右下角X坐标
        y1: 右下角Y坐标
    """
    x0: float
    y0: float
    x1: float
    y1: float
    
    @classmethod
    def from_list(cls, bbox_list: List[float]) -> 'BBox':
        """
        从列表创建BBox对象
        
        Args:
            bbox_list: 坐标列表 [x0, y0, x1, y1] 或 [x0, y0, x1, y1]
            
        Returns:
            BBox: 边界框对象
        """
        if len(bbox_list) != 4:
            raise ValueError(f"坐标列表必须包含4个元素，当前有 {len(bbox_list)} 个")
        return cls(bbox_list[0], bbox_list[1], bbox_list[2], bbox_list[3])
    
    @classmethod
    def from_dict(cls, bbox_dict: dict) -> 'BBox':
        """
        从字典创建BBox对象
        
        Args:
            bbox_dict: 坐标字典，支持多种格式：
                - {'x0': ..., 'y0': ..., 'x1': ..., 'y1': ...}
                - {'left': ..., 'top': ..., 'right': ..., 'bottom': ...}
                - {'x': ..., 'y': ..., 'width': ..., 'height': ...}
                
        Returns:
            BBox: 边界框对象
        """
        if all(k in bbox_dict for k in ['x0', 'y0', 'x1', 'y1']):
            return cls(bbox_dict['x0'], bbox_dict['y0'], bbox_dict['x1'], bbox_dict['y1'])
        elif all(k in bbox_dict for k in ['left', 'top', 'right', 'bottom']):
            return cls(bbox_dict['left'], bbox_dict['top'], bbox_dict['right'], bbox_dict['bottom'])
        elif all(k in bbox_dict for k in ['x', 'y', 'width', 'height']):
            x, y, w, h = bbox_dict['x'], bbox_dict['y'], bbox_dict['width'], bbox_dict['height']
            return cls(x, y, x + w, y + h)
        else:
            raise ValueError(f"不支持的坐标字典格式: {bbox_dict.keys()}")
    
    def to_tuple(self) -> Tuple[int, int, int, int]:
        """
        转换为整数元组 (x0, y0, x1, y1)
        
        Returns:
            Tuple[int, int, int, int]: 整数坐标元组
        """
        return (int(self.x0), int(self.y0), int(self.x1), int(self.y1))
    
    def width(self) -> float:
        """获取宽度"""
        return self.x1 - self.x0
    
    def height(self) -> float:
        """获取高度"""
        return self.y1 - self.y0


class PDFHighlighter:
    """PDF高亮器，用于在PDF页面上绘制高亮区域"""
    
    # 默认DPI设置
    DEFAULT_DPI = 200
    
    # 默认高亮颜色 (BGR格式)
    DEFAULT_HIGHLIGHT_COLOR = (0, 255, 255)  # 黄色
    
    # 默认高亮透明度 (0.0-1.0)
    DEFAULT_ALPHA = 0.3
    
    # 默认边框颜色 (BGR格式)
    DEFAULT_BORDER_COLOR = (0, 0, 255)  # 红色
    
    # 默认边框宽度
    DEFAULT_BORDER_WIDTH = 2
    
    @classmethod
    def highlight_pdf_regions(
        cls,
        pdf_path: Union[str, Path, bytes],
        page_num: int,
        bboxes: List[Union[List[float], dict, BBox]],
        dpi: int = DEFAULT_DPI,
        highlight_color: Tuple[int, int, int] = DEFAULT_HIGHLIGHT_COLOR,
        border_color: Tuple[int, int, int] = DEFAULT_BORDER_COLOR,
        alpha: float = DEFAULT_ALPHA,
        border_width: int = DEFAULT_BORDER_WIDTH,
        output_format: str = 'PNG'
    ) -> str:
        """
        在PDF页面上高亮指定区域，上传到MinIO并返回URL
        
        Args:
            pdf_path: PDF文件路径或字节内容
            page_num: 页码（从0开始）
            bboxes: 边界框列表，支持多种格式：
                - List[float]: [x0, y0, x1, y1]
                - dict: {'x0': ..., 'y0': ..., 'x1': ..., 'y1': ...}
                - BBox: BBox对象
            dpi: 渲染DPI，影响清晰度
            highlight_color: 高亮颜色 (B, G, R) 格式
            border_color: 边框颜色 (B, G, R) 格式
            alpha: 高亮透明度 (0.0-1.0)
            border_width: 边框宽度（像素）
            output_format: 输出格式 ('PNG' 或 'JPEG')
            
        Returns:
            str: MinIO上的图片访问URL
            
        Raises:
            PDFConversionError: PDF处理或上传失败时抛出
        """
        try:
            # 1. 打开PDF并获取指定页面
            doc = cls._open_pdf(pdf_path)
            
            if page_num < 0 or page_num >= len(doc):
                raise PDFConversionError(f"页码 {page_num} 超出范围（PDF共 {len(doc)} 页）")
            
            page = doc.load_page(page_num)
            
            # 2. 将PDF页面渲染为图片
            zoom = dpi / 72.0  # PyMuPDF使用72 DPI作为基准
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # 3. 转换为OpenCV格式 (numpy array)
            img_data = pix.tobytes("ppm")
            img_pil = Image.open(io.BytesIO(img_data))
            img_cv = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
            
            # 4. 解析并标准化所有边界框
            normalized_bboxes = cls._normalize_bboxes(bboxes)
            
            # 5. 在图像上绘制高亮区域
            highlighted_img = cls._draw_highlights(
                img_cv,
                normalized_bboxes,
                highlight_color,
                border_color,
                alpha,
                border_width,
                zoom
            )
            
            # 6. 上传到MinIO并获取URL
            url = cls._upload_to_minio(highlighted_img, output_format)
            
            doc.close()
            return url
            
        except fitz.FileDataError as e:
            raise PDFConversionError(f"PDF文件损坏或格式不正确: {str(e)}")
        except MinIOClientError as e:
            raise PDFConversionError(f"上传图片到MinIO失败: {str(e)}")
        except Exception as e:
            raise PDFConversionError(f"PDF高亮处理失败: {str(e)}")
    
    @classmethod
    def highlight_single_region(
        cls,
        pdf_path: Union[str, Path, bytes],
        page_num: int,
        bbox: Union[List[float], dict, BBox],
        **kwargs
    ) -> str:
        """
        在PDF页面上高亮单个区域的便捷方法
        
        Args:
            pdf_path: PDF文件路径或字节内容
            page_num: 页码（从0开始）
            bbox: 单个边界框
            **kwargs: 其他参数，参见 highlight_pdf_regions
            
        Returns:
            str: MinIO上的图片访问URL
        """
        return cls.highlight_pdf_regions(pdf_path, page_num, [bbox], **kwargs)
    
    @classmethod
    def generate_highlight_image(
        cls,
        pdf_path: Union[str, Path, bytes],
        page_num: int,
        bboxes: List[Union[List[float], dict, BBox]],
        dpi: int = DEFAULT_DPI,
        highlight_color: Tuple[int, int, int] = DEFAULT_HIGHLIGHT_COLOR,
        border_color: Tuple[int, int, int] = DEFAULT_BORDER_COLOR,
        alpha: float = DEFAULT_ALPHA,
        border_width: int = DEFAULT_BORDER_WIDTH,
        output_format: str = 'JPEG',
        jpeg_quality: int = 85
    ) -> Optional[bytes]:
        """
        生成高亮图片（不上传），返回图片字节数据
        
        用于批量生成后统一上传，减少网络往返次数
        
        Args:
            pdf_path: PDF文件路径或字节内容
            page_num: 页码（从0开始）
            bboxes: 边界框列表，支持多种格式
            dpi: 渲染DPI，影响清晰度
            highlight_color: 高亮颜色 (B, G, R) 格式
            border_color: 边框颜色 (B, G, R) 格式
            alpha: 高亮透明度 (0.0-1.0)
            border_width: 边框宽度（像素）
            output_format: 输出格式 'JPEG' 或 'PNG'（默认 JPEG，更快）
            jpeg_quality: JPEG 质量（1-100，默认 85）
            
        Returns:
            Optional[bytes]: 图片字节数据，失败返回 None
        """
        try:
            # 1. 打开PDF并获取指定页面
            doc = cls._open_pdf(pdf_path)
            
            if page_num < 0 or page_num >= len(doc):
                doc.close()
                return None
            
            page = doc.load_page(page_num)
            
            # 2. 将PDF页面渲染为图片
            zoom = dpi / 72.0  # PyMuPDF使用72 DPI作为基准
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # 3. 转换为OpenCV格式 (numpy array)
            img_data = pix.tobytes("ppm")
            img_pil = Image.open(io.BytesIO(img_data))
            img_cv = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
            
            # 4. 解析并标准化所有边界框
            normalized_bboxes = cls._normalize_bboxes(bboxes)
            
            # 5. 在图像上绘制高亮区域
            highlighted_img = cls._draw_highlights(
                img_cv,
                normalized_bboxes,
                highlight_color,
                border_color,
                alpha,
                border_width,
                zoom
            )
            
            doc.close()
            
            # 6. 转换为指定格式的字节
            img_rgb = cv2.cvtColor(highlighted_img, cv2.COLOR_BGR2RGB)
            img_pil_out = Image.fromarray(img_rgb)
            buffer = io.BytesIO()
            
            if output_format.upper() == 'JPEG':
                # JPEG 编码更快
                if img_pil_out.mode == 'RGBA':
                    img_pil_out = img_pil_out.convert('RGB')
                img_pil_out.save(buffer, format='JPEG', quality=jpeg_quality, optimize=False)
            else:
                # PNG 编码较慢但无损
                img_pil_out.save(buffer, format='PNG', optimize=False)
            
            return buffer.getvalue()
            
        except Exception as e:
            return None
    
    @classmethod
    def _open_pdf(cls, pdf_path: Union[str, Path, bytes]) -> fitz.Document:
        """
        打开PDF文档
        
        Args:
            pdf_path: PDF文件路径或字节内容
            
        Returns:
            fitz.Document: PDF文档对象
        """
        if isinstance(pdf_path, (str, Path)):
            return fitz.open(str(pdf_path))
        elif isinstance(pdf_path, bytes):
            return fitz.open(stream=pdf_path, filetype="pdf")
        else:
            raise PDFConversionError(f"不支持的PDF输入类型: {type(pdf_path)}")
    
    @classmethod
    def _normalize_bboxes(cls, bboxes: List[Union[List[float], dict, BBox]]) -> List[BBox]:
        """
        标准化边界框列表
        
        Args:
            bboxes: 各种格式的边界框列表
            
        Returns:
            List[BBox]: 标准化的BBox对象列表
        """
        normalized = []
        for bbox in bboxes:
            if isinstance(bbox, BBox):
                normalized.append(bbox)
            elif isinstance(bbox, list):
                normalized.append(BBox.from_list(bbox))
            elif isinstance(bbox, dict):
                normalized.append(BBox.from_dict(bbox))
            else:
                raise ValueError(f"不支持的边界框类型: {type(bbox)}")
        return normalized
    
    @classmethod
    def _draw_highlights(
        cls,
        img: np.ndarray,
        bboxes: List[BBox],
        highlight_color: Tuple[int, int, int],
        border_color: Tuple[int, int, int],
        alpha: float,
        border_width: int,
        zoom: float = 1.0
    ) -> np.ndarray:
        """
        在图像上绘制高亮区域
        
        Args:
            img: OpenCV图像 (BGR格式)
            bboxes: 边界框列表
            highlight_color: 高亮颜色
            border_color: 边框颜色
            alpha: 透明度
            border_width: 边框宽度
            zoom: 缩放比例（用于调整坐标）
            
        Returns:
            np.ndarray: 绘制后的图像
        """
        # 创建图像副本，避免修改原图
        result = img.copy()
        
        # 创建半透明覆盖层
        overlay = img.copy()
        
        for bbox in bboxes:
            # 应用缩放比例到坐标
            x0 = int(bbox.x0 * zoom)
            y0 = int(bbox.y0 * zoom)
            x1 = int(bbox.x1 * zoom)
            y1 = int(bbox.y1 * zoom)
            
            # 确保坐标在图像范围内
            h, w = img.shape[:2]
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(w, x1), min(h, y1)
            
            # 绘制半透明高亮区域
            cv2.rectangle(overlay, (x0, y0), (x1, y1), highlight_color, -1)
            
            # 绘制边框
            cv2.rectangle(result, (x0, y0), (x1, y1), border_color, border_width)
        
        # 混合原图和覆盖层，实现半透明效果
        cv2.addWeighted(overlay, alpha, result, 1 - alpha, 0, result)
        
        return result
    
    @classmethod
    def _upload_to_minio(cls, img: np.ndarray, output_format: str = 'PNG', expires_days: int = 7) -> str:
        """
        将OpenCV图像上传到MinIO并返回URL
        
        Args:
            img: OpenCV图像 (BGR格式)
            output_format: 输出格式 ('PNG' 或 'JPEG')
            expires_days: 过期天数，默认7天后自动删除
            
        Returns:
            str: MinIO上的图片访问URL
            
        Raises:
            MinIOClientError: 上传失败时抛出
        """
        # 转换为PIL Image
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img_pil = Image.fromarray(img_rgb)
        
        # 编码为指定格式
        buffer = io.BytesIO()
        if output_format.upper() == 'JPEG':
            # JPEG不支持透明度
            if img_pil.mode == 'RGBA':
                img_pil = img_pil.convert('RGB')
            img_pil.save(buffer, format='JPEG', quality=95)
            content_type = 'image/jpeg'
        else:
            img_pil.save(buffer, format='PNG')
            content_type = 'image/png'
        
        # 上传到MinIO，设置过期时间
        buffer.seek(0)
        img_bytes = buffer.getvalue()
        
        minio_client = get_minio_client()
        url = minio_client.upload_bytes(
            data=img_bytes,
            content_type=content_type,
            expires_days=expires_days  # 设置过期天数
        )
        
        return url
    
    @classmethod
    def _image_to_base64(cls, img: np.ndarray, output_format: str = 'PNG') -> str:
        """
        将OpenCV图像转换为base64编码（保留用于向后兼容）
        
        Args:
            img: OpenCV图像 (BGR格式)
            output_format: 输出格式 ('PNG' 或 'JPEG')
            
        Returns:
            str: base64编码的图片字符串
        """
        # 转换为PIL Image
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img_pil = Image.fromarray(img_rgb)
        
        # 编码为指定格式
        buffer = io.BytesIO()
        if output_format.upper() == 'JPEG':
            # JPEG不支持透明度
            if img_pil.mode == 'RGBA':
                img_pil = img_pil.convert('RGB')
            img_pil.save(buffer, format='JPEG', quality=95)
        else:
            img_pil.save(buffer, format='PNG')
        
        # 转换为base64
        buffer.seek(0)
        img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        return img_base64
    
    @classmethod
    def get_page_dimensions(
        cls,
        pdf_path: Union[str, Path, bytes],
        page_num: int
    ) -> Tuple[float, float]:
        """
        获取PDF页面的尺寸
        
        Args:
            pdf_path: PDF文件路径或字节内容
            page_num: 页码（从0开始）
            
        Returns:
            Tuple[float, float]: (宽度, 高度) 单位为点（1/72英寸）
        """
        try:
            doc = cls._open_pdf(pdf_path)
            
            if page_num < 0 or page_num >= len(doc):
                raise PDFConversionError(f"页码 {page_num} 超出范围（PDF共 {len(doc)} 页）")
            
            page = doc.load_page(page_num)
            rect = page.rect
            
            doc.close()
            return (rect.width, rect.height)
            
        except Exception as e:
            raise PDFConversionError(f"获取页面尺寸失败: {str(e)}")


# 便捷函数
def highlight_pdf_page(
    pdf_path: Union[str, Path, bytes],
    page_num: int,
    regions: List[Union[List[float], dict]],
    **kwargs
) -> str:
    """
    便捷函数：在PDF页面上高亮指定区域并上传到MinIO
    
    Args:
        pdf_path: PDF文件路径或字节内容
        page_num: 页码（从0开始）
        regions: 区域列表，每个区域可以是：
            - [x0, y0, x1, y1] 列表
            - {'x0': ..., 'y0': ..., 'x1': ..., 'y1': ...} 字典
        **kwargs: 其他可选参数
            - dpi: 渲染DPI（默认200）
            - highlight_color: 高亮颜色，BGR格式（默认黄色）
            - border_color: 边框颜色，BGR格式（默认红色）
            - alpha: 透明度 0.0-1.0（默认0.3）
            - border_width: 边框宽度（默认2）
            - output_format: 输出格式 'PNG'/'JPEG'（默认PNG）
    
    Returns:
        str: MinIO上的图片访问URL
        
    Example:
        >>> # 示例1：使用列表格式的坐标
        >>> img_url = highlight_pdf_page(
        ...     "document.pdf",
        ...     0,
        ...     [[100, 100, 300, 200], [150, 250, 350, 350]]
        ... )
        
        >>> # 示例2：使用字典格式的坐标
        >>> img_url = highlight_pdf_page(
        ...     "document.pdf",
        ...     1,
        ...     [{'x0': 100, 'y0': 100, 'x1': 300, 'y1': 200}],
        ...     highlight_color=(255, 0, 0),  # 蓝色高亮
        ...     alpha=0.5
        ... )
        
        >>> # 示例3：MinerU格式的坐标
        >>> mineru_bbox = {'x': 100, 'y': 100, 'width': 200, 'height': 100}
        >>> img_url = highlight_pdf_page(
        ...     pdf_bytes,
        ...     0,
        ...     [mineru_bbox]
        ... )
    """
    return PDFHighlighter.highlight_pdf_regions(pdf_path, page_num, regions, **kwargs)

