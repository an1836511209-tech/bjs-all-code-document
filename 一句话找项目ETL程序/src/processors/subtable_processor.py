#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
子表数据处理器模块
负责处理业务子表的数据映射和转换
"""

import json
import itertools
from typing import Dict, Any, List, Tuple
from datetime import datetime

from .base_processor import BaseDataProcessor
from src.core.config import get_config


class SubtableDataProcessor(BaseDataProcessor):
    """
    子表数据处理器
    负责业务子表的数据映射、转换和处理
    """
    
    def __init__(self):
        """
        初始化子表数据处理器
        """
        super().__init__()
        self.field_mapping = get_config('field_mapping', {})
    
    def get_table_name_by_biz_sys(self, biz_sys: str) -> str:
        """
        根据业务系统获取表名
        
        Args:
            biz_sys: 业务系统名称
            
        Returns:
            表名
        """
        biz_sys_mapping = get_config('biz_sys_mapping', {})
        table_name = biz_sys_mapping.get(biz_sys)
        return table_name
    
    def process_data_by_biz_sys(self, api_data_list: List[Dict[str, Any]], 
                               biz_sys: str) -> List[Dict[str, Any]]:
        """
        根据业务系统处理数据（通用方法）
        
        Args:
            api_data_list: API数据列表
            biz_sys: 业务系统名称
            
        Returns:
            处理后的数据列表
        """
        table_name = self.get_table_name_by_biz_sys(biz_sys)
        
        if not table_name:
            self.logger.warning(f"未找到业务系统 '{biz_sys}' 对应的表名")
            return []
        
        # 使用通用的数据处理方法
        processed_data = self.process_table_data(api_data_list, table_name)
        
        # 验证处理后的数据
        valid_records = []
        for record in processed_data:
            if self.validate_record(record, table_name):
                valid_records.append(record)
        
        self.logger.info(f"数据验证完成，有效记录: {len(valid_records)}/{len(processed_data)}")
        return valid_records
    
    def process_table_data(self, api_data_list: List[Dict[str, Any]], 
                          table_name: str) -> List[Dict[str, Any]]:
        """
        通用的表数据处理方法
        
        Args:
            api_data_list: API数据列表
            table_name: 表名
            
        Returns:
            处理后的数据库记录列表（展开后可能比输入多）
        """
        if not api_data_list:
            return []
        
        try:
            # 从配置中获取表的字段映射配置
            table_config = self.field_mapping.get(table_name, {})
            field_mapping = table_config.get('fields', {})
            
            if not field_mapping:
                self.logger.warning(f"表 '{table_name}' 没有配置字段映射")
                return []
            
            # 标准化字段路径（移除 data.list[] 前缀）
            normalized_mapping = self._normalize_field_paths(field_mapping)
            
            # 分组普通字段和数组字段
            normal_fields, array_groups = self._group_array_fields(normalized_mapping)
            
            processed_records = []
            
            for api_data in api_data_list:
                try:
                    # 处理普通字段
                    base_record = self._process_normal_fields(api_data, normal_fields)
                    
                    # 展开数组字段，生成多条记录
                    expanded_records = self._expand_array_fields(api_data, array_groups)
                    
                    # 为每个展开的记录添加基础字段
                    for expanded_record in expanded_records:
                        # 合并基础记录和展开记录
                        final_record = base_record.copy()
                        final_record.update(expanded_record)
                        
                        # 添加默认字段
                        final_record = self._add_default_fields(final_record)
                        
                        processed_records.append(final_record)
                    
                except Exception as e:
                    self.logger.error(f"处理单条记录失败: {e}, 数据: {api_data.get('id', 'unknown')}")
                    continue
            
            self.logger.info(f"{table_name}数据处理完成，输入: {len(api_data_list)}, 输出: {len(processed_records)}")
            return processed_records
            
        except Exception as e:
            self.logger.error(f"{table_name}批量数据处理失败: {e}")
            raise
    
    def _group_array_fields(self, field_mapping: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
        """
        分组普通字段和数组字段
        
        Args:
            field_mapping: 字段映射配置
            
        Returns:
            (普通字段映射, 数组字段分组)
        """
        normal_fields = {}
        array_groups = {}
        
        for db_field, api_path in field_mapping.items():
            if '[]' in api_path:
                # 数组字段
                array_path = api_path.split('[]')[0]  # 获取数组路径部分
                if array_path not in array_groups:
                    array_groups[array_path] = []
                array_groups[array_path].append((db_field, api_path))
            else:
                # 普通字段
                normal_fields[db_field] = api_path
        
        return normal_fields, array_groups
    
    def _process_normal_fields(self, api_data: Dict[str, Any], 
                             field_mapping: Dict[str, str]) -> Dict[str, Any]:
        """
        处理普通字段（非数组字段）
        
        Args:
            api_data: API数据
            field_mapping: 字段映射
            
        Returns:
            处理后的字段字典
        """
        result = {}
        
        for db_field, api_path in field_mapping.items():
            # 检查是否是默认值（包含中文字符、逗号或等于'0'/'1'，且不是典型的API字段名）
            if isinstance(api_path, str) and (
                # 包含中文字符或逗号，明显是默认值
                any('\u4e00' <= char <= '\u9fff' for char in api_path) or ',' in api_path or
                # 等于'0'或'1'的特殊默认值
                api_path == '0' or api_path == '1'
            ) and not ('.' in api_path or '[' in api_path):
                # 如果是默认值，直接使用该值
                value = api_path
            else:
                # 否则从API数据中提取值
                value = self.path_resolver.get_value_by_path(api_data, api_path)
            
            # 特殊字段处理
            if db_field in ['dic_start', 'dic_end', 'created_at', 'updated_at', 'register_date', 'ratify_date']:
                value = self._convert_datetime(value)
            elif db_field in ['BDJBXX', 'JYLC', 'content']:
                value = self._clean_html(value)
            elif db_field in ['track_tags', 'trending_tags', 'listed_tags']:
                # 标签字段特殊处理：数组转换为逗号分隔的字符串
                if isinstance(value, list):
                    value = ','.join(str(item) for item in value if item) if value else None
                elif isinstance(value, str):
                    value = value  # 保持字符串不变
                else:
                    value = None
            elif isinstance(value, (list, dict)):
                # 如果是复杂类型，转换为JSON字符串
                try:
                    value = json.dumps(value, ensure_ascii=False) if value else None
                except Exception:
                    value = str(value) if value else None
            
            result[db_field] = value
        
        return result
    
    def _expand_array_fields(self, api_data: Dict[str, Any], 
                           array_groups: Dict[str, List[Tuple[str, str]]]) -> List[Dict[str, Any]]:
        """
        展开数组字段，生成笛卡尔积记录
        
        Args:
            api_data: API数据
            array_groups: 数组字段分组
            
        Returns:
            展开后的记录列表
        """
        if not array_groups:
            return [{}]
        
        # 收集所有数组数据
        arrays_data = {}
        
        for array_path, field_list in array_groups.items():
            # 获取数组数据
            array_data = self.path_resolver.get_value_by_path(api_data, array_path)
            
            if isinstance(array_data, list) and len(array_data) > 0:
                arrays_data[array_path] = {
                    'data': array_data,
                    'fields': field_list
                }
        
        # 如果没有有效的数组数据，返回空记录
        if not arrays_data:
            # 创建包含所有数组字段的空记录
            empty_record = {}
            for field_list in array_groups.values():
                for db_field, _ in field_list:
                    empty_record[db_field] = None
            return [empty_record]
        
        # 生成笛卡尔积
        array_names = list(arrays_data.keys())
        array_values = [arrays_data[name]['data'] for name in array_names]
        
        expanded_records = []
        for combination in itertools.product(*array_values):
            record = {}
            
            # 为每个数组字段添加对应的值
            for i, array_name in enumerate(array_names):
                array_item = combination[i]
                field_list = arrays_data[array_name]['fields']
                
                for db_field, api_path in field_list:
                    # 检查是否是默认值（包含中文字符、逗号或等于'0'，且不是典型的API字段名）
                    if isinstance(api_path, str) and (
                        # 包含中文字符或逗号，明显是默认值
                        any('\u4e00' <= char <= '\u9fff' for char in api_path) or ',' in api_path or
                        # 等于'0'的特殊默认值
                        api_path == '0' or
                        # 等于'1'的特殊默认值
                        api_path == '1'
                    ) and not ('.' in api_path or '[' in api_path):
                        # 如果是默认值，直接使用该值
                        value = api_path
                    else:
                        # 从数组元素中提取字段值
                        value = self.path_resolver.get_value_by_path(api_data, api_path)
                        
                        # 如果是数组路径，从当前组合项中获取值
                        if '[]' in api_path and isinstance(array_item, dict):
                            field_part = api_path.split('[]', 1)[1].lstrip('.')
                            if field_part:
                                value = self.path_resolver.get_value_by_path(array_item, field_part)
                            else:
                                value = array_item
                    
                    # 特殊字段处理
                    if db_field in ['ratify_date', 'register_date']:
                        value = self._convert_datetime(value)
                    elif db_field in ['content']:
                        value = self._clean_html(value)
                    
                    record[db_field] = str(value) if value is not None else None
            
            # 确保所有数组字段都有值（即使是None）
            for field_list in array_groups.values():
                for db_field, _ in field_list:
                    if db_field not in record:
                        record[db_field] = None
            
            expanded_records.append(record)
        
        return expanded_records
