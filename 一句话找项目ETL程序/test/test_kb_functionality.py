#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库功能测试脚本

测试知识库相关功能是否正常工作
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.logger import setup_logging, get_logger
from src.knowledge_base.kb_manager import KnowledgeBaseManager
from src.knowledge_base.kb_client import KnowledgeBaseClient
from src.knowledge_base.kb_exporter import DataExporter


def test_configuration():
    """测试配置验证"""
    print("🔧 测试知识库配置...")
    
    try:
        kb_manager = KnowledgeBaseManager()
        validation_result = kb_manager.validate_configuration()
        
        if validation_result['valid']:
            print("✅ 知识库配置验证通过")
            return True
        else:
            print("❌ 知识库配置验证失败:")
            for error in validation_result['errors']:
                print(f"  - {error}")
            return False
            
    except Exception as e:
        print(f"❌ 配置测试异常: {e}")
        return False


def test_kb_client():
    """测试知识库客户端初始化"""
    print("🌐 测试知识库客户端...")
    
    try:
        client = KnowledgeBaseClient()
        print("✅ 知识库客户端初始化成功")
        print(f"  - 主机: {client.host}")
        print(f"  - 认证密钥: {client.auth_key[:10]}...")
        return True
        
    except Exception as e:
        print(f"❌ 知识库客户端初始化失败: {e}")
        return False


def test_data_exporter():
    """测试数据导出器"""
    print("📊 测试数据导出器...")
    
    try:
        exporter = DataExporter()
        print("✅ 数据导出器初始化成功")
        print(f"  - 导出目录: {exporter.output_dir}")
        print(f"  - 文件格式: {exporter.file_format}")
        print(f"  - 最大行数: {exporter.max_rows_per_file}")
        
        # 检查导出目录是否存在
        if os.path.exists(exporter.output_dir):
            print(f"  - 导出目录已存在")
        else:
            print(f"  - 导出目录将自动创建")
            
        return True
        
    except Exception as e:
        print(f"❌ 数据导出器初始化失败: {e}")
        return False


def test_kb_mapping():
    """测试知识库映射"""
    print("🗂️  测试知识库映射...")
    
    try:
        kb_manager = KnowledgeBaseManager()
        mapping_info = kb_manager.get_kb_mapping_info()
        
        print("✅ 知识库映射获取成功")
        print(f"  - 总表数: {mapping_info['total_tables']}")
        print(f"  - 知识库ID数量: {len(mapping_info['kb_ids'])}")
        print(f"  - 知识库IDs: {mapping_info['kb_ids']}")
        
        # 显示前几个映射
        print("  - 表映射示例:")
        for i, (table, kb_id) in enumerate(mapping_info['kb_mapping'].items()):
            if i < 3:  # 只显示前3个
                print(f"    {table} -> {kb_id}")
            elif i == 3:
                print(f"    ... 共{len(mapping_info['kb_mapping'])}个表")
                break
        
        return True
        
    except Exception as e:
        print(f"❌ 知识库映射测试失败: {e}")
        return False


def test_database_connection():
    """测试数据库连接"""
    print("🗄️  测试数据库连接...")
    
    try:
        exporter = DataExporter()
        
        # 测试数据库连接
        with exporter.db_manager.get_session() as session:
            from sqlalchemy import text
            result = session.execute(text("SELECT 1"))
            result = result.fetchone()
            
        if result:
            print("✅ 数据库连接成功")
            return True
        else:
            print("❌ 数据库查询失败")
            return False
            
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        return False


def test_table_existence():
    """测试主表是否存在"""
    print("📋 测试主表存在性...")
    
    try:
        kb_manager = KnowledgeBaseManager()
        exporter = DataExporter()
        
        # 获取配置的表列表
        mapping_info = kb_manager.get_kb_mapping_info()
        tables = list(mapping_info['kb_mapping'].keys())
        
        existing_tables = []
        missing_tables = []
        
        with exporter.db_manager.get_session() as session:
            from sqlalchemy import text
            
            for table_name in tables:
                try:
                    result = session.execute(text(f"SHOW TABLES LIKE '{table_name}'"))
                    if result.fetchone():
                        existing_tables.append(table_name)
                    else:
                        missing_tables.append(table_name)
                except Exception as e:
                    missing_tables.append(table_name)
                    print(f"    检查表 {table_name} 时出错: {e}")
        
        print(f"✅ 表存在性检查完成")
        print(f"  - 存在的表: {len(existing_tables)}")
        print(f"  - 缺失的表: {len(missing_tables)}")
        
        if missing_tables:
            print("  - 缺失的表列表:")
            for table in missing_tables[:5]:  # 只显示前5个
                print(f"    - {table}")
            if len(missing_tables) > 5:
                print(f"    - ... 共{len(missing_tables)}个缺失表")
        
        return len(existing_tables) > 0
        
    except Exception as e:
        print(f"❌ 表存在性测试失败: {e}")
        return False


def main():
    """主测试函数"""
    print("🚀 开始知识库功能测试")
    print("=" * 50)
    
    # 设置日志
    log_config = {
        'logging': {
            'level': 'INFO',
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        }
    }
    setup_logging(log_config)
    logger = get_logger(__name__)
    
    # 执行各项测试
    tests = [
        ("配置验证", test_configuration),
        ("知识库客户端", test_kb_client),
        ("数据导出器", test_data_exporter),
        ("知识库映射", test_kb_mapping),
        ("数据库连接", test_database_connection),
        ("主表存在性", test_table_existence),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print()
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"❌ {test_name} 测试异常: {e}")
            results.append((test_name, False))
    
    # 输出测试总结
    print()
    print("=" * 50)
    print("📊 测试结果总结:")
    
    passed = 0
    failed = 0
    
    for test_name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"  {test_name:20} - {status}")
        if success:
            passed += 1
        else:
            failed += 1
    
    print()
    print(f"总计: {len(results)} 项测试, {passed} 项通过, {failed} 项失败")
    
    if failed == 0:
        print("🎉 所有测试通过！知识库功能配置正确。")
        return 0
    else:
        print("⚠️  部分测试失败，请检查配置和环境。")
        return 1


if __name__ == '__main__':
    sys.exit(main())
