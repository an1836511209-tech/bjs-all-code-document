"""
全局环境配置

统一管理所有服务的环境配置，支持通过环境变量或启动参数切换开发/生产环境
"""

import os
from typing import Literal


# 环境类型
EnvType = Literal['dev', 'prod']

# 全局环境变量（默认生产环境）
_CURRENT_ENV: EnvType = 'prod'
# 提取缓存配置（默认启用）
_EXTRACTION_CACHE_ENABLED: bool = True
# 初始化标志（避免重复初始化）
_INITIALIZED: bool = False


def get_current_env() -> EnvType:
    """
    获取当前环境
    
    Returns:
        str: 当前环境 ('dev' 或 'prod')
    """
    return _CURRENT_ENV


def is_extraction_cache_enabled() -> bool:
    """获取提取缓存是否启用"""
    return _EXTRACTION_CACHE_ENABLED


def set_extraction_cache_enabled(enabled: bool):
    """
    设置提取缓存启用状态
    
    Args:
        enabled: 是否启用缓存
    """
    global _EXTRACTION_CACHE_ENABLED
    _EXTRACTION_CACHE_ENABLED = enabled
    os.environ['EXTRACTION_CACHE_ENABLED'] = str(enabled).lower()


def set_current_env(env: EnvType):
    """
    设置当前环境
    
    Args:
        env: 环境名称 ('dev' 或 'prod')
        
    Raises:
        ValueError: 如果环境名称无效
    """
    global _CURRENT_ENV
    
    if env not in ['dev', 'prod']:
        raise ValueError(f"无效的环境配置: {env}，必须是 'dev' 或 'prod'")
    
    _CURRENT_ENV = env
    
    # 同步更新到各个配置模块
    os.environ['ENV'] = env
    
    # 更新 LLM 配置
    try:
        from config.llm_config import LLMConfig
        LLMConfig.set_environment(env)
    except ImportError:
        pass
    
    # 更新 Paddle 配置
    try:
        import config.paddle_config as paddle_config
        paddle_config.CURRENT_ENV = env
    except ImportError:
        pass
    
    # 更新 Tika 配置
    try:
        import config.tika_config as tika_config
        tika_config.CURRENT_ENV = env
    except ImportError:
        pass
    
    # 更新 MinIO 配置
    try:
        import config.minio_config as minio_config
        minio_config.CURRENT_ENV = env
    except ImportError:
        pass
    
    # 更新 Gotenberg 配置
    try:
        import config.gotenberg_config as gotenberg_config
        gotenberg_config.CURRENT_ENV = env
    except ImportError:
        pass
    
    # 更新 Redis 配置
    try:
        from config.redis_config import RedisConfig
        RedisConfig.set_environment(env)
    except ImportError:
        pass


def init_env_from_args_or_env():
    """
    从环境变量或启动参数初始化环境配置
    
    优先级：环境变量 ENV > 默认值 'prod'
    
    注意：该方法只会执行一次，重复调用会被忽略
    """
    global _INITIALIZED
    
    # 避免重复初始化
    if _INITIALIZED:
        return
    
    # 安全获取环境变量并转换为小写
    env = str(os.getenv('ENV', 'prod')).lower()
    
    if env not in ['dev', 'prod']:
        env = 'prod'
    
    set_current_env(env)
    
    # 初始化缓存配置
    cache_enabled_str = str(os.getenv('EXTRACTION_CACHE_ENABLED', 'true')).lower()
    cache_enabled = cache_enabled_str in ('true', '1', 'yes', 'on')
    set_extraction_cache_enabled(cache_enabled)
    
    _INITIALIZED = True


# 默认初始化
init_env_from_args_or_env()

