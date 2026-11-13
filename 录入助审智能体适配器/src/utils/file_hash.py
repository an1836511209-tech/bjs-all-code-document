"""
文件哈希工具

用于生成文件列表的唯一哈希标识，支持结果缓存

文件唯一性识别策略：
- 使用 file_content_hash（文件内容的MD5哈希）作为唯一标识
- 如果文件没有 file_content_hash，该文件不参与缓存哈希计算
"""

import hashlib
import json
from typing import List, Dict, Any, Union
from pathlib import Path
from loguru import logger

from src.schemas.extraction import ExtractionFileInput


class FileHasher:
    """文件哈希生成器"""
    
    @staticmethod
    def compute_file_content_hash(file_path: Union[str, Path]) -> str:
        """
        计算文件内容的MD5哈希值（基于字节流）
        
        适用于所有文件类型（PDF、Word、Excel、图片等）
        按固定大小的块读取文件，避免大文件内存溢出
        
        Args:
            file_path: 文件路径（本地路径）
            
        Returns:
            str: MD5哈希值（十六进制字符串，32位）
            
        Example:
            >>> hash_val = FileHasher.compute_file_content_hash("document.pdf")
            >>> print(hash_val)  # "5d41402abc4b2a76b9719d911017c592"
        """
        try:
            file_path = Path(file_path)
            
            if not file_path.exists():
                logger.warning(f"文件不存在，无法计算哈希: {file_path}")
                return ""
            
            # 使用MD5算法（速度快，适合文件内容识别）
            md5_hash = hashlib.md5()
            
            # 按块读取文件，避免大文件内存溢出
            # 8KB 每块，对于大文件也能快速处理
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    md5_hash.update(chunk)
            
            content_hash = md5_hash.hexdigest()
            logger.debug(f"文件内容哈希: {file_path.name} -> {content_hash}")
            
            return content_hash
            
        except Exception as e:
            logger.error(f"计算文件内容哈希失败 [{file_path}]: {e}", exc_info=True)
            return ""
    
    @staticmethod
    def compute_content_hash_from_bytes(content: bytes) -> str:
        """
        从字节流计算MD5哈希值
        
        适用于已下载到内存中的文件内容
        
        Args:
            content: 文件内容字节流
            
        Returns:
            str: MD5哈希值（十六进制字符串，32位）
        """
        if not content:
            return ""
        
        md5_hash = hashlib.md5(content)
        return md5_hash.hexdigest()
    
    @staticmethod
    def compute_file_size(file_path: Union[str, Path]) -> int:
        """
        获取文件大小（字节）
        
        Args:
            file_path: 文件路径
            
        Returns:
            int: 文件大小（字节），失败返回0
        """
        try:
            file_path = Path(file_path)
            if file_path.exists():
                return file_path.stat().st_size
            return 0
        except Exception as e:
            logger.error(f"获取文件大小失败 [{file_path}]: {e}")
            return 0
    
    @staticmethod
    def _get_file_content_hash(file: ExtractionFileInput) -> str:
        """
        获取文件内容哈希
        
        Args:
            file: 文件输入对象
            
        Returns:
            str: 文件内容哈希，如果没有则返回空字符串
        """
        if hasattr(file, 'file_content_hash') and file.file_content_hash:
            return file.file_content_hash
        return ""
    
    @staticmethod
    def compute_files_hash(
        files: List[ExtractionFileInput],
        extraction_type: str = None,
        rule_config_id: str = None
    ) -> str:
        """
        计算文件列表的哈希值
        
        只基于文件内容哈希（file_content_hash）生成唯一标识
        如果有文件没有 file_content_hash，返回空字符串（无法使用缓存）
        
        注意：extraction_type 和 rule_config_id 参数保留是为了向后兼容，但不参与哈希计算
        
        Args:
            files: 文件列表
            extraction_type: 提取类型（保留参数，不参与计算）
            rule_config_id: 规则配置ID（保留参数，不参与计算）
            
        Returns:
            str: SHA256哈希值（十六进制字符串），如果有文件没有 content_hash 则返回空字符串
        """
        try:
            if not files:
                return ""
            
            # 收集所有文件的内容哈希
            content_hashes = []
            for f in files:
                content_hash = FileHasher._get_file_content_hash(f)
                if not content_hash:
                    # 如果有文件没有 content_hash，无法准确计算缓存哈希
                    logger.debug(f"文件 {f.file_name} 没有 content_hash，无法计算缓存哈希")
                    return ""
                content_hashes.append(content_hash)
            
            # 对哈希列表排序，确保相同文件不同顺序也能得到相同结果
            sorted_hashes = sorted(content_hashes)
            
            # 拼接所有哈希并计算最终哈希
            combined = "|".join(sorted_hashes)
            hash_obj = hashlib.sha256(combined.encode('utf-8'))
            files_hash = hash_obj.hexdigest()
            
            logger.debug(f"计算文件哈希: {files_hash[:16]}... (共{len(files)}个文件)")
            
            return files_hash
            
        except Exception as e:
            logger.error(f"计算文件哈希失败: {e}", exc_info=True)
            return ""
    
    @staticmethod
    def compute_files_hash_from_dict(
        files: List[Dict[str, Any]],
        extraction_type: str = None,
        rule_config_id: str = None
    ) -> str:
        """
        从字典列表计算文件哈希
        
        便捷方法，用于处理原始字典数据
        
        Args:
            files: 文件字典列表
            extraction_type: 提取类型（保留参数，不参与计算）
            rule_config_id: 规则配置ID（保留参数，不参与计算）
            
        Returns:
            str: SHA256哈希值（十六进制字符串）
        """
        try:
            # 转换为ExtractionFileInput对象
            file_inputs = [
                ExtractionFileInput(**f) for f in files
            ]
            
            return FileHasher.compute_files_hash(files=file_inputs)
            
        except Exception as e:
            logger.error(f"从字典计算文件哈希失败: {e}", exc_info=True)
            return ""
    
    @staticmethod
    def validate_hash(files_hash: str) -> bool:
        """
        验证哈希值是否有效
        
        Args:
            files_hash: 文件哈希值
            
        Returns:
            bool: 是否有效
        """
        if not files_hash:
            return False
        
        # SHA256哈希应该是64个十六进制字符
        if len(files_hash) != 64:
            return False
        
        try:
            int(files_hash, 16)
            return True
        except ValueError:
            return False

