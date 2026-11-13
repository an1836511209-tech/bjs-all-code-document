"""
API接口配置

配置API接口的限流、超时等参数
"""

import os
from typing import Dict
from pydantic import BaseModel, Field
from loguru import logger


# ============================================================
# 外部访问配置
# ============================================================

# 外部访问基础URL（用于拼接文件预览等绝对路径）
# 格式：协议://IP或域名:端口，末尾不要加斜杠
# 示例：http://192.168.1.100:8000 或 https://api.example.com
# EXTERNAL_BASE_URL: str = os.getenv("EXTERNAL_BASE_URL", "http://10.254.89.129:7580")


# ============================================================
# 质量检测进程池配置
# ============================================================

def _get_default_quality_check_workers() -> int:
    """计算默认的质量检测进程池 worker 数量"""
    cpu_count = os.cpu_count() or 4
    # 使用 CPU 核心数的一半到 20 之间，预留资源给主进程和其他服务
    return min(max(cpu_count // 2, 4), 20)

# 质量检测进程池最大 worker 数量
# 用于图像质量检测和 PDF 页面处理等 CPU 密集型任务
# 建议值：CPU 核心数的一半，最大不超过 20
# 环境变量：QUALITY_CHECK_MAX_WORKERS
QUALITY_CHECK_MAX_WORKERS: int = int(
    os.getenv("QUALITY_CHECK_MAX_WORKERS", _get_default_quality_check_workers())
)


class RateLimitConfig(BaseModel):
    """API限流配置"""
    
    # 字段提取接口限流配置
    extraction_sync_max_concurrent: int = Field(
        default=15,
        description="字段提取同步接口最大并发数"
    )
    extraction_stream_max_concurrent: int = Field(
        default=15,
        description="字段提取流式接口最大并发数"
    )
    
    # 规则审核接口限流配置
    audit_sync_max_concurrent: int = Field(
        default=5,
        description="规则审核同步接口最大并发数"
    )
    audit_stream_max_concurrent: int = Field(
        default=5,
        description="规则审核流式接口最大并发数"
    )
    
    def get_limit(self, endpoint_name: str) -> int:
        """
        获取指定端点的限流配置
        
        Args:
            endpoint_name: 端点名称（如 'extraction_sync', 'audit_sync'）
            
        Returns:
            int: 最大并发数
        """
        attr_name = f"{endpoint_name}_max_concurrent"
        if hasattr(self, attr_name):
            return getattr(self, attr_name)
        
        logger.warning(f"未找到端点 {endpoint_name} 的限流配置，使用默认值 10")
        return 10
    
    def to_dict(self) -> Dict[str, int]:
        """
        转换为字典格式
        
        Returns:
            Dict[str, int]: 端点名称到最大并发数的映射
        """
        return {
            "extraction_sync": self.extraction_sync_max_concurrent,
            "extraction_stream": self.extraction_stream_max_concurrent,
            "audit_sync": self.audit_sync_max_concurrent,
            "audit_stream": self.audit_stream_max_concurrent,
        }


class APIConfig:
    """API配置"""
    
    # 默认配置
    _default_config = RateLimitConfig()
    
    # 当前配置
    _current_config: RateLimitConfig = _default_config
    
    @classmethod
    def get_rate_limit_config(cls) -> RateLimitConfig:
        """
        获取限流配置
        
        Returns:
            RateLimitConfig: 限流配置对象
        """
        return cls._current_config
    
    @classmethod
    def set_rate_limit_config(cls, config: RateLimitConfig):
        """
        设置限流配置
        
        Args:
            config: 限流配置对象
        """
        cls._current_config = config
        logger.info(f"限流配置已更新: {config.to_dict()}")
    
    @classmethod
    def init_from_env(cls):
        """
        从环境变量初始化配置
        
        环境变量格式：
        - EXTRACTION_SYNC_MAX_CONCURRENT: 字段提取同步接口最大并发数
        - EXTRACTION_STREAM_MAX_CONCURRENT: 字段提取流式接口最大并发数
        - AUDIT_SYNC_MAX_CONCURRENT: 规则审核同步接口最大并发数
        - AUDIT_STREAM_MAX_CONCURRENT: 规则审核流式接口最大并发数
        
        注意：如果环境变量未设置，将使用 RateLimitConfig 类定义的默认值
        """
        # 先创建默认配置（使用类定义的默认值）
        default_config = RateLimitConfig()
        
        # 从环境变量读取配置，如果未设置则使用默认值
        config = RateLimitConfig(
            extraction_sync_max_concurrent=int(
                os.getenv("EXTRACTION_SYNC_MAX_CONCURRENT", default_config.extraction_sync_max_concurrent)
            ),
            extraction_stream_max_concurrent=int(
                os.getenv("EXTRACTION_STREAM_MAX_CONCURRENT", default_config.extraction_stream_max_concurrent)
            ),
            audit_sync_max_concurrent=int(
                os.getenv("AUDIT_SYNC_MAX_CONCURRENT", default_config.audit_sync_max_concurrent)
            ),
            audit_stream_max_concurrent=int(
                os.getenv("AUDIT_STREAM_MAX_CONCURRENT", default_config.audit_stream_max_concurrent)
            ),
        )
        cls.set_rate_limit_config(config)


# 获取限流配置的便捷函数
def get_rate_limit_config() -> RateLimitConfig:
    """
    获取限流配置
    
    Returns:
        RateLimitConfig: 限流配置对象
    """
    return APIConfig.get_rate_limit_config()


# 默认初始化（从环境变量加载）
APIConfig.init_from_env()

