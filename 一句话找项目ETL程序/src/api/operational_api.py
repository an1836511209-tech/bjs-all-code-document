#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
房源运营信息API客户端模块
负责与房源运营信息接口的通信
"""

import logging
from typing import Dict, Any, Optional, List

from .base_client import BaseAPIClient, APIException
from src.core.database import DatabaseManager


class OperationalAPIClient(BaseAPIClient):
    """
    房源运营信息API客户端
    负责与房源运营信息接口通信
    """
    
    def __init__(self):
        """
        初始化房源运营信息API客户端
        """
        super().__init__('operational_api')
        self.base_url = self.config.get('base_url')
        if not self.base_url:
            raise ValueError("未配置房源运营信息API base_url")
    
    def get_operational_data(self, project_id_list: List[int], 
                           channel: Optional[str] = None) -> Dict[str, Any]:
        """
        获取房源运营信息数据
        
        Args:
            project_id_list: 项目ID列表
            channel: 渠道，默认使用配置中的channel
            
        Returns:
            API响应数据
        """
        try:
            if not project_id_list:
                self.logger.warning("项目ID列表为空")
                return {'code': 200, 'data': [], 'message': '项目ID列表为空'}
            
            # 使用配置中的channel或传入的channel
            if channel is None:
                channel = self.config.get('channel', 'sszt')
            
            # 构建请求参数
            request_data = {
                'projectIdList': project_id_list,
                'channel': channel
            }
            
            self.logger.info(f"开始获取房源运营信息，项目数量: {len(project_id_list)}, 渠道: {channel}")
            
            # 发起POST请求
            response_data = self.post_json(self.base_url, request_data)
            
            # 检查API响应状态
            if response_data.get('code') != 200:
                error_msg = f"API返回错误，code: {response_data.get('code')}, message: {response_data.get('message')}"
                self.logger.error(error_msg)
                raise APIException(error_msg)
            
            # 获取数据
            data = response_data.get('data', [])
            
            self.logger.info(f"成功获取房源运营信息，返回项目数: {len(data)}")
            
            return response_data
            
        except Exception as e:
            self.logger.error(f"获取房源运营信息失败: {e}")
            raise APIException(f"获取房源运营信息失败: {e}")
    
    def test_connection(self) -> bool:
        """
        测试API连接
        
        Returns:
            连接是否成功
        """
        # 使用测试项目ID测试连接
        test_data = {
            'projectIdList': [194046],  # 使用文档中的测试ID
            'channel': 'sszt'
        }
        
        try:
            response_data = self.post_json(self.base_url, test_data)
            if response_data.get('code') == 200:
                self.logger.info("房源运营信息API连接测试成功")
                return True
            else:
                self.logger.error(f"房源运营信息API连接测试失败，返回码: {response_data.get('code')}")
                return False
        except Exception as e:
            self.logger.error(f"房源运营信息API连接测试失败: {e}")
            return False


class ProjectIdFetcher:
    """
    项目ID获取器
    从指定表中获取projectId
    """
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)
    
    def get_project_ids_from_tables(self, table_names: List[str]) -> List[int]:
        """
        从指定表中获取所有projectId并去重
        
        Args:
            table_names: 表名列表
            
        Returns:
            项目ID列表
        """
        project_ids = set()
        
        for table_name in table_names:
            try:
                # 检查表是否存在projectId字段
                sql = f"""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = '{table_name}' 
                    AND COLUMN_NAME = 'projectId'
                """
                result = self.db_manager.execute_query(sql)
                
                if not result:
                    self.logger.warning(f"表 {table_name} 不存在projectId字段，跳过")
                    continue
                
                # 获取projectId
                sql = f"SELECT DISTINCT projectId FROM `{table_name}` WHERE projectId IS NOT NULL AND projectId != ''"
                results = self.db_manager.execute_query(sql)
                
                for row in results:
                    project_id = row['projectId']
                    # 尝试转换为整数
                    try:
                        if isinstance(project_id, str):
                            project_id = int(project_id)
                        elif isinstance(project_id, (int, float)):
                            project_id = int(project_id)
                        else:
                            continue
                        
                        if project_id > 0:
                            project_ids.add(project_id)
                    except (ValueError, TypeError):
                        self.logger.warning(f"无法转换projectId为整数: {project_id}")
                        continue
                
                self.logger.info(f"从表 {table_name} 获取到 {len([r for r in results if r['projectId']])} 个projectId")
                
            except Exception as e:
                self.logger.error(f"从表 {table_name} 获取projectId失败: {e}")
                continue
        
        project_id_list = list(project_ids)
        self.logger.info(f"共获取到 {len(project_id_list)} 个唯一的projectId")
        
        return project_id_list
