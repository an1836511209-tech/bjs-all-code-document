"""
MinIO客户端工具模块

提供MinIO对象存储的封装功能，包括：
1. 文件上传
2. 文件下载
3. 文件删除
4. URL生成
5. 对象生命周期管理（自动过期删除）
"""

import io
import uuid
import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Union, Optional, List, Dict, Tuple
from urllib.parse import urljoin
from xml.etree import ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from minio import Minio
from minio.error import S3Error
from minio.lifecycleconfig import LifecycleConfig, Rule, Expiration
from minio.commonconfig import Filter
from loguru import logger as minio_logger

from config.minio_config import get_minio_config
from config.env_config import get_current_env


class MinIOClientError(Exception):
    """MinIO客户端异常"""
    pass


class MinIOClient:
    """MinIO客户端封装类"""
    
    def __init__(
        self,
        endpoint: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        secure: Optional[bool] = None,
        bucket_name: Optional[str] = None,
        env: Optional[str] = None
    ):
        """
        初始化MinIO客户端
        
        Args:
            endpoint: MinIO服务器地址
            access_key: 访问密钥
            secret_key: 密钥
            secure: 是否使用HTTPS
            bucket_name: 存储桶名称
            env: 环境名称（dev/prod），默认使用当前环境
        """
        # 获取配置
        self.env = env or get_current_env()
        config = get_minio_config(self.env)
        
        self.endpoint = endpoint or config['endpoint']
        self.access_key = access_key or config['access_key']
        self.secret_key = secret_key or config['secret_key']
        self.secure = secure if secure is not None else config['secure']
        self.bucket_name = bucket_name or config['bucket_name']
        self.file_prefix = config['file_prefix']
        self.public_url = config['public_url']
        self.connect_timeout = config['connect_timeout']
        self.read_timeout = config['read_timeout']
        
        # 初始化MinIO客户端
        try:
            self.client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure
            )
            minio_logger.debug(f"MinIO客户端初始化 | 环境: {self.env} | Endpoint: {self.endpoint}")
        except Exception as e:
            raise MinIOClientError(f"初始化MinIO客户端失败: {str(e)}")
        
        # 确保bucket存在
        self._ensure_bucket_exists()
    
    def _ensure_bucket_exists(self):
        """确保存储桶存在，不存在则创建"""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
        except S3Error as e:
            raise MinIOClientError(f"创建存储桶失败: {str(e)}")
    
    def upload_bytes(
        self,
        data: bytes,
        object_name: Optional[str] = None,
        content_type: str = "application/octet-stream",
        metadata: Optional[dict] = None,
        expires_days: Optional[int] = None
    ) -> str:
        """
        上传字节数据到MinIO
        
        Args:
            data: 要上传的字节数据
            object_name: 对象名称（文件路径），如果为None则自动生成
            content_type: 内容类型
            metadata: 元数据字典
            expires_days: 过期天数，如果设置则在元数据中记录过期时间
            
        Returns:
            str: 文件的代理访问URL（相对路径，如 /api/v1/preview/files/xxx）
            
        Raises:
            MinIOClientError: 上传失败时抛出
        """
        try:
            # 如果未指定对象名称，则自动生成
            if object_name is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                unique_id = str(uuid.uuid4())[:8]
                ext = self._get_extension_from_content_type(content_type)
                object_name = f"{self.file_prefix}/{timestamp}_{unique_id}{ext}"
            
            # 添加过期时间到元数据
            if metadata is None:
                metadata = {}
            
            if expires_days is not None:
                expires_at = datetime.now() + timedelta(days=expires_days)
                metadata['expires-at'] = expires_at.isoformat()
                metadata['upload-time'] = datetime.now().isoformat()
            
            # 上传文件
            data_stream = io.BytesIO(data)
            self.client.put_object(
                self.bucket_name,
                object_name,
                data_stream,
                length=len(data),
                content_type=content_type,
                metadata=metadata
            )
            
            # 返回代理访问URL（相对路径）
            return self.get_proxy_url(object_name)
            
        except S3Error as e:
            raise MinIOClientError(f"上传文件失败: {str(e)}")
        except Exception as e:
            raise MinIOClientError(f"上传文件时发生错误: {str(e)}")
    
    async def upload_bytes_batch(
        self,
        files_data: List[Dict[str, any]],
        max_concurrent: int = 10
    ) -> List[Tuple[bool, Optional[str], Optional[str]]]:
        """
        批量并发上传字节数据到MinIO
        
        性能优化：
        - 使用线程池并发上传，减少总耗时
        - 复用同一个客户端连接
        - 批量生成对象名称，减少重复操作
        
        Args:
            files_data: 文件数据列表，每项包含：
                - data: 字节数据 (bytes)
                - content_type: 内容类型 (str, 可选，默认 'application/octet-stream')
                - object_name: 对象名称 (str, 可选，自动生成)
                - metadata: 元数据 (dict, 可选)
                - expires_days: 过期天数 (int, 可选)
            max_concurrent: 最大并发数（默认10）
            
        Returns:
            List[Tuple[bool, Optional[str], Optional[str]]]: 上传结果列表
                - (成功, URL/None, 错误信息/None)
            
        Example:
            >>> files_data = [
            ...     {'data': img1_bytes, 'content_type': 'image/png'},
            ...     {'data': img2_bytes, 'content_type': 'image/png'},
            ...     {'data': img3_bytes, 'content_type': 'image/png'}
            ... ]
            >>> results = await client.upload_bytes_batch(files_data)
            >>> for success, url, error in results:
            ...     if success:
            ...         print(f"上传成功: {url}")
            ...     else:
            ...         print(f"上传失败: {error}")
        """
        if not files_data:
            return []
        
        minio_logger.info(f"开始批量上传 {len(files_data)} 个文件（并发数: {max_concurrent}）")
        
        def upload_single(file_info: Dict[str, any], index: int) -> Tuple[bool, Optional[str], Optional[str]]:
            """上传单个文件的同步函数"""
            try:
                data = file_info['data']
                content_type = file_info.get('content_type', 'application/octet-stream')
                object_name = file_info.get('object_name')
                metadata = file_info.get('metadata')
                expires_days = file_info.get('expires_days')
                
                # 调用同步上传方法
                url = self.upload_bytes(
                    data=data,
                    object_name=object_name,
                    content_type=content_type,
                    metadata=metadata,
                    expires_days=expires_days
                )
                
                return (True, url, None)
                
            except Exception as e:
                error_msg = f"上传第 {index} 个文件失败: {str(e)}"
                minio_logger.error(error_msg)
                return (False, None, error_msg)
        
        # 使用线程池并发上传
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            # 创建所有任务
            tasks = [
                loop.run_in_executor(executor, upload_single, file_info, idx)
                for idx, file_info in enumerate(files_data)
            ]
            
            # 并发执行
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 统计结果
        success_count = sum(1 for r in results if not isinstance(r, Exception) and r[0])
        fail_count = len(results) - success_count
        
        minio_logger.info(
            f"批量上传完成: 成功 {success_count}/{len(files_data)}，"
            f"失败 {fail_count}"
        )
        
        # 处理异常
        final_results = []
        for result in results:
            if isinstance(result, Exception):
                final_results.append((False, None, str(result)))
            else:
                final_results.append(result)
        
        return final_results
    
    def upload_file(
        self,
        file_path: Union[str, Path],
        object_name: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> str:
        """
        上传本地文件到MinIO
        
        Args:
            file_path: 本地文件路径
            object_name: 对象名称（文件路径），如果为None则使用文件名
            content_type: 内容类型，如果为None则自动推断
            metadata: 元数据字典
            
        Returns:
            str: 文件的代理访问URL（相对路径，如 /api/v1/preview/files/xxx）
            
        Raises:
            MinIOClientError: 上传失败时抛出
        """
        try:
            file_path = Path(file_path)
            
            if not file_path.exists():
                raise MinIOClientError(f"文件不存在: {file_path}")
            
            # 如果未指定对象名称，则使用文件名
            if object_name is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                unique_id = str(uuid.uuid4())[:8]
                object_name = f"{self.file_prefix}/{timestamp}_{unique_id}_{file_path.name}"
            
            # 如果未指定内容类型，则根据文件扩展名推断
            if content_type is None:
                content_type = self._guess_content_type(file_path.suffix)
            
            # 上传文件
            self.client.fput_object(
                self.bucket_name,
                object_name,
                str(file_path),
                content_type=content_type,
                metadata=metadata
            )
            
            # 返回代理访问URL（相对路径）
            return self.get_proxy_url(object_name)
            
        except S3Error as e:
            raise MinIOClientError(f"上传文件失败: {str(e)}")
        except Exception as e:
            raise MinIOClientError(f"上传文件时发生错误: {str(e)}")
    
    def download_file(self, object_name: str, file_path: Union[str, Path]) -> None:
        """
        从MinIO下载文件到本地
        
        Args:
            object_name: 对象名称（文件路径）
            file_path: 本地保存路径
            
        Raises:
            MinIOClientError: 下载失败时抛出
        """
        try:
            self.client.fget_object(self.bucket_name, object_name, str(file_path))
        except S3Error as e:
            raise MinIOClientError(f"下载文件失败: {str(e)}")
        except Exception as e:
            raise MinIOClientError(f"下载文件时发生错误: {str(e)}")
    
    def download_bytes(self, object_name: str) -> bytes:
        """
        从MinIO下载文件为字节数据
        
        Args:
            object_name: 对象名称（文件路径）
            
        Returns:
            bytes: 文件内容
            
        Raises:
            MinIOClientError: 下载失败时抛出
        """
        try:
            response = self.client.get_object(self.bucket_name, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            raise MinIOClientError(f"下载文件失败: {str(e)}")
        except Exception as e:
            raise MinIOClientError(f"下载文件时发生错误: {str(e)}")
    
    def delete_file(self, object_name: str) -> None:
        """
        删除MinIO中的文件
        
        Args:
            object_name: 对象名称（文件路径）
            
        Raises:
            MinIOClientError: 删除失败时抛出
        """
        try:
            self.client.remove_object(self.bucket_name, object_name)
        except S3Error as e:
            raise MinIOClientError(f"删除文件失败: {str(e)}")
        except Exception as e:
            raise MinIOClientError(f"删除文件时发生错误: {str(e)}")
    
    def get_public_url(self, object_name: str) -> str:
        """
        获取文件的公网访问URL
        
        Args:
            object_name: 对象名称（文件路径）
            
        Returns:
            str: 公网访问URL
        """
        # 构造公网访问URL
        base_url = self.public_url.rstrip('/')
        bucket_name = self.bucket_name
        object_name = object_name.lstrip('/')
        
        return f"{base_url}/{bucket_name}/{object_name}"
    
    def get_proxy_url(self, object_name: str) -> str:
        """
        获取通过代理接口访问的相对路径 URL
        
        返回直连本服务 preview 接口的相对路径，便于业务后端直连访问。
        
        Args:
            object_name: 对象名称（文件路径）
            
        Returns:
            str: 相对路径 URL（如 /api/v1/preview/files/highlights/xxx.jpg）
        """
        object_name = object_name.lstrip('/')
        return f"/api/v1/preview/files/{object_name}"
    
    def get_presigned_url(
        self,
        object_name: str,
        expires: timedelta = timedelta(hours=1)
    ) -> str:
        """
        获取文件的预签名URL（临时访问链接）
        
        Args:
            object_name: 对象名称（文件路径）
            expires: 过期时间
            
        Returns:
            str: 预签名URL
            
        Raises:
            MinIOClientError: 生成URL失败时抛出
        """
        try:
            url = self.client.presigned_get_object(
                self.bucket_name,
                object_name,
                expires=expires
            )
            return url
        except S3Error as e:
            raise MinIOClientError(f"生成预签名URL失败: {str(e)}")
        except Exception as e:
            raise MinIOClientError(f"生成预签名URL时发生错误: {str(e)}")
    
    def file_exists(self, object_name: str) -> bool:
        """
        检查文件是否存在
        
        Args:
            object_name: 对象名称（文件路径）
            
        Returns:
            bool: 文件是否存在
        """
        try:
            self.client.stat_object(self.bucket_name, object_name)
            return True
        except S3Error:
            return False
        except Exception:
            return False
    
    def set_bucket_lifecycle(self, days: int = 7, prefix: str = "") -> None:
        """
        设置存储桶的生命周期规则，自动删除过期对象
        
        Args:
            days: 对象过期天数
            prefix: 对象路径前缀，只对匹配的对象应用规则
            
        Raises:
            MinIOClientError: 设置失败时抛出
        """
        try:
            # 创建过期规则
            rule = Rule(
                rule_id=f"expire-{prefix or 'all'}-after-{days}-days",
                status="Enabled",
                rule_filter=Filter(prefix=prefix) if prefix else None,
                expiration=Expiration(days=days)
            )
            
            # 创建生命周期配置
            lifecycle_config = LifecycleConfig([rule])
            
            # 应用到bucket
            self.client.set_bucket_lifecycle(self.bucket_name, lifecycle_config)
            
        except S3Error as e:
            raise MinIOClientError(f"设置生命周期规则失败: {str(e)}")
        except Exception as e:
            raise MinIOClientError(f"设置生命周期规则时发生错误: {str(e)}")
    
    def get_bucket_lifecycle(self) -> Optional[LifecycleConfig]:
        """
        获取存储桶的生命周期配置
        
        Returns:
            Optional[LifecycleConfig]: 生命周期配置，如果没有则返回None
            
        Raises:
            MinIOClientError: 获取失败时抛出
        """
        try:
            return self.client.get_bucket_lifecycle(self.bucket_name)
        except S3Error as e:
            if "NoSuchLifecycleConfiguration" in str(e):
                return None
            raise MinIOClientError(f"获取生命周期配置失败: {str(e)}")
        except Exception as e:
            raise MinIOClientError(f"获取生命周期配置时发生错误: {str(e)}")
    
    def delete_bucket_lifecycle(self) -> None:
        """
        删除存储桶的生命周期配置
        
        Raises:
            MinIOClientError: 删除失败时抛出
        """
        try:
            self.client.delete_bucket_lifecycle(self.bucket_name)
        except S3Error as e:
            raise MinIOClientError(f"删除生命周期配置失败: {str(e)}")
        except Exception as e:
            raise MinIOClientError(f"删除生命周期配置时发生错误: {str(e)}")
    
    def cleanup_expired_objects(self, check_metadata: bool = True) -> List[str]:
        """
        手动清理过期的对象（根据元数据中的过期时间）
        
        Args:
            check_metadata: 是否检查对象元数据中的expires-at字段
            
        Returns:
            List[str]: 已删除的对象名称列表
            
        Raises:
            MinIOClientError: 清理失败时抛出
        """
        deleted_objects = []
        
        try:
            # 列出所有对象
            objects = self.client.list_objects(
                self.bucket_name,
                prefix=self.file_prefix,
                recursive=True
            )
            
            now = datetime.now()
            
            for obj in objects:
                should_delete = False
                
                if check_metadata:
                    try:
                        # 获取对象的元数据
                        stat = self.client.stat_object(self.bucket_name, obj.object_name)
                        metadata = stat.metadata
                        
                        # 检查是否有过期时间
                        if 'expires-at' in metadata:
                            expires_at = datetime.fromisoformat(metadata['expires-at'])
                            if now >= expires_at:
                                should_delete = True
                    except Exception:
                        # 如果获取元数据失败，跳过这个对象
                        continue
                
                # 删除过期对象
                if should_delete:
                    try:
                        self.client.remove_object(self.bucket_name, obj.object_name)
                        deleted_objects.append(obj.object_name)
                    except Exception:
                        # 删除失败，继续处理其他对象
                        continue
            
            return deleted_objects
            
        except S3Error as e:
            raise MinIOClientError(f"清理过期对象失败: {str(e)}")
        except Exception as e:
            raise MinIOClientError(f"清理过期对象时发生错误: {str(e)}")
    
    def get_object_metadata(self, object_name: str) -> Dict[str, str]:
        """
        获取对象的元数据
        
        Args:
            object_name: 对象名称（文件路径）
            
        Returns:
            Dict[str, str]: 元数据字典
            
        Raises:
            MinIOClientError: 获取失败时抛出
        """
        try:
            stat = self.client.stat_object(self.bucket_name, object_name)
            return dict(stat.metadata)
        except S3Error as e:
            raise MinIOClientError(f"获取对象元数据失败: {str(e)}")
        except Exception as e:
            raise MinIOClientError(f"获取对象元数据时发生错误: {str(e)}")
    
    @staticmethod
    def _guess_content_type(extension: str) -> str:
        """
        根据文件扩展名推断内容类型
        
        Args:
            extension: 文件扩展名（包含点号）
            
        Returns:
            str: 内容类型
        """
        content_types = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.webp': 'image/webp',
            '.pdf': 'application/pdf',
            '.txt': 'text/plain',
            '.json': 'application/json',
            '.xml': 'application/xml',
            '.zip': 'application/zip',
        }
        return content_types.get(extension.lower(), 'application/octet-stream')
    
    @staticmethod
    def _get_extension_from_content_type(content_type: str) -> str:
        """
        根据内容类型获取文件扩展名
        
        Args:
            content_type: 内容类型
            
        Returns:
            str: 文件扩展名（包含点号）
        """
        extensions = {
            'image/png': '.png',
            'image/jpeg': '.jpg',
            'image/gif': '.gif',
            'image/bmp': '.bmp',
            'image/webp': '.webp',
            'application/pdf': '.pdf',
            'text/plain': '.txt',
            'application/json': '.json',
            'application/xml': '.xml',
            'application/zip': '.zip',
        }
        return extensions.get(content_type.lower(), '.bin')


# 创建全局单例
_minio_client_instance = None


def get_minio_client() -> MinIOClient:
    """
    获取MinIO客户端单例
    
    Returns:
        MinIOClient: MinIO客户端实例
    """
    global _minio_client_instance
    if _minio_client_instance is None:
        _minio_client_instance = MinIOClient()
    return _minio_client_instance

