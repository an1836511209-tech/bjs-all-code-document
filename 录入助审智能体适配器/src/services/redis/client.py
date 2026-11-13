"""Redis客户端封装"""
import json
import redis
from redis.sentinel import Sentinel
from typing import Optional, Any, Dict, List
from datetime import datetime, timedelta
from loguru import logger

from config.redis_config import get_redis_config


class RedisClient:
    """Redis客户端封装（支持Sentinel）"""
    
    def __init__(self):
        self.config = get_redis_config()
        self._client: Optional[redis.Redis] = None
        self._sentinel: Optional[Sentinel] = None
        self._pubsub = None
        self._connect()
    
    def _connect(self):
        """建立Redis连接"""
        try:
            if self.config.mode == 'sentinel':
                # Sentinel模式
                self._sentinel = Sentinel(
                    self.config.sentinel_nodes,
                    socket_timeout=self.config.socket_timeout,
                    socket_connect_timeout=self.config.socket_connect_timeout,
                    password=self.config.password
                )
                self._client = self._sentinel.master_for(
                    self.config.master_name,
                    socket_timeout=self.config.socket_timeout,
                    socket_connect_timeout=self.config.socket_connect_timeout,
                    password=self.config.password,
                    db=self.config.db,
                    decode_responses=True
                )
                logger.info(f"已连接到Redis Sentinel: {self.config.master_name}")
            else:
                # 直连模式
                host, port = self.config.sentinel_nodes[0]
                self._client = redis.Redis(
                    host=host,
                    port=port,
                    password=self.config.password,
                    db=self.config.db,
                    decode_responses=True,
                    socket_timeout=self.config.socket_timeout,
                    socket_connect_timeout=self.config.socket_connect_timeout
                )
                logger.info(f"已连接到Redis: {host}:{port}")
            
            # 测试连接
            self._client.ping()
            logger.info("Redis连接测试成功")
        except Exception as e:
            logger.error(f"Redis连接失败: {e}")
            raise
    
    @property
    def client(self) -> redis.Redis:
        """获取Redis客户端"""
        return self._client
    
    def get_pubsub(self):
        """获取Pub/Sub对象"""
        if self._pubsub is None:
            self._pubsub = self._client.pubsub(ignore_subscribe_messages=True)
        return self._pubsub


# 单例
_redis_client = None

def get_redis_client() -> RedisClient:
    """获取Redis客户端单例"""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client

