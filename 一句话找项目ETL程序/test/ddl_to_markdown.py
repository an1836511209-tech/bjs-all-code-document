#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DDL SQL转Markdown表格脚本
读取DDL SQL文件，解析表结构，生成Markdown表格格式
"""

import re
import os
from typing import List, Dict, Tuple


class DDLToMarkdownConverter:
    """DDL SQL转Markdown转换器"""
    
    def __init__(self, ddl_file_path: str, output_dir: str = "test"):
        """
        初始化转换器
        
        Args:
            ddl_file_path: DDL SQL文件路径
            output_dir: 输出目录
        """
        self.ddl_file_path = ddl_file_path
        self.output_dir = output_dir
        
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
    
    def parse_ddl_file(self) -> List[Dict]:
        """
        解析DDL文件，提取所有表的结构信息
        
        Returns:
            表结构信息列表
        """
        tables = []
        
        with open(self.ddl_file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        
        # 按CREATE TABLE语句分割
        table_statements = re.split(r'CREATE TABLE', content)
        
        for statement in table_statements[1:]:  # 跳过第一个空的部分
            table_info = self._parse_single_table(statement)
            if table_info:
                tables.append(table_info)
        
        return tables
    
    def _parse_single_table(self, statement: str) -> Dict:
        """
        解析单个表的DDL语句
        
        Args:
            statement: CREATE TABLE语句（去掉CREATE TABLE部分）
            
        Returns:
            表信息字典
        """
        # 提取表名
        table_name_match = re.search(r'`([^`]+)`', statement)
        if not table_name_match:
            return None
        
        table_name = table_name_match.group(1)
        
        # 提取表注释
        comment_match = re.search(r"COMMENT='([^']+)'", statement)
        table_comment = comment_match.group(1) if comment_match else ""
        
        # 提取字段信息
        fields = self._extract_fields(statement)
        
        return {
            'name': table_name,
            'comment': table_comment,
            'fields': fields
        }
    
    def _extract_fields(self, statement: str) -> List[Dict]:
        """
        提取表的字段信息
        
        Args:
            statement: CREATE TABLE语句
            
        Returns:
            字段信息列表
        """
        fields = []
        
        # 匹配字段定义的正则表达式
        field_pattern = r'`([^`]+)`\s+([^,\s]+(?:\s*\([^)]+\))?(?:\s+[^,\s]+)*)\s*(?:COMMENT\s+[\'"]([^\'"]*)[\'"])?'
        
        # 提取表定义部分（括号内的内容）
        table_def_match = re.search(r'\((.*)\)\s*ENGINE', statement, re.DOTALL)
        if not table_def_match:
            return fields
        
        table_definition = table_def_match.group(1)
        
        # 按行分割并处理每一行
        lines = table_definition.split('\n')
        
        for line in lines:
            line = line.strip()
            
            # 跳过空行、约束定义、索引定义等
            if (not line or 
                line.startswith('PRIMARY KEY') or 
                line.startswith('KEY') or 
                line.startswith('INDEX') or 
                line.startswith('UNIQUE') or
                line.startswith('FOREIGN KEY') or
                line == ',' or
                line == ')' or
                'AUTO_INCREMENT' in line.upper() and '`' not in line):
                continue
            
            # 使用更精确的正则表达式匹配字段
            field_match = re.match(r'`([^`]+)`\s+([^,]+?)(?:\s+COMMENT\s+[\'"]([^\'"]*)[\'"])?(?:,|$)', line)
            
            if field_match:
                field_name = field_match.group(1)
                field_type_raw = field_match.group(2).strip()
                field_comment = field_match.group(3) if field_match.group(3) else ""
                
                # 清理字段类型，移除不必要的修饰符
                field_type = self._clean_field_type(field_type_raw)
                
                # 跳过主键字段的特殊处理（如果它包含AUTO_INCREMENT等）
                if field_name != 'id' or not any(keyword in field_type_raw.upper() 
                                               for keyword in ['AUTO_INCREMENT', 'PRIMARY']):
                    fields.append({
                        'name': field_name,
                        'type': field_type,
                        'comment': field_comment,
                        'raw_definition': field_type_raw
                    })
                elif field_name == 'id':
                    # 对于ID字段，简化类型显示
                    clean_type = re.sub(r'\s+(AUTO_INCREMENT|PRIMARY\s+KEY).*', '', field_type_raw)
                    fields.append({
                        'name': field_name,
                        'type': clean_type.strip(),
                        'comment': field_comment,
                        'raw_definition': field_type_raw
                    })
        
        return fields
    
    def _clean_field_type(self, field_type_raw: str) -> str:
        """
        清理字段类型，移除不必要的修饰符
        
        Args:
            field_type_raw: 原始字段类型
            
        Returns:
            清理后的字段类型
        """
        # 移除常见的修饰符
        field_type = field_type_raw
        
        # 移除AUTO_INCREMENT, PRIMARY KEY, NOT NULL, DEFAULT等
        field_type = re.sub(r'\s+(AUTO_INCREMENT|PRIMARY\s+KEY|NOT\s+NULL|DEFAULT\s+[^,\s]+|ON\s+UPDATE\s+[^,\s]+)', '', field_type, flags=re.IGNORECASE)
        
        # 移除TIMESTAMP的默认值设置
        field_type = re.sub(r'\s+DEFAULT\s+CURRENT_TIMESTAMP.*', '', field_type, flags=re.IGNORECASE)
        
        return field_type.strip()
    
    def generate_markdown(self, tables: List[Dict]) -> str:
        """
        生成Markdown格式的表结构文档
        
        Args:
            tables: 表结构信息列表
            
        Returns:
            Markdown内容
        """
        markdown_lines = []
        markdown_lines.append("# 数据库表结构文档\n")
        markdown_lines.append("## 表结构信息\n")
        
        for table in tables:
            # 表标题
            markdown_lines.append(f"### {table['comment']} ({table['name']})\n")
            
            # 表格头部
            markdown_lines.append("| 字段名 | 字段类型 | 中文名称 | 备注 |")
            markdown_lines.append("|--------|----------|----------|------|")
            
            # 字段信息
            for field in table['fields']:
                field_name = field['name']
                field_type = field['type']
                field_comment = field['comment']
                
                # 处理备注信息
                remark = ""
                if field_name == 'id':
                    remark = "主键ID，自增"
                elif field_name in ['created_at', 'updated_at']:
                    remark = "系统自动维护"
                
                markdown_lines.append(f"| {field_name} | {field_type} | {field_comment} | {remark} |")
            
            markdown_lines.append("")  # 表之间的空行
        
        return "\n".join(markdown_lines)
    
    def save_markdown(self, content: str, filename: str = "database_tables.md") -> str:
        """
        保存Markdown内容到文件
        
        Args:
            content: Markdown内容
            filename: 文件名
            
        Returns:
            保存的文件路径
        """
        output_path = os.path.join(self.output_dir, filename)
        
        with open(output_path, 'w', encoding='utf-8') as file:
            file.write(content)
        
        return output_path
    
    def convert(self, output_filename: str = "database_tables.md") -> str:
        """
        执行完整的转换流程
        
        Args:
            output_filename: 输出文件名
            
        Returns:
            输出文件路径
        """
        print(f"正在解析DDL文件: {self.ddl_file_path}")
        tables = self.parse_ddl_file()
        print(f"成功解析 {len(tables)} 个表")
        
        print("正在生成Markdown内容...")
        markdown_content = self.generate_markdown(tables)
        
        print(f"正在保存到文件: {output_filename}")
        output_path = self.save_markdown(markdown_content, output_filename)
        
        print(f"转换完成！文件已保存到: {output_path}")
        return output_path


def main():
    """主函数"""
    # DDL文件路径
    ddl_file = "表结构信息/主表/create_table_ddl_all.sql"
    
    # 检查文件是否存在
    if not os.path.exists(ddl_file):
        print(f"错误: DDL文件不存在: {ddl_file}")
        return
    
    # 创建转换器并执行转换
    converter = DDLToMarkdownConverter(ddl_file, "test")
    output_file = converter.convert("database_tables.md")
    
    print(f"\n✅ 转换成功完成!")
    print(f"📄 输出文件: {output_file}")


if __name__ == "__main__":
    main()







