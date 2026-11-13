"""
文件处理公共方法

提供文件下载、哈希计算等公共方法，避免代码重复
"""

import asyncio
from typing import List, Tuple, Dict, Any
from loguru import logger

from src.utils.file_handler import FileHandler
from src.utils.file_hash import FileHasher
from src.services.storage.cache_service import get_disk_cache


async def download_files_and_compute_hashes(
    files: List[Any],
    file_input_class: type,
    existing_cache: Dict[str, bytes] = None
) -> Tuple[List[Any], Dict[str, bytes]]:
    """
    下载所有文件并计算文件内容哈希
    
    此方法用于在缓存查询前获取准确的文件哈希：
    1. 对于已有 file_content_hash 的文件，跳过下载
    2. 对于在 existing_cache 中已存在的文件，复用缓存内容
    3. 对于没有 file_content_hash 的文件，下载并计算哈希
    4. 返回更新后的文件列表和已下载的文件内容（用于后续复用）
    
    Args:
        files: 文件输入列表
        file_input_class: 文件输入类（用于创建更新后的对象）
        existing_cache: 已有的文件内容缓存（key为file_url，value为bytes），
            用于避免重复下载，通常来自其他服务已下载的文件
            
    Returns:
        Tuple[List[Any], Dict[str, bytes]]: 
            - 更新了 file_content_hash 的文件列表
            - 本次新下载的文件内容缓存 {file_url: bytes}（不包含 existing_cache 中的文件）
    """
    # 已有的文件缓存
    _existing_cache = existing_cache or {}
    
    # 本次新下载的文件内容缓存
    downloaded_files: Dict[str, bytes] = {}
    updated_files = []
    
    # 获取磁盘缓存服务
    disk_cache = get_disk_cache()
    
    async def download_and_hash(file_input):
        """下载单个文件并计算哈希"""
        # 如果已有 content_hash，直接返回
        if hasattr(file_input, 'file_content_hash') and file_input.file_content_hash:
            logger.debug(f"文件 {file_input.file_name} 已有 content_hash，跳过下载")
            return file_input, None, False  # False 表示使用了原有哈希
        
        file_url = file_input.file_url
        
        # 优先从磁盘缓存查询 content_hash（避免重复下载）
        hash_cache_key = f"file_content_hash:{file_url}"
        cached_hash_data = await disk_cache.get(hash_cache_key)
        if cached_hash_data and isinstance(cached_hash_data, dict):
            content_hash = cached_hash_data.get("hash")
            file_size = cached_hash_data.get("size", 0)
            if content_hash:
                logger.info(f"文件 {file_input.file_name} 从磁盘缓存获取哈希: {content_hash[:16]}...（跳过下载）")
                updated_file = file_input_class(
                    file_url=file_input.file_url,
                    file_name=file_input.file_name,
                    file_type=file_input.file_type,
                    file_content_hash=content_hash,
                    file_size=file_size
                )
                return updated_file, None, True  # 复用磁盘缓存的 hash
        
        # 检查是否在内存缓存中（来自其他服务已下载的文件）
        if file_url in _existing_cache:
            file_content = _existing_cache[file_url]
            content_hash = FileHasher.compute_content_hash_from_bytes(file_content)
            file_size = len(file_content)
            
            logger.info(f"文件 {file_input.file_name} 复用内存缓存，计算哈希: {content_hash[:16]}...")
            
            # 缓存 hash 到磁盘（供后续请求使用）
            await disk_cache.set(hash_cache_key, {"hash": content_hash, "size": file_size})
            
            updated_file = file_input_class(
                file_url=file_input.file_url,
                file_name=file_input.file_name,
                file_type=file_input.file_type,
                file_content_hash=content_hash,
                file_size=file_size
            )
            return updated_file, None, True  # 复用了内存缓存，不需要添加到新下载列表
        
        try:
            # 下载文件
            file_content, _ = await FileHandler.process_file_input(
                file_url=file_input.file_url,
                file_name=file_input.file_name
            )
            
            # 计算哈希
            content_hash = FileHasher.compute_content_hash_from_bytes(file_content)
            file_size = len(file_content)
            
            logger.info(f"文件 {file_input.file_name} 下载完成，计算哈希: {content_hash[:16]}...")
            
            # 缓存 hash 到磁盘（供后续请求使用）
            await disk_cache.set(hash_cache_key, {"hash": content_hash, "size": file_size})
            
            # 创建更新后的文件对象（使用传入的类）
            updated_file = file_input_class(
                file_url=file_input.file_url,
                file_name=file_input.file_name,
                file_type=file_input.file_type,
                file_content_hash=content_hash,
                file_size=file_size
            )
            
            return updated_file, file_content, False  # file_content 用于添加到新下载列表
            
        except Exception as e:
            logger.error(f"下载文件失败 {file_input.file_name}: {e}")
            # 下载失败时返回原文件对象
            return file_input, None, False
    
    # 并行下载所有文件
    tasks = [download_and_hash(f) for f in files]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"下载任务异常: {result}")
            continue
        
        updated_file, file_content, _ = result
        updated_files.append(updated_file)
        
        # 缓存本次新下载的文件内容（不包含复用缓存的文件）
        if file_content is not None:
            downloaded_files[updated_file.file_url] = file_content
    
    return updated_files, downloaded_files

