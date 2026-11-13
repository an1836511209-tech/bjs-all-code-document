#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DDL转JSON转换器
用于遍历表结构信息/主表目录下的ddl.sql文件，
并将建表SQL语句转换为指定格式的JSON字符串。

作者: AI Assistant
创建时间: 2025年
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class DDLToJSONConverter:
    """DDL到JSON转换器类"""
    
    def __init__(self, main_tables_dir: str = "表结构信息/主表"):
        """
        初始化转换器
        
        Args:
            main_tables_dir: 主表目录路径
        """
        self.main_tables_dir = Path(main_tables_dir)
        self.table_schemas = {}
    
    def parse_mysql_type_to_simple_type(self, mysql_type: str) -> str:
        """
        将MySQL数据类型转换为简化类型
        
        Args:
            mysql_type: MySQL数据类型，如 VARCHAR(100), BIGINT, TEXT等
            
        Returns:
            简化的数据类型字符串
        """
        mysql_type = mysql_type.upper().strip()
        
        # 映射规则
        type_mapping = {
            'BIGINT': 'int',
            'INT': 'int',
            'INTEGER': 'int',
            'SMALLINT': 'int',
            'TINYINT': 'int',
            'DECIMAL': 'decimal',
            'NUMERIC': 'decimal',
            'FLOAT': 'decimal',
            'DOUBLE': 'decimal',
            'VARCHAR': 'varchar',
            'CHAR': 'varchar',
            'TEXT': 'varchar',
            'LONGTEXT': 'varchar',
            'MEDIUMTEXT': 'varchar',
            'DATETIME': 'date',
            'DATE': 'date',
            'TIMESTAMP': 'date',
            'TIME': 'date',
            'YEAR': 'date'
        }
        
        # 提取基础类型（去掉括号及其内容）
        base_type = re.split(r'[\(\s]', mysql_type)[0]
        
        return type_mapping.get(base_type, 'varchar')
    
    def extract_table_comment(self, ddl_content: str) -> str:
        """
        从DDL语句中提取表注释
        
        Args:
            ddl_content: DDL语句内容
            
        Returns:
            表注释文本
        """
        # 匹配表注释的正则表达式
        comment_pattern = r"COMMENT\s*=\s*['\"]([^'\"]*)['\"]"
        match = re.search(comment_pattern, ddl_content, re.IGNORECASE | re.MULTILINE)
        
        if match:
            return match.group(1)
        
        return ""
    
    def parse_ddl_fields(self, ddl_content: str) -> List[Dict[str, str]]:
        """
        从DDL语句中解析字段信息
        
        Args:
            ddl_content: DDL语句内容
            
        Returns:
            字段信息列表
        """
        fields = []
        
        # 提取CREATE TABLE语句中的字段定义
        # 匹配从CREATE TABLE到最后一个)的内容
        table_pattern = r'CREATE\s+TABLE\s+[`\w]+\s*\((.*)\)\s*ENGINE'
        table_match = re.search(table_pattern, ddl_content, re.IGNORECASE | re.DOTALL)
        
        if not table_match:
            return fields
        
        table_body = table_match.group(1)
        
        # 分割字段定义（按逗号分割，但要考虑括号内的逗号）
        field_lines = []
        current_line = ""
        paren_depth = 0
        
        for char in table_body:
            if char == '(':
                paren_depth += 1
            elif char == ')':
                paren_depth -= 1
            elif char == ',' and paren_depth == 0:
                field_lines.append(current_line.strip())
                current_line = ""
                continue
            current_line += char
        
        if current_line.strip():
            field_lines.append(current_line.strip())
        
        # 解析每个字段定义
        for line in field_lines:
            line = line.strip()
            if not line or line.startswith('PRIMARY KEY') or line.startswith('KEY') or line.startswith('INDEX'):
                continue
            
            # 匹配字段定义的正则表达式
            # 例如: `field_name` VARCHAR(100) COMMENT '字段描述'
            # 改进的正则表达式，更好地处理COMMENT部分
            field_pattern = r'`([^`]+)`\s+([A-Z]+(?:\([^)]*\))?)\s*(?:[A-Z_\s]*)*\s*COMMENT\s+[\'"]([^\'"]*)[\'"]'
            match = re.search(field_pattern, line, re.IGNORECASE)
            
            if match:
                field_name = match.group(1)
                field_type = match.group(2).strip()
                field_comment = match.group(3) if match.group(3) else ""
                
                # 跳过特殊字段
                if field_name in ['created_at', 'updated_at']:
                    continue
                
                # 转换数据类型
                simple_type = self.parse_mysql_type_to_simple_type(field_type)
                
                fields.append({
                    "name": field_name,
                    "type": simple_type,
                    "desc": field_comment
                })
        
        return fields
    
    def parse_ddl_file(self, ddl_file_path: Path) -> Optional[Tuple[str, Dict]]:
        """
        解析单个DDL文件
        
        Args:
            ddl_file_path: DDL文件路径
            
        Returns:
            (表名, 表schema字典) 或 None
        """
        try:
            with open(ddl_file_path, 'r', encoding='utf-8') as f:
                ddl_content = f.read()
            
            # 提取表名
            table_pattern = r'CREATE\s+TABLE\s+`([^`]+)`'
            table_match = re.search(table_pattern, ddl_content, re.IGNORECASE)
            
            if not table_match:
                print(f"警告: 无法从 {ddl_file_path} 中提取表名")
                return None
            
            table_name = table_match.group(1)
            
            # 提取表注释
            table_desc = self.extract_table_comment(ddl_content)
            
            # 解析字段
            fields = self.parse_ddl_fields(ddl_content)
            
            table_schema = {
                "table_name": table_name,
                "table_desc": table_desc,
                "fields": fields
            }
            
            return table_name, table_schema
            
        except Exception as e:
            print(f"错误: 解析文件 {ddl_file_path} 时出错: {e}")
            return None
    
    def scan_main_tables_directory(self) -> Dict[str, Dict]:
        """
        扫描主表目录，解析所有DDL文件
        
        Returns:
            包含所有表schema的字典
        """
        if not self.main_tables_dir.exists():
            raise FileNotFoundError(f"主表目录不存在: {self.main_tables_dir}")
        
        table_schemas = {}
        
        # 遍历主表目录下的所有子目录
        for table_dir in self.main_tables_dir.iterdir():
            if not table_dir.is_dir():
                continue
            
            # 查找DDL文件
            ddl_files = list(table_dir.glob("*_ddl.sql"))
            
            if not ddl_files:
                print(f"警告: 在目录 {table_dir} 中未找到DDL文件")
                continue
            
            for ddl_file in ddl_files:
                result = self.parse_ddl_file(ddl_file)
                if result:
                    table_name, table_schema = result
                    table_schemas[table_name] = table_schema
                    print(f"成功解析表: {table_name} (文件: {ddl_file})")
        
        return table_schemas
    
    def convert_to_json(self) -> str:
        """
        转换为JSON字符串
        
        Returns:
            格式化的JSON字符串
        """
        # 扫描并解析所有DDL文件
        self.table_schemas = self.scan_main_tables_directory()
        
        # 转换为JSON字符串（格式化输出）
        json_str = json.dumps(self.table_schemas, ensure_ascii=False, indent=2)
        
        return json_str
    
    def save_to_txt_file(self, output_file: str = "test/table_schemas.txt"):
        """
        保存JSON结果到文本文件
        
        Args:
            output_file: 输出文件路径
        """
        json_str = self.convert_to_json()
        
        # 确保输出目录存在
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(json_str)
        
        print(f"\n=== 转换完成 ===")
        print(f"共解析了 {len(self.table_schemas)} 个表")
        print(f"结果已保存到: {output_path.absolute()}")
        
        # 打印表名列表
        print(f"\n解析的表名列表:")
        for i, table_name in enumerate(self.table_schemas.keys(), 1):
            print(f"  {i}. {table_name}")


def main():
    """主函数"""
    print("=== DDL转JSON转换器 ===\n")
    
    # 创建转换器实例
    converter = DDLToJSONConverter()
    
    try:
        # 执行转换并保存到文件
        converter.save_to_txt_file()
        
    except Exception as e:
        print(f"转换过程中出现错误: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
