#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志配置和错误处理模块
提供统一的日志配置和错误处理机制
"""

import os
import sys
import logging
import logging.handlers
from datetime import datetime
from typing import Optional, Dict, Any
import traceback
import functools


class ColoredFormatter(logging.Formatter):
    """
    彩色日志格式化器
    """
    
    # 颜色代码
    COLORS = {
        'DEBUG': '\033[36m',    # 青色
        'INFO': '\033[32m',     # 绿色
        'WARNING': '\033[33m',  # 黄色
        'ERROR': '\033[31m',    # 红色
        'CRITICAL': '\033[35m', # 紫色
        'RESET': '\033[0m'      # 重置
    }
    
    def format(self, record):
        # 获取原始格式化结果
        log_message = super().format(record)
        
        # 添加颜色
        if record.levelname in self.COLORS:
            color = self.COLORS[record.levelname]
            reset = self.COLORS['RESET']
            log_message = f"{color}{log_message}{reset}"
        
        return log_message


class LoggerManager:
    """
    日志管理器
    负责配置和管理应用程序的日志系统
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化日志管理器
        
        Args:
            config: 日志配置字典
        """
        self.config = config or self._get_default_config()
        self.loggers = {}
        self._setup_root_logger()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """
        获取默认日志配置
        
        Returns:
            默认配置字典
        """
        return {
            'level': 'INFO',
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            'file': 'logs/sync.log',
            'max_bytes': 10 * 1024 * 1024,  # 10MB
            'backup_count': 5,
            'console_output': True,
            'colored_output': True
        }
    
    def _setup_root_logger(self):
        """
        设置根日志记录器
        """
        # 获取配置
        log_level = getattr(logging, self.config.get('level', 'INFO').upper())
        log_format = self.config.get('format')
        log_file = self.config.get('file')
        max_bytes = self.config.get('max_bytes', 10 * 1024 * 1024)
        backup_count = self.config.get('backup_count', 5)
        console_output = self.config.get('console_output', True)
        colored_output = self.config.get('colored_output', True)
        
        # 创建日志目录
        if log_file:
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
        
        # 清除现有的处理器
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # 设置日志级别
        root_logger.setLevel(log_level)
        
        handlers = []
        
        # 文件处理器
        if log_file:
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_formatter = logging.Formatter(log_format)
            file_handler.setFormatter(file_formatter)
            handlers.append(file_handler)
        
        # 控制台处理器
        if console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            if colored_output and sys.stdout.isatty():
                console_formatter = ColoredFormatter(log_format)
            else:
                console_formatter = logging.Formatter(log_format)
            console_handler.setFormatter(console_formatter)
            handlers.append(console_handler)
        
        # 添加处理器到根日志记录器
        for handler in handlers:
            root_logger.addHandler(handler)
    
    def get_logger(self, name: str) -> logging.Logger:
        """
        获取指定名称的日志记录器
        
        Args:
            name: 日志记录器名称
            
        Returns:
            日志记录器实例
        """
        if name not in self.loggers:
            logger = logging.getLogger(name)
            self.loggers[name] = logger
        
        return self.loggers[name]
    
    def set_level(self, level: str):
        """
        设置日志级别
        
        Args:
            level: 日志级别字符串
        """
        log_level = getattr(logging, level.upper())
        logging.getLogger().setLevel(log_level)
        
        # 更新所有处理器的级别
        for handler in logging.getLogger().handlers:
            handler.setLevel(log_level)


class ErrorHandler:
    """
    错误处理器
    提供统一的错误处理和记录机制
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        初始化错误处理器
        
        Args:
            logger: 日志记录器
        """
        self.logger = logger or logging.getLogger(__name__)
    
    def handle_exception(self, exc: Exception, context: str = "", 
                        reraise: bool = True) -> Optional[str]:
        """
        处理异常
        
        Args:
            exc: 异常对象
            context: 上下文信息
            reraise: 是否重新抛出异常
            
        Returns:
            错误信息字符串
        """
        error_msg = f"{context}: {str(exc)}" if context else str(exc)
        
        # 记录错误日志
        self.logger.error(error_msg)
        self.logger.error(traceback.format_exc())
        
        # 是否重新抛出异常
        if reraise:
            raise exc
        
        return error_msg
    
    def log_and_raise(self, message: str, exception_class: type = Exception):
        """
        记录错误并抛出异常
        
        Args:
            message: 错误消息
            exception_class: 异常类型
        """
        self.logger.error(message)
        raise exception_class(message)


def exception_handler(logger: Optional[logging.Logger] = None, 
                     reraise: bool = True, 
                     default_return: Any = None):
    """
    异常处理装饰器
    
    Args:
        logger: 日志记录器
        reraise: 是否重新抛出异常
        default_return: 异常时的默认返回值
        
    Returns:
        装饰器函数
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_logger = logger or logging.getLogger(func.__module__)
                error_handler = ErrorHandler(error_logger)
                
                context = f"函数 {func.__name__} 执行失败"
                
                if reraise:
                    error_handler.handle_exception(e, context, reraise=True)
                else:
                    error_handler.handle_exception(e, context, reraise=False)
                    return default_return
        
        return wrapper
    return decorator


