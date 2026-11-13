"""
日志配置模块

提供统一的日志配置和管理功能
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger


class LogConfig:
    """日志配置管理器"""
    
    def __init__(self):
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)
        
        # 确保logs目录存在
        if not self.log_dir.exists():
            self.log_dir.mkdir(parents=True)
    
    def setup_logger(self, 
                    debug: bool = False,
                    enable_file_logging: bool = True,
                    log_level: str = None) -> None:
        """
        设置日志配置
        
        日志级别优先级：
        1. 显式传入的 log_level 参数
        2. 环境变量 LOG_LEVEL
        3. 根据 ENV 环境自动判断（prod=INFO, dev=DEBUG）
        
        Args:
            debug: 是否启用调试模式（已废弃，改用log_level）
            enable_file_logging: 是否启用文件日志
            log_level: 日志级别（INFO/DEBUG/WARNING/ERROR），None表示自动判断
        """
        # 确定日志级别（优先级：参数 > 环境变量 > 环境判断）
        if log_level is None:
            # 优先从环境变量读取
            log_level = os.getenv("LOG_LEVEL")
            
            if log_level is None:
                # 根据ENV环境判断
                env = os.getenv("ENV", "prod").lower()
                if env == "prod":
                    log_level = "INFO"  # 生产环境默认INFO级别
                else:
                    log_level = "DEBUG"  # 开发环境默认DEBUG级别
                    
        # 将log_level统一转换为大写
        log_level = log_level.upper() if log_level else "INFO"
        # 移除默认处理器
        logger.remove()
        
        # 控制台日志配置
        console_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        )
        
        if debug:
            console_format = (
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<magenta>{extra[trace_id]}</magenta> - "
                "<level>{message}</level>"
            )
        
        # 添加控制台处理器
        # debug参数向后兼容，但优先使用log_level
        effective_level = "DEBUG" if (debug and log_level == "INFO") else log_level
        logger.add(
            sys.stdout,
            format=console_format,
            level=effective_level,
            colorize=True,
            backtrace=(log_level == "DEBUG"),
            diagnose=(log_level == "DEBUG")
        )
        
        if enable_file_logging:
            self._setup_file_logging(debug, log_level)
        
        # 设置全局extra信息
        logger.configure(extra={"trace_id": "main"})
        
        logger.info(f"🔧 日志系统初始化完成 - 级别: {log_level}, 调试: {debug}")
    
    def _setup_file_logging(self, debug: bool, log_level: str) -> None:
        """设置文件日志"""
        
        # 详细日志文件格式
        file_format = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} | {extra[trace_id]} | {message}"
        )
        
        # 通用日志文件（所有日志）
        logger.add(
            self.log_dir / "app_{time:YYYY-MM-DD}.log",
            format=file_format,
            level=log_level,
            rotation="1 day",
            retention="30 days",
            compression="zip",
            encoding="utf-8",
            backtrace=debug,
            diagnose=debug
        )
        
        # 错误日志文件（仅错误）
        logger.add(
            self.log_dir / "error_{time:YYYY-MM-DD}.log",
            format=file_format,
            level="ERROR",
            rotation="1 day", 
            retention="90 days",
            compression="zip",
            encoding="utf-8",
            backtrace=True,
            diagnose=True
        )
        
        # 调试模式下的详细日志
        if debug:
            logger.add(
                self.log_dir / "debug_{time:YYYY-MM-DD}.log",
                format=file_format,
                level="DEBUG",
                rotation="1 day",
                retention="7 days",
                compression="zip",
                encoding="utf-8",
                backtrace=True,
                diagnose=True
            )
            
            # 文件质量检测专用日志
            logger.add(
                self.log_dir / "quality_check_{time:YYYY-MM-DD}.log",
                format=file_format,
                level="DEBUG",
                rotation="1 day",
                retention="14 days",
                compression="zip",
                encoding="utf-8",
                filter=lambda record: "quality_check" in record["extra"],
                backtrace=True,
                diagnose=True
            )
    
    def get_logger(self, name: str, trace_id: Optional[str] = None):
        """
        获取带上下文的logger
        
        Args:
            name: logger名称
            trace_id: 追踪ID
            
        Returns:
            配置好的logger实例
        """
        extra = {"trace_id": trace_id or "unknown"}
        return logger.bind(**extra)


# 全局日志配置实例
log_config = LogConfig()

# 便捷函数
def setup_logging(debug: bool = False, log_level: str = "INFO"):
    """设置日志系统"""
    log_config.setup_logger(debug=debug, log_level=log_level)

def get_logger(name: str, trace_id: Optional[str] = None):
    """获取logger实例"""
    return log_config.get_logger(name, trace_id)
