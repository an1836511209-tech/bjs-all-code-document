"""
进程池管理器模块

用于管理 CPU 密集型任务的进程池，支持：
1. 图像质量检测（OpenCV 计算）
2. PDF 页面转换和处理（PyMuPDF 渲染）

针对 Linux 环境优化，使用 spawn 模式避免 fork 相关问题。
"""

import os
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from typing import Optional

from loguru import logger


def _init_multiprocessing():
    """
    初始化多进程启动方法
    
    Linux 环境下使用 spawn 模式，避免 fork 导致的问题：
    - OpenCV、PyMuPDF 等 C 扩展的初始化问题
    - 日志处理器的重复问题
    - 文件句柄的复制问题
    """
    try:
        current_method = mp.get_start_method(allow_none=True)
        if current_method != 'spawn':
            mp.set_start_method('spawn', force=True)
            logger.debug(f"多进程启动方法已设置为 'spawn'（原为 '{current_method}'）")
    except RuntimeError:
        # 已经设置过，忽略
        pass


# 模块加载时初始化多进程设置
_init_multiprocessing()


class ProcessPoolManager:
    """
    CPU 密集型任务的进程池管理器（Linux 优化版）
    
    特点：
    - 使用 spawn 模式创建子进程
    - 延迟初始化，首次使用时创建
    - 支持通过环境变量配置 worker 数量
    - 提供优雅关闭方法
    
    使用示例：
        executor = ProcessPoolManager.get_executor()
        future = executor.submit(cpu_intensive_func, arg1, arg2)
        result = future.result()
        
    异步使用：
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            ProcessPoolManager.get_executor(),
            cpu_intensive_func,
            arg1, arg2
        )
    """
    
    _executor: Optional[ProcessPoolExecutor] = None
    _max_workers: int = 0
    
    @classmethod
    def get_executor(cls) -> ProcessPoolExecutor:
        """
        获取进程池执行器（延迟初始化）
        
        Returns:
            ProcessPoolExecutor: 进程池执行器实例
        """
        if cls._executor is None:
            # 从环境变量读取配置，默认使用 CPU 核心数的一半到 20 之间
            cpu_count = os.cpu_count() or 4
            default_workers = min(max(cpu_count // 2, 4), 20)
            cls._max_workers = int(os.getenv("QUALITY_CHECK_MAX_WORKERS", default_workers))
            
            cls._executor = ProcessPoolExecutor(max_workers=cls._max_workers)
            logger.info(f"✅ 进程池初始化完成，worker 数量: {cls._max_workers}")
        
        return cls._executor
    
    @classmethod
    def get_max_workers(cls) -> int:
        """获取当前配置的最大 worker 数量"""
        if cls._executor is None:
            cls.get_executor()  # 触发初始化
        return cls._max_workers
    
    @classmethod
    def shutdown(cls, wait: bool = True):
        """
        关闭进程池
        
        Args:
            wait: 是否等待所有任务完成
        """
        if cls._executor is not None:
            logger.info("正在关闭进程池...")
            cls._executor.shutdown(wait=wait)
            cls._executor = None
            logger.info("✅ 进程池已关闭")
    
    @classmethod
    def is_initialized(cls) -> bool:
        """检查进程池是否已初始化"""
        return cls._executor is not None





