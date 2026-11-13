"""
MinIO初始化模块

在应用启动时自动初始化MinIO配置，包括设置生命周期策略
"""

from loguru import logger

from src.utils.minio.client import get_minio_client, MinIOClientError
from config.env_config import get_current_env


def initialize_minio(auto_cleanup_days: int = 7) -> None:
    """
    初始化MinIO配置
    
    Args:
        auto_cleanup_days: 自动清理天数，默认7天
    """
    try:
        logger.info("正在初始化MinIO配置...")
        
        # 获取MinIO客户端
        client = get_minio_client()
        
        # 检查bucket是否存在（客户端初始化时会自动创建）
        logger.info(f"✓ MinIO连接成功，使用bucket: {client.bucket_name}")
        
        # 设置生命周期策略
        if auto_cleanup_days > 0:
            try:
                client.set_bucket_lifecycle(
                    days=auto_cleanup_days,
                    prefix=client.file_prefix
                )
                logger.info(
                    f"✓ 生命周期策略已设置: {client.file_prefix}/* "
                    f"将在 {auto_cleanup_days} 天后自动删除"
                )
            except MinIOClientError as e:
                logger.warning(f"设置生命周期策略失败（可能MinIO版本不支持）: {str(e)}")
                logger.info("提示: 可以使用定期清理任务作为替代方案")
        
        logger.info("✓ MinIO初始化完成")
        
    except Exception as e:
        logger.error(f"✗ MinIO初始化失败: {str(e)}")
        logger.warning("应用将继续运行，但PDF高亮功能可能不可用")


def check_minio_health() -> bool:
    """
    检查MinIO连接健康状态
    
    Returns:
        bool: 连接是否正常
    """
    try:
        client = get_minio_client()
        # 尝试检查bucket是否存在
        exists = client.client.bucket_exists(client.bucket_name)
        return exists
    except Exception as e:
        logger.error(f"MinIO健康检查失败: {str(e)}")
        return False

