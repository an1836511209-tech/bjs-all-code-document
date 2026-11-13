"""
PDF转换工具模块

提供PDF到图像的转换功能，支持：
1. PDF文件转为图像
2. 高质量渲染
3. 多页面处理
"""

import io
from typing import List, Union
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image
import numpy as np

from src.utils.exceptions import PDFConversionError


class PDFConverter:
    """PDF转换器，将PDF页面转换为图像"""
    
    # 默认DPI设置（影响图像质量）
    DEFAULT_DPI = 200
    
    # 支持的输出格式
    SUPPORTED_OUTPUT_FORMATS = {'PNG', 'JPEG', 'JPG'}
    
    @classmethod
    def convert_to_images(
        cls,
        pdf_content: Union[bytes, io.BytesIO, str],
        dpi: int = DEFAULT_DPI,
        output_format: str = 'PNG',
        max_pages: int = 10
    ) -> List[Image.Image]:
        """
        将PDF转换为图像列表
        
        Args:
            pdf_content: PDF内容（字节、文件对象或文件路径）
            dpi: 输出图像DPI，影响清晰度
            output_format: 输出格式（PNG/JPEG）
            max_pages: 最大处理页数
            
        Returns:
            List[Image.Image]: PIL图像对象列表
            
        Raises:
            PDFConversionError: PDF转换失败时抛出
        """
        if output_format.upper() not in cls.SUPPORTED_OUTPUT_FORMATS:
            raise PDFConversionError(f"不支持的输出格式: {output_format}")
            
        try:
            # 打开PDF文档
            if isinstance(pdf_content, str):
                # 文件路径
                doc = fitz.open(pdf_content)
            elif isinstance(pdf_content, (bytes, io.BytesIO)):
                # 二进制内容
                if isinstance(pdf_content, io.BytesIO):
                    pdf_bytes = pdf_content.getvalue()
                else:
                    pdf_bytes = pdf_content
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            else:
                raise PDFConversionError(f"不支持的PDF内容类型: {type(pdf_content)}")
            
            images = []
            page_count = min(len(doc), max_pages)
            
            for page_num in range(page_count):
                try:
                    page = doc.load_page(page_num)
                    
                    # 设置渲染参数
                    zoom = dpi / 72.0  # PyMuPDF使用72 DPI作为基准
                    mat = fitz.Matrix(zoom, zoom)
                    
                    # 渲染页面为图像
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    
                    # 转换为PIL Image
                    img_data = pix.tobytes("ppm")
                    img = Image.open(io.BytesIO(img_data))
                    
                    # 如果需要，转换为指定格式
                    if output_format.upper() == 'JPEG' and img.mode == 'RGBA':
                        # JPEG不支持透明度，转换为RGB
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                        img = background
                    
                    images.append(img)
                    
                except Exception as e:
                    # 单页转换失败，记录错误但继续处理其他页面
                    print(f"警告：第{page_num + 1}页转换失败: {str(e)}")
                    continue
                    
            doc.close()
            
            if not images:
                raise PDFConversionError("PDF转换失败：无法提取任何页面")
                
            return images
            
        except fitz.FileDataError as e:
            raise PDFConversionError(f"PDF文件损坏或格式不正确: {str(e)}")
        except Exception as e:
            raise PDFConversionError(f"PDF转换失败: {str(e)}")
    
    @classmethod
    def convert_first_page(
        cls,
        pdf_content: Union[bytes, io.BytesIO, str],
        dpi: int = DEFAULT_DPI,
        output_format: str = 'PNG'
    ) -> Image.Image:
        """
        仅转换PDF的第一页
        
        Args:
            pdf_content: PDF内容
            dpi: 输出图像DPI
            output_format: 输出格式
            
        Returns:
            Image.Image: 第一页的PIL图像对象
        """
        images = cls.convert_to_images(pdf_content, dpi, output_format, max_pages=1)
        if not images:
            raise PDFConversionError("无法转换PDF第一页")
        return images[0]
    
    @classmethod
    def convert_to_numpy_arrays(
        cls,
        pdf_content: Union[bytes, io.BytesIO, str],
        dpi: int = DEFAULT_DPI,
        max_pages: int = 10
    ) -> List[np.ndarray]:
        """
        将PDF转换为NumPy数组列表（适合OpenCV处理）
        
        Args:
            pdf_content: PDF内容
            dpi: 输出图像DPI
            max_pages: 最大处理页数
            
        Returns:
            List[np.ndarray]: NumPy数组列表，格式为BGR（OpenCV标准）
        """
        images = cls.convert_to_images(pdf_content, dpi, 'RGB', max_pages)
        numpy_arrays = []
        
        for img in images:
            # 转换PIL图像为NumPy数组
            img_array = np.array(img)
            
            # 如果是RGB，转换为BGR（OpenCV标准）
            if len(img_array.shape) == 3 and img_array.shape[2] == 3:
                img_array = img_array[:, :, ::-1]  # RGB -> BGR
                
            numpy_arrays.append(img_array)
            
        return numpy_arrays
    
    @classmethod
    def get_pdf_info(cls, pdf_content: Union[bytes, io.BytesIO, str]) -> dict:
        """
        获取PDF基本信息
        
        Args:
            pdf_content: PDF内容
            
        Returns:
            dict: PDF信息字典
        """
        try:
            # 打开PDF文档
            if isinstance(pdf_content, str):
                doc = fitz.open(pdf_content)
            elif isinstance(pdf_content, (bytes, io.BytesIO)):
                if isinstance(pdf_content, io.BytesIO):
                    pdf_bytes = pdf_content.getvalue()
                else:
                    pdf_bytes = pdf_content
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            else:
                raise PDFConversionError(f"不支持的PDF内容类型: {type(pdf_content)}")
            
            info = {
                'page_count': len(doc),
                'title': doc.metadata.get('title', ''),
                'author': doc.metadata.get('author', ''),
                'subject': doc.metadata.get('subject', ''),
                'creator': doc.metadata.get('creator', ''),
                'producer': doc.metadata.get('producer', ''),
                'creation_date': doc.metadata.get('creationDate', ''),
                'modification_date': doc.metadata.get('modDate', ''),
                'encrypted': doc.needs_pass,
            }
            
            # 获取第一页尺寸信息
            if len(doc) > 0:
                first_page = doc.load_page(0)
                rect = first_page.rect
                info.update({
                    'page_width': rect.width,
                    'page_height': rect.height,
                })
            
            doc.close()
            return info
            
        except Exception as e:
            raise PDFConversionError(f"获取PDF信息失败: {str(e)}")