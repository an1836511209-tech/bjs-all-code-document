#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块
负责加载和管理系统配置
"""

import os
import yaml
import logging
from typing import Dict, Any, Optional
from pathlib import Path


class ConfigManager:
    """
    配置管理器
    单例模式管理系统配置
    """
    
    _instance = None
    _config = None
    
    def __new__(cls, config_path: Optional[str] = None):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, config_path: Optional[str] = None):
        if self._config is None:
            self.logger = logging.getLogger(__name__)
            self._config_path = config_path or self._find_config_file()
            self._config = self._load_config()
    
    def _find_config_file(self) -> str:
        """
        查找配置文件
        
        Returns:
            配置文件路径
        """
        # 查找顺序：优先config目录 -> 当前目录 -> 上级目录
        possible_paths = [
            'config/config.yaml',    # 优先查找config目录下的配置文件
            'config.yaml',           # 当前目录
            '../config/config.yaml', # 上级目录的config目录
            '../config.yaml',        # 上级目录
            '../../config.yaml'      # 再上级目录
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        raise FileNotFoundError("未找到配置文件config.yaml，请确保config/config.yaml文件存在")
    
    def _load_config(self) -> Dict[str, Any]:
        """
        加载配置文件
        
        Returns:
            配置字典
        """
        try:
            with open(self._config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            # 验证必要的配置项
            self._validate_config(config)
            
            self.logger.info(f"配置文件加载成功: {self._config_path}")
            return config
            
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
            raise
    
    def _validate_config(self, config: Dict[str, Any]) -> None:
        """
        验证配置文件必要项
        
        Args:
            config: 配置字典
        """
        required_sections = ['database', 'api', 'operational_api', 'logging']
        
        for section in required_sections:
            if section not in config:
                raise ValueError(f"配置文件缺少必要节点: {section}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值（支持点分割路径）
        
        Args:
            key: 配置键，支持点分割（如 'database.host'）
            default: 默认值
            
        Returns:
            配置值
        """
        keys = key.split('.')
        value = self._config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """
        获取配置节
        
        Args:
            section: 节名
            
        Returns:
            配置节字典
        """
        return self._config.get(section, {})
    
    def reload(self) -> None:
        """
        重新加载配置文件
        """
        self._config = self._load_config()
        self.logger.info("配置文件已重新加载")
    
    @property
    def config(self) -> Dict[str, Any]:
        """
        获取完整配置
        
        Returns:
            配置字典
        """
        return self._config
    
    @property
    def config_path(self) -> str:
        """
        获取配置文件路径
        
        Returns:
            配置文件路径
        """
        return self._config_path


# 全局配置实例
config_manager = ConfigManager()


def get_config(key: str = None, default: Any = None) -> Any:
    """
    获取配置的便捷函数
    
    Args:
        key: 配置键
        default: 默认值
        
    Returns:
        配置值或完整配置
    """
    if key is None:
        return config_manager.config
    return config_manager.get(key, default)


def get_config_section(section: str) -> Dict[str, Any]:
    """
    获取配置节的便捷函数
    
    Args:
        section: 节名
        
    Returns:
        配置节字典
    """
    return config_manager.get_section(section)
