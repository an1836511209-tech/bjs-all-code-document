"""分布式锁管理"""
import time
import uuid
import asyncio
from typing import Optional
from loguru import logger

from src.services.redis.client import get_redis_client
from config.redis_config import get_redis_config


class DistributedLock:
    """基于Redis的分布式锁"""
    
    def __init__(self, lock_key: str, ttl_seconds: Optional[int] = None):
        self.redis_client = get_redis_client().client
        self.config = get_redis_config()
        self.lock_key = lock_key
        self.ttl = ttl_seconds or self.config.lock_ttl_seconds
        self.lock_value = f"{uuid.uuid4().hex}:{int(time.time())}"
        self._acquired = False
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.acquire()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.release()
    
    async def acquire(self, timeout: int = 30, retry_interval: float = 0.1) -> bool:
        """
        获取锁
        
        Args:
            timeout: 最大等待时间（秒）
            retry_interval: 重试间隔（秒）
        
        Returns:
            bool: 是否成功获取锁
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # 使用SET NX EX原子操作获取锁
            acquired = self.redis_client.set(
                self.lock_key,
                self.lock_value,
                nx=True,  # 只在key不存在时设置
                ex=self.ttl  # 过期时间
            )
            
            if acquired:
                self._acquired = True
                logger.debug(f"获取分布式锁成功: {self.lock_key}")
                return True
            
            # 检查锁的剩余时间，如果快过期了，等一会儿
            ttl = self.redis_client.ttl(self.lock_key)
            if ttl > 0 and ttl < 5:
                await asyncio.sleep(min(ttl + 0.5, retry_interval))
            else:
                await asyncio.sleep(retry_interval)
        
        logger.warning(f"获取分布式锁超时: {self.lock_key}")
        return False
    
    async def release(self) -> bool:
        """
        释放锁（使用Lua脚本保证原子性）
        
        Returns:
            bool: 是否成功释放
        """
        if not self._acquired:
            return True
        
        # Lua脚本：只有持有锁的客户端才能释放
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        
        try:
            result = self.redis_client.eval(lua_script, 1, self.lock_key, self.lock_value)
            self._acquired = False
            if result:
                logger.debug(f"释放分布式锁成功: {self.lock_key}")
            else:
                logger.warning(f"释放分布式锁失败（锁可能已被其他进程持有）: {self.lock_key}")
            return bool(result)
        except Exception as e:
            logger.error(f"释放分布式锁异常: {e}")
            return False


def create_extraction_lock(files_hash: str) -> DistributedLock:
    """创建提取服务的分布式锁"""
    return DistributedLock(f"lock:extract:{files_hash}")

