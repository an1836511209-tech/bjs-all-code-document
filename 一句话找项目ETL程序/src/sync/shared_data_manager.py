#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共享数据管理器
负责统一获取API数据，避免重复调用，提高同步效率
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from src.api.project_api import ProjectAPIClient


class SharedDataManager:
    """
    共享数据管理器
    
    统一管理API数据的获取和分发，避免重复调用同一个API接口
    实现一次API调用，多个子表共享数据的模式
    """
    
    def __init__(self):
        """
        初始化共享数据管理器
        """
        self.logger = logging.getLogger(__name__)
        self.api_client = ProjectAPIClient()
        
        # 缓存API数据
        self._cached_data = None
        self._cache_timestamp = None
        self._cache_params = None
    
    def get_shared_data(self, last_sync_time: Optional[str] = None, 
                       force_full: bool = False, force_refresh: bool = False) -> Dict[str, Any]:
        """
        获取共享数据（带缓存机制）
        
        Args:
            last_sync_time: 上次同步时间
            force_full: 是否强制全量同步
            force_refresh: 是否强制刷新缓存
            
        Returns:
            API响应数据
        """
        try:
            # 构建请求参数标识
            current_params = {
                'last_sync_time': last_sync_time,
                'force_full': force_full
            }
            
            # 检查是否需要重新获取数据
            if (not force_refresh and 
                self._cached_data is not None and 
                self._cache_params == current_params and
                self._is_cache_valid()):
                
                self.logger.info("使用缓存的API数据")
                return self._cached_data
            
            # 获取新数据
            self.logger.info("开始获取API数据...")
            
            if force_full:
                self.logger.info("执行全量数据同步")
                api_response = self.api_client.get_full_data()
            else:
                self.logger.info(f"执行增量数据同步，基准时间: {last_sync_time}")
                api_response = self.api_client.get_incremental_data(last_sync_time)
            
            # 缓存数据
            self._cached_data = api_response
            self._cache_timestamp = datetime.now()
            self._cache_params = current_params
            
            all_data = api_response.get('list', [])
            self.logger.info(f"✅ 从API获取到 {len(all_data)} 条数据")
            
            return api_response
            
        except Exception as e:
            self.logger.error(f"获取共享数据失败: {e}")
            raise
    
    def get_data_by_biz_sys(self, biz_sys: str, last_sync_time: Optional[str] = None,
                           force_full: bool = False) -> List[Dict[str, Any]]:
        """
        根据业务系统过滤数据
        
        Args:
            biz_sys: 业务系统名称
            last_sync_time: 上次同步时间
            force_full: 是否强制全量同步
            
        Returns:
            过滤后的数据列表
        """
        try:
            # 获取共享数据
            api_response = self.get_shared_data(last_sync_time, force_full)
            all_data = api_response.get('list', [])
            
            # 过滤出指定业务系统的数据
            filtered_data = []
            for item in all_data:
                if item.get('bizSys') == biz_sys:
                    filtered_data.append(item)
            
            self.logger.info(f"业务系统 '{biz_sys}' 过滤后数据: {len(filtered_data)} 条")
            return filtered_data
            
        except Exception as e:
            self.logger.error(f"根据业务系统获取数据失败 {biz_sys}: {e}")
            raise
    
    def get_all_biz_sys_data(self, biz_sys_list: List[str], 
                            last_sync_time: Optional[str] = None,
                            force_full: bool = False) -> Dict[str, List[Dict[str, Any]]]:
        """
        一次性获取所有业务系统的数据
        
        Args:
            biz_sys_list: 业务系统列表
            last_sync_time: 上次同步时间
            force_full: 是否强制全量同步
            
        Returns:
            按业务系统分组的数据字典
        """
        try:
            # 获取共享数据
            api_response = self.get_shared_data(last_sync_time, force_full)
            all_data = api_response.get('list', [])
            
            # 按业务系统分组数据
            grouped_data = {}
            for biz_sys in biz_sys_list:
                grouped_data[biz_sys] = []
            
            # 分类数据
            for item in all_data:
                biz_sys = item.get('bizSys')
                if biz_sys in grouped_data:
                    grouped_data[biz_sys].append(item)
            
            # 记录统计信息
            for biz_sys, data in grouped_data.items():
                self.logger.info(f"业务系统 '{biz_sys}': {len(data)} 条数据")
            
            return grouped_data
            
        except Exception as e:
            self.logger.error(f"获取所有业务系统数据失败: {e}")
            raise
    
    def _is_cache_valid(self, cache_timeout_minutes: int = 30) -> bool:
        """
        检查缓存是否有效
        
        Args:
            cache_timeout_minutes: 缓存超时时间（分钟）
            
        Returns:
            缓存是否有效
        """
        if self._cache_timestamp is None:
            return False
        
        time_diff = datetime.now() - self._cache_timestamp
        return time_diff.total_seconds() < cache_timeout_minutes * 60
    
    def clear_cache(self):
        """
        清空缓存
        """
        self._cached_data = None
        self._cache_timestamp = None
        self._cache_params = None
        self.logger.info("已清空数据缓存")
    
    def get_cache_info(self) -> Dict[str, Any]:
        """
        获取缓存信息
        
        Returns:
            缓存状态信息
        """
        if self._cached_data is None:
            return {
                'has_cache': False,
                'cache_timestamp': None,
                'cache_size': 0
            }
        
        return {
            'has_cache': True,
            'cache_timestamp': self._cache_timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'cache_size': len(self._cached_data.get('list', [])),
            'is_valid': self._is_cache_valid()
        }
    
    def close(self):
        """
        关闭连接并清理资源
        """
        try:
            if self.api_client:
                self.api_client.close()
            self.clear_cache()
            self.logger.info("共享数据管理器已关闭")
        except Exception as e:
            self.logger.error(f"关闭共享数据管理器失败: {e}")

