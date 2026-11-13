"""
API限流中间件

提供基于asyncio.Semaphore的API并发限流功能
"""

import asyncio
import time
from typing import Dict, Callable, Any, AsyncGenerator
from functools import wraps
from contextlib import asynccontextmanager
from loguru import logger

from config.api_config import get_rate_limit_config


# 全局信号量字典，为每个端点维护独立的Semaphore
_semaphores: Dict[str, asyncio.Semaphore] = {}

# 请求计数器（用于监控和日志）
_request_counters: Dict[str, int] = {}
_active_requests: Dict[str, int] = {}


def init_rate_limiter():
    """
    初始化限流器
    
    根据配置创建各端点的Semaphore实例
    """
    global _semaphores, _request_counters, _active_requests
    
    config = get_rate_limit_config()
    limits = config.to_dict()
    
    logger.info("初始化API限流器...")
    
    for endpoint_name, max_concurrent in limits.items():
        _semaphores[endpoint_name] = asyncio.Semaphore(max_concurrent)
        _request_counters[endpoint_name] = 0
        _active_requests[endpoint_name] = 0
        logger.info(f"  - {endpoint_name}: 最大并发数={max_concurrent}")
    
    logger.info("✅ API限流器初始化完成")


def get_semaphore(endpoint_name: str) -> asyncio.Semaphore:
    """
    获取指定端点的信号量
    
    Args:
        endpoint_name: 端点名称
        
    Returns:
        asyncio.Semaphore: 信号量对象
        
    Raises:
        ValueError: 如果端点未初始化
    """
    if endpoint_name not in _semaphores:
        raise ValueError(f"端点 {endpoint_name} 的限流器未初始化，请先调用 init_rate_limiter()")
    
    return _semaphores[endpoint_name]


def rate_limit(endpoint_name: str):
    """
    限流装饰器
    
    控制指定端点的并发请求数量，超过限制的请求会自动排队等待
    
    Args:
        endpoint_name: 端点名称（如 'extraction_sync', 'audit_sync'）
        
    Example:
        @rate_limit("extraction_sync")
        async def extract_fields_sync(request: ExtractionRequest):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # 获取信号量
            semaphore = get_semaphore(endpoint_name)
            
            # 增加请求计数
            _request_counters[endpoint_name] = _request_counters.get(endpoint_name, 0) + 1
            request_id = _request_counters[endpoint_name]
            
            # 记录当前活跃请求数
            active = _active_requests.get(endpoint_name, 0)
            waiting_count = max(0, active - semaphore._value)
            
            # 如果需要等待，记录日志
            if semaphore.locked():
                logger.info(
                    f"[限流] {endpoint_name} 请求#{request_id} 等待执行 "
                    f"(活跃: {active}, 排队: {waiting_count})"
                )
            
            start_time = time.time()
            
            # 获取信号量（如果达到限制会自动等待）
            async with semaphore:
                # 更新活跃请求计数
                _active_requests[endpoint_name] = _active_requests.get(endpoint_name, 0) + 1
                active = _active_requests[endpoint_name]
                
                wait_time = time.time() - start_time
                
                # 记录获取信号量的日志
                if wait_time > 0.1:  # 等待超过100ms才记录
                    logger.info(
                        f"[限流] {endpoint_name} 请求#{request_id} 开始执行 "
                        f"(等待: {wait_time:.2f}s, 活跃: {active})"
                    )
                else:
                    logger.debug(
                        f"[限流] {endpoint_name} 请求#{request_id} 开始执行 "
                        f"(活跃: {active})"
                    )
                
                try:
                    # 执行实际的函数
                    result = await func(*args, **kwargs)
                    return result
                finally:
                    # 减少活跃请求计数
                    _active_requests[endpoint_name] -= 1
                    active = _active_requests[endpoint_name]
                    
                    execution_time = time.time() - start_time - wait_time
                    logger.debug(
                        f"[限流] {endpoint_name} 请求#{request_id} 执行完成 "
                        f"(耗时: {execution_time:.2f}s, 剩余活跃: {active})"
                    )
        
        return wrapper
    return decorator


@asynccontextmanager
async def rate_limit_context(endpoint_name: str):
    """
    限流上下文管理器
    
    用于流式接口，确保在整个流式传输过程中持有信号量
    
    Args:
        endpoint_name: 端点名称
        
    Example:
        async with rate_limit_context("extraction_stream"):
            # 流式处理逻辑
            async for item in generator:
                yield item
    """
    semaphore = get_semaphore(endpoint_name)
    
    # 增加请求计数
    _request_counters[endpoint_name] = _request_counters.get(endpoint_name, 0) + 1
    request_id = _request_counters[endpoint_name]
    
    # 记录当前活跃请求数
    active = _active_requests.get(endpoint_name, 0)
    
    # 如果需要等待，记录日志
    if semaphore.locked():
        logger.info(
            f"[限流] {endpoint_name} 请求#{request_id} 等待执行 "
            f"(活跃: {active})"
        )
    
    start_time = time.time()
    
    # 获取信号量
    await semaphore.acquire()
    
    try:
        # 更新活跃请求计数
        _active_requests[endpoint_name] = _active_requests.get(endpoint_name, 0) + 1
        active = _active_requests[endpoint_name]
        
        wait_time = time.time() - start_time
        
        # 记录获取信号量的日志
        if wait_time > 0.1:
            logger.info(
                f"[限流] {endpoint_name} 请求#{request_id} 开始执行 "
                f"(等待: {wait_time:.2f}s, 活跃: {active})"
            )
        else:
            logger.debug(
                f"[限流] {endpoint_name} 请求#{request_id} 开始执行 "
                f"(活跃: {active})"
            )
        
        yield request_id
        
    finally:
        # 释放信号量
        semaphore.release()
        
        # 减少活跃请求计数
        _active_requests[endpoint_name] -= 1
        active = _active_requests[endpoint_name]
        
        execution_time = time.time() - start_time
        logger.debug(
            f"[限流] {endpoint_name} 请求#{request_id} 执行完成 "
            f"(总耗时: {execution_time:.2f}s, 剩余活跃: {active})"
        )


def get_rate_limit_stats() -> Dict[str, Dict[str, int]]:
    """
    获取限流统计信息
    
    Returns:
        Dict[str, Dict[str, int]]: 各端点的统计信息
    """
    stats = {}
    
    for endpoint_name in _semaphores.keys():
        semaphore = _semaphores[endpoint_name]
        stats[endpoint_name] = {
            "max_concurrent": semaphore._value + (_active_requests.get(endpoint_name, 0)),
            "available": semaphore._value,
            "active": _active_requests.get(endpoint_name, 0),
            "total_requests": _request_counters.get(endpoint_name, 0),
        }
    
    return stats

