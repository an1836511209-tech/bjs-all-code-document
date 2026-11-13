"""
知识库API客户端

处理与灵搭API的交互，包括文件上传和数据源创建
"""

import os
import time
import requests
from pathlib import Path
from typing import Optional, Dict, Any
from src.core.logger import get_logger
from src.core.config import get_config

logger = get_logger(__name__)


class KnowledgeBaseClient:
    """知识库API客户端"""
    
    def __init__(self):
        """初始化客户端"""
        self.config = get_config()
        self.kb_config = self.config.get('knowledge_base', {})
        self.host = self.kb_config.get('host', 'https://uat.agentspro.cn')
        self.auth_key = self.kb_config.get('auth_key', '')
        self.auth_secret = self.kb_config.get('auth_secret', '')
        self.api_config = self.kb_config.get('api', {})
        
        # API端点
        self.upload_endpoint = self.api_config.get('upload_endpoint', '/openapi/fs/upload')
        self.create_ds_endpoint = self.api_config.get('create_ds_endpoint', '/openapi/kb/createDsAndTask')
        
        # 请求配置
        self.timeout = self.api_config.get('timeout', 60)
        self.retry_times = self.api_config.get('retry_times', 3)
        self.retry_delay = self.api_config.get('retry_delay', 5)
        
        # 验证配置
        if not self.auth_key or not self.auth_secret:
            raise ValueError("知识库认证信息未配置")
    
    def _get_auth_header(self) -> str:
        """获取认证头"""
        return f"Bearer {self.auth_key}.{self.auth_secret}"
    
    def _make_request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """带重试的请求方法"""
        last_exception = None
        
        for attempt in range(self.retry_times):
            try:
                response = requests.request(method, url, timeout=self.timeout, **kwargs)
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                last_exception = e
                logger.warning(f"请求失败，第{attempt + 1}次尝试: {e}")
                if attempt < self.retry_times - 1:
                    time.sleep(self.retry_delay)
                    
        raise last_exception
    
    def upload_file(self, file_path: str, return_type: str = "id", metadata: Optional[Dict] = None) -> str:
        """
        上传文件到知识库
        
        Args:
            file_path: 文件路径
            return_type: 返回类型，id或url，默认id
            metadata: 文件元数据
            
        Returns:
            文件ID或URL
            
        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 上传失败
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
            
        url = f"{self.host.rstrip('/')}{self.upload_endpoint}"
        headers = {
            "Authorization": self._get_auth_header()
        }
        
        file_name = Path(file_path).name
        logger.info(f"开始上传文件: {file_name}")
        
        try:
            with open(file_path, 'rb') as file:
                files = {
                    'file': (file_name, file, 'application/octet-stream')
                }
                data = {
                    'returnType': return_type
                }
                if metadata:
                    import json
                    data['metadata'] = json.dumps(metadata)
                
                response = self._make_request_with_retry(
                    'POST', url, headers=headers, files=files, data=data
                )
                
                result = response.json()
                if result.get('code') == 1:
                    file_id = result.get('data')
                    logger.info(f"文件上传成功: {file_name}, ID: {file_id}")
                    return file_id
                else:
                    raise ValueError(f"文件上传失败: {result.get('msg', '未知错误')}")
                    
        except Exception as e:
            logger.error(f"文件上传异常: {e}")
            raise
    
    def create_dataset_and_task(
        self, 
        kb_id: int, 
        file_id: str, 
        dataset_name: str,
        parser_type: str = "table",
        skip_if_exists: bool = False,
        auto_start_chunk_task: bool = True,
        always_create_new: bool = False
    ) -> int:
        """
        创建数据集并开始任务
        
        Args:
            kb_id: 知识库ID
            file_id: 上传文件的ID
            dataset_name: 数据集名称
            parser_type: 解析类型，默认table
            skip_if_exists: 如果存在则跳过，默认False
            auto_start_chunk_task: 自动开始分块任务，默认True
            always_create_new: 总是创建新的，默认False
            
        Returns:
            数据集ID
            
        Raises:
            ValueError: 创建失败
        """
        url = f"{self.host.rstrip('/')}{self.create_ds_endpoint}"
        headers = {
            "Authorization": self._get_auth_header(),
            "Content-Type": "application/json"
        }
        
        data = {
            "kbId": kb_id,
            "fileId": file_id,
            "name": dataset_name,
            "parserType": parser_type,
            "skipIfExists": skip_if_exists,
            "autoStartChunkTask": auto_start_chunk_task,
            "alwaysCreateNew": always_create_new
        }
        
        logger.info(f"开始创建数据集: {dataset_name}, 知识库ID: {kb_id}")
        
        try:
            response = self._make_request_with_retry(
                'POST', url, headers=headers, json=data
            )
            
            result = response.json()
            if result.get('code') == 1:
                dataset_id = result.get('data')
                logger.info(f"数据集创建成功: {dataset_name}, ID: {dataset_id}")
                return dataset_id
            else:
                raise ValueError(f"数据集创建失败: {result.get('msg', '未知错误')}")
                
        except Exception as e:
            logger.error(f"数据集创建异常: {e}")
            raise
    
    def upload_and_create_dataset(
        self, 
        file_path: str, 
        kb_id: int, 
        dataset_name: str,
        parser_type: str = "table"
    ) -> tuple[str, int]:
        """
        上传文件并创建数据集的便捷方法
        
        Args:
            file_path: 文件路径
            kb_id: 知识库ID
            dataset_name: 数据集名称
            parser_type: 解析类型，默认table
            
        Returns:
            (文件ID, 数据集ID)
        """
        # 上传文件
        file_id = self.upload_file(file_path)
        
        # 创建数据集
        dataset_id = self.create_dataset_and_task(
            kb_id=kb_id,
            file_id=file_id,
            dataset_name=dataset_name,
            parser_type=parser_type
        )
        
        return file_id, dataset_id
