"""
MinerU客户端（更新版）

严格按照官方文档实现
参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/
"""

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Optional, Dict, Any, Union
import json

import httpx
from loguru import logger

from config.mineru_config import (
    get_mineru_config,
    get_api_endpoint,
    CURRENT_ENV
)
from src.services.mineru.models import ParseResult
from src.services.mineru.parser import MinerUParser
from src.utils.exceptions import FileProcessingError


# 全局单例实例
_mineru_client_instance: Optional['MinerUClient'] = None


class MinerUError(Exception):
    """MinerU服务错误"""
    pass


class MinerUClient:
    """
    MinerU API客户端
    
    提供文档解析功能的封装，支持pipeline和VLM后端
    """
    
    def __init__(self, env: str = None):
        """
        初始化MinerU客户端
        
        Args:
            env: 环境名称（dev/prod），默认使用配置文件中的环境
        """
        self.env = env or CURRENT_ENV
        self.config = get_mineru_config(self.env)
        self.api_config = self.config['api']
        self.parse_options = self.config['parse_options']
        
        # 创建解析器
        self.parser = MinerUParser()
        
        # 创建HTTP客户端
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.api_config['timeout']),
            follow_redirects=True
        )
        
        logger.info(
            f"MinerU客户端初始化完成 | "
            f"环境: {self.env} | "
            f"URL: {self.api_config['base_url']}"
        )
    
    async def close(self):
        """关闭客户端"""
        await self.client.aclose()
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()
    
    async def parse_file(
        self,
        file_path: Optional[Union[str, Path]] = None,
        file_content: Optional[bytes] = None,
        file_name: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> ParseResult:
        """
        解析文档文件
        
        Args:
            file_path: 文件路径或URL（支持本地路径、http://、https://）
            file_content: 文件内容（字节）
            file_name: 文件名称
            options: 解析选项（覆盖默认配置）
            
        Returns:
            ParseResult: 解析结果
            
        Raises:
            MinerUError: 解析失败时抛出
        """
        start_time = time.time()
        
        try:
            # 准备文件内容
            if file_path:
                file_path_str = str(file_path)
                
                # 规范化 URL：将反斜杠替换为正斜杠（处理 Windows 路径问题）
                if '\\' in file_path_str and ('http:' in file_path_str or 'https:' in file_path_str):
                    file_path_str = file_path_str.replace('\\', '/')
                    logger.info(f"规范化 URL 格式: {file_path_str}")
                
                # 检查是否为 URL
                if file_path_str.startswith(('http://', 'https://')):
                    # 从 URL 下载文件
                    # 使用统一的文件处理器（带重试和更长超时）
                    logger.info(f"从 URL 下载文件: {file_path_str}")
                    from src.utils.file_handler import FileHandler
                    file_content, _ = await FileHandler._download_from_url(
                        file_path_str,
                        max_retries=3,
                        timeout=120.0
                    )
                    
                    # 从 URL 中提取文件名
                    if not file_name:
                        from urllib.parse import urlparse, unquote
                        parsed_url = urlparse(file_path_str)
                        file_name = unquote(Path(parsed_url.path).name)
                else:
                    # 本地文件路径
                    file_path = Path(file_path)
                    file_name = file_name or file_path.name
                    with open(file_path, 'rb') as f:
                        file_content = f.read()
            elif file_content is None:
                raise ValueError("必须提供 file_path 或 file_content")
            
            if not file_name:
                file_name = 'unknown_file'
            
            # 获取文件类型
            file_type = Path(file_name).suffix.lower()
            
            # 合并解析选项
            parse_opts = {**self.parse_options, **(options or {})}
            
            # 调用API
            logger.info(
                f"开始解析文件 | "
                f"文件: {file_name} | "
                f"大小: {len(file_content)} 字节"
            )
            
            raw_response = await self._call_api(file_content, file_name, parse_opts)
            
            # 解析响应
            parse_result = self.parser.parse_response(raw_response, file_name, file_type)
            
            # 记录解析时间
            parse_time = time.time() - start_time
            parse_result.parse_time = parse_time
            
            if parse_result.success:
                logger.info(
                    f"文件解析成功 | "
                    f"文件: {file_name} | "
                    f"页数: {parse_result.total_pages} | "
                    f"后端: {parse_result.backend} | "
                    f"耗时: {parse_time:.2f}s"
                )
            else:
                logger.error(
                    f"文件解析失败 | "
                    f"文件: {file_name} | "
                    f"错误: {parse_result.error_message}"
                )
            
            return parse_result
            
        except httpx.HTTPError as e:
            logger.error(f"MinerU API调用失败: {e}")
            raise MinerUError(f"API调用失败: {str(e)}")
        except ValueError as e:
            # ValueError直接抛出（不包装）
            raise
        except Exception as e:
            logger.error(f"文件解析异常: {e}", exc_info=True)
            raise MinerUError(f"解析失败: {str(e)}")
    
    async def _call_api(
        self,
        file_content: bytes,
        file_name: str,
        options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        调用MinerU API
        
        Args:
            file_content: 文件内容
            file_name: 文件名
            options: 解析选项（将被转换为表单字段）
            
        Returns:
            Dict[str, Any]: API响应结果
        """
        url = get_api_endpoint('/file_parse', self.env)
        
        # 准备multipart/form-data
        # 注意：MinerU API 期望的字段名是 'files' (复数)
        files = {
            'files': (file_name, file_content, self._get_content_type(file_name))
        }
        
        # 准备表单参数（根据 MinerU API 文档）
        # 参考: API 需要独立的表单字段，而不是一个 options JSON
        
        # 获取语言列表
        languages = options.get('languages', ['ch', 'en'])
        
        # 基础参数（非数组）
        data = {
            # 核心参数
            'backend': options.get('backend', 'pipeline'),
            'parse_method': options.get('parse_method', 'auto'),
            
            # 功能开关（转换为字符串）
            'formula_enable': str(options.get('formula_enable', True)).lower(),
            'table_enable': str(options.get('table_enable', True)).lower(),
            
            # 返回格式控制（关键！）
            'return_md': str(options.get('return_md', True)).lower(),
            'return_middle_json': str(options.get('return_middle_json', True)).lower(),  # 必须开启，用于溯源
            'return_content_list': str(options.get('return_content_list', True)).lower(),  # 必须开启，用于 LLM 提取
            'return_model_output': str(options.get('return_model_output', True)).lower(),  # VLM 必需，model.json 是关键数据源
            'return_images': str(options.get('return_images', False)).lower(),
            
            # 页面范围
            'start_page_id': str(options.get('start_page_id', 0)),
            'end_page_id': str(options.get('end_page_id', 99999)),
        }
        
        # 语言列表（数组参数）- httpx 会自动将列表转换为多个同名字段
        # 如果 languages=['ch', 'en']，会生成：lang_list=ch&lang_list=en
        if languages:
            data['lang_list'] = languages
        
        logger.debug(f"MinerU API 请求参数: {data}")
        
        # 重试逻辑
        max_retries = self.api_config['max_retries']
        retry_delay = self.api_config['retry_delay']
        
        last_error = None
        for attempt in range(max_retries):
            try:
                logger.debug(f"API请求 (尝试 {attempt + 1}/{max_retries}): {url}")
                
                response = await self.client.post(
                    url,
                    files=files,
                    data=data if data else None
                )
                
                # 检查响应状态
                if response.status_code == 200:
                    try:
                        return response.json()
                    except json.JSONDecodeError as e:
                        error_msg = f"JSON解析失败: {e}, 响应内容: {response.text[:200]}"
                        logger.error(error_msg)
                        raise MinerUError(error_msg)
                
                else:
                    error_msg = f"API返回错误状态码: {response.status_code}"
                    try:
                        error_detail = response.json()
                        error_msg += f", 详情: {error_detail}"
                    except:
                        error_msg += f", 响应: {response.text[:200]}"
                    
                    logger.warning(error_msg)
                    
                    # 检查是否可重试
                    if response.status_code in self.config['error']['retryable_status_codes']:
                        last_error = MinerUError(error_msg)
                        if attempt < max_retries - 1:
                            logger.info(f"将在 {retry_delay}秒 后重试...")
                            await asyncio.sleep(retry_delay)
                            continue
                    
                    raise MinerUError(error_msg)
                    
            except httpx.TimeoutException as e:
                logger.warning(f"请求超时 (尝试 {attempt + 1}/{max_retries}): {e}")
                last_error = MinerUError(f"请求超时: {str(e)}")
                
                if attempt < max_retries - 1:
                    logger.info(f"将在 {retry_delay}秒 后重试...")
                    await asyncio.sleep(retry_delay)
                    continue
                    
            except httpx.RequestError as e:
                logger.warning(f"请求错误 (尝试 {attempt + 1}/{max_retries}): {e}")
                last_error = MinerUError(f"请求错误: {str(e)}")
                
                if attempt < max_retries - 1:
                    logger.info(f"将在 {retry_delay}秒 后重试...")
                    await asyncio.sleep(retry_delay)
                    continue
        
        # 所有重试都失败了
        raise last_error or MinerUError("API调用失败")
    
    @staticmethod
    def _get_content_type(file_name: str) -> str:
        """
        根据文件名获取Content-Type
        
        Args:
            file_name: 文件名
            
        Returns:
            str: Content-Type
        """
        suffix = Path(file_name).suffix.lower()
        
        content_types = {
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.bmp': 'image/bmp',
            '.tiff': 'image/tiff',
            '.tif': 'image/tiff',
            '.webp': 'image/webp',
        }
        
        return content_types.get(suffix, 'application/octet-stream')


# 便捷函数

async def parse_file(
    file_path: Optional[Union[str, Path]] = None,
    file_content: Optional[bytes] = None,
    file_name: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    env: str = None
) -> ParseResult:
    """
    便捷函数：解析文档文件
    
    Args:
        file_path: 文件路径
        file_content: 文件内容（字节）
        file_name: 文件名称
        options: 解析选项
        env: 环境名称
        
    Returns:
        ParseResult: 解析结果
        
    Example:
        >>> # 从文件路径解析
        >>> result = await parse_file(file_path="document.pdf")
        
        >>> # 从字节内容解析
        >>> result = await parse_file(
        ...     file_content=pdf_bytes,
        ...     file_name="document.pdf"
        ... )
        
        >>> # 自定义解析选项
        >>> result = await parse_file(
        ...     file_path="document.pdf",
        ...     options={'parse_tables': True, 'parse_formulas': False}
        ... )
    """
    async with MinerUClient(env) as client:
        return await client.parse_file(file_path, file_content, file_name, options)


async def parse_pdf_page(
    file_path: Union[str, Path],
    page_num: int,
    env: str = None
) -> Optional[Any]:
    """
    便捷函数：解析PDF的指定页面
    
    Args:
        file_path: PDF文件路径
        page_num: 页码（从0开始）
        env: 环境名称
        
    Returns:
        Optional[ParsedPage]: 解析的页面，如果失败返回None
    """
    result = await parse_file(file_path=file_path, env=env)
    
    if result.success:
        return result.get_page(page_num)
    else:
        logger.error(f"PDF解析失败: {result.error_message}")
        return None


# ============ 单例获取函数 ============


def get_mineru_client(env: str = None) -> 'MinerUClient':
    """
    获取MinerU客户端单例
    
    Args:
        env: 环境名称（dev/prod）
        
    Returns:
        MinerUClient: 客户端实例
    """
    global _mineru_client_instance
    if _mineru_client_instance is None:
        _mineru_client_instance = MinerUClient(env)
        logger.debug(f"创建MinerU客户端单例: env={env or CURRENT_ENV}")
    return _mineru_client_instance


async def close_mineru_client():
    """关闭MinerU客户端"""
    global _mineru_client_instance
    if _mineru_client_instance is not None:
        try:
            await _mineru_client_instance.close()
            logger.debug("关闭MinerU客户端")
        except Exception as e:
            logger.warning(f"关闭MinerU客户端失败: {e}")
        finally:
            _mineru_client_instance = None

