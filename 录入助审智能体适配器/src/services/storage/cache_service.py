"""
磁盘缓存服务

负责将大对象（如解析结果）序列化存储到磁盘，减轻内存压力。
支持定期清理过期缓存文件（默认7天）。
使用orjson进行高性能JSON序列化。
"""

import os
import hashlib
import aiofiles
import asyncio
import time
from typing import Any, Optional, Dict
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger

try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    import json
    HAS_ORJSON = False
    logger.warning("orjson未安装，将使用标准json库（性能较低）")

class DiskCacheService:
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, cache_dir: str = "storage/cache", max_age_days: int = 7):
        if self._initialized:
            return
            
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_days = max_age_days
        self._cleanup_task = None
        self._initialized = True
        logger.info(f"磁盘缓存服务初始化完成，目录: {self.cache_dir}，缓存有效期: {max_age_days}天")
        
    def _get_file_path(self, key: str) -> Path:
        """根据key获取文件路径"""
        # 使用MD5作为文件名，避免特殊字符问题
        safe_name = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{safe_name}.json"
    
    async def set(self, key: str, value: Any) -> bool:
        """
        异步保存数据到磁盘（使用orjson提升性能）
        """
        try:
            file_path = self._get_file_path(key)
            
            # 使用orjson或标准json序列化
            if HAS_ORJSON:
                # orjson返回bytes，需要直接写入
                json_bytes = orjson.dumps(value)
                async with aiofiles.open(file_path, mode='wb') as f:
                    await f.write(json_bytes)
            else:
                # 标准json
                async with aiofiles.open(file_path, mode='w', encoding='utf-8') as f:
                    await f.write(json.dumps(value, ensure_ascii=False))
            
            return True
        except Exception as e:
            logger.error(f"写入磁盘缓存失败 [{key}]: {e}")
            return False
            
    async def get(self, key: str) -> Optional[Any]:
        """
        异步从磁盘读取数据（使用orjson提升性能）
        """
        try:
            file_path = self._get_file_path(key)
            if not file_path.exists():
                return None
            
            # 使用orjson或标准json反序列化
            if HAS_ORJSON:
                # orjson需要bytes
                async with aiofiles.open(file_path, mode='rb') as f:
                    content = await f.read()
                    return orjson.loads(content)
            else:
                # 标准json
                async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
                    content = await f.read()
                    return json.loads(content)
        except Exception as e:
            logger.error(f"读取磁盘缓存失败 [{key}]: {e}")
            return None
            
    def exists(self, key: str) -> bool:
        """检查缓存是否存在"""
        return self._get_file_path(key).exists()
        
    async def delete(self, key: str) -> bool:
        """删除缓存"""
        try:
            file_path = self._get_file_path(key)
            if file_path.exists():
                os.remove(file_path)
                return True
            return False
        except Exception as e:
            logger.error(f"删除磁盘缓存失败 [{key}]: {e}")
            return False
    
    async def cleanup_expired(self) -> int:
        """
        清理过期的缓存文件
        
        Returns:
            int: 清理的文件数量
        """
        try:
            now = time.time()
            max_age_seconds = self.max_age_days * 24 * 60 * 60
            deleted_count = 0
            
            if not self.cache_dir.exists():
                return 0
            
            for file_path in self.cache_dir.glob("*.json"):
                try:
                    # 检查文件修改时间
                    mtime = file_path.stat().st_mtime
                    age = now - mtime
                    
                    if age > max_age_seconds:
                        os.remove(file_path)
                        deleted_count += 1
                        logger.debug(f"清理过期缓存文件: {file_path.name}（已存在 {age/86400:.1f} 天）")
                except Exception as e:
                    logger.warning(f"清理缓存文件失败 {file_path}: {e}")
                    continue
            
            if deleted_count > 0:
                logger.info(f"磁盘缓存清理完成，删除 {deleted_count} 个过期文件（>{self.max_age_days}天）")
            
            return deleted_count
        except Exception as e:
            logger.error(f"清理过期缓存失败: {e}")
            return 0
    
    async def _cleanup_loop(self):
        """定期清理任务循环（每天运行一次）"""
        while True:
            try:
                # 等待24小时
                await asyncio.sleep(24 * 60 * 60)
                await self.cleanup_expired()
            except asyncio.CancelledError:
                logger.info("磁盘缓存清理任务已停止")
                break
            except Exception as e:
                logger.error(f"磁盘缓存清理任务异常: {e}")
    
    def start_cleanup_task(self):
        """启动定期清理任务（后台运行）"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("磁盘缓存定期清理任务已启动（每24小时运行一次）")
    
    def stop_cleanup_task(self):
        """停止定期清理任务"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            logger.info("磁盘缓存定期清理任务已停止")

# 全局实例
disk_cache = DiskCacheService()

def get_disk_cache() -> DiskCacheService:
    return disk_cache

