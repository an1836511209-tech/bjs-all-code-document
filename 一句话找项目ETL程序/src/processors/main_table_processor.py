#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主表ETL处理器
负责主表的通用ETL逻辑处理，支持配置驱动的字段映射
"""

import json
import os
import logging
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

from src.processors.base_processor import BaseDataProcessor


class MainTableETLProcessor(BaseDataProcessor):
    """
    主表ETL处理器
    
    负责根据配置文件实现通用的主表ETL逻辑：
    1. 读取主表目录下的ETL配置
    2. 从子表获取数据
    3. 根据映射规则转换数据
    4. 生成主表数据
    """
    
    def __init__(self):
        """初始化主表ETL处理器"""
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.main_table_config_dir = Path("表结构信息/主表")
    
    def get_main_table_configs(self) -> Dict[str, Dict]:
        """
        获取所有主表配置
        
        Returns:
            主表配置字典，key为主表名，value为配置信息
        """
        configs = {}
        
        try:
            if not self.main_table_config_dir.exists():
                self.logger.error(f"主表配置目录不存在: {self.main_table_config_dir}")
                return configs
            
            # 遍历主表目录
            for main_table_dir in self.main_table_config_dir.iterdir():
                if main_table_dir.is_dir():
                    # 提取主表名（去掉中文描述）
                    main_table_name = self._extract_table_name(main_table_dir.name)
                    
                    # 读取主表配置
                    config = self._load_main_table_config(main_table_dir, main_table_name)
                    if config:
                        configs[main_table_name] = config
            
            self.logger.info(f"加载主表配置完成，共 {len(configs)} 个主表")
            return configs
            
        except Exception as e:
            self.logger.error(f"获取主表配置失败: {e}")
            return configs
    
    def _extract_table_name(self, dir_name: str) -> str:
        """
        从目录名提取主表名
        
        Args:
            dir_name: 目录名，如 "股权增资表equity_increase"
            
        Returns:
            主表名，如 "equity_increase"
        """
        # 查找英文表名（下划线命名）
        import re
        match = re.search(r'([a-z_]+)$', dir_name)
        if match:
            return match.group(1)
        else:
            # 如果没有找到，直接返回目录名
            return dir_name
    
    def _load_main_table_config(self, main_table_dir: Path, main_table_name: str) -> Optional[Dict]:
        """
        加载单个主表的配置
        
        Args:
            main_table_dir: 主表目录路径
            main_table_name: 主表名
            
        Returns:
            主表配置信息
        """
        try:
            config = {
                'name': main_table_name,
                'directory': str(main_table_dir),
                'etl_mappings': [],
                'table_schema': None
            }
            
            # 1. 读取所有ETL映射文件
            for file_path in main_table_dir.glob("*子表etl.json"):
                etl_mapping = self._load_etl_mapping(file_path)
                if etl_mapping:
                    config['etl_mappings'].extend(etl_mapping)
            
            # 2. 读取主表schema文件
            schema_files = list(main_table_dir.glob(f"*{main_table_name}.json"))
            if schema_files:
                config['table_schema'] = self._load_table_schema(schema_files[0])
            
            if not config['etl_mappings']:
                self.logger.warning(f"主表 {main_table_name} 没有ETL映射配置")
                return None
            
            self.logger.info(f"加载主表配置成功: {main_table_name}, ETL映射数: {len(config['etl_mappings'])}")
            return config
            
        except Exception as e:
            self.logger.error(f"加载主表配置失败 {main_table_name}: {e}")
            return None
    
    def _load_etl_mapping(self, file_path: Path) -> Optional[List[Dict]]:
        """
        加载ETL映射文件
        
        Args:
            file_path: ETL映射文件路径
            
        Returns:
            ETL映射列表
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                mappings = json.load(f)
            
            # 验证映射格式
            if not isinstance(mappings, list):
                self.logger.error(f"ETL映射文件格式错误: {file_path}")
                return None
            
            # 验证每个映射的必要字段
            for mapping in mappings:
                required_fields = ['子表名', '子表字段', '主表名', '主表字段']
                if not all(field in mapping for field in required_fields):
                    self.logger.error(f"ETL映射缺少必要字段: {file_path}, 映射: {mapping}")
                    return None
            
            self.logger.debug(f"加载ETL映射成功: {file_path}, 映射数: {len(mappings)}")
            return mappings
            
        except Exception as e:
            self.logger.error(f"加载ETL映射文件失败 {file_path}: {e}")
            return None
    
    def _load_table_schema(self, file_path: Path) -> Optional[List[Dict]]:
        """
        加载主表schema文件
        
        Args:
            file_path: schema文件路径
            
        Returns:
            主表字段定义列表
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                schema = json.load(f)
            
            if not isinstance(schema, list):
                self.logger.error(f"主表schema文件格式错误: {file_path}")
                return None
            
            self.logger.debug(f"加载主表schema成功: {file_path}, 字段数: {len(schema)}")
            return schema
            
        except Exception as e:
            self.logger.error(f"加载主表schema文件失败 {file_path}: {e}")
            return None
    
    def process_main_table_data(self, main_table_name: str, subtable_data: Dict[str, List[Dict]]) -> List[Dict[str, Any]]:
        """
        处理主表数据
        支持特殊ETL逻辑：property_land和property_rental的bjdc_lease_house补充数据处理
        
        Args:
            main_table_name: 主表名
            subtable_data: 子表数据，key为子表名，value为数据列表
            
        Returns:
            处理后的主表数据列表
        """
        try:
            # 获取主表配置
            all_configs = self.get_main_table_configs()
            if main_table_name not in all_configs:
                raise ValueError(f"未找到主表配置: {main_table_name}")
            
            config = all_configs[main_table_name]
            etl_mappings = config['etl_mappings']
            
            # 特殊处理：property_land和property_rental主表的笛卡尔积逻辑
            if main_table_name in ['property_land', 'property_rental']:
                return self._process_special_main_table_data(main_table_name, subtable_data, etl_mappings)
            
            # 常规处理：按子表分组映射规则
            mappings_by_subtable = self._group_mappings_by_subtable(etl_mappings)
            
            # 处理每个子表数据并合并（允许数据冗余）
            main_table_records = []
            
            for subtable_name, mappings in mappings_by_subtable.items():
                if subtable_name not in subtable_data:
                    self.logger.warning(f"未找到子表数据: {subtable_name}")
                    continue
                
                # 处理该子表的数据
                self.logger.info(f"开始处理子表 {subtable_name}，数据量: {len(subtable_data[subtable_name])}")
                records = self._process_subtable_to_main(
                    subtable_data[subtable_name], 
                    mappings
                )
                self.logger.info(f"子表 {subtable_name} 处理完成，生成记录数: {len(records)}")
                main_table_records.extend(records)
            
            # 数据后处理：填充默认值、类型转换等
            processed_records = self._post_process_main_table_data(main_table_records, config)
            
            self.logger.info(f"主表 {main_table_name} 数据处理完成，生成记录数: {len(processed_records)}")
            return processed_records
            
        except Exception as e:
            self.logger.error(f"处理主表数据失败 {main_table_name}: {e}")
            raise
    
    def _group_mappings_by_subtable(self, etl_mappings: List[Dict]) -> Dict[str, List[Dict]]:
        """
        按子表名分组ETL映射
        
        Args:
            etl_mappings: ETL映射列表
            
        Returns:
            按子表名分组的映射字典
        """
        mappings_by_subtable = {}
        
        for mapping in etl_mappings:
            subtable_name = mapping['子表名']
            if subtable_name not in mappings_by_subtable:
                mappings_by_subtable[subtable_name] = []
            mappings_by_subtable[subtable_name].append(mapping)
        
        return mappings_by_subtable
    
    def _process_subtable_to_main(self, subtable_records: List[Dict], mappings: List[Dict], processed_projects: set = None) -> List[Dict]:
        """
        将子表数据转换为主表数据
        
        Args:
            subtable_records: 子表数据记录列表
            mappings: 该子表的字段映射规则
            processed_projects: 已处理的项目集合（保留参数兼容性，但不使用）
            
        Returns:
            转换后的主表数据记录列表
        """
        main_records = []
        
        # 创建字段映射字典
        field_mapping = {}
        for mapping in mappings:
            subtable_field = mapping['子表字段']
            main_field = mapping['主表字段']
            field_mapping[subtable_field] = main_field
        
        for record in subtable_records:
            try:
                # 创建主表记录
                main_record = {}
                
                # 根据映射转换字段
                for subtable_field, main_field in field_mapping.items():
                    if subtable_field in record:
                        main_record[main_field] = record[subtable_field]
                
                # 直接添加记录，不进行去重处理
                main_records.append(main_record)
                
            except Exception as e:
                self.logger.error(f"转换子表记录失败: {e}, 记录: {record.get('id', 'unknown')}")
                continue
        
        return main_records
    
    
    def _post_process_main_table_data(self, records: List[Dict], config: Dict) -> List[Dict]:
        """
        主表数据后处理
        
        Args:
            records: 原始主表记录
            config: 主表配置
            
        Returns:
            后处理的主表记录
        """
        processed_records = []
        
        for record in records:
            try:
                # 1. 添加默认字段
                processed_record = self._add_default_fields(record.copy())
                
                # 2. 数据类型转换和清理
                processed_record = self._clean_and_convert_data(processed_record)
                
                # 3. 验证必要字段
                if self._validate_record(processed_record):
                    processed_records.append(processed_record)
                else:
                    self.logger.warning(f"记录验证失败，跳过: {processed_record.get('project_code', 'unknown')}")
                
            except Exception as e:
                self.logger.error(f"后处理记录失败: {e}")
                continue
        
        return processed_records
    
    def _clean_and_convert_data(self, record: Dict) -> Dict:
        """
        清理和转换数据
        
        Args:
            record: 原始记录
            
        Returns:
            清理后的记录
        """
        cleaned_record = {}
        
        for field, value in record.items():
            try:
                # 处理None值和空字符串
                if value is None or value == '':
                    # 根据字段类型提供默认值
                    cleaned_record[field] = self._get_default_value_for_field(field)
                # 处理字符串
                elif isinstance(value, str):
                    cleaned_value = value.strip()
                    cleaned_record[field] = cleaned_value if cleaned_value else self._get_default_value_for_field(field)
                # 其他类型直接保留
                else:
                    cleaned_record[field] = value
                    
            except Exception as e:
                self.logger.warning(f"清理字段数据失败 {field}: {e}")
                cleaned_record[field] = self._get_default_value_for_field(field)
        
        return cleaned_record
    
    def _get_default_value_for_field(self, field_name: str) -> Any:
        """
        为字段获取默认值
        
        Args:
            field_name: 字段名
            
        Returns:
            默认值
        """
        # 根据字段名或类型返回适当的默认值
        if field_name in ['project_status']:
            return '0'  # 状态字段默认为字符串'0'
        elif 'date' in field_name.lower() or 'time' in field_name.lower():
            return None  # 日期时间字段可以为None
        elif field_name in ['created_at', 'updated_at']:
            return None  # 时间戳字段由数据库自动处理
        elif 'count' in field_name.lower() or 'number' in field_name.lower():
            return 0  # 数量字段默认为0
        elif 'amount' in field_name.lower() or 'price' in field_name.lower():
            return '0'  # 金额字段默认为字符串'0'
        else:
            return ''  # 其他字段默认为空字符串
    
    def _validate_record(self, record: Dict) -> bool:
        """
        验证记录是否有效
        
        Args:
            record: 记录数据
            
        Returns:
            是否有效
        """
        # 检查关键字段
        key_fields = [ 'project_code']
        
        for field in key_fields:
            if field in record and record[field]:
                return True
        
        # 如果关键字段都为空，认为记录无效
        return False
    
    def _process_special_main_table_data(self, main_table_name: str, subtable_data: Dict[str, List[Dict]], etl_mappings: List[Dict]) -> List[Dict[str, Any]]:
        """
        处理property_land和property_rental主表的特殊ETL逻辑
        1. 先按常规ETL处理正常数据源，生成独立的主表记录
        2. 再用bjdc_lease_house作为补充数据源，为现有记录补充字段（笛卡尔积）
        
        Args:
            main_table_name: 主表名
            subtable_data: 子表数据字典
            etl_mappings: ETL映射配置
            
        Returns:
            处理后的主表数据列表
        """
        try:
            self.logger.info(f"开始处理{main_table_name}主表的特殊ETL逻辑")
            
            # 按子表分组映射规则
            mappings_by_subtable = self._group_mappings_by_subtable(etl_mappings)
            
            # 定义常规数据源（使用ETL配置文件）
            if main_table_name == 'property_land':
                normal_sources = ['bjhl_bulk', 'bjht_real_estate_transfer']
            elif main_table_name == 'property_rental':
                normal_sources = ['bjhl_house_rent', 'bjht_house_rent', 'bjhl_info_disclosure']
            else:
                raise ValueError(f"不支持的特殊处理主表: {main_table_name}")
            
            # 第一步：按常规ETL处理正常数据源，生成基础记录
            base_records = []
            
            for source_name in normal_sources:
                if source_name not in subtable_data:
                    self.logger.warning(f"未找到常规数据源: {source_name}")
                    continue
                
                if source_name not in mappings_by_subtable:
                    self.logger.warning(f"未找到常规数据源的映射配置: {source_name}")
                    continue
                
                source_data = subtable_data[source_name]
                source_mappings = mappings_by_subtable[source_name]
                
                self.logger.info(f"按常规ETL处理数据源 {source_name}，数据量: {len(source_data)}")
                
                # 按常规ETL处理：每条记录生成一个独立的主表记录
                source_records = self._process_subtable_to_main(source_data, source_mappings)
                
                # 为后续补充处理保留project_code信息
                for i, record in enumerate(source_records):
                    if i < len(source_data):
                        record['_source_project_code'] = source_data[i].get('project_code')
                        record['_source_table'] = source_name
                
                base_records.extend(source_records)
            
            self.logger.info(f"常规ETL处理完成，生成基础记录数: {len(base_records)}")
            
            # 第二步：用bjdc_lease_house补充字段（不依赖ETL配置文件）
            supplement_data = subtable_data.get('bjdc_lease_house', [])
            
            if not supplement_data:
                self.logger.warning("未找到bjdc_lease_house补充数据")
                # 清理临时字段后返回基础记录
                final_records = []
                for record in base_records:
                    record.pop('_source_project_code', None)
                    record.pop('_source_table', None)
                    final_records.append(record)
                return final_records
            
            self.logger.info(f"处理bjdc_lease_house补充数据，数据量: {len(supplement_data)}")
            
            # 按project_code分组补充数据（bjdc_lease_house用的是projectCode字段）
            supplement_by_project = {}
            for supplement_record in supplement_data:
                project_code = supplement_record.get('projectCode')  # bjdc_lease_house用的是projectCode
                if project_code:
                    if project_code not in supplement_by_project:
                        supplement_by_project[project_code] = []
                    supplement_by_project[project_code].append(supplement_record)
            
            # 第三步：执行笛卡尔积匹配补充
            final_records = []
            
            for base_record in base_records:
                source_project_code = base_record.get('_source_project_code')
                
                # 查找对应的补充数据
                matching_supplements = supplement_by_project.get(source_project_code, [])
                
                if matching_supplements:
                    # 笛卡尔积：一个基础记录对应多个补充记录
                    for supplement_record in matching_supplements:
                        try:
                            # 创建组合记录
                            enhanced_record = base_record.copy()
                            
                            # 添加bjdc_lease_house的补充字段（硬编码映射）
                            supplement_fields = self._extract_bjdc_lease_house_fields(supplement_record, main_table_name)
                            enhanced_record.update(supplement_fields)
                            
                            # 清理临时字段
                            enhanced_record.pop('_source_project_code', None)
                            enhanced_record.pop('_source_table', None)
                            
                            final_records.append(enhanced_record)
                            
                        except Exception as e:
                            self.logger.error(f"补充bjdc_lease_house字段失败: {e}")
                            continue
                else:
                    # 如果没有对应的补充数据，保留基础记录
                    base_record.pop('_source_project_code', None)
                    base_record.pop('_source_table', None)
                    final_records.append(base_record)
            
            self.logger.info(f"{main_table_name}特殊ETL处理完成: 基础记录数={len(base_records)}, 补充数据组数={len(supplement_by_project)}, 最终记录数={len(final_records)}")
            
            return final_records
            
        except Exception as e:
            self.logger.error(f"特殊ETL处理失败 {main_table_name}: {e}")
            raise
    
    def _convert_record_with_mappings(self, record: Dict[str, Any], mappings: List[Dict]) -> Dict[str, Any]:
        """
        根据映射配置转换记录
        
        Args:
            record: 原始记录
            mappings: 字段映射配置
            
        Returns:
            转换后的记录
        """
        converted_record = {}
        
        for mapping in mappings:
            source_field = mapping['子表字段']
            target_field = mapping['主表字段']
            
            if source_field in record:
                converted_record[target_field] = record[source_field]
        
        return converted_record
    
    def _extract_bjdc_lease_house_fields(self, record: Dict[str, Any], main_table_name: str) -> Dict[str, Any]:
        """
        从bjdc_lease_house记录中提取补充字段（硬编码映射，不依赖ETL配置文件）
        只提取补充字段，跳过关键字段避免覆盖
        
        Args:
            record: bjdc_lease_house记录
            main_table_name: 主表名
            
        Returns:
            补充字段字典
        """
        supplement_fields = {}
        
        # 通用补充字段映射（两个主表都适用）
        common_field_mappings = {
            'assetCls': 'asset_category_name',           # 资产分类名称
            'houseLabelCode': 'house_label_code',        # 房源标签
            'community': 'community_name',               # 所属小区
            'houseType': 'house_layout',                 # 房源户型
            'floor': 'floor_number',                     # 所在楼层
            'allFloor': 'total_floors',                  # 总楼层
            'houseTowardName': 'house_orientation',      # 房源朝向
            'decoration': 'decoration_status',           # 装修情况
            'isElevator': 'has_elevator',                # 配备电梯
            'heatingMethod': 'heating_method',           # 供暖方式
            'houseFeatures': 'house_features',           # 房源特色
            'elevatorType': 'elevator_type',             # 电梯类型
            'parking': 'has_parking',                    # 停车场
            'carSpaceType': 'parking_space_type',        # 车位类型
            'chargingStation': 'has_charging_station',   # 充电桩
            'listed_tags': 'listed_tags'                 # 挂牌标签
        }
        
        # 从record中提取补充字段
        for source_field, target_field in common_field_mappings.items():
            if source_field in record:
                value = record[source_field]
                if value is not None:  # 只有非null值才补充
                    supplement_fields[target_field] = value
        
        self.logger.debug(f"从bjdc_lease_house提取到 {len(supplement_fields)} 个补充字段: {list(supplement_fields.keys())}")
        
        return supplement_fields
