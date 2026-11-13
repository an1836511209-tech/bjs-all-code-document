#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基础数据处理器模块
提供通用的数据映射和转换功能
"""

import logging
import json
import re
from typing import Dict, Any, List, Optional, Union, Tuple
from datetime import datetime
from html import unescape

from src.core.config import get_config


class FieldPathResolver:
    """
    字段路径解析器
    支持深层字段访问、JSON解析和数组展开
    """
    
    @staticmethod
    def get_value_by_path(data: Dict[str, Any], path: str) -> Any:
        """
        根据路径获取数据值
        
        支持的路径格式：
        - simple_field: 简单字段
        - detail.field_name: 嵌套字段
        - labels[0].track_tags: JSON数组索引访问
        - detail.array[].field: 数组展开（返回所有元素的值列表）
        
        Args:
            data: 数据字典
            path: 字段路径
            
        Returns:
            字段值或值列表（数组展开时）
        """
        if not path or not data:
            return None
        
        try:
            # 检查是否是数组展开路径
            if '[]' in path:
                return FieldPathResolver._get_array_values(data, path)
            
            # 处理普通路径
            return FieldPathResolver._get_single_value(data, path)
            
        except Exception as e:
            logging.getLogger(__name__).warning(f"字段路径解析失败: {path}, 错误: {e}")
            return None
    
    @staticmethod
    def _get_single_value(data: Dict[str, Any], path: str) -> Any:
        """
        获取单个值
        
        Args:
            data: 数据字典
            path: 字段路径
            
        Returns:
            字段值
        """
        parts = FieldPathResolver._split_path(path)
        current_data = data
        
        for part in parts:
            if current_data is None:
                return None
            
            # 处理数组索引 [0]
            if '[' in part and ']' in part and '[]' not in part:
                field_name, index_part = part.split('[', 1)
                index = int(index_part.replace(']', ''))
                
                if field_name:
                    # 先获取字段值
                    field_value = current_data.get(field_name) if isinstance(current_data, dict) else None
                    
                    # 如果是JSON字符串，先解析
                    if isinstance(field_value, str):
                        try:
                            field_value = json.loads(field_value)
                        except (json.JSONDecodeError, TypeError):
                            return None
                    
                    current_data = field_value
                else:
                    # 直接索引当前数据
                    pass
                
                if isinstance(current_data, (list, tuple)) and len(current_data) > index:
                    current_data = current_data[index]
                else:
                    return None
            else:
                # 普通字段访问
                if isinstance(current_data, dict):
                    current_data = current_data.get(part)
                    
                    # 如果获取到的值是JSON字符串，尝试解析
                    if isinstance(current_data, str) and (current_data.startswith('[') or current_data.startswith('{')):
                        try:
                            parsed_data = json.loads(current_data)
                            current_data = parsed_data
                        except (json.JSONDecodeError, TypeError):
                            # 解析失败时保持原值，可能不是JSON格式
                            pass
                else:
                    return None
        
        return current_data
    
    @staticmethod
    def _get_array_values(data: Dict[str, Any], path: str) -> List[Any]:
        """
        获取数组展开的所有值
        
        Args:
            data: 数据字典
            path: 数组路径（包含[]）
            
        Returns:
            值列表
        """
        # 分割数组路径：detail.top_shareholders_company[].shareholderName
        # 分为：detail.top_shareholders_company 和 shareholderName
        array_part, field_part = path.split('[]', 1)
        field_part = field_part.lstrip('.')  # 移除开头的点
        
        # 获取数组数据
        array_data = FieldPathResolver._get_single_value(data, array_part)
        
        # 如果是JSON字符串，先解析为对象
        if isinstance(array_data, str):
            try:
                array_data = json.loads(array_data)
            except (json.JSONDecodeError, TypeError):
                logging.getLogger(__name__).warning(f"无法解析JSON字符串: {array_data}")
                return []
        
        if not isinstance(array_data, list):
            return []
        
        # 从每个数组元素中提取字段值
        values = []
        for item in array_data:
            if isinstance(item, dict):
                if field_part:
                    # 提取子字段
                    value = FieldPathResolver._get_single_value(item, field_part)
                else:
                    # 直接使用整个元素
                    value = item
                values.append(value)
            elif not field_part:
                # 如果没有子字段路径，且元素不是字典，直接使用元素值
                # 这种情况适用于简单值数组，如 ['金融', '科技']
                values.append(item)
        
        return values
    
    @staticmethod
    def _split_path(path: str) -> List[str]:
        """
        分割字段路径
        
        Args:
            path: 字段路径
            
        Returns:
            路径部分列表
        """
        parts = []
        current_part = ""
        bracket_count = 0
        
        for char in path:
            if char == '.':
                if bracket_count == 0:
                    if current_part:
                        parts.append(current_part)
                        current_part = ""
                else:
                    current_part += char
            elif char == '[':
                bracket_count += 1
                current_part += char
            elif char == ']':
                bracket_count -= 1
                current_part += char
            else:
                current_part += char
        
        if current_part:
            parts.append(current_part)
        
        return parts


class BaseDataProcessor:
    """
    基础数据处理器
    提供通用的数据映射、转换和处理功能
    """
    
    def __init__(self):
        """
        初始化基础数据处理器
        """
        self.logger = logging.getLogger(__name__)
        sync_config = get_config('sync', {})
        self.date_format = sync_config.get('date_format', '%Y-%m-%d %H:%M:%S')
        self.path_resolver = FieldPathResolver()
    
    def _safe_get_value(self, data: Dict[str, Any], key: str, default: Any = None) -> Any:
        """
        安全获取字典值
        
        Args:
            data: 数据字典
            key: 键名
            default: 默认值
            
        Returns:
            值
        """
        value = data.get(key, default)
        
        # 处理空值情况
        if value in ['', [], None, 'null', 'NULL']:
            return None
        
        return value
    
    def _convert_datetime(self, datetime_str: Optional[str]) -> Optional[str]:
        """
        转换日期时间格式
        
        Args:
            datetime_str: 日期时间字符串
            
        Returns:
            格式化后的日期时间字符串
        """
        if not datetime_str or datetime_str in ['', 'null', 'NULL']:
            return None
        
        try:
            # 尝试解析不同的日期格式
            formats = [
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%d',
                '%Y/%m/%d %H:%M:%S',
                '%Y/%m/%d'
            ]
            
            for fmt in formats:
                try:
                    dt = datetime.strptime(datetime_str, fmt)
                    return dt.strftime(self.date_format)
                except ValueError:
                    continue
            
            # 如果都不匹配，返回原值
            self.logger.warning(f"无法解析日期格式: {datetime_str}")
            return datetime_str
            
        except Exception as e:
            self.logger.warning(f"日期转换失败: {datetime_str}, 错误: {e}")
            return datetime_str
    
    def _clean_html(self, html_str: Optional[str]) -> Optional[str]:
        """
        清理HTML标签
        
        Args:
            html_str: HTML字符串
            
        Returns:
            清理后的文本
        """
        if not html_str or html_str in ['', 'null', 'NULL']:
            return None
        
        try:
            # 移除HTML标签
            clean_text = re.sub(r'<[^>]+>', '', str(html_str))
            # 解码HTML实体
            clean_text = unescape(clean_text)
            # 移除多余的空白字符
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()
            
            return clean_text if clean_text else None
            
        except Exception as e:
            self.logger.warning(f"HTML清理失败: {e}")
            return str(html_str)
    
    def validate_record(self, record: Dict[str, Any], table_name: str = "") -> bool:
        """
        验证记录数据
        
        Args:
            record: 记录数据
            table_name: 表名
            
        Returns:
            是否有效
        """
        try:
            # 基础验证：检查记录是否为有效的字典
            if not record or not isinstance(record, dict):
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"记录验证失败: {e}")
            return False
    
    def _normalize_field_paths(self, field_mapping: Dict[str, str]) -> Dict[str, str]:
        """
        标准化字段路径，移除 data.list[] 前缀
        
        Args:
            field_mapping: 原始字段映射
            
        Returns:
            标准化后的字段映射
        """
        normalized_mapping = {}
        
        for db_field, api_path in field_mapping.items():
            # 移除 data.list[] 前缀，因为我们处理的是单个记录
            if api_path.startswith('data.list[].'):
                normalized_path = api_path[12:]  # 移除 'data.list[].' 前缀
            elif api_path.startswith('data.list[]'):
                normalized_path = api_path[11:]  # 移除 'data.list[]' 前缀
            else:
                normalized_path = api_path
            
            normalized_mapping[db_field] = normalized_path
        
        return normalized_mapping
    
    def _add_default_fields(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        添加默认字段
        
        Args:
            record: 记录字典
            
        Returns:
            添加默认字段后的记录
        """
        # 设置默认值
        if 'created_at' not in record or not record['created_at']:
            record['created_at'] = datetime.now().strftime(self.date_format)
        if 'updated_at' not in record or not record['updated_at']:
            record['updated_at'] = datetime.now().strftime(self.date_format)
        
        return record
