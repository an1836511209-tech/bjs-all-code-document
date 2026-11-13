"""
Redis 配置管理

配置 Redis Sentinel 连接、连接池和任务相关参数
支持开发环境和生产环境的独立配置
"""

from typing import List, Tuple, Dict, Any
from pydantic import BaseModel, Field
from config.env_config import get_current_env
from loguru import logger


class RedisConnectionConfig(BaseModel):
    """Redis 连接配置"""
    mode: str = Field(default="sentinel", description="连接模式: 'sentinel' 或 'direct'")
    master_name: str = Field(default="mymaster", description="Sentinel 主节点名称")
    sentinel_nodes: List[Tuple[str, int]] = Field(
        default_factory=list, 
        description="Sentinel 节点列表 [(host, port), ...]"
    )
    password: str = Field(default="", description="Redis 密码")
    db: int = Field(default=0, description="数据库索引")
    
    # 直连模式配置（当 mode='direct' 时使用）
    host: str = Field(default="localhost", description="直连模式主机地址")
    port: int = Field(default=6379, description="直连模式端口")


class RedisPoolConfig(BaseModel):
    """Redis 连接池配置"""
    max_connections: int = Field(default=50, description="最大连接数")
    socket_timeout: int = Field(default=20, description="Socket 超时时间（秒）")
    socket_connect_timeout: int = Field(default=20, description="连接超时时间（秒）")


class RedisTaskConfig(BaseModel):
    """Redis 任务相关配置"""
    task_ttl_days: int = Field(default=360, description="任务数据过期天数")
    lock_ttl_seconds: int = Field(default=1800, description="分布式锁过期时间（秒）")


class RedisConfig:
    """
    Redis 配置管理类
    
    提供开发环境和生产环境的独立配置，支持 Sentinel 模式
    """
    
    # 开发环境配置
    DEV_CONFIG = {
        "connection": RedisConnectionConfig(
            mode="sentinel",
            master_name="mymaster",
            sentinel_nodes=[
                ("10.254.89.131", 26379),
                ("10.254.89.132", 26379),
                ("10.254.89.133", 26379),
            ],
            password="hiAgents2025",
            db=0
        ),
        "pool": RedisPoolConfig(
            max_connections=50,
            socket_timeout=5,
            socket_connect_timeout=5
        ),
        "task": RedisTaskConfig(
            task_ttl_days=90,
            lock_ttl_seconds=1800  # 30 分钟
        )
    }
    
    # 生产环境配置
    PROD_CONFIG = {
        "connection": RedisConnectionConfig(
            mode="sentinel",
            master_name="mymaster",
            sentinel_nodes=[
                ("10.254.89.131", 26379),
                ("10.254.89.132", 26379),
                ("10.254.89.133", 26379),
            ],
            password="hiAgents2025",
            db=0
        ),
        "pool": RedisPoolConfig(
            max_connections=50,
            socket_timeout=5,
            socket_connect_timeout=5
        ),
        "task": RedisTaskConfig(
            task_ttl_days=90,
            lock_ttl_seconds=1800  # 30 分钟
        )
    }
    
    # 当前环境（从全局环境配置获取）
    CURRENT_ENV = get_current_env()
    
    @classmethod
    def _get_config(cls) -> Dict[str, Any]:
        """获取当前环境的完整配置"""
        return cls.DEV_CONFIG if cls.CURRENT_ENV == "dev" else cls.PROD_CONFIG
    
    @classmethod
    def get_connection_config(cls) -> RedisConnectionConfig:
        """获取 Redis 连接配置"""
        return cls._get_config()["connection"]
    
    @classmethod
    def get_pool_config(cls) -> RedisPoolConfig:
        """获取连接池配置"""
        return cls._get_config()["pool"]
    
    @classmethod
    def get_task_config(cls) -> RedisTaskConfig:
        """获取任务配置"""
        return cls._get_config()["task"]
    
    @classmethod
    def set_environment(cls, env: str):
        """
        设置当前环境
        
        Args:
            env: 环境名称 ('dev' 或 'prod')
        """
        if env not in ["dev", "prod"]:
            raise ValueError(f"无效的环境配置: {env}，必须是 'dev' 或 'prod'")
        cls.CURRENT_ENV = env
        logger.info(f"Redis 配置环境已切换至: {env}")
    
    # ==================== 便捷属性（兼容旧代码） ====================
    
    @classmethod
    def get_mode(cls) -> str:
        """获取连接模式"""
        return cls.get_connection_config().mode
    
    @classmethod
    def get_master_name(cls) -> str:
        """获取 Sentinel 主节点名称"""
        return cls.get_connection_config().master_name
    
    @classmethod
    def get_sentinel_nodes(cls) -> List[Tuple[str, int]]:
        """获取 Sentinel 节点列表"""
        return cls.get_connection_config().sentinel_nodes
    
    @classmethod
    def get_password(cls) -> str:
        """获取 Redis 密码"""
        return cls.get_connection_config().password
    
    @classmethod
    def get_db(cls) -> int:
        """获取数据库索引"""
        return cls.get_connection_config().db
    
    @classmethod
    def get_max_connections(cls) -> int:
        """获取最大连接数"""
        return cls.get_pool_config().max_connections
    
    @classmethod
    def get_socket_timeout(cls) -> int:
        """获取 Socket 超时时间"""
        return cls.get_pool_config().socket_timeout
    
    @classmethod
    def get_socket_connect_timeout(cls) -> int:
        """获取连接超时时间"""
        return cls.get_pool_config().socket_connect_timeout
    
    @classmethod
    def get_task_ttl_days(cls) -> int:
        """获取任务数据过期天数"""
        return cls.get_task_config().task_ttl_days
    
    @classmethod
    def get_lock_ttl_seconds(cls) -> int:
        """获取分布式锁过期时间"""
        return cls.get_task_config().lock_ttl_seconds


# 导出配置实例
redis_config = RedisConfig()


class RedisConfigWrapper:
    """
    Redis 配置包装器
    
    提供与旧版 RedisConfig 实例兼容的属性访问方式
    用于向后兼容，新代码建议直接使用 RedisConfig 类方法
    """
    
    @property
    def env(self) -> str:
        """当前环境"""
        return RedisConfig.CURRENT_ENV
    
    @property
    def mode(self) -> str:
        """连接模式"""
        return RedisConfig.get_mode()
    
    @property
    def master_name(self) -> str:
        """Sentinel 主节点名称"""
        return RedisConfig.get_master_name()
    
    @property
    def sentinel_nodes(self) -> List[Tuple[str, int]]:
        """Sentinel 节点列表"""
        return RedisConfig.get_sentinel_nodes()
    
    @property
    def password(self) -> str:
        """Redis 密码"""
        return RedisConfig.get_password()
    
    @property
    def db(self) -> int:
        """数据库索引"""
        return RedisConfig.get_db()
    
    @property
    def max_connections(self) -> int:
        """最大连接数"""
        return RedisConfig.get_max_connections()
    
    @property
    def socket_timeout(self) -> int:
        """Socket 超时时间"""
        return RedisConfig.get_socket_timeout()
    
    @property
    def socket_connect_timeout(self) -> int:
        """连接超时时间"""
        return RedisConfig.get_socket_connect_timeout()
    
    @property
    def task_ttl_days(self) -> int:
        """任务数据过期天数"""
        return RedisConfig.get_task_ttl_days()
    
    @property
    def lock_ttl_seconds(self) -> int:
        """分布式锁过期时间"""
        return RedisConfig.get_lock_ttl_seconds()


# 单例包装器（用于向后兼容）
_redis_config_wrapper = None


def get_redis_config() -> RedisConfigWrapper:
    """
    获取 Redis 配置（向后兼容）
    
    Returns:
        RedisConfigWrapper: 配置包装器，提供与旧版相同的属性访问方式
    """
    global _redis_config_wrapper
    if _redis_config_wrapper is None:
        _redis_config_wrapper = RedisConfigWrapper()
    return _redis_config_wrapper
