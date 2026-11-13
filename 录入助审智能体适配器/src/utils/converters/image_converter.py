"""
图片转 PDF 转换器

提供图片格式转换功能：
- 单张图片转 PDF
- 多张图片合并为一个 PDF
"""

from typing import List, Union
from io import BytesIO
from pathlib import Path
from loguru import logger
import img2pdf
from PIL import Image

from src.utils.exceptions import FileProcessingError


class ImageToPDFConverter:
    """图片转 PDF 转换器"""
    
    # 支持的图片格式
    SUPPORTED_FORMATS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.gif', '.webp'}
    
    @classmethod
    def convert_single_image(
        cls, 
        image_content: bytes,
        file_name: str = "image"
    ) -> bytes:
        """
        将单张图片转换为 PDF
        
        Args:
            image_content: 图片字节内容
            file_name: 文件名（用于日志）
            
        Returns:
            bytes: PDF 字节内容
            
        Raises:
            FileProcessingError: 转换失败时抛出
        """
        try:
            logger.info(f"转换图片为 PDF | 文件: {file_name} | 大小: {len(image_content)} 字节")
            
            # 使用 img2pdf 转换
            # 先验证图片格式
            with Image.open(BytesIO(image_content)) as img:
                # 如果是 RGBA 模式（如 PNG），转换为 RGB
                if img.mode in ('RGBA', 'LA', 'P'):
                    logger.info(f"转换图片模式: {img.mode} -> RGB")
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    
                    # 保存为 JPEG 格式
                    img_buffer = BytesIO()
                    rgb_img.save(img_buffer, format='JPEG', quality=95)
                    image_content = img_buffer.getvalue()
            
            # 转换为 PDF
            pdf_bytes = img2pdf.convert(image_content)
            
            logger.info(f"图片转 PDF 成功 | 文件: {file_name} | PDF 大小: {len(pdf_bytes)} 字节")
            return pdf_bytes
            
        except Exception as e:
            error_msg = f"图片转 PDF 失败 | 文件: {file_name} | 错误: {str(e)}"
            logger.error(error_msg)
            raise FileProcessingError(error_msg)
    
    @classmethod
    def merge_images_to_pdf(
        cls,
        image_contents: List[bytes],
        file_names: List[str] = None
    ) -> bytes:
        """
        将多张图片合并为一个 PDF
        
        Args:
            image_contents: 图片字节内容列表
            file_names: 文件名列表（用于日志，可选）
            
        Returns:
            bytes: 合并后的 PDF 字节内容
            
        Raises:
            FileProcessingError: 转换失败时抛出
        """
        if not image_contents:
            raise FileProcessingError("图片列表为空，无法生成 PDF")
        
        try:
            logger.info(f"合并 {len(image_contents)} 张图片为 PDF")
            
            # 预处理所有图片（处理 RGBA 等模式）
            processed_images = []
            for idx, img_content in enumerate(image_contents):
                file_name = file_names[idx] if file_names and idx < len(file_names) else f"image_{idx}"
                
                try:
                    with Image.open(BytesIO(img_content)) as img:
                        # 如果是 RGBA 模式，转换为 RGB
                        if img.mode in ('RGBA', 'LA', 'P'):
                            logger.info(f"转换图片模式 [{file_name}]: {img.mode} -> RGB")
                            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                            if img.mode == 'P':
                                img = img.convert('RGBA')
                            rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                            
                            # 保存为 JPEG
                            img_buffer = BytesIO()
                            rgb_img.save(img_buffer, format='JPEG', quality=95)
                            processed_images.append(img_buffer.getvalue())
                        else:
                            processed_images.append(img_content)
                            
                except Exception as e:
                    logger.warning(f"处理图片失败 [{file_name}]: {e}，跳过此图片")
                    continue
            
            if not processed_images:
                raise FileProcessingError("所有图片处理失败，无法生成 PDF")
            
            # 使用 img2pdf 合并为 PDF
            pdf_bytes = img2pdf.convert(processed_images)
            
            logger.info(f"图片合并 PDF 成功 | 图片数量: {len(processed_images)} | PDF 大小: {len(pdf_bytes)} 字节")
            return pdf_bytes
            
        except Exception as e:
            error_msg = f"合并图片为 PDF 失败: {str(e)}"
            logger.error(error_msg)
            raise FileProcessingError(error_msg)
    
    @classmethod
    def is_supported_format(cls, file_extension: str) -> bool:
        """
        检查文件格式是否支持转换
        
        Args:
            file_extension: 文件扩展名（带点，如 .jpg）
            
        Returns:
            bool: 是否支持
        """
        return file_extension.lower() in cls.SUPPORTED_FORMATS
    
    @classmethod
    def validate_image(cls, image_content: bytes) -> bool:
        """
        验证图片是否有效
        
        Args:
            image_content: 图片字节内容
            
        Returns:
            bool: 是否为有效图片
        """
        try:
            with Image.open(BytesIO(image_content)) as img:
                img.verify()
                return True
        except Exception as e:
            logger.warning(f"图片验证失败: {e}")
            return False



