"""
Apache Tika 服务配置
"""

from typing import Dict, Any
from functools import lru_cache
from config.env_config import get_current_env


# Tika 配置
TIKA_CONFIG = {
    # 'dev': {
    #     'server_url': 'http://101.126.54.157:7581',
    #     'timeout': 60,
    #     'extract_metadata': False,
    # },
    'dev': {
        'server_url': 'http://10.193.2.31:9998',
        'timeout': 60,
        'extract_metadata': False,
    },
    'prod': {
        'server_url': 'http://10.193.2.31:9998',
        'timeout': 60,
        'extract_metadata': False,
    }
}

# 当前环境（从全局环境配置获取）
CURRENT_ENV = get_current_env()


def get_tika_config(env: str = None) -> Dict[str, Any]:
    """
    获取Tika配置
    
    Args:
        env: 环境名称（dev/prod），默认使用CURRENT_ENV
        
    Returns:
        dict: Tika配置字典
    """
    if env is None:
        env = CURRENT_ENV
    
    return TIKA_CONFIG.get(env, TIKA_CONFIG['dev'])


@lru_cache()
def get_tika_server_url(env: str = None) -> str:
    """
    获取Tika服务器地址
    
    Args:
        env: 环境名称
        
    Returns:
        str: 服务器地址
    """
    config = get_tika_config(env)
    return config['server_url']



