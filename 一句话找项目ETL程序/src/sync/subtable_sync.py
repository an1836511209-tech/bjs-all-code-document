#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
子表数据同步模块
负责业务子表的数据同步逻辑
"""

import logging
from typing import Dict, Any, Optional

from src.core.database import DatabaseManager, DataSyncDAO
from src.api.project_api import ProjectAPIClient, ProjectDataFetcher
from src.processors.subtable_processor import SubtableDataProcessor
from src.sync.shared_data_manager import SharedDataManager
from src.core.config import get_config


class SubtableSyncManager:
    """
    子表数据同步管理器
    负责协调各个模块完成子表数据同步任务
    """
    
    def __init__(self):
        """
        初始化子表数据同步管理器
        """
        self.logger = logging.getLogger(__name__)
        
        # 初始化各个组件
        self.db_manager = DatabaseManager()
        self.data_sync_dao = DataSyncDAO(self.db_manager)
        self.api_client = ProjectAPIClient()
        self.data_fetcher = ProjectDataFetcher(self.api_client)
        self.data_processor = SubtableDataProcessor()
        
        # 初始化共享数据管理器
        self.shared_data_manager = SharedDataManager()
    
    def sync_table_by_biz_sys(self, biz_sys: str, last_sync_time: Optional[str] = None, 
                                force_full: bool = False) -> Dict[str, Any]:
        """
        通用的业务系统数据同步方法
        
        Args:
            biz_sys: 业务系统名称
            last_sync_time: 上次同步时间
            force_full: 是否强制全量同步
            
        Returns:
            同步结果统计
        """
        try:
            # 获取表名
            table_name = self.data_processor.get_table_name_by_biz_sys(biz_sys)
            if not table_name:
                return {
                    'success': False,
                    'error': f'未找到业务系统 "{biz_sys}" 对应的表名',
                    'total_fetched': 0,
                    'filtered_count': 0,
                    'processed_count': 0,
                    'synced_count': 0
                }
            
            self.logger.info(f"开始同步{biz_sys}数据到{table_name}表")
            
            # 如果没有指定上次同步时间，从数据库获取
            if not last_sync_time and not force_full:
                last_sync_time = self.data_sync_dao.get_last_sync_time(table_name)
                if last_sync_time:
                    self.logger.info(f"从数据库获取到上次同步时间: {last_sync_time}")
                else:
                    self.logger.info("数据库中无同步记录，将进行全量同步")
                    force_full = True
            
            # 使用共享数据管理器获取指定业务系统的数据
            filtered_data = self.shared_data_manager.get_data_by_biz_sys(
                biz_sys, last_sync_time, force_full
            )
            
            if not filtered_data:
                self.logger.info("没有需要同步的数据")
                return {
                    'success': True,
                    'total_fetched': 0,
                    'filtered_count': 0,
                    'processed_count': 0,
                    'synced_count': 0
                }
            
            # 处理数据
            processed_data = self.data_processor.process_data_by_biz_sys(filtered_data, biz_sys)
            self.logger.info(f"数据处理完成，有效记录: {len(processed_data)} 条")
            
            if not processed_data:
                self.logger.warning("没有有效的处理数据")
                return {
                    'success': True,
                    'total_fetched': len(filtered_data),
                    'filtered_count': len(filtered_data),
                    'processed_count': 0,
                    'synced_count': 0
                }
            
            # 同步到数据库
            synced_count = self.data_sync_dao.sync_table_data(table_name, processed_data)
            
            result = {
                'success': True,
                'total_fetched': len(filtered_data),
                'filtered_count': len(filtered_data),
                'processed_count': len(processed_data),
                'synced_count': synced_count
            }
            
            self.logger.info(f"同步完成: {result}")
            return result
            
        except Exception as e:
            self.logger.error(f"同步{biz_sys}数据失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'total_fetched': 0,
                'filtered_count': 0,
                'processed_count': 0,
                'synced_count': 0
            }
    
    def sync_all_subtables(self, last_sync_time: Optional[str] = None, 
                          force_full: bool = False, clear_old_data: bool = False) -> Dict[str, Any]:
        """
        同步所有子表数据（优化版：一次API调用获取所有数据）
        
        Args:
            last_sync_time: 上次同步时间
            force_full: 是否强制全量同步
            clear_old_data: 是否清空旧数据（T+1全量同步模式）
            
        Returns:
            同步结果统计
        """
        try:
            self.logger.info("开始同步所有子表数据（优化模式：一次API调用）")
            if clear_old_data:
                self.logger.info("🗑️ T+1全量同步模式：将清空所有子表旧数据")
            
            # 从配置中获取所有业务系统
            biz_sys_mapping = get_config('biz_sys_mapping', {})
            
            # 如果启用清空旧数据，先清空所有子表
            if clear_old_data:
                self._clear_all_subtables(biz_sys_mapping)
            
            # 一次性获取所有业务系统的数据
            self.logger.info("🚀 优化：一次性获取所有业务系统数据...")
            all_biz_sys_data = self.shared_data_manager.get_all_biz_sys_data(
                list(biz_sys_mapping.keys()), last_sync_time, force_full
            )
            
            results = {}
            total_fetched = sum(len(data) for data in all_biz_sys_data.values())
            self.logger.info(f"✅ 一次API调用获取到总计 {total_fetched} 条数据")
            
            # 处理每个业务系统的数据
            for biz_sys, table_name in biz_sys_mapping.items():
                try:
                    self.logger.info(f"开始处理业务系统: {biz_sys} -> {table_name}")
                    
                    # 获取该业务系统的数据
                    filtered_data = all_biz_sys_data.get(biz_sys, [])
                    
                    if not filtered_data:
                        self.logger.info(f"业务系统 {biz_sys} 没有需要同步的数据")
                        results[table_name] = {
                            'success': True,
                            'total_fetched': 0,
                            'filtered_count': 0,
                            'processed_count': 0,
                            'synced_count': 0
                        }
                        continue
                    
                    # 处理数据
                    processed_data = self.data_processor.process_data_by_biz_sys(filtered_data, biz_sys)
                    self.logger.info(f"业务系统 {biz_sys} 数据处理完成，有效记录: {len(processed_data)} 条")
                    
                    if not processed_data:
                        self.logger.warning(f"业务系统 {biz_sys} 没有有效的处理数据")
                        results[table_name] = {
                            'success': True,
                            'total_fetched': len(filtered_data),
                            'filtered_count': len(filtered_data),
                            'processed_count': 0,
                            'synced_count': 0
                        }
                        continue
                    
                    # 同步到数据库
                    synced_count = self.data_sync_dao.sync_table_data(table_name, processed_data)
                    
                    results[table_name] = {
                        'success': True,
                        'total_fetched': len(filtered_data),
                        'filtered_count': len(filtered_data),
                        'processed_count': len(processed_data),
                        'synced_count': synced_count
                    }
                    
                    self.logger.info(f"业务系统 {biz_sys} 同步完成: {results[table_name]}")
                    
                except Exception as e:
                    self.logger.error(f"处理业务系统 {biz_sys} 失败: {e}")
                    results[table_name] = {
                        'success': False,
                        'error': str(e),
                        'total_fetched': 0,
                        'filtered_count': 0,
                        'processed_count': 0,
                        'synced_count': 0
                    }
            
            # 统计总体结果
            total_result = {
                'success': all(r.get('success', False) for r in results.values()),
                'tables': results,
                'summary': {
                    'total_tables': len(results),
                    'success_tables': sum(1 for r in results.values() if r.get('success', False)),
                    'total_synced': sum(r.get('synced_count', 0) for r in results.values()),
                    'api_calls_saved': len(biz_sys_mapping) - 1  # 节省的API调用次数
                }
            }
            
            self.logger.info(f"🎉 所有子表同步完成（节省了 {total_result['summary']['api_calls_saved']} 次API调用）: {total_result['summary']}")
            return total_result
            
        except Exception as e:
            self.logger.error(f"同步所有子表失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'tables': {},
                'summary': {
                    'total_tables': 0,
                    'success_tables': 0,
                    'total_synced': 0,
                    'api_calls_saved': 0
                }
            }
    
    def _clear_all_subtables(self, biz_sys_mapping: Dict[str, str]):
        """
        清空所有子表数据（T+1全量同步模式）
        
        Args:
            biz_sys_mapping: 业务系统映射配置
        """
        try:
            self.logger.info("开始清空所有子表数据...")
            
            cleared_count = 0
            for biz_sys, table_name in biz_sys_mapping.items():
                try:
                    sql = f"TRUNCATE TABLE `{table_name}`"
                    self.db_manager.execute_non_query(sql)
                    self.logger.info(f"✅ 已清空子表: {table_name} (业务系统: {biz_sys})")
                    cleared_count += 1
                except Exception as e:
                    self.logger.error(f"❌ 清空子表失败 {table_name}: {e}")
                    # 继续处理其他表，不中断整个流程
            
            self.logger.info(f"子表清空完成，成功清空 {cleared_count}/{len(biz_sys_mapping)} 个表")
            
        except Exception as e:
            self.logger.error(f"清空子表过程发生异常: {e}")
            raise
    
    def close(self):
        """
        关闭所有连接
        """
        try:
            if self.shared_data_manager:
                self.shared_data_manager.close()
            if self.api_client:
                self.api_client.close()
            if self.db_manager:
                self.db_manager.close()
            self.logger.info("子表同步管理器连接已关闭")
        except Exception as e:
            self.logger.error(f"关闭子表同步管理器连接失败: {e}")
