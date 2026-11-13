#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MySQL建表语句生成脚本
根据JSON表结构信息生成MySQL DDL语句
"""

import json
import os
import re
import argparse
from typing import List, Dict, Any


class MySQLDDLGenerator:
    """MySQL DDL生成器"""
    
    def __init__(self):
        self.type_mapping = {
            # 字符串类型
            'varchar': 'VARCHAR',
            'text': 'TEXT',
            'longtext': 'LONGTEXT',
            'mediumtext': 'MEDIUMTEXT',
            'char': 'CHAR',
            
            # 数值类型
            'int': 'INT',
            'bigint': 'BIGINT',
            'tinyint': 'TINYINT',
            'smallint': 'SMALLINT',
            'mediumint': 'MEDIUMINT',
            'decimal': 'DECIMAL',
            'float': 'FLOAT',
            'double': 'DOUBLE',
            
            # 日期时间类型
            'datetime': 'DATETIME',
            'date': 'DATE',
            'time': 'TIME',
            'timestamp': 'TIMESTAMP',
            'year': 'YEAR',
            
            # 其他类型
            'json': 'JSON',
            'blob': 'BLOB',
            'longblob': 'LONGBLOB',
            'mediumblob': 'MEDIUMBLOB',
            'tinyblob': 'TINYBLOB'
        }
    
    def parse_field_type(self, field_type: str) -> str:
        """解析字段类型"""
        field_type = field_type.lower().strip()
        
        # 处理带括号的类型，如 varchar(500), tinyint(1)
        if '(' in field_type:
            base_type = field_type.split('(')[0]
            if base_type in self.type_mapping:
                return field_type.upper()
        
        # 处理基本类型
        if field_type in self.type_mapping:
            return self.type_mapping[field_type]
        
        # 如果找不到匹配的类型，返回原始类型（转为大写）
        return field_type.upper()
    
    def sanitize_table_name(self, table_name: str) -> str:
        """清理表名，确保符合MySQL命名规范"""
        # 移除特殊字符，只保留字母、数字和下划线
        table_name = re.sub(r'[^\w]', '_', table_name)
        # 确保不以数字开头
        if table_name and table_name[0].isdigit():
            table_name = 'table_' + table_name
        return table_name.lower()
    
    def generate_ddl_from_json(self, json_file_path: str, table_name: str = None) -> str:
        """从JSON文件生成DDL语句"""
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                fields_data = json.load(f)
            
            if not isinstance(fields_data, list):
                raise ValueError("JSON文件应包含字段定义的数组")
            
            # 如果没有指定表名，从文件名推导
            table_comment = ""
            if not table_name:
                file_name = os.path.basename(json_file_path)
                file_name_without_ext = os.path.splitext(file_name)[0]
                
                # 处理"中文注释_英文表名"格式的文件名
                # 查找空格+下划线的模式，这通常是中文注释和英文表名的分隔符
                if ' _' in file_name_without_ext:
                    # 按照" _"分割，前面是中文注释，后面是英文表名
                    parts = file_name_without_ext.split(' _', 1)
                    if len(parts) == 2:
                        table_comment = parts[0].strip()
                        table_name = parts[1].strip()
                    else:
                        table_name = file_name_without_ext
                        table_comment = ""
                elif '_' in file_name_without_ext:
                    # 如果没有" _"模式，但有下划线，尝试找到最后一个连续的英文部分
                    # 从右往左找，直到遇到非英文字符
                    parts = file_name_without_ext.split('_')
                    english_parts = []
                    chinese_parts = []
                    
                    # 从后往前遍历，收集连续的英文部分
                    for i in range(len(parts) - 1, -1, -1):
                        part = parts[i]
                        if re.match(r'^[a-zA-Z][a-zA-Z0-9]*$', part):
                            english_parts.insert(0, part)
                        else:
                            # 遇到非纯英文部分，剩余的都是中文注释
                            chinese_parts = parts[:i+1]
                            break
                    
                    if english_parts:
                        table_name = '_'.join(english_parts)
                        table_comment = '_'.join(chinese_parts).replace('_', '') if chinese_parts else ""
                    else:
                        table_name = file_name_without_ext
                        table_comment = ""
                else:
                    table_name = file_name_without_ext
                    table_comment = ""
            
            table_name = self.sanitize_table_name(table_name)
            
            # 生成DDL语句
            ddl_lines = [f"CREATE TABLE `{table_name}` ("]
            
            # 添加主键ID字段
            ddl_lines.append("  `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',")
            
            # 处理每个字段
            for field in fields_data:
                field_name = field.get('字段名', '')
                field_type = field.get('字段类型', 'VARCHAR(255)')
                field_comment = field.get('字段中文名称', '')
                
                if not field_name:
                    continue
                
                mysql_type = self.parse_field_type(field_type)
                comment_part = f" COMMENT '{field_comment}'" if field_comment else ""
                
                ddl_lines.append(f"  `{field_name}` {mysql_type}{comment_part},")
            
            # 添加通用字段
            ddl_lines.extend([
                "  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',",
                "  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'"
            ])
            
            # 结束语句
            comment_text = table_comment if table_comment else f"{table_name}表"
            ddl_lines.append(f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='{comment_text}';")
            
            return '\n'.join(ddl_lines)
            
        except FileNotFoundError:
            raise FileNotFoundError(f"找不到文件: {json_file_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON文件格式错误: {e}")
        except Exception as e:
            raise Exception(f"生成DDL时发生错误: {e}")
    
    def generate_ddl_for_directory(self, directory_path: str, output_file: str = None) -> Dict[str, str]:
        """为目录中的所有JSON文件生成DDL语句"""
        ddl_results = {}
        
        if not os.path.exists(directory_path):
            raise FileNotFoundError(f"目录不存在: {directory_path}")
        
        # 遍历目录中的所有JSON文件
        for root, dirs, files in os.walk(directory_path):
            for file in files:
                if file.endswith('.json'):
                    json_file_path = os.path.join(root, file)
                    try:
                        # 从文件路径推导表名
                        relative_path = os.path.relpath(json_file_path, directory_path)
                        table_name = os.path.splitext(relative_path.replace(os.sep, '_'))[0]
                        
                        ddl = self.generate_ddl_from_json(json_file_path, table_name)
                        ddl_results[relative_path] = ddl
                        
                        print(f"✓ 成功生成DDL: {relative_path}")
                        
                    except Exception as e:
                        print(f"✗ 生成DDL失败 {file}: {e}")
                        ddl_results[relative_path] = f"-- 生成失败: {e}"
        
        # 如果指定了输出文件，将所有DDL写入文件
        if output_file:
            self.save_ddl_to_file(ddl_results, output_file)
        
        return ddl_results
    
    def generate_ddl_for_subtables(self, subtables_directory: str, output_file: str = None) -> Dict[str, str]:
        """为子表目录中的所有表生成DDL语句"""
        ddl_results = {}
        
        if not os.path.exists(subtables_directory):
            raise FileNotFoundError(f"子表目录不存在: {subtables_directory}")
        
        # 遍历子表目录下的所有子文件夹
        for item in os.listdir(subtables_directory):
            item_path = os.path.join(subtables_directory, item)
            
            # 只处理文件夹
            if os.path.isdir(item_path):
                # 在子文件夹中查找JSON文件
                for file in os.listdir(item_path):
                    if file.endswith('.json'):
                        json_file_path = os.path.join(item_path, file)
                        try:
                            # 从文件夹名称推导表名
                            folder_name = item
                            # 提取英文表名部分（下划线后的部分）
                            if '_' in folder_name:
                                # 找到最后一个下划线后的部分作为表名
                                parts = folder_name.split('_')
                                # 从后往前找连续的英文部分
                                english_parts = []
                                for i in range(len(parts) - 1, -1, -1):
                                    part = parts[i]
                                    if re.match(r'^[a-zA-Z][a-zA-Z0-9]*$', part):
                                        english_parts.insert(0, part)
                                    else:
                                        break
                                
                                if english_parts:
                                    table_name = '_'.join(english_parts)
                                else:
                                    table_name = self.sanitize_table_name(folder_name)
                            else:
                                table_name = self.sanitize_table_name(folder_name)
                            
                            ddl = self.generate_ddl_from_json(json_file_path, table_name)
                            ddl_results[folder_name] = ddl
                            
                            print(f"✓ 成功生成DDL: {folder_name} -> {table_name}")
                            
                        except Exception as e:
                            print(f"✗ 生成DDL失败 {folder_name}: {e}")
                            ddl_results[folder_name] = f"-- 生成失败: {e}"
                        
                        # 每个文件夹只处理第一个JSON文件
                        break
        
        # 如果指定了输出文件，将所有DDL写入文件
        if output_file:
            self.save_ddl_to_file(ddl_results, output_file)
        
        return ddl_results
    
    def save_ddl_to_file(self, ddl_results: Dict[str, str], output_file: str):
        """将DDL结果保存到文件"""
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write("-- MySQL DDL语句\n")
                f.write("-- 自动生成时间: " + str(os.popen('date /t').read().strip()) + "\n\n")
                
                for json_file, ddl in ddl_results.items():
                    f.write(f"-- 来源文件: {json_file}\n")
                    f.write(ddl)
                    f.write("\n\n")
            
            print(f"✓ DDL语句已保存到: {output_file}")
            
        except Exception as e:
            print(f"✗ 保存DDL文件失败: {e}")


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='MySQL DDL生成器 - 从JSON表结构信息生成MySQL建表语句')
    
    parser.add_argument('-f', '--file', type=str, help='指定单个JSON文件路径')
    parser.add_argument('-d', '--directory', type=str, help='指定包含JSON文件的目录路径')
    parser.add_argument('-s', '--subtables', type=str, help='指定子表目录路径（每个子文件夹包含一个表的JSON文件）')
    parser.add_argument('-o', '--output', type=str, help='指定输出SQL文件路径')
    parser.add_argument('-t', '--table', type=str, help='指定表名（仅在处理单个文件时有效）')
    parser.add_argument('--demo', action='store_true', help='运行演示模式（处理子表目录）')
    
    return parser.parse_args()

def main():
    """主函数"""
    args = parse_arguments()
    generator = MySQLDDLGenerator()
    
    try:
        # 如果没有提供任何参数或者指定了demo模式，运行演示
        if not any([args.file, args.directory, args.subtables]) or args.demo:
            print("运行演示模式...")
            print("=" * 50)
            
            # 演示：处理子表目录
            subtables_directory = r"e:\code\北交所数据同步程序\表结构信息\子表"
            
            if os.path.exists(subtables_directory):
                print("正在为子表目录生成DDL语句...")
                output_file = r"e:\code\北交所数据同步程序\表结构信息\subtables_ddl.sql"
                
                ddl_results = generator.generate_ddl_for_subtables(subtables_directory, output_file)
                print(f"\n✓ 总共处理了 {len(ddl_results)} 个子表")
            else:
                print("子表目录不存在，请检查目录路径")
        
        # 处理单个文件
        elif args.file:
            print(f"正在处理文件: {args.file}")
            print("=" * 50)
            
            if not os.path.exists(args.file):
                print(f"错误: 文件不存在 - {args.file}")
                return
            
            table_name = args.table if args.table else None
            ddl = generator.generate_ddl_from_json(args.file, table_name)
            
            print("生成的DDL语句:")
            print(ddl)
            
            if args.output:
                ddl_results = {os.path.basename(args.file): ddl}
                generator.save_ddl_to_file(ddl_results, args.output)
            else:
                print("\n提示: 使用 -o 参数指定输出文件路径来保存DDL语句")
        
        # 处理目录
        elif args.directory:
            print(f"正在处理目录: {args.directory}")
            print("=" * 50)
            
            if not os.path.exists(args.directory):
                print(f"错误: 目录不存在 - {args.directory}")
                return
            
            output_file = args.output if args.output else os.path.join(args.directory, "generated_ddl.sql")
            ddl_results = generator.generate_ddl_for_directory(args.directory, output_file)
            
            print(f"\n✓ 总共处理了 {len(ddl_results)} 个JSON文件")
        
        # 处理子表目录
        elif args.subtables:
            print(f"正在处理子表目录: {args.subtables}")
            print("=" * 50)
            
            if not os.path.exists(args.subtables):
                print(f"错误: 子表目录不存在 - {args.subtables}")
                return
            
            output_file = args.output if args.output else os.path.join(args.subtables, "subtables_ddl.sql")
            ddl_results = generator.generate_ddl_for_subtables(args.subtables, output_file)
            
            print(f"\n✓ 总共处理了 {len(ddl_results)} 个子表")
        
        print("=" * 50)
        
    except Exception as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    main()