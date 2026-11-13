"""
MinIO对象存储清理工具

提供两种清理方式：
1. 使用MinIO生命周期策略自动清理（推荐）
2. 手动清理脚本，可定期执行
"""

import sys
from datetime import datetime
from typing import Optional

from loguru import logger

from src.utils.minio.client import get_minio_client, MinIOClientError
from config.env_config import get_current_env


class MinIOCleanupService:
    """MinIO清理服务"""
    
    def __init__(self):
        """初始化清理服务"""
        self.client = get_minio_client()
    
    def setup_auto_cleanup(self, days: int = 7) -> bool:
        """
        设置MinIO自动清理策略（推荐方式）
        
        使用MinIO的生命周期策略，自动删除超过指定天数的对象
        
        Args:
            days: 对象保留天数，超过此天数的对象将被自动删除
            
        Returns:
            bool: 是否设置成功
        """
        try:
            logger.info(f"正在设置MinIO生命周期策略: {days}天后自动删除")
            
            # 设置生命周期规则
            self.client.set_bucket_lifecycle(
                days=days,
                prefix=self.client.file_prefix  # 只对高亮图片目录生效
            )
            
            logger.info(f"✓ 生命周期策略设置成功: {self.client.file_prefix}/* 将在 {days} 天后自动删除")
            
            # 验证设置
            lifecycle = self.client.get_bucket_lifecycle()
            if lifecycle:
                logger.info(f"✓ 当前生命周期配置: {lifecycle}")
            
            return True
            
        except MinIOClientError as e:
            logger.error(f"✗ 设置生命周期策略失败: {str(e)}")
            return False
    
    def manual_cleanup(self) -> int:
        """
        手动清理过期对象
        
        根据对象元数据中的expires-at字段判断是否过期并删除
        
        Returns:
            int: 删除的对象数量
        """
        try:
            logger.info("开始手动清理过期对象...")
            
            deleted_objects = self.client.cleanup_expired_objects(check_metadata=True)
            
            if deleted_objects:
                logger.info(f"✓ 清理完成，删除了 {len(deleted_objects)} 个过期对象:")
                for obj in deleted_objects:
                    logger.info(f"  - {obj}")
            else:
                logger.info("✓ 没有发现过期对象")
            
            return len(deleted_objects)
            
        except MinIOClientError as e:
            logger.error(f"✗ 清理过期对象失败: {str(e)}")
            return 0
    
    def get_lifecycle_status(self) -> Optional[str]:
        """
        获取当前生命周期配置状态
        
        Returns:
            Optional[str]: 生命周期配置信息，如果未配置则返回None
        """
        try:
            lifecycle = self.client.get_bucket_lifecycle()
            if lifecycle:
                return str(lifecycle)
            else:
                return None
        except MinIOClientError as e:
            logger.error(f"获取生命周期配置失败: {str(e)}")
            return None
    
    def remove_lifecycle(self) -> bool:
        """
        移除生命周期策略
        
        Returns:
            bool: 是否移除成功
        """
        try:
            logger.info("正在移除MinIO生命周期策略...")
            self.client.delete_bucket_lifecycle()
            logger.info("✓ 生命周期策略已移除")
            return True
        except MinIOClientError as e:
            logger.error(f"✗ 移除生命周期策略失败: {str(e)}")
            return False


def setup_auto_cleanup(days: int = 7) -> None:
    """
    设置MinIO自动清理（推荐使用此方法）
    
    Args:
        days: 对象保留天数
    """
    service = MinIOCleanupService()
    service.setup_auto_cleanup(days=days)


def manual_cleanup() -> None:
    """
    手动执行清理任务
    
    可以通过cron或Celery定期调用此函数
    """
    service = MinIOCleanupService()
    service.manual_cleanup()


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="MinIO对象存储清理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 设置7天自动清理策略（推荐）
  python -m src.utils.minio_cleanup --setup 7
  
  # 手动清理过期对象
  python -m src.utils.minio_cleanup --cleanup
  
  # 查看当前生命周期配置
  python -m src.utils.minio_cleanup --status
  
  # 移除生命周期策略
  python -m src.utils.minio_cleanup --remove
        """
    )
    
    parser.add_argument(
        '--setup',
        type=int,
        metavar='DAYS',
        help='设置MinIO生命周期策略，自动删除超过指定天数的对象'
    )
    
    parser.add_argument(
        '--cleanup',
        action='store_true',
        help='手动清理过期对象（根据元数据中的过期时间）'
    )
    
    parser.add_argument(
        '--status',
        action='store_true',
        help='查看当前生命周期配置状态'
    )
    
    parser.add_argument(
        '--remove',
        action='store_true',
        help='移除生命周期策略'
    )
    
    args = parser.parse_args()
    
    service = MinIOCleanupService()
    
    if args.setup:
        service.setup_auto_cleanup(days=args.setup)
    elif args.cleanup:
        service.manual_cleanup()
    elif args.status:
        status = service.get_lifecycle_status()
        if status:
            logger.info(f"当前生命周期配置:\n{status}")
        else:
            logger.info("未配置生命周期策略")
    elif args.remove:
        service.remove_lifecycle()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()

