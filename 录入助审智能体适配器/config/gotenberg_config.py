"""
Gotenberg 配置

Gotenberg 是一个基于 Docker 的文档转换 API 服务，支持将 Word、Excel 等文档转换为 PDF。
官网: https://gotenberg.dev/
安装文档: https://gotenberg.dev/docs/getting-started/installation
"""

from typing import Dict, Any
from functools import lru_cache
from config.env_config import get_current_env
import os


# Gotenberg 配置
GOTENBERG_CONFIG = {
    'dev': {
        'server_url': 'http://10.254.89.129:3000',
        'timeout': 60,
        'enabled': True,
        'pdfa_format': '',
        'merge': False,
        'landscape': False,
        'page_ranges': '',
    },

    'prod': {
        'server_url': 'http://10.254.89.129:3000',
        'timeout': 60,
        'enabled': True,
        'pdfa_format': '',
        'merge': False,
        'landscape': False,
        'page_ranges': '',
    }
}

# 当前环境（从全局环境配置获取）
CURRENT_ENV = get_current_env()


def get_gotenberg_config(env: str = None) -> Dict[str, Any]:
    """
    获取Gotenberg配置
    
    支持环境变量 GOTENBERG_URL 覆盖默认配置
    
    Args:
        env: 环境名称（dev/prod），默认使用CURRENT_ENV
        
    Returns:
        dict: Gotenberg配置字典
    """
    if env is None:
        env = CURRENT_ENV
    
    config = GOTENBERG_CONFIG.get(env, GOTENBERG_CONFIG['dev']).copy()
    
    # 支持环境变量覆盖 server_url（用于灵活配置）
    gotenberg_url = os.environ.get('GOTENBERG_URL')
    if gotenberg_url:
        config['server_url'] = gotenberg_url
    
    return config


@lru_cache()
def get_gotenberg_server_url(env: str = None) -> str:
    """
    获取Gotenberg服务器地址
    
    Args:
        env: 环境名称
        
    Returns:
        str: 服务器地址
    """
    config = get_gotenberg_config(env)
    return config['server_url']
