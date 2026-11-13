#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
房源运营数据同步模块
负责房源运营信息的数据同步逻辑
"""

import logging
from typing import Dict, Any, List

from src.core.database import DatabaseManager, DataSyncDAO
from src.api.operational_api import OperationalAPIClient, ProjectIdFetcher
from src.processors.operational_processor import OperationalDataProcessor


class OperationalSyncManager:
    """
    房源运营数据同步管理器
    负责协调房源运营信息的数据同步任务
    """
    
    def __init__(self):
        """
        初始化房源运营数据同步管理器
        """
        self.logger = logging.getLogger(__name__)
        
        # 初始化各个组件
        self.db_manager = DatabaseManager()
        self.data_sync_dao = DataSyncDAO(self.db_manager)
        self.operational_api_client = OperationalAPIClient()
        self.project_id_fetcher = ProjectIdFetcher(self.db_manager)
        self.data_processor = OperationalDataProcessor()
    
    def sync_operational_data(self, clear_old_data: bool = True) -> Dict[str, Any]:
        """
        同步房源运营信息数据
        
        Args:
            clear_old_data: 是否清空旧数据（T+1全量同步模式）
        
        Returns:
            同步结果统计
        """
        try:
            self.logger.info("开始同步房源运营信息数据")
            if clear_old_data:
                self.logger.info("🗑️ T+1全量同步模式：将清空房源运营表旧数据")
            
            # 如果启用清空旧数据，先清空房源运营表
            if clear_old_data:
                self._clear_operational_table()
            
            # 需要检索projectId的表
            table_names = [
                'bjht_real_estate_transfer',
                'bjhl_bulk', 
                'bjhl_info_disclosure',
                'bjht_house_rent',
                'bjhl_house_rent'
            ]
            
            # 获取所有projectId
            project_ids = self.project_id_fetcher.get_project_ids_from_tables(table_names)
            
            if not project_ids:
                self.logger.info("未找到任何projectId，跳过房源运营信息同步")
                return {
                    'success': True,
                    'total_projects': 0,
                    'fetched_count': 0,
                    'processed_count': 0,
                    'synced_count': 0
                }
            
            self.logger.info(f"共获取到 {len(project_ids)} 个projectId")
            
            # 批量获取房源运营信息（为了避免请求过大，可以分批处理）
            batch_size = 200  # 每批200个项目ID，避免单次请求超时
            all_operational_data = []
            
            for i in range(0, len(project_ids), batch_size):
                batch_project_ids = project_ids[i:i + batch_size]
                self.logger.info(f"处理第 {i//batch_size + 1} 批，项目数: {len(batch_project_ids)}")
                
                try:
                    # 获取房源运营信息
                    response = self.operational_api_client.get_operational_data(batch_project_ids)
                    data = response.get('data', [])
                    all_operational_data.extend(data)
                    
                    self.logger.info(f"第 {i//batch_size + 1} 批获取到 {len(data)} 条数据")
                    
                    # 在批次之间添加短暂延迟，避免服务器过载
                    if i + batch_size < len(project_ids):
                        import time
                        time.sleep(1)  # 延迟1秒
                    
                except Exception as e:
                    self.logger.error(f"第 {i//batch_size + 1} 批数据获取失败: {e}")
                    continue
            
            self.logger.info(f"共获取到 {len(all_operational_data)} 条房源运营信息")
            
            if not all_operational_data:
                self.logger.info("未获取到任何房源运营信息，跳过数据处理")
                return {
                    'success': True,
                    'total_projects': len(project_ids),
                    'fetched_count': 0,
                    'processed_count': 0,
                    'synced_count': 0
                }
            
            # 处理数据
            processed_data = self.data_processor.process_operational_data(all_operational_data)
            self.logger.info(f"数据处理完成，有效记录: {len(processed_data)} 条")
            
            if not processed_data:
                self.logger.warning("没有有效的处理数据")
                return {
                    'success': True,
                    'total_projects': len(project_ids),
                    'fetched_count': len(all_operational_data),
                    'processed_count': 0,
                    'synced_count': 0
                }
            
            # 同步到数据库
            synced_count = self.data_sync_dao.sync_table_data('bjdc_lease_house', processed_data)
            
            result = {
                'success': True,
                'total_projects': len(project_ids),
                'fetched_count': len(all_operational_data),
                'processed_count': len(processed_data),
                'synced_count': synced_count
            }
            
            self.logger.info(f"房源运营信息同步完成: {result}")
            return result
            
        except Exception as e:
            self.logger.error(f"房源运营信息同步失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'total_projects': 0,
                'fetched_count': 0,
                'processed_count': 0,
                'synced_count': 0
            }
    
    def sync_single_project(self, project_id: int) -> Dict[str, Any]:
        """
        同步单个项目的房源运营信息
        
        Args:
            project_id: 项目ID
            
        Returns:
            同步结果
        """
        try:
            self.logger.info(f"开始同步单个项目的房源运营信息: {project_id}")
            
            # 获取房源运营信息
            response = self.operational_api_client.get_operational_data([project_id])
            operational_data = response.get('data', [])
            
            if not operational_data:
                self.logger.warning(f"未获取到项目 {project_id} 的房源运营信息")
                return {
                    'success': True,
                    'project_id': project_id,
                    'fetched_count': 0,
                    'processed_count': 0,
                    'synced_count': 0
                }
            
            # 处理数据
            processed_data = self.data_processor.process_operational_data(operational_data)
            
            if not processed_data:
                self.logger.warning(f"项目 {project_id} 数据处理后无有效记录")
                return {
                    'success': True,
                    'project_id': project_id,
                    'fetched_count': len(operational_data),
                    'processed_count': 0,
                    'synced_count': 0
                }
            
            # 同步到数据库
            synced_count = self.data_sync_dao.sync_table_data('bjdc_lease_house', processed_data)
            
            result = {
                'success': True,
                'project_id': project_id,
                'fetched_count': len(operational_data),
                'processed_count': len(processed_data),
                'synced_count': synced_count
            }
            
            self.logger.info(f"项目 {project_id} 房源运营信息同步完成: {result}")
            return result
            
        except Exception as e:
            self.logger.error(f"同步项目 {project_id} 房源运营信息失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'project_id': project_id,
                'fetched_count': 0,
                'processed_count': 0,
                'synced_count': 0
            }
    
    def delete_project_data(self, project_id: str) -> bool:
        """
        删除指定项目的房源运营数据
        
        Args:
            project_id: 项目ID
            
        Returns:
            删除是否成功
        """
        try:
            sql = "DELETE FROM `bjdc_lease_house` WHERE `projectId` = :project_id"
            affected_rows = self.db_manager.execute_non_query(sql, {'project_id': project_id})
            self.logger.info(f"删除项目 {project_id} 的房源运营数据，影响行数: {affected_rows}")
            return True
        except Exception as e:
            self.logger.error(f"删除项目 {project_id} 房源运营数据失败: {e}")
            return False
    
    def _clear_operational_table(self):
        """
        清空房源运营数据表（T+1全量同步模式）
        """
        try:
            sql = "TRUNCATE TABLE `bjdc_lease_house`"
            self.db_manager.execute_non_query(sql)
            self.logger.info("✅ 已清空房源运营数据表: bjdc_lease_house")
        except Exception as e:
            self.logger.error(f"❌ 清空房源运营数据表失败: {e}")
            raise
    
    def close(self):
        """
        关闭所有连接
        """
        try:
            if self.operational_api_client:
                self.operational_api_client.close()
            if self.db_manager:
                self.db_manager.close()
            self.logger.info("房源运营同步管理器连接已关闭")
        except Exception as e:
            self.logger.error(f"关闭房源运营同步管理器连接失败: {e}")
