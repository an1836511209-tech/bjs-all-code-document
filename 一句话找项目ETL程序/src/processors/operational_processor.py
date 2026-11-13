#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
房源运营数据处理器模块
负责处理房源运营信息的数据映射和转换
"""

from typing import Dict, Any, List
from datetime import datetime

from .base_processor import BaseDataProcessor
from src.core.config import get_config


class OperationalDataProcessor(BaseDataProcessor):
    """
    房源运营数据处理器
    专门处理房源运营信息数据（bjdc_lease_house表）
    """
    
    def __init__(self):
        """
        初始化房源运营数据处理器
        """
        super().__init__()
        self.field_mapping = get_config('field_mapping', {})
    
    def process_operational_data(self, api_data_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        处理房源运营信息数据（专门用于bjdc_lease_house表）
        
        Args:
            api_data_list: 房源运营信息API数据列表
            
        Returns:
            处理后的数据库记录列表
        """
        if not api_data_list:
            return []
        
        try:
            # 获取bjdc_lease_house表的字段映射配置
            table_config = self.field_mapping.get('bjdc_lease_house', {})
            field_mapping = table_config.get('fields', {})
            
            if not field_mapping:
                self.logger.warning("bjdc_lease_house表没有配置字段映射")
                return []
            
            processed_records = []
            
            for api_data in api_data_list:
                try:
                    # 获取项目基础信息
                    project_id = api_data.get('projectId')
                    target_list = api_data.get('targetList', [])
                    
                    if not target_list:
                        # 如果没有targetList，创建一条只有projectId的记录
                        base_record = {
                            'projectId': project_id,
                            'created_at': datetime.now().strftime(self.date_format),
                            'updated_at': datetime.now().strftime(self.date_format)
                        }
                        
                        # 设置其他字段为None或默认值
                        for db_field, api_path in field_mapping.items():
                            if db_field not in base_record:
                                # 检查是否是默认值（包含中文字符、逗号或等于'0'/'1'，且不是典型的API字段名）
                                if isinstance(api_path, str) and (
                                    # 包含中文字符或逗号，明显是默认值
                                    any('\u4e00' <= char <= '\u9fff' for char in api_path) or ',' in api_path or
                                    # 等于'0'或'1'的特殊默认值
                                    api_path == '0' or api_path == '1'
                                ) and not ('.' in api_path or '[' in api_path):
                                    # 如果是默认值，直接使用该值
                                    base_record[db_field] = api_path
                                else:
                                    base_record[db_field] = None
                        
                        processed_records.append(base_record)
                        continue
                    
                    # 遍历每个target，为每个target创建记录
                    for target in target_list:
                        try:
                            record = {
                                'projectId': project_id,
                                'created_at': datetime.now().strftime(self.date_format),
                                'updated_at': datetime.now().strftime(self.date_format)
                            }
                            
                            # 处理每个字段映射
                            for db_field, api_path in field_mapping.items():
                                if db_field in ['created_at', 'updated_at', 'projectId']:
                                    continue  # 这些字段已经处理了
                                
                                # 检查是否是默认值（包含中文字符、逗号或等于'0'/'1'，且不是典型的API字段名）
                                if isinstance(api_path, str) and (
                                    # 包含中文字符或逗号，明显是默认值
                                    any('\u4e00' <= char <= '\u9fff' for char in api_path) or ',' in api_path or
                                    # 等于'0'或'1'的特殊默认值
                                    api_path == '0' or api_path == '1'
                                ) and not ('.' in api_path or '[' in api_path):
                                    # 如果是默认值，直接使用该值
                                    record[db_field] = api_path
                                    continue
                                
                                value = None
                                
                                if api_path.startswith('targetList[].'):
                                    # 从target中获取值
                                    field_path = api_path[13:]  # 移除 'targetList[].' 前缀
                                    value = self._get_target_value(target, field_path)
                                else:
                                    # 从项目根级别获取值（如projectId）
                                    value = self.path_resolver.get_value_by_path(api_data, api_path)
                                
                                # 处理特殊字段类型
                                if db_field == 'allFloor' and value is not None:
                                    try:
                                        value = str(int(value)) if value != '' else None
                                    except (ValueError, TypeError):
                                        value = None
                                
                                record[db_field] = value
                            
                            processed_records.append(record)
                            
                        except Exception as e:
                            self.logger.error(f"处理target失败: {e}, target: {target}")
                            continue
                    
                except Exception as e:
                    self.logger.error(f"处理项目数据失败: {e}, projectId: {api_data.get('projectId', 'unknown')}")
                    continue
            
            self.logger.info(f"房源运营信息数据处理完成，输入: {len(api_data_list)}, 输出: {len(processed_records)}")
            return processed_records
            
        except Exception as e:
            self.logger.error(f"房源运营信息批量数据处理失败: {e}")
            raise
    
    def _get_target_value(self, target: Dict[str, Any], field_path: str) -> Any:
        """
        从target数据中获取字段值
        
        Args:
            target: target数据字典
            field_path: 字段路径
            
        Returns:
            字段值
        """
        try:
            # 处理数组字段（如houseLabelList[].houseLabelCode）
            if '[]' in field_path:
                array_part, field_part = field_path.split('[]', 1)
                field_part = field_part.lstrip('.')  # 移除开头的点
                
                # 获取数组数据
                array_data = target.get(array_part)
                if not isinstance(array_data, list) or not array_data:
                    return None
                
                # 如果有子字段，提取第一个元素的子字段值
                if field_part:
                    first_item = array_data[0]
                    if isinstance(first_item, dict):
                        return first_item.get(field_part)
                    return None
                else:
                    # 直接返回第一个元素
                    return array_data[0] if array_data else None
            else:
                # 普通字段访问
                return target.get(field_path)
                
        except Exception as e:
            self.logger.warning(f"获取target字段值失败: {field_path}, 错误: {e}")
            return None
