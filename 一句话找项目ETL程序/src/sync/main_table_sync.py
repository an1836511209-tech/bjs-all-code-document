#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主表数据同步模块
负责主表的数据同步逻辑，支持配置驱动的通用ETL
"""

import logging
from typing import Dict, Any, List

from src.core.database import DatabaseManager, DataSyncDAO
from src.processors.main_table_processor import MainTableETLProcessor
from src.knowledge_base.kb_manager import KnowledgeBaseManager


class MainTableSyncManager:
    """
    主表数据同步管理器
    负责协调主表的数据同步任务
    
    主表数据来源于子表和补充表的汇总，
    实现T+1的定时同步任务，支持配置驱动的通用ETL逻辑
    """
    
    # 主表和bjhl_info_disclosure下项目类型的映射关系
    INFO_DISCLOSURE_PROJECT_TYPE_MAPPING = {
        'equity_transfer': ["股权转让"],
        'equity_increase': ["股权增资"], 
        'culture_tourism_sports': ["文旅体育"],
        'property_rental': ["房屋出租"],
        'debt_assets': ["债权资产"],
        'other_assets': ["资产转让","其他招商"],
    }

    # 主表和bjhl_bulk下资产类型的映射关系
    BULK_ASSET_TYPE_MAPPING = {
        'debt_assets': ["债权"],
        'other_assets': ["机械设备","存货","交通运输工具","在建工程","技术类无形资产","其他"],
        'property_land': ["土地","房屋建筑物"]
    }

    # bjhl_bulk下ASSET_TYPE字段资产类型的映射关系
    BJHL_BULK_ASSET_TYPE_MAPPING = {
        '债权': ["CLAIM_name","bookValue","principal","fruits","baseDate","otherExpenses","debtorRelatedInformation","isThereAnyPledge"],
        '机械设备': ["mecequname","mechanical_equipment_address","mecequno","mecequunit","mecequnums","mecequrate","mechanical_equipment_mortgage"],
        '存货': ["stockname","inventory_address","stockmodel","stockunit","stocknums","inventory_mortgage"],
        '交通运输工具': ["isaerocraft","trafficno","trafficmodel","buydate","nums","registerdate","aged","colour","drivingkilo","transportation_mortgage","transportation_address"],
        '在建工程': ["progressname","progressdesc","construction_process_mortgage"],
        '技术类无形资产': ["technical_intangible_assets_name","num","obligee","remark","technical_intangible_assets_mortgage"],
        '其他': ["othername","otherunit","othermodel","othernums","address","mortgage"],
        '土地': ["landage","landuse","landaged", "landarea", "landtype", "land_has_mortgage", "landcoding", "land_location"],
        '房屋建筑物': ["house_location","housecoding","houseuse","houseestablishment","housearea","houseage","houseaged"],
    }

    
    def __init__(self, enable_kb_sync: bool = True):
        """
        初始化主表数据同步管理器
        
        Args:
            enable_kb_sync: 是否启用知识库同步，默认True
        """
        self.logger = logging.getLogger(__name__)
        self.enable_kb_sync = enable_kb_sync
        
        # 初始化各个组件
        self.db_manager = DatabaseManager()
        self.data_sync_dao = DataSyncDAO(self.db_manager)
        self.etl_processor = MainTableETLProcessor()
        
        # 初始化知识库管理器（如果启用）
        self.kb_manager = None
        if self.enable_kb_sync:
            try:
                self.kb_manager = KnowledgeBaseManager()
                self.logger.info("知识库同步功能已启用")
            except Exception as e:
                self.logger.warning(f"知识库管理器初始化失败，将跳过知识库同步: {e}")
                self.enable_kb_sync = False
        
        # 初始化数据分发缓存
        self._bulk_distribution_cache = {}
        self._disclosure_distribution_cache = {}
    
    def sync_main_table(self, main_table_name: str) -> Dict[str, Any]:
        """
        同步指定主表数据（通用方法）
        
        Args:
            main_table_name: 主表名称
            
        Returns:
            同步结果统计
        """
        try:
            self.logger.info(f"开始同步主表数据: {main_table_name}")
            
            # 1. 获取主表配置
            all_configs = self.etl_processor.get_main_table_configs()
            if main_table_name not in all_configs:
                raise ValueError(f"未找到主表配置: {main_table_name}")
            
            config = all_configs[main_table_name]
            
            # 2. 获取所需的子表数据
            subtable_data = self._fetch_subtable_data(config)
            
            # 3. 处理ETL逻辑
            main_table_records = self.etl_processor.process_main_table_data(
                main_table_name, subtable_data
            )
            
            # 4. 写入主表
            synced_count = self._save_main_table_data(main_table_name, main_table_records)
            
            result = {
                'success': True,
                'message': f'主表 {main_table_name} 同步完成',
                'synced_count': synced_count,
                'main_table': main_table_name,
                'kb_sync_result': None
            }
            
            # 5. 同步到知识库（如果启用）
            if self.enable_kb_sync and self.kb_manager and synced_count > 0:
                try:
                    self.logger.info(f"开始同步主表 {main_table_name} 到知识库")
                    kb_result = self.kb_manager.sync_table_to_kb(main_table_name)
                    result['kb_sync_result'] = kb_result
                    
                    if kb_result.get('success'):
                        self.logger.info(f"主表 {main_table_name} 知识库同步成功")
                    else:
                        self.logger.error(f"主表 {main_table_name} 知识库同步失败: {kb_result.get('error')}")
                        
                except Exception as e:
                    self.logger.error(f"主表 {main_table_name} 知识库同步异常: {e}")
                    result['kb_sync_result'] = {
                        'success': False,
                        'error': str(e)
                    }
            
            self.logger.info(f"主表 {main_table_name} 同步完成: {result}")
            return result
            
        except Exception as e:
            self.logger.error(f"主表 {main_table_name} 同步失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'synced_count': 0,
                'main_table': main_table_name
            }
    
    def sync_equity_transfer_main_table(self) -> Dict[str, Any]:
        """
        同步股权转让主表数据
        
        Returns:
            同步结果统计
        """
        return self.sync_main_table('equity_transfer')
    
    def sync_equity_increase_main_table(self) -> Dict[str, Any]:
        """
        同步股权增资主表数据
        
        Returns:
            同步结果统计
        """
        return self.sync_main_table('equity_increase')
    
    def sync_property_land_main_table(self) -> Dict[str, Any]:
        """
        同步房屋土地主表数据（包含特殊ETL逻辑）
        
        Returns:
            同步结果统计
        """
        return self.sync_main_table('property_land')
    
    def sync_property_rental_main_table(self) -> Dict[str, Any]:
        """
        同步房屋出租主表数据（包含特殊ETL逻辑）
        
        Returns:
            同步结果统计
        """
        return self.sync_main_table('property_rental')
    
    def refresh_asset_types_and_distribute(self) -> Dict[str, Any]:
        """
        刷新bjhl_bulk表的assetType字段并执行数据分发
        这是一个便于单独调用的方法
        
        Returns:
            操作结果统计
        """
        try:
            self.logger.info("开始刷新assetType并执行数据分发")
            
            # 刷新assetType
            refresh_result = self.refresh_bjhl_bulk_asset_type()
            
            # 执行数据分发
            bulk_result = self.sync_bjhl_bulk_to_main_tables()
            disclosure_result = self.sync_bjhl_info_disclosure_to_main_tables()
            
            result = {
                'success': True,
                'message': 'assetType刷新和数据分发完成',
                'refresh_result': refresh_result,
                'bulk_distribution': bulk_result,
                'disclosure_distribution': disclosure_result
            }
            
            self.logger.info(f"assetType刷新和数据分发完成: {result}")
            return result
            
        except Exception as e:
            self.logger.error(f"assetType刷新和数据分发失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def sync_all_main_tables(self, batch_kb_sync: bool = False) -> Dict[str, Any]:
        """
        同步所有配置的主表数据
        集成特殊处理逻辑：先进行数据分发，再执行主表同步
        
        Args:
            batch_kb_sync: 是否在所有表同步完成后进行批量知识库同步，默认False（跟随单表同步）
        
        Returns:
            同步结果统计
        """
        try:
            self.logger.info("开始同步所有主表数据（包含特殊处理逻辑）")
            
            # 第一步：执行数据分发
            self.logger.info("第一步：执行bjhl_bulk和bjhl_info_disclosure数据分发")
            
            # 分发bjhl_bulk数据
            bulk_result = self.sync_bjhl_bulk_to_main_tables()
            if not bulk_result.get('success'):
                self.logger.warning(f"bjhl_bulk数据分发失败: {bulk_result.get('error')}")
            else:
                self.logger.info(f"bjhl_bulk数据分发成功: {bulk_result.get('distributed_count')} 条记录")
            
            # 分发bjhl_info_disclosure数据
            disclosure_result = self.sync_bjhl_info_disclosure_to_main_tables()
            if not disclosure_result.get('success'):
                self.logger.warning(f"bjhl_info_disclosure数据分发失败: {disclosure_result.get('error')}")
            else:
                self.logger.info(f"bjhl_info_disclosure数据分发成功: {disclosure_result.get('distributed_count')} 条记录")
            
            # 第二步：获取所有主表配置并进行同步
            self.logger.info("第二步：执行主表同步")
            all_configs = self.etl_processor.get_main_table_configs()
            
            results = {}
            
            # 遍历所有配置的主表进行同步
            for main_table_name in all_configs.keys():
                try:
                    self.logger.info(f"开始同步主表: {main_table_name}")
                    result = self.sync_main_table(main_table_name)
                    results[main_table_name] = result
                except Exception as e:
                    self.logger.error(f"同步主表 {main_table_name} 失败: {e}")
                    results[main_table_name] = {
                        'success': False,
                        'error': str(e),
                        'synced_count': 0,
                        'main_table': main_table_name
                    }
            
            # 统计总体结果
            total_result = {
                'success': all(r.get('success', False) for r in results.values()),
                'tables': results,
                'summary': {
                    'total_tables': len(results),
                    'success_tables': sum(1 for r in results.values() if r.get('success', False)),
                    'total_synced': sum(r.get('synced_count', 0) for r in results.values())
                },
                'data_distribution': {
                    'bulk_distribution': bulk_result,
                    'disclosure_distribution': disclosure_result
                },
                'batch_kb_sync_result': None
            }
            
            # 批量知识库同步（如果启用）
            if batch_kb_sync and self.enable_kb_sync and self.kb_manager:
                try:
                    self.logger.info("开始批量同步所有主表到知识库")
                    kb_batch_result = self.kb_manager.sync_all_tables_to_kb()
                    total_result['batch_kb_sync_result'] = kb_batch_result
                    
                    if kb_batch_result.get('success'):
                        self.logger.info("批量知识库同步成功")
                    else:
                        self.logger.error(f"批量知识库同步失败: {kb_batch_result.get('error', '未知错误')}")
                        
                except Exception as e:
                    self.logger.error(f"批量知识库同步异常: {e}")
                    total_result['batch_kb_sync_result'] = {
                        'success': False,
                        'error': str(e)
                    }
            
            self.logger.info(f"所有主表同步完成: {total_result['summary']}")
            return total_result
            
        except Exception as e:
            self.logger.error(f"同步所有主表失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'tables': {},
                'summary': {
                    'total_tables': 0,
                    'success_tables': 0,
                    'total_synced': 0
                }
            }
    
    def _fetch_subtable_data(self, config: Dict) -> Dict[str, List[Dict]]:
        """
        从数据库获取所需的子表数据
        支持特殊数据处理逻辑（如property_land和property_rental的特殊ETL）
        
        Args:
            config: 主表配置
            
        Returns:
            子表数据字典，key为子表名，value为数据列表
        """
        subtable_data = {}
        
        try:
            main_table_name = config['name']
            
            # 特殊处理：property_land和property_rental主表
            if main_table_name == 'property_land':
                self.logger.info("执行property_land主表的特殊数据获取逻辑")
                
                # 获取过滤后的bjhl_bulk数据（assetType包含土地或房屋建筑物）
                bulk_data = self._get_filtered_bulk_data_for_property_land()
                
                # 获取bjht_real_estate_transfer数据
                real_estate_transfer_data = self._get_filtered_bjht_real_estate_transfer_data()
                
                # 获取所有常规数据源的project_code来查询bjdc_lease_house
                all_project_codes = []
                for record in bulk_data:
                    if record.get('project_code'):
                        all_project_codes.append(record.get('project_code'))
                for record in real_estate_transfer_data:
                    if record.get('project_code'):
                        all_project_codes.append(record.get('project_code'))
                
                # 获取对应的bjdc_lease_house数据
                lease_house_data = self._get_lease_house_data_by_project_codes(all_project_codes)
                
                # 分别提供子表数据，让ETL处理器进行处理
                subtable_data['bjhl_bulk'] = bulk_data
                subtable_data['bjht_real_estate_transfer'] = real_estate_transfer_data
                subtable_data['bjdc_lease_house'] = lease_house_data
                
                # 同时获取分发缓存中的数据（如果有）
                cached_bulk_data = self._bulk_distribution_cache.get(main_table_name, [])
                disclosure_data = self._disclosure_distribution_cache.get(main_table_name, [])
                
                # 合并缓存数据
                if cached_bulk_data:
                    subtable_data['bjhl_bulk'].extend(cached_bulk_data)
                if disclosure_data:
                    subtable_data['bjhl_info_disclosure'] = disclosure_data
                
                return subtable_data
                
            elif main_table_name == 'property_rental':
                self.logger.info("执行property_rental主表的特殊数据获取逻辑")
                
                # 获取bjhl_house_rent数据
                house_rent_data = self._get_filtered_house_rent_data()
                
                # 获取bjht_house_rent数据
                bjht_house_rent_data = self._get_filtered_bjht_house_rent_data()
                
                # 获取所有house_rent相关的project_code来查询bjdc_lease_house
                all_project_codes = []
                for record in house_rent_data:
                    if record.get('project_code'):
                        all_project_codes.append(record.get('project_code'))
                for record in bjht_house_rent_data:
                    if record.get('project_code'):
                        all_project_codes.append(record.get('project_code'))
                
                # 获取对应的bjdc_lease_house数据
                lease_house_data = self._get_lease_house_data_by_project_codes(all_project_codes)
                
                # 分别提供子表数据，让ETL处理器进行处理
                subtable_data['bjhl_house_rent'] = house_rent_data
                subtable_data['bjht_house_rent'] = bjht_house_rent_data
                subtable_data['bjdc_lease_house'] = lease_house_data
                
                # 获取分发缓存中的disclosure数据（如果有）
                disclosure_data = self._disclosure_distribution_cache.get(main_table_name, [])
                if disclosure_data:
                    subtable_data['bjhl_info_disclosure'] = disclosure_data
                
                return subtable_data
            
            # 常规处理：其他主表
            # 首先检查是否有分发缓存的数据
            bulk_data = self._bulk_distribution_cache.get(main_table_name, [])
            disclosure_data = self._disclosure_distribution_cache.get(main_table_name, [])
            
            if bulk_data:
                subtable_data['bjhl_bulk'] = bulk_data
                self.logger.info(f"使用分发缓存的bjhl_bulk数据: {len(bulk_data)} 条记录")
            
            if disclosure_data:
                subtable_data['bjhl_info_disclosure'] = disclosure_data
                self.logger.info(f"使用分发缓存的bjhl_info_disclosure数据: {len(disclosure_data)} 条记录")
            
            # 获取配置中需要的其他子表数据
            required_subtables = set()
            for mapping in config['etl_mappings']:
                subtable_name = mapping['子表名']
                # 跳过已经从缓存获取的数据
                if subtable_name not in ['bjhl_bulk', 'bjhl_info_disclosure']:
                    required_subtables.add(subtable_name)
            
            # 获取当前主表的项目类型过滤条件
            project_type_filter = self._get_project_type_filter(main_table_name)
            
            # 从数据库获取每个子表的数据
            for subtable_name in required_subtables:
                try:
                    self.logger.info(f"获取子表数据: {subtable_name}")
                    
                    # 构建查询SQL，添加项目类型和状态过滤
                    query = self._build_subtable_query(subtable_name, project_type_filter)
                    
                    # 执行查询
                    table_data = self.db_manager.execute_query(query)
                    subtable_data[subtable_name] = table_data
                    self.logger.info(f"获取子表 {subtable_name} 数据完成，记录数: {len(table_data)} (已应用过滤条件)")
                
                except Exception as e:
                    self.logger.error(f"获取子表数据失败 {subtable_name}: {e}")
                    subtable_data[subtable_name] = []
            
            return subtable_data
            
        except Exception as e:
            self.logger.error(f"获取子表数据失败: {e}")
            return {}
    
    def _get_project_type_filter(self, main_table_name: str) -> str:
        """
        根据主表名获取项目类型过滤条件
        
        Args:
            main_table_name: 主表名
            
        Returns:
            项目类型过滤SQL条件
        """
        # 获取该主表对应的项目类型（从bjhl_info_disclosure）
        project_types = self.INFO_DISCLOSURE_PROJECT_TYPE_MAPPING.get(main_table_name)
        
        if not project_types:
            self.logger.warning(f"未找到主表 {main_table_name} 的项目类型映射，将不过滤项目类型")
            return ""
        
        # project_types已经是列表，直接使用
        type_list = project_types
        
        # 构建LIKE条件
        like_conditions = []
        for project_type in type_list:
            like_conditions.append(f"project_type LIKE '%{project_type}%'")
        
        filter_condition = " OR ".join(like_conditions)
        self.logger.info(f"主表 {main_table_name} 项目类型过滤条件: {filter_condition}")
        
        return f"({filter_condition})"
    
    def _build_subtable_query(self, subtable_name: str, project_type_filter: str) -> str:
        """
        构建子表查询SQL
        
        Args:
            subtable_name: 子表名
            project_type_filter: 项目类型过滤条件
            
        Returns:
            完整的查询SQL
        """
        conditions = []
        
        # 添加项目状态过滤条件（project_state 或 project_status = '1'）
        status_filter = self._get_project_status_filter(subtable_name)
        if status_filter:
            conditions.append(status_filter)
        
        # 添加项目类型过滤条件
        if project_type_filter and self._check_table_has_project_type_column(subtable_name):
            conditions.append(project_type_filter)
        elif project_type_filter:
            self.logger.warning(f"子表 {subtable_name} 没有project_type字段，跳过项目类型过滤")
        
        # 构建完整查询
        if conditions:
            where_clause = " AND ".join(conditions)
            query = f"SELECT * FROM `{subtable_name}` WHERE {where_clause}"
        else:
            query = f"SELECT * FROM `{subtable_name}`"
        
        self.logger.debug(f"子表 {subtable_name} 查询SQL: {query}")
        return query
    
    def _get_project_status_filter(self, table_name: str) -> str:
        """
        获取项目状态过滤条件（project_state 或 project_status = '1'）
        
        Args:
            table_name: 表名
            
        Returns:
            状态过滤SQL条件，如果表没有状态字段则返回空字符串
        """
        try:
            # 根据已知的表结构来确定状态字段，避免每次都查询数据库
            # 使用 project_state 的表
            if table_name in ['bjhl_property_transfer', 'bjhl_enterprise_increase', 'bjhl_bulk', 
                             'bjht_real_estate_transfer', 'bjhl_info_disclosure', 'bjht_equity_transfer']:
                self.logger.debug(f"表 {table_name} 使用 project_state 字段进行状态过滤")
                return "project_state = '1'"
            # 使用 project_status 的表  
            elif table_name in ['bjht_credit_asset', 'bjdc_lease_house', 'bjhl_house_rent', 
                               'bjht_house_rent', 'bjht_equity_increase']:
                self.logger.debug(f"表 {table_name} 使用 project_status 字段进行状态过滤")
                return "project_status = '1'"
            else:
                # 对于未知的表，动态检查字段
                if self._check_table_has_column(table_name, 'project_state'):
                    self.logger.debug(f"表 {table_name} 使用 project_state 字段进行状态过滤")
                    return "project_state = '1'"
                elif self._check_table_has_column(table_name, 'project_status'):
                    self.logger.debug(f"表 {table_name} 使用 project_status 字段进行状态过滤")
                    return "project_status = '1'"
                else:
                    self.logger.warning(f"表 {table_name} 没有 project_state 或 project_status 字段，跳过状态过滤")
                    return ""
                
        except Exception as e:
            self.logger.warning(f"获取状态过滤条件失败 {table_name}: {e}")
            return ""
    
    def _check_table_has_project_type_column(self, table_name: str) -> bool:
        """
        检查表是否有project_type字段
        
        Args:
            table_name: 表名
            
        Returns:
            是否有project_type字段
        """
        return self._check_table_has_column(table_name, 'project_type')
    
    def _check_table_has_column(self, table_name: str, column_name: str) -> bool:
        """
        检查表是否有指定字段
        
        Args:
            table_name: 表名
            column_name: 字段名
            
        Returns:
            是否有指定字段
        """
        try:
            # 查询表结构
            query = f"SHOW COLUMNS FROM `{table_name}` LIKE '{column_name}'"
            result = self.db_manager.execute_query(query)
            has_column = len(result) > 0
            
            if not has_column:
                self.logger.debug(f"表 {table_name} 没有 {column_name} 字段")
            
            return has_column
            
        except Exception as e:
            self.logger.warning(f"检查表字段失败 {table_name}.{column_name}: {e}")
            return False
    
    def _save_main_table_data(self, main_table_name: str, records: List[Dict]) -> int:
        """
        保存主表数据到数据库
        
        Args:
            main_table_name: 主表名
            records: 要保存的记录列表
            
        Returns:
            保存的记录数量
        """
        try:
            if not records:
                self.logger.warning(f"没有数据需要保存到主表: {main_table_name}")
                return 0
            
            # 清空主表现有数据（可选，根据业务需求）
            self._truncate_main_table(main_table_name)
            
            # 预处理记录，确保所有字段都有值
            processed_records = self._preprocess_records_for_insert(records)
            
            # 使用数据库管理器的批量插入功能
            saved_count = self.db_manager.batch_insert(
                main_table_name, 
                processed_records, 
                on_duplicate_update=False
            )
            
            self.logger.info(f"主表 {main_table_name} 数据保存完成，总计: {saved_count} 条记录")
            return saved_count
            
        except Exception as e:
            self.logger.error(f"保存主表数据失败 {main_table_name}: {e}")
            raise
    
    def _truncate_main_table(self, main_table_name: str):
        """
        清空主表数据
        
        Args:
            main_table_name: 主表名
        """
        try:
            sql = f"TRUNCATE TABLE `{main_table_name}`"
            self.db_manager.execute_non_query(sql)
            self.logger.info(f"已清空主表: {main_table_name}")
        except Exception as e:
            self.logger.error(f"清空主表失败 {main_table_name}: {e}")
            raise
    
    def _preprocess_records_for_insert(self, records: List[Dict]) -> List[Dict]:
        """
        预处理记录，确保所有字段都有合适的值
        
        Args:
            records: 原始记录列表
            
        Returns:
            预处理后的记录列表
        """
        if not records:
            return []
            
        # 获取所有记录中的所有字段
        all_fields = set()
        for record in records:
            all_fields.update(record.keys())
        
        processed_records = []
        
        for i, record in enumerate(records):
            processed_record = {}
            
            # 确保每个记录都有所有字段
            for field in all_fields:
                value = record.get(field)
                
                # 处理None值或缺失字段，替换为合适的默认值
                if value is None:
                    if field in ['project_status', 'project_state']:
                        processed_record[field] = '0'
                    elif 'date' in field.lower() and field not in ['created_at', 'updated_at']:
                        processed_record[field] = None  # 日期字段可以为None
                    elif field in ['created_at', 'updated_at']:
                        # 这些字段由数据库自动处理，不需要显式插入
                        continue
                    else:
                        processed_record[field] = ''  # 其他字段使用空字符串
                else:
                    processed_record[field] = value
            
            # 特别确保关键字段存在（根据实际字段名）
            status_fields = ['project_status', 'project_state']
            status_field_found = False
            for status_field in status_fields:
                if status_field in all_fields:
                    if status_field not in processed_record:
                        processed_record[status_field] = '0'
                    status_field_found = True
                    break
                
            processed_records.append(processed_record)
            
        
        return processed_records
    
    def refresh_bjhl_bulk_asset_type(self) -> Dict[str, Any]:
        """
        刷新bjhl_bulk表的assetType字段
        根据BJHL_BULK_ASSET_TYPE_MAPPING判断每条记录的资产类型
        
        Returns:
            刷新结果统计
        """
        try:
            self.logger.info("开始刷新bjhl_bulk表的assetType字段")
            
            # 获取bjhl_bulk表的所有数据
            query = "SELECT * FROM bjhl_bulk"
            bulk_records = self.db_manager.execute_query(query)
            
            if not bulk_records:
                self.logger.warning("bjhl_bulk表没有数据")
                return {
                    'success': True,
                    'message': 'bjhl_bulk表没有数据需要处理',
                    'updated_count': 0
                }
            
            # 准备批量更新的数据
            batch_update_data = []
            
            # 处理每条记录，构建批量更新数据
            for record in bulk_records:
                # 判断资产类型
                asset_types = self._determine_asset_types(record)
                
                if asset_types:
                    # 更新assetType字段
                    asset_type_str = ','.join(asset_types)
                    
                    # 获取记录的主键（假设有id或其他主键字段）
                    record_id = record.get('id') or record.get('project_code')
                    if not record_id:
                        self.logger.warning(f"记录缺少主键，跳过更新: {record}")
                        continue
                    
                    # 构建更新数据
                    update_data = {
                        'assetType': asset_type_str
                    }
                    
                    # 添加主键字段
                    if record.get('id'):
                        update_data['id'] = record_id
                    else:
                        update_data['project_code'] = record_id
                    
                    batch_update_data.append(update_data)
                    self.logger.debug(f"准备更新记录 {record_id} 的assetType为: {asset_type_str}")
            
            # 执行批量更新
            updated_count = 0
            if batch_update_data:
                # 确定主键字段
                key_fields = ['id'] if batch_update_data[0].get('id') else ['project_code']
                
                # 如果同时存在id和project_code作为主键的记录，需要分开处理
                id_updates = [data for data in batch_update_data if 'id' in data]
                project_code_updates = [data for data in batch_update_data if 'project_code' in data and 'id' not in data]
                
                # 批量更新使用id作为主键的记录
                if id_updates:
                    updated_count += self.db_manager.batch_update(
                        'bjhl_bulk', 
                        id_updates, 
                        ['id']
                    )
                
                # 批量更新使用project_code作为主键的记录
                if project_code_updates:
                    updated_count += self.db_manager.batch_update(
                        'bjhl_bulk', 
                        project_code_updates, 
                        ['project_code']
                    )
            
            result = {
                'success': True,
                'message': f'bjhl_bulk表assetType字段刷新完成',
                'updated_count': updated_count,
                'total_records': len(bulk_records),
                'prepared_updates': len(batch_update_data)
            }
            
            self.logger.info(f"bjhl_bulk表assetType字段刷新完成: 总记录数={len(bulk_records)}, 准备更新={len(batch_update_data)}, 实际更新行数={updated_count}")
            return result
            
        except Exception as e:
            self.logger.error(f"刷新bjhl_bulk表assetType字段失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'updated_count': 0
            }
    
    def _determine_asset_types(self, record: Dict[str, Any]) -> List[str]:
        """
        根据记录数据判断资产类型
        
        Args:
            record: 数据记录
            
        Returns:
            匹配的资产类型列表
        """
        matched_types = []
        
        # 遍历每种资产类型及其对应的字段
        for asset_type, field_names in self.BJHL_BULK_ASSET_TYPE_MAPPING.items():
            # 检查该资产类型对应的字段是否有值
            has_value = False
            for field_name in field_names:
                field_value = record.get(field_name)
                # 字段有值且不为空字符串
                if field_value is not None and str(field_value).strip() != '':
                    has_value = True
                    break
            
            if has_value:
                matched_types.append(asset_type)
        
        return matched_types
    
    def sync_bjhl_bulk_to_main_tables(self) -> Dict[str, Any]:
        """
        将bjhl_bulk数据根据assetType分发到对应的主表
        
        Returns:
            分发结果统计
        """
        try:
            self.logger.info("开始将bjhl_bulk数据分发到主表")
            
            # 首先刷新assetType字段
            refresh_result = self.refresh_bjhl_bulk_asset_type()
            if not refresh_result.get('success'):
                return {
                    'success': False,
                    'error': f"刷新assetType失败: {refresh_result.get('error')}",
                    'distributed_count': 0
                }
            
            # 获取更新后的bjhl_bulk数据
            query = "SELECT * FROM bjhl_bulk WHERE assetType IS NOT NULL AND assetType != ''"
            bulk_records = self.db_manager.execute_query(query)
            
            distribution_results = {}
            
            # 遍历每条记录进行分发
            for record in bulk_records:
                asset_type_str = record.get('assetType', '')
                if not asset_type_str:
                    continue
                
                # 解析多个资产类型
                asset_types = [t.strip() for t in asset_type_str.split(',') if t.strip()]
                
                # 为每个资产类型找到对应的主表
                for asset_type in asset_types:
                    target_tables = self._get_main_tables_for_asset_type(asset_type)
                    
                    for table_name in target_tables:
                        if table_name not in distribution_results:
                            distribution_results[table_name] = []
                        distribution_results[table_name].append(record)
            
            # 将分发结果写入各主表的临时数据中
            # 这里暂时存储结果，后续在主同步流程中使用
            self._bulk_distribution_cache = distribution_results
            
            total_distributed = sum(len(records) for records in distribution_results.values())
            
            result = {
                'success': True,
                'message': 'bjhl_bulk数据分发完成',
                'distributed_count': total_distributed,
                'target_tables': list(distribution_results.keys()),
                'distribution_details': {table: len(records) for table, records in distribution_results.items()}
            }
            
            self.logger.info(f"bjhl_bulk数据分发完成: {result}")
            return result
            
        except Exception as e:
            self.logger.error(f"bjhl_bulk数据分发失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'distributed_count': 0
            }
    
    def sync_bjhl_info_disclosure_to_main_tables(self) -> Dict[str, Any]:
        """
        将bjhl_info_disclosure数据根据project_type分发到对应的主表
        
        Returns:
            分发结果统计
        """
        try:
            self.logger.info("开始将bjhl_info_disclosure数据分发到主表")
            
            # 获取bjhl_info_disclosure数据（只获取有效状态的数据）
            # 只使用project_state字段，bjhl_info_disclosure表没有project_status字段
            query = """
            SELECT * FROM bjhl_info_disclosure 
            WHERE project_state = '1' 
            AND project_type IS NOT NULL AND project_type != ''
            """
            disclosure_records = self.db_manager.execute_query(query)
            
            distribution_results = {}
            
            # 遍历每条记录进行分发
            for record in disclosure_records:
                project_type_str = record.get('project_type', '')
                if not project_type_str:
                    continue
                
                # 解析多个项目类型
                project_types = [t.strip() for t in project_type_str.split(',') if t.strip()]
                
                # 为每个项目类型找到对应的主表
                for project_type in project_types:
                    target_tables = self._get_main_tables_for_project_type(project_type)
                    
                    for table_name in target_tables:
                        if table_name not in distribution_results:
                            distribution_results[table_name] = []
                        distribution_results[table_name].append(record)
            
            # 将分发结果写入各主表的临时数据中
            self._disclosure_distribution_cache = distribution_results
            
            total_distributed = sum(len(records) for records in distribution_results.values())
            
            result = {
                'success': True,
                'message': 'bjhl_info_disclosure数据分发完成',
                'distributed_count': total_distributed,
                'target_tables': list(distribution_results.keys()),
                'distribution_details': {table: len(records) for table, records in distribution_results.items()}
            }
            
            self.logger.info(f"bjhl_info_disclosure数据分发完成: {result}")
            return result
            
        except Exception as e:
            self.logger.error(f"bjhl_info_disclosure数据分发失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'distributed_count': 0
            }
    
    def _get_main_tables_for_asset_type(self, asset_type: str) -> List[str]:
        """
        根据资产类型获取对应的主表名列表
        
        Args:
            asset_type: 资产类型
            
        Returns:
            主表名列表
        """
        target_tables = []
        
        for table_name, asset_types in self.BULK_ASSET_TYPE_MAPPING.items():
            if asset_type in asset_types:
                target_tables.append(table_name)
        
        return target_tables
    
    def _get_main_tables_for_project_type(self, project_type: str) -> List[str]:
        """
        根据项目类型获取对应的主表名列表
        
        Args:
            project_type: 项目类型
            
        Returns:
            主表名列表
        """
        target_tables = []
        
        for table_name, project_types in self.INFO_DISCLOSURE_PROJECT_TYPE_MAPPING.items():
            if project_type in project_types:
                target_tables.append(table_name)
        
        return target_tables
    
    def _get_filtered_bulk_data_for_property_land(self) -> List[Dict[str, Any]]:
        """
        获取property_land主表需要的过滤后的bjhl_bulk数据
        （assetType包含土地或房屋建筑物）
        
        Returns:
            过滤后的bjhl_bulk数据列表
        """
        try:
            self.logger.info("获取property_land相关的bjhl_bulk数据")
            
            query = """
            SELECT * FROM bjhl_bulk 
            WHERE (assetType LIKE '%土地%' OR assetType LIKE '%房屋建筑物%')
            AND assetType IS NOT NULL AND assetType != ''
            AND project_state = '1'
            """
            bulk_records = self.db_manager.execute_query(query)
            
            self.logger.info(f"获取到property_land相关的bjhl_bulk数据: {len(bulk_records)} 条")
            return bulk_records
            
        except Exception as e:
            self.logger.error(f"获取property_land的bjhl_bulk数据失败: {e}")
            return []
    
    def _get_filtered_lease_house_data(self, bulk_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        根据bjhl_bulk数据获取对应的bjdc_lease_house数据
        
        Args:
            bulk_data: bjhl_bulk数据列表
            
        Returns:
            对应的bjdc_lease_house数据列表
        """
        try:
            if not bulk_data:
                self.logger.info("没有bjhl_bulk数据，跳过bjdc_lease_house查询")
                return []
            
            # 获取所有相关的project_code
            project_codes = [record.get('project_code') for record in bulk_data if record.get('project_code')]
            
            if not project_codes:
                self.logger.warning("bjhl_bulk数据中没有有效的project_code")
                return []
            
            self.logger.info(f"根据 {len(project_codes)} 个project_code查询bjdc_lease_house数据")
            
            # 获取bjdc_lease_house中对应的数据
            project_codes_str = "','".join(project_codes)
            query = f"""
            SELECT * FROM bjdc_lease_house 
            WHERE projectCode IN ('{project_codes_str}')
            AND project_status = '1'
            """
            lease_records = self.db_manager.execute_query(query)
            
            self.logger.info(f"获取到bjdc_lease_house数据: {len(lease_records)} 条")
            return lease_records
            
        except Exception as e:
            self.logger.error(f"获取bjdc_lease_house数据失败: {e}")
            return []
    
    def _get_filtered_house_rent_data(self) -> List[Dict[str, Any]]:
        """
        获取property_rental主表需要的bjhl_house_rent数据
        
        Returns:
            过滤后的bjhl_house_rent数据列表
        """
        try:
            self.logger.info("获取property_rental相关的bjhl_house_rent数据")
            
            query = """
            SELECT * FROM bjhl_house_rent 
            WHERE project_status = '1'
            """
            rent_records = self.db_manager.execute_query(query)
            
            self.logger.info(f"获取到bjhl_house_rent数据: {len(rent_records)} 条")
            return rent_records
            
        except Exception as e:
            self.logger.error(f"获取bjhl_house_rent数据失败: {e}")
            return []
    
    def _get_filtered_bjht_house_rent_data(self) -> List[Dict[str, Any]]:
        """
        获取property_rental主表需要的bjht_house_rent数据
        
        Returns:
            过滤后的bjht_house_rent数据列表
        """
        try:
            self.logger.info("获取property_rental相关的bjht_house_rent数据")
            
            query = """
            SELECT * FROM bjht_house_rent 
            WHERE project_status = '1'
            """
            rent_records = self.db_manager.execute_query(query)
            
            self.logger.info(f"获取到bjht_house_rent数据: {len(rent_records)} 条")
            return rent_records
            
        except Exception as e:
            self.logger.error(f"获取bjht_house_rent数据失败: {e}")
            return []
    
    def _get_lease_house_data_by_project_codes(self, project_codes: List[str]) -> List[Dict[str, Any]]:
        """
        根据project_code列表获取bjdc_lease_house数据
        
        Args:
            project_codes: project_code列表
            
        Returns:
            对应的bjdc_lease_house数据列表
        """
        try:
            if not project_codes:
                self.logger.info("没有project_code，跳过bjdc_lease_house查询")
                return []
            
            self.logger.info(f"根据 {len(project_codes)} 个project_code查询bjdc_lease_house数据")
            
            # 去重project_codes
            unique_project_codes = list(set(project_codes))
            
            # 获取bjdc_lease_house中对应的数据
            project_codes_str = "','".join(unique_project_codes)
            query = f"""
            SELECT * FROM bjdc_lease_house 
            WHERE projectCode IN ('{project_codes_str}')
            AND project_status = '1'
            """
            lease_records = self.db_manager.execute_query(query)
            
            self.logger.info(f"获取到bjdc_lease_house数据: {len(lease_records)} 条")
            return lease_records
            
        except Exception as e:
            self.logger.error(f"获取bjdc_lease_house数据失败: {e}")
            return []
    
    def _get_filtered_bjht_real_estate_transfer_data(self) -> List[Dict[str, Any]]:
        """
        获取property_land主表需要的bjht_real_estate_transfer数据
        
        Returns:
            过滤后的bjht_real_estate_transfer数据列表
        """
        try:
            self.logger.info("获取property_land相关的bjht_real_estate_transfer数据")
            
            query = """
            SELECT * FROM bjht_real_estate_transfer 
            WHERE project_state = '1'
            """
            transfer_records = self.db_manager.execute_query(query)
            
            self.logger.info(f"获取到bjht_real_estate_transfer数据: {len(transfer_records)} 条")
            return transfer_records
            
        except Exception as e:
            self.logger.error(f"获取bjht_real_estate_transfer数据失败: {e}")
            return []
    
    def close(self):
        """
        关闭所有连接
        """
        try:
            if self.db_manager:
                self.db_manager.close()
            self.logger.info("主表同步管理器连接已关闭")
        except Exception as e:
            self.logger.error(f"关闭主表同步管理器连接失败: {e}")


# 主表数据同步的设计思路和实现要点：
#
# 1. 数据源整合
#    - 从业务子表（bjhl_property_transfer、bjht_equity_transfer等）获取基础数据
#    - 从补充表（bjdc_lease_house）获取房源运营信息
#    - 按照业务逻辑进行数据关联和汇总
#
# 2. 数据处理流程
#    - 数据清洗：去重、格式化、空值处理
#    - 数据转换：字段映射、类型转换、计算字段
#    - 数据聚合：按项目维度进行数据汇总
#
# 3. 定时同步策略
#    - T+1同步：每日凌晨处理前一日的数据
#    - 增量同步：基于更新时间戳进行增量处理
#    - 全量同步：定期进行全量数据重建
#
# 4. 数据质量保证
#    - 数据校验：业务规则校验、完整性检查
#    - 错误处理：异常数据记录和处理
#    - 监控告警：同步状态监控和异常告警
#
# 5. 性能优化
#    - 批量处理：避免逐条处理，提高效率
#    - 并行处理：多线程/多进程处理不同业务表
#    - 缓存机制：合理使用缓存减少数据库压力
