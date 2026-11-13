#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re

# 测试字段行
test_lines = [
    "`id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',",
    "`project_name` TEXT COMMENT '项目名称',",
    "`project_code` VARCHAR(100) COMMENT '项目编号',",
    "`disclosure_start_date` DATETIME COMMENT '披露开始日期',",
    "`claim_book_value` VARCHAR(50) COMMENT '债权账面价值',",
]

# 测试当前的正则表达式
field_pattern = r'`([^`]+)`\s+([^\s]+(?:\([^)]*\))?(?:\s+[A-Z_]*)*)\s*(?:COMMENT\s+[\'"]([^\'"]*)[\'"])?'

print("=== 调试字段解析正则表达式 ===\n")

for line in test_lines:
    print(f"测试行: {line}")
    match = re.search(field_pattern, line, re.IGNORECASE)
    
    if match:
        field_name = match.group(1)
        field_type = match.group(2).strip()
        field_comment = match.group(3) if match.group(3) else ""
        
        # 清理field_type
        field_type_clean = re.split(r'\s+', field_type)[0]
        
        print(f"  字段名: {field_name}")
        print(f"  原始类型: {field_type}")
        print(f"  清理后类型: {field_type_clean}")
        print(f"  注释: '{field_comment}'")
    else:
        print("  未匹配到!")
    
    print()

# 尝试改进的正则表达式
print("=== 尝试改进的正则表达式 ===\n")
improved_pattern = r'`([^`]+)`\s+([A-Z]+(?:\([^)]*\))?)\s*(?:[A-Z_\s]*)*\s*COMMENT\s+[\'"]([^\'"]*)[\'"]'

for line in test_lines:
    print(f"测试行: {line}")
    match = re.search(improved_pattern, line, re.IGNORECASE)
    
    if match:
        field_name = match.group(1)
        field_type = match.group(2)
        field_comment = match.group(3) if match.group(3) else ""
        
        print(f"  字段名: {field_name}")
        print(f"  类型: {field_type}")
        print(f"  注释: '{field_comment}'")
    else:
        print("  未匹配到!")
    
    print()
