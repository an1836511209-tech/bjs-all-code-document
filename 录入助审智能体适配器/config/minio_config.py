"""
MinIO对象存储配置
"""

from typing import Dict, Any
from functools import lru_cache
from config.env_config import get_current_env


# MinIO 配置
MINIO_CONFIG = {
    # 'dev': {
    #     'endpoint': '115.190.11.152:9000',
    #     'access_key': 'j00MvwsnLsZyuEogxPRb',
    #     'secret_key': 'TzMr41qepvJZGpmOVdZtFX3WeY6yKlG2U6g3wrmY',
    #     'secure': False,
    #     'bucket_name': 'pdf-highlights',
    #     'file_prefix': 'highlights',
    #     'public_url': 'http://115.190.11.152:9000',
    #     'connect_timeout': 30,
    #     'read_timeout': 60,
    # },
    'dev': {
        'endpoint': '10.254.89.130:9000',
        'access_key': '8jhcKkxmALabS1KtptAY',
        'secret_key': 'stfeFAE9Vr9jgPosPWYzKpXMUdJ6Nr5F4dEuoCqk',
        'secure': False,
        'bucket_name': 'bjs-file',
        'file_prefix': 'highlights',
        'public_url': 'http://10.254.89.130:9000',
        'connect_timeout': 30,
        'read_timeout': 60,
    },
    'prod': {
        'endpoint': '10.254.89.130:9000',
        'access_key': '8jhcKkxmALabS1KtptAY',
        'secret_key': 'stfeFAE9Vr9jgPosPWYzKpXMUdJ6Nr5F4dEuoCqk',
        'secure': False,
        'bucket_name': 'bjs-file',
        'file_prefix': 'highlights',
        'public_url': 'http://10.254.89.130:9000',
        'connect_timeout': 30,
        'read_timeout': 60,
    }
}

# 当前环境（从全局环境配置获取）
CURRENT_ENV = get_current_env()


def get_minio_config(env: str = None) -> Dict[str, Any]:
    """
    获取MinIO配置
    
    Args:
        env: 环境名称（dev/prod），默认使用CURRENT_ENV
        
    Returns:
        dict: MinIO配置字典
    """
    if env is None:
        env = CURRENT_ENV
    
    return MINIO_CONFIG.get(env, MINIO_CONFIG['dev'])


@lru_cache()
def get_minio_endpoint(env: str = None) -> str:
    """
    获取MinIO服务器地址
    
    Args:
        env: 环境名称
        
    Returns:
        str: 服务器地址
    """
    config = get_minio_config(env)
    return config['endpoint']



