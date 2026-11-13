"""
Apache Tika 客户端

提供文档文本提取功能，支持：
- Word 文档 (.doc, .docx)
- 文本文件 (.txt)
- 其他 Tika 支持的文档格式
"""

from typing import Optional
import httpx
from io import BytesIO
from loguru import logger

from src.utils.exceptions import FileProcessingError
from config.tika_config import get_tika_config
from config.env_config import get_current_env


# 全局单例实例
_tika_client_instance: Optional['TikaClient'] = None


class TikaClient:
    """Apache Tika 客户端，用于从文档中提取文本"""
    
    def __init__(self, env: str = None):
        """
        初始化 Tika 客户端
        
        Args:
            env: 环境名称（dev/prod），默认使用当前环境
        """
        self.env = env or get_current_env()
        self.config = get_tika_config(self.env)
        self.tika_server_url = self.config['server_url'].rstrip('/')
        self.timeout = float(self.config['timeout'])
        
        # 创建持久的HTTP客户端
        self.client = httpx.AsyncClient(timeout=self.timeout)
        
        logger.debug(f"Tika客户端初始化 | 环境: {self.env} | URL: {self.tika_server_url}")
        
    async def extract_text(
        self, 
        file_content: bytes, 
        file_name: str,
        extract_metadata: bool = False
    ) -> dict:
        """
        从文档中提取文本内容
        
        Args:
            file_content: 文件字节内容
            file_name: 文件名（用于推断文件类型）
            extract_metadata: 是否提取元数据
            
        Returns:
            dict: {
                "text": "提取的文本内容",
                "metadata": {...}  # 可选，如果 extract_metadata=True
            }
            
        Raises:
            FileProcessingError: 提取失败时抛出
        """
        try:
            # 使用 Tika /tika endpoint 提取文本
            url = f"{self.tika_server_url}/tika"
            
            headers = {
                "Accept": "text/plain",
                "Content-Type": "application/octet-stream"
            }
            
            logger.info(f"调用 Tika 提取文本 | 文件: {file_name} | 大小: {len(file_content)} 字节")
                
            response = await self.client.put(
                    url,
                    content=file_content,
                    headers=headers
                )
                
            if response.status_code != 200:
                error_msg = f"Tika 返回错误状态码: {response.status_code}, 详情: {response.text}"
                logger.error(error_msg)
                raise FileProcessingError(error_msg)
            
            text = response.text
            logger.info(f"Tika 提取文本成功 | 文件: {file_name} | 文本长度: {len(text)} 字符")
            
            result = {"text": text}
            
            # 如果需要元数据，再发一次请求
            if extract_metadata:
                metadata = await self._extract_metadata(file_content, file_name)
                result["metadata"] = metadata
            
            return result
                
        except httpx.RequestError as e:
            error_msg = f"Tika 服务请求失败: {str(e)}"
            logger.error(error_msg)
            raise FileProcessingError(error_msg)
        except Exception as e:
            error_msg = f"Tika 文本提取失败: {str(e)}"
            logger.error(error_msg)
            raise FileProcessingError(error_msg)
    
    async def _extract_metadata(self, file_content: bytes, file_name: str) -> dict:
        """
        提取文档元数据
        
        Args:
            file_content: 文件字节内容
            file_name: 文件名
            
        Returns:
            dict: 元数据字典
        """
        try:
            url = f"{self.tika_server_url}/meta"
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/octet-stream"
            }
            
            response = await self.client.put(
                    url,
                    content=file_content,
                    headers=headers
                )
                
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Tika 元数据提取失败: {response.status_code}")
                return {}
                    
        except Exception as e:
            logger.warning(f"Tika 元数据提取异常: {e}")
            return {}
    
    async def check_health(self) -> bool:
        """
        检查 Tika 服务是否健康
        
        Returns:
            bool: 服务是否可用
        """
        try:
            response = await self.client.get(f"{self.tika_server_url}/tika")
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Tika 健康检查失败: {e}")
            return False
    
    async def close(self):
        """关闭HTTP客户端连接"""
        if self.client:
            await self.client.aclose()
            logger.debug("Tika客户端HTTP连接已关闭")
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        await self.close()
    
    @staticmethod
    def is_supported_format(file_extension: str) -> bool:
        """
        检查文件格式是否支持 Tika 提取
        
        Args:
            file_extension: 文件扩展名（带点，如 .docx）
            
        Returns:
            bool: 是否支持
        """
        supported_formats = {
            # Word 文档
            '.doc', '.docx', '.dot', '.dotx',
            # 文本文件
            '.txt', '.text',
            # Rich Text
            '.rtf',
            # OpenDocument
            '.odt', '.ott',
            # HTML
            '.html', '.htm',
            # Markdown
            '.md', '.markdown',
            # Excel
            '.xlsx', '.xlsm',
            # CSV
            '.csv'
        }
        return file_extension.lower() in supported_formats


# ============ 单例获取函数 ============


def get_tika_client(env: str = None) -> TikaClient:
    """
    获取Tika客户端单例
    
    Args:
        env: 环境名称（dev/prod）
        
    Returns:
        TikaClient: 客户端实例
    """
    global _tika_client_instance
    if _tika_client_instance is None:
        _tika_client_instance = TikaClient(env)
        logger.debug(f"创建Tika客户端单例: env={env or get_current_env()}")
    return _tika_client_instance


async def close_tika_client():
    """关闭Tika客户端"""
    global _tika_client_instance
    if _tika_client_instance is not None:
        try:
            await _tika_client_instance.close()
            logger.debug("关闭Tika客户端")
        except Exception as e:
            logger.warning(f"关闭Tika客户端失败: {e}")
        finally:
            _tika_client_instance = None