def retry_on_exception(max_retries: int = 3, 
                      delay: float = 1.0, 
                      exceptions: tuple = (Exception,),
                      logger: Optional[logging.Logger] = None):
    """
    异常重试装饰器
    
    Args:
        max_retries: 最大重试次数
        delay: 重试延迟（秒）
        exceptions: 需要重试的异常类型
        logger: 日志记录器
        
    Returns:
        装饰器函数
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retry_logger = logger or logging.getLogger(func.__module__)
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries:
                        retry_logger.error(f"函数 {func.__name__} 重试 {max_retries} 次后仍然失败")
                        raise e
                    else:
                        retry_logger.warning(
                            f"函数 {func.__name__} 第 {attempt + 1} 次尝试失败，{delay} 秒后重试: {e}"
                        )
                        import time
                        time.sleep(delay)
        
        return wrapper
    return decorator


class PerformanceMonitor:
    """
    性能监控器
    用于监控函数执行时间和性能
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        初始化性能监控器
        
        Args:
            logger: 日志记录器
        """
        self.logger = logger or logging.getLogger(__name__)
    
    def monitor(self, func_name: str = ""):
        """
        性能监控装饰器
        
        Args:
            func_name: 函数名称（可选）
            
        Returns:
            装饰器函数
        """
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                import time
                
                name = func_name or func.__name__
                start_time = time.time()
                
                try:
                    result = func(*args, **kwargs)
                    end_time = time.time()
                    execution_time = end_time - start_time
                    
                    self.logger.info(f"函数 {name} 执行完成，耗时: {execution_time:.3f} 秒")
                    return result
                    
                except Exception as e:
                    end_time = time.time()
                    execution_time = end_time - start_time
                    
                    self.logger.error(f"函数 {name} 执行失败，耗时: {execution_time:.3f} 秒，错误: {e}")
                    raise
            
            return wrapper
        return decorator


# 全局日志管理器实例
_global_logger_manager = None


def setup_logging(config: Optional[Dict[str, Any]] = None) -> LoggerManager:
    """
    设置全局日志配置
    
    Args:
        config: 日志配置字典
        
    Returns:
        日志管理器实例
    """
    global _global_logger_manager
    _global_logger_manager = LoggerManager(config)
    return _global_logger_manager


def get_logger(name: str) -> logging.Logger:
    """
    获取日志记录器
    
    Args:
        name: 日志记录器名称
        
    Returns:
        日志记录器实例
    """
    global _global_logger_manager
    if _global_logger_manager is None:
        _global_logger_manager = LoggerManager()
    
    return _global_logger_manager.get_logger(name)
