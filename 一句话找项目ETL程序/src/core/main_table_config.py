#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主表ETL配置管理模块
提供主表ETL配置的统一管理和验证
"""

import os
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path


class MainTableConfigManager:
    """
    主表ETL配置管理器
    
    负责管理主表ETL的配置信息，包括：
    1. 主表目录配置
    2. ETL映射规则验证
    3. 配置文件路径管理
    """
    
    def __init__(self, config_base_dir: str = "表结构信息/主表"):
        """
        初始化配置管理器
        
        Args:
            config_base_dir: 主表配置基础目录
        """
        self.logger = logging.getLogger(__name__)
        self.config_base_dir = Path(config_base_dir)
        self._cached_configs = None
    
    def get_available_main_tables(self) -> List[str]:
        """
        获取所有可用的主表列表
        
        Returns:
            主表名称列表
        """
        try:
            if not self.config_base_dir.exists():
                self.logger.error(f"主表配置目录不存在: {self.config_base_dir}")
                return []
            
            main_tables = []
            for item in self.config_base_dir.iterdir():
                if item.is_dir():
                    # 提取主表名
                    table_name = self._extract_table_name_from_dir(item.name)
                    if table_name:
                        main_tables.append(table_name)
            
            self.logger.info(f"发现主表: {main_tables}")
            return main_tables
            
        except Exception as e:
            self.logger.error(f"获取可用主表列表失败: {e}")
            return []
    
    def _extract_table_name_from_dir(self, dir_name: str) -> Optional[str]:
        """
        从目录名提取主表名
        
        Args:
            dir_name: 目录名，如 "股权增资表equity_increase"
            
        Returns:
            主表名，如 "equity_increase"
        """
        import re
        # 查找英文表名（下划线命名）
        match = re.search(r'([a-z_]+)$', dir_name)
        if match:
            return match.group(1)
        return None
    
    def validate_main_table_config(self, main_table_name: str) -> Dict[str, Any]:
        """
        验证主表配置的完整性
        
        Args:
            main_table_name: 主表名
            
        Returns:
            验证结果字典
        """
        result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'table_name': main_table_name
        }
        
        try:
            # 1. 检查主表目录是否存在
            table_dir = self._get_main_table_directory(main_table_name)
            if not table_dir or not table_dir.exists():
                result['valid'] = False
                result['errors'].append(f"主表目录不存在: {main_table_name}")
                return result
            
            # 2. 检查ETL映射文件
            etl_files = list(table_dir.glob("*子表etl.json"))
            if not etl_files:
                result['valid'] = False
                result['errors'].append(f"未找到ETL映射文件: {main_table_name}")
            else:
                result['warnings'].append(f"找到 {len(etl_files)} 个ETL映射文件")
            
            # 3. 检查主表schema文件
            schema_files = list(table_dir.glob(f"*{main_table_name}.json"))
            if not schema_files:
                result['warnings'].append(f"未找到主表schema文件: {main_table_name}")
            
            # 4. 检查DDL文件
            ddl_files = list(table_dir.glob("*.sql"))
            if not ddl_files:
                result['warnings'].append(f"未找到DDL文件: {main_table_name}")
            
            self.logger.info(f"主表配置验证完成: {main_table_name}, 有效: {result['valid']}")
            return result
            
        except Exception as e:
            result['valid'] = False
            result['errors'].append(f"验证配置时发生错误: {e}")
            self.logger.error(f"验证主表配置失败 {main_table_name}: {e}")
            return result
    
    def _get_main_table_directory(self, main_table_name: str) -> Optional[Path]:
        """
        获取主表配置目录
        
        Args:
            main_table_name: 主表名
            
        Returns:
            主表目录路径，如果不存在则返回None
        """
        if not self.config_base_dir.exists():
            return None
        
        # 查找包含该主表名的目录
        for item in self.config_base_dir.iterdir():
            if item.is_dir() and main_table_name in item.name:
                return item
        
        return None
    
    def get_main_table_etl_files(self, main_table_name: str) -> List[Path]:
        """
        获取主表的所有ETL映射文件
        
        Args:
            main_table_name: 主表名
            
        Returns:
            ETL映射文件路径列表
        """
        try:
            table_dir = self._get_main_table_directory(main_table_name)
            if not table_dir:
                return []
            
            etl_files = list(table_dir.glob("*子表etl.json"))
            self.logger.debug(f"主表 {main_table_name} ETL文件: {[f.name for f in etl_files]}")
            return etl_files
            
        except Exception as e:
            self.logger.error(f"获取ETL文件失败 {main_table_name}: {e}")
            return []
    
    def get_config_summary(self) -> Dict[str, Any]:
        """
        获取配置摘要信息
        
        Returns:
            配置摘要字典
        """
        summary = {
            'base_directory': str(self.config_base_dir),
            'directory_exists': self.config_base_dir.exists(),
            'main_tables': [],
            'total_tables': 0,
            'valid_tables': 0,
            'invalid_tables': 0
        }
        
        try:
            available_tables = self.get_available_main_tables()
            summary['total_tables'] = len(available_tables)
            
            for table_name in available_tables:
                validation = self.validate_main_table_config(table_name)
                table_info = {
                    'name': table_name,
                    'valid': validation['valid'],
                    'errors': validation['errors'],
                    'warnings': validation['warnings']
                }
                summary['main_tables'].append(table_info)
                
                if validation['valid']:
                    summary['valid_tables'] += 1
                else:
                    summary['invalid_tables'] += 1
            
            return summary
            
        except Exception as e:
            self.logger.error(f"获取配置摘要失败: {e}")
            summary['error'] = str(e)
            return summary
    
    def generate_config_report(self) -> str:
        """
        生成配置报告
        
        Returns:
            配置报告文本
        """
        try:
            summary = self.get_config_summary()
            
            report_lines = [
                "=" * 60,
                "主表ETL配置报告",
                "=" * 60,
                f"配置目录: {summary['base_directory']}",
                f"目录状态: {'存在' if summary['directory_exists'] else '不存在'}",
                f"主表总数: {summary['total_tables']}",
                f"有效配置: {summary['valid_tables']}",
                f"无效配置: {summary['invalid_tables']}",
                "",
                "主表详情:",
                "-" * 40
            ]
            
            for table_info in summary['main_tables']:
                status = "✓" if table_info['valid'] else "✗"
                report_lines.append(f"{status} {table_info['name']}")
                
                if table_info['errors']:
                    for error in table_info['errors']:
                        report_lines.append(f"    错误: {error}")
                
                if table_info['warnings']:
                    for warning in table_info['warnings']:
                        report_lines.append(f"    警告: {warning}")
                
                report_lines.append("")
            
            report_lines.extend([
                "=" * 60,
                "报告生成完成",
                "=" * 60
            ])
            
            return "\n".join(report_lines)
            
        except Exception as e:
            self.logger.error(f"生成配置报告失败: {e}")
            return f"生成配置报告失败: {e}"


# 提供便捷的访问接口
def get_main_table_config_manager() -> MainTableConfigManager:
    """
    获取主表配置管理器实例
    
    Returns:
        主表配置管理器实例
    """
    return MainTableConfigManager()


def get_available_main_tables() -> List[str]:
    """
    获取所有可用的主表列表（便捷方法）
    
    Returns:
        主表名称列表
    """
    manager = get_main_table_config_manager()
    return manager.get_available_main_tables()


def validate_main_table_config(main_table_name: str) -> Dict[str, Any]:
    """
    验证主表配置（便捷方法）
    
    Args:
        main_table_name: 主表名
        
    Returns:
        验证结果字典
    """
    manager = get_main_table_config_manager()
    return manager.validate_main_table_config(main_table_name)


def print_config_report():
    """
    打印配置报告（便捷方法）
    """
    manager = get_main_table_config_manager()
    report = manager.generate_config_report()
    print(report)


if __name__ == "__main__":
    # 直接运行时显示配置报告
    print_config_report()

