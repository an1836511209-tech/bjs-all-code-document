#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
项目数据API客户端模块
负责与项目数据API接口的通信
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from .base_client import BaseAPIClient, APIException
from src.core.config import get_config


class ProjectAPIClient(BaseAPIClient):
    """
    项目数据API客户端
    负责与项目数据API接口通信
    """
    
    def __init__(self):
        """
        初始化项目数据API客户端
        """
        super().__init__('api')
        self.base_url = self.config.get('base_url')
        if not self.base_url:
            raise ValueError("未配置项目数据API base_url")
    
    def get_project_data(self, update_time: Optional[str] = None, 
                        is_full: int = 0, page: int = 1, 
                        limit: int = 999999999, project_code: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        获取项目数据
        
        Args:
            update_time: 更新时间，格式: YYYY-MM-DD
            is_full: 是否全量同步，0为增量，1为全量
            page: 页码
            limit: 每页数量
            project_code: 项目代码列表（可选）
            
        Returns:
            API响应数据
        """
        try:
            # 如果没有指定更新时间，使用配置中的默认时间
            if not update_time:
                sync_config = get_config('sync', {})
                update_time = sync_config.get('default_update_time', 
                                            datetime.now().strftime('%Y-%m-%d'))
            
            # 构建请求参数
            request_data = {
                'page': page,
                'limit': limit,
                'update_time': update_time,
                'is_full': is_full
            }
            
            # 如果指定了项目代码，添加到请求参数中
            if project_code:
                request_data['projectCode'] = project_code
            
            self.logger.info(f"开始获取项目数据，参数: {request_data}")
            
            # 发起POST请求
            response_data = self.post_json(self.base_url, request_data)
            
            # 检查API响应状态
            if response_data.get('code') != 0:
                error_msg = f"API返回错误，code: {response_data.get('code')}, msg: {response_data.get('msg')}"
                self.logger.error(error_msg)
                raise APIException(error_msg)
            
            # 获取数据
            data = response_data.get('data', {})
            total = data.get('total', 0)
            data_list = data.get('list', [])
            
            self.logger.info(f"成功获取项目数据，总数: {total}, 当前批次: {len(data_list)}")
            
            return {
                'total': total,
                'list': data_list,
                'page': page,
                'limit': limit
            }
            
        except Exception as e:
            self.logger.error(f"获取项目数据失败: {e}")
            raise APIException(f"获取项目数据失败: {e}")
    
    def get_incremental_data(self, last_sync_time: Optional[str] = None) -> Dict[str, Any]:
        """
        获取增量数据
        
        Args:
            last_sync_time: 上次同步时间
            
        Returns:
            增量数据
        """
        # 如果没有上次同步时间，使用昨天的日期
        if not last_sync_time:
            yesterday = datetime.now() - timedelta(days=1)
            last_sync_time = yesterday.strftime('%Y-%m-%d')
        else:
            # 如果传入的是datetime格式，转换为日期格式
            if ' ' in last_sync_time:
                last_sync_time = last_sync_time.split(' ')[0]
        
        self.logger.info(f"获取增量数据，基准时间: {last_sync_time}")
        
        return self.get_project_data(
            update_time=last_sync_time,
            is_full=0  # 增量同步
        )
    
    def get_full_data(self) -> Dict[str, Any]:
        """
        获取全量数据
        
        Returns:
            全量数据
        """
        self.logger.info("获取全量数据")
        
        # 全量同步时也需要提供update_time参数，使用当前日期
        current_date = datetime.now().strftime('%Y-%m-%d')
        
        return self.get_project_data(
            update_time=current_date,
            is_full=1  # 全量同步
        )
    
    def test_connection(self) -> bool:
        """
        测试API连接
        
        Returns:
            连接是否成功
        """
        # 使用最小参数测试连接
        test_data = {
            'page': 1,
            'limit': 1,
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_full': 0
        }
        
        try:
            response_data = self.post_json(self.base_url, test_data)
            if response_data.get('code') == 0:
                self.logger.info("项目数据API连接测试成功")
                return True
            else:
                self.logger.error(f"项目数据API连接测试失败，返回码: {response_data.get('code')}")
                return False
        except Exception as e:
            self.logger.error(f"项目数据API连接测试失败: {e}")
            return False


class ProjectDataFetcher:
    """
    项目数据获取器
    专门用于获取和预处理项目数据
    """
    
    def __init__(self, api_client: ProjectAPIClient):
        self.api_client = api_client
        self.logger = logging.getLogger(__name__)
    
    def fetch_by_biz_sys(self, biz_sys: str, last_sync_time: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        根据业务系统获取数据
        
        Args:
            biz_sys: 业务系统名称
            last_sync_time: 上次同步时间
            
        Returns:
            过滤后的数据列表
        """
        try:
            # 获取增量数据
            response_data = self.api_client.get_incremental_data(last_sync_time)
            all_data = response_data.get('list', [])
            
            # 根据bizSys过滤数据
            filtered_data = []
            for item in all_data:
                if item.get('bizSys') == biz_sys:
                    filtered_data.append(item)
            
            self.logger.info(f"业务系统 '{biz_sys}' 过滤后数据量: {len(filtered_data)}")
            return filtered_data
            
        except Exception as e:
            self.logger.error(f"根据业务系统获取数据失败: {e}")
            raise
    
    def fetch_bjhl_info_disclosure_data(self, last_sync_time: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取互联信息披露数据
        
        Args:
            last_sync_time: 上次同步时间
            
        Returns:
            互联信息披露数据列表
        """
        return self.fetch_by_biz_sys('互联信息披露', last_sync_time)
