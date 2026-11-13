"""
Word 转 PDF 转换器

使用 Gotenberg API 服务将 Word 文档转换为 PDF 格式，用于溯源和高亮功能。
Gotenberg 是基于 Docker 的文档转换服务，支持跨平台使用。
官网: https://gotenberg.dev/
"""

import asyncio
from pathlib import Path
from typing import Union
from loguru import logger

from src.services.gotenberg.client import GotenbergClient


class WordToPDFConverter:
    """Word 转 PDF 转换器（使用 Gotenberg API）"""
    
    @classmethod
    def is_available(cls) -> bool:
        """
        检查转换器是否可用
        
        Returns:
            bool: Gotenberg 服务是否可用
        """
        try:
            client = GotenbergClient()
            return client.is_available()
        except Exception as e:
            logger.warning(f"检查 Gotenberg 服务可用性失败: {e}")
            return False
    
    @classmethod
    async def convert_to_pdf_async(
        cls,
        word_content: bytes,
        file_name: str = "document.docx"
    ) -> bytes:
        """
        将 Word 文档转换为 PDF（异步方法）
        
        使用 Gotenberg API 服务进行转换，支持跨平台使用。
        
        Args:
            word_content: Word 文档的二进制内容
            file_name: 文件名（用于识别文件类型）
            
        Returns:
            bytes: 转换后的 PDF 文件内容
            
        Raises:
            RuntimeError: 如果 Gotenberg 服务不可用或转换失败
        """
        # 获取文件扩展名
        file_extension = Path(file_name).suffix.lower()
        if file_extension not in ['.doc', '.docx', '.dot', '.dotx', '.word']:
            raise ValueError(f"不支持的 Word 格式: {file_extension}")
        
        try:
            logger.info(f"开始使用 Gotenberg 转换 Word 文档为 PDF: {file_name}")
            
            # 使用 Gotenberg 客户端转换
            client = GotenbergClient()
            pdf_content = await client.convert_word_to_pdf(
                word_content=word_content,
                file_name=file_name
            )
            
            logger.info(f"Word 文档转换成功，PDF 大小: {len(pdf_content)} 字节")
            
            return pdf_content
            
        except Exception as e:
            logger.error(f"Word 转 PDF 失败: {e}", exc_info=True)
            raise RuntimeError(f"Word 转 PDF 失败: {str(e)}")
    
    @classmethod
    def convert_to_pdf(
        cls,
        word_content: bytes,
        file_name: str = "document.docx"
    ) -> bytes:
        """
        将 Word 文档转换为 PDF（同步方法）
        
        这是一个同步包装器，内部调用异步方法。
        推荐在异步环境中直接使用 convert_to_pdf_async。
        
        Args:
            word_content: Word 文档的二进制内容
            file_name: 文件名（用于识别文件类型）
            
        Returns:
            bytes: 转换后的 PDF 文件内容
            
        Raises:
            RuntimeError: 如果 Gotenberg 服务不可用或转换失败
        """
        # 在同步环境中运行异步方法
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(
            cls.convert_to_pdf_async(word_content, file_name)
        )
    
    @classmethod
    async def convert_file_to_pdf_async(
        cls,
        word_path: str,
        output_path: str = None
    ) -> str:
        """
        将 Word 文件转换为 PDF 文件（异步方法）
        
        Args:
            word_path: Word 文件路径
            output_path: 输出 PDF 路径（可选，默认与源文件同名）
            
        Returns:
            str: 生成的 PDF 文件路径
            
        Raises:
            RuntimeError: 如果 Gotenberg 服务不可用或转换失败
        """
        word_path_obj = Path(word_path)
        if not word_path_obj.exists():
            raise FileNotFoundError(f"Word 文件不存在: {word_path}")
        
        # 确定输出路径
        if output_path is None:
            output_path = str(word_path_obj.with_suffix('.pdf'))
        
        try:
            logger.info(f"开始转换 Word 文件: {word_path} -> {output_path}")
            
            # 读取 Word 文件内容
            with open(word_path, 'rb') as f:
                word_content = f.read()
            
            # 使用 Gotenberg 转换
            pdf_content = await cls.convert_to_pdf_async(
                word_content=word_content,
                file_name=word_path_obj.name
            )
            
            # 写入输出文件
            with open(output_path, 'wb') as f:
                f.write(pdf_content)
            
            logger.info(f"Word 文件转换成功: {output_path}")
            
            return output_path
            
        except Exception as e:
            logger.error(f"Word 转 PDF 失败: {e}", exc_info=True)
            raise RuntimeError(f"Word 转 PDF 失败: {str(e)}")
    
    @classmethod
    def convert_file_to_pdf(
        cls,
        word_path: str,
        output_path: str = None
    ) -> str:
        """
        将 Word 文件转换为 PDF 文件（同步方法）
        
        这是一个同步包装器，内部调用异步方法。
        推荐在异步环境中直接使用 convert_file_to_pdf_async。
        
        Args:
            word_path: Word 文件路径
            output_path: 输出 PDF 路径（可选，默认与源文件同名）
            
        Returns:
            str: 生成的 PDF 文件路径
            
        Raises:
            RuntimeError: 如果 Gotenberg 服务不可用或转换失败
        """
        # 在同步环境中运行异步方法
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(
            cls.convert_file_to_pdf_async(word_path, output_path)
        )

