"""
Gotenberg 客户端

用于与 Gotenberg API 服务交互，实现 Word、Excel 等文档转 PDF 的功能。
官方文档: https://gotenberg.dev/docs/routes
"""

import io
from typing import Optional, Dict, Any
from pathlib import Path

import httpx
from loguru import logger

from config.gotenberg_config import get_gotenberg_config
from config.env_config import get_current_env


# 全局单例实例
_gotenberg_client_instance: Optional['GotenbergClient'] = None


class GotenbergClient:
    """Gotenberg API 客户端"""
    
    def __init__(self, env: str = None):
        """
        初始化 Gotenberg 客户端
        
        Args:
            env: 环境名称（dev/prod），默认使用当前环境
        """
        self.env = env or get_current_env()
        self.config = get_gotenberg_config(self.env)
        self.base_url = self.config['server_url'].rstrip('/')
        self.timeout = self.config['timeout']
        self.enabled = self.config['enabled']
        
        # 创建持久的HTTP客户端
        self.client = httpx.AsyncClient(timeout=self.timeout)
        
        logger.debug(f"Gotenberg客户端初始化 | 环境: {self.env} | URL: {self.base_url}")
    
    def is_available(self) -> bool:
        """
        检查 Gotenberg 服务是否可用
        
        Returns:
            bool: 服务是否可用
        """
        if not self.enabled:
            return False
        
        try:
            response = httpx.get(f"{self.base_url}/health", timeout=5)
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Gotenberg 服务不可用: {e}")
            return False
    
    async def convert_office_to_pdf(
        self,
        file_content: bytes,
        file_name: str,
        landscape: bool = False,
        pdfa_format: Optional[str] = None,
        merge: bool = False
    ) -> bytes:
        """
        将 Office 文档（Word、Excel、PowerPoint）转换为 PDF
        
        使用 LibreOffice 引擎进行转换
        API 文档: https://gotenberg.dev/docs/routes#libreoffice
        
        Args:
            file_content: 文件的二进制内容
            file_name: 文件名（用于识别文件类型）
            landscape: 是否横向打印
            pdfa_format: PDF/A 格式（如 "PDF/A-1b"）
            merge: 是否合并多个文件
            
        Returns:
            bytes: 转换后的 PDF 文件内容
            
        Raises:
            RuntimeError: 转换失败时抛出
        """
        if not self.enabled:
            raise RuntimeError("Gotenberg 服务未启用")
        
        # 构建 API 端点
        endpoint = f"{self.base_url}/forms/libreoffice/convert"
        
        # 准备表单数据
        files = {
            'files': (file_name, file_content)
        }
        
        # 准备表单字段
        data = {}
        if landscape:
            data['landscape'] = 'true'
        if pdfa_format:
            data['pdfa'] = pdfa_format
        if merge:
            data['merge'] = 'true'
        
        try:
            logger.info(f"开始使用 Gotenberg 转换文档: {file_name}")
            
            response = await self.client.post(
                endpoint,
                files=files,
                data=data
            )
            
            response.raise_for_status()
            
            pdf_content = response.content
            logger.info(f"Gotenberg 转换成功，PDF 大小: {len(pdf_content)} 字节")
            
            return pdf_content
                
        except httpx.TimeoutException:
            error_msg = f"Gotenberg 转换超时（{self.timeout}秒）: {file_name}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        except httpx.HTTPStatusError as e:
            error_msg = f"Gotenberg 转换失败 (HTTP {e.response.status_code}): {e.response.text}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        except Exception as e:
            error_msg = f"Gotenberg 转换异常: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg)
    
    async def convert_word_to_pdf(
        self,
        word_content: bytes,
        file_name: str = "document.docx"
    ) -> bytes:
        """
        将 Word 文档转换为 PDF（便捷方法）
        
        Args:
            word_content: Word 文档的二进制内容
            file_name: 文件名
            
        Returns:
            bytes: 转换后的 PDF 文件内容
            
        Raises:
            RuntimeError: 转换失败时抛出
        """
        # 使用配置中的默认参数
        return await self.convert_office_to_pdf(
            file_content=word_content,
            file_name=file_name,
            landscape=self.config.get('landscape', False),
            pdfa_format=self.config.get('pdfa_format') or None,
            merge=self.config.get('merge', False)
        )
    
    async def convert_html_to_pdf(
        self,
        html_content: str,
        header_html: Optional[str] = None,
        footer_html: Optional[str] = None,
        margin_top: float = 1.0,
        margin_bottom: float = 1.0,
        margin_left: float = 1.0,
        margin_right: float = 1.0
    ) -> bytes:
        """
        将 HTML 转换为 PDF
        
        使用 Chromium 引擎进行转换
        API 文档: https://gotenberg.dev/docs/routes#chromium
        
        Args:
            html_content: HTML 内容
            header_html: 页眉 HTML（可选）
            footer_html: 页脚 HTML（可选）
            margin_top: 上边距（英寸）
            margin_bottom: 下边距（英寸）
            margin_left: 左边距（英寸）
            margin_right: 右边距（英寸）
            
        Returns:
            bytes: 转换后的 PDF 文件内容
            
        Raises:
            RuntimeError: 转换失败时抛出
        """
        if not self.enabled:
            raise RuntimeError("Gotenberg 服务未启用")
        
        # 构建 API 端点
        endpoint = f"{self.base_url}/forms/chromium/convert/html"
        
        # 准备文件
        files = {
            'files': ('index.html', html_content.encode('utf-8'))
        }
        
        if header_html:
            files['files'] = [
                ('index.html', html_content.encode('utf-8')),
                ('header.html', header_html.encode('utf-8'))
            ]
        
        if footer_html:
            files['files'] = [
                ('index.html', html_content.encode('utf-8')),
                ('footer.html', footer_html.encode('utf-8'))
            ]
        
        # 准备表单字段
        data = {
            'marginTop': str(margin_top),
            'marginBottom': str(margin_bottom),
            'marginLeft': str(margin_left),
            'marginRight': str(margin_right)
        }
        
        try:
            logger.info("开始使用 Gotenberg 转换 HTML 为 PDF")
            
            response = await self.client.post(
                endpoint,
                files=files,
                data=data
            )
            
            response.raise_for_status()
            
            pdf_content = response.content
            logger.info(f"Gotenberg HTML 转换成功，PDF 大小: {len(pdf_content)} 字节")
            
            return pdf_content
                
        except Exception as e:
            error_msg = f"Gotenberg HTML 转换失败: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg)
    
    async def merge_pdfs(
        self,
        pdf_files: list[tuple[str, bytes]]
    ) -> bytes:
        """
        合并多个 PDF 文件
        
        API 文档: https://gotenberg.dev/docs/routes#merge-pdfs
        
        Args:
            pdf_files: PDF 文件列表，格式为 [(文件名, 文件内容), ...]
            
        Returns:
            bytes: 合并后的 PDF 文件内容
            
        Raises:
            RuntimeError: 合并失败时抛出
        """
        if not self.enabled:
            raise RuntimeError("Gotenberg 服务未启用")
        
        if len(pdf_files) < 2:
            raise ValueError("至少需要 2 个 PDF 文件才能合并")
        
        # 构建 API 端点
        endpoint = f"{self.base_url}/forms/pdfengines/merge"
        
        # 准备文件
        files = [('files', (name, content)) for name, content in pdf_files]
        
        try:
            logger.info(f"开始使用 Gotenberg 合并 {len(pdf_files)} 个 PDF")
            
            response = await self.client.post(
                endpoint,
                files=files
            )
            
            response.raise_for_status()
            
            pdf_content = response.content
            logger.info(f"Gotenberg 合并成功，PDF 大小: {len(pdf_content)} 字节")
            
            return pdf_content
                
        except Exception as e:
            error_msg = f"Gotenberg PDF 合并失败: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg)
    
    async def close(self):
        """关闭HTTP客户端连接"""
        if self.client:
            await self.client.aclose()
            logger.debug("Gotenberg客户端HTTP连接已关闭")
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        await self.close()


# ============ 单例获取函数 ============


def get_gotenberg_client(env: str = None) -> GotenbergClient:
    """
    获取Gotenberg客户端单例
    
    Args:
        env: 环境名称（dev/prod）
        
    Returns:
        GotenbergClient: 客户端实例
    """
    global _gotenberg_client_instance
    if _gotenberg_client_instance is None:
        _gotenberg_client_instance = GotenbergClient(env)
        logger.debug(f"创建Gotenberg客户端单例: env={env or get_current_env()}")
    return _gotenberg_client_instance


async def close_gotenberg_client():
    """关闭Gotenberg客户端"""
    global _gotenberg_client_instance
    if _gotenberg_client_instance is not None:
        try:
            await _gotenberg_client_instance.close()
            logger.debug("关闭Gotenberg客户端")
        except Exception as e:
            logger.warning(f"关闭Gotenberg客户端失败: {e}")
        finally:
            _gotenberg_client_instance = None



