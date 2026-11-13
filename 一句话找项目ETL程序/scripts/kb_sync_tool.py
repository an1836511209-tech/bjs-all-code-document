#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库同步工具

提供独立的知识库数据同步功能，支持：
1. 单表数据导出和上传到知识库
2. 全量主表数据同步到知识库
3. 知识库配置验证
4. 同步状态查询
"""

import os
import sys
import argparse
import json
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.logger import get_logger, setup_logging
from src.knowledge_base.kb_manager import KnowledgeBaseManager


def setup_argparse() -> argparse.ArgumentParser:
    """设置命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description='知识库同步工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
    # 验证知识库配置
    python kb_sync_tool.py validate

    # 同步单个表到知识库
    python kb_sync_tool.py sync-table bjhl_property_transfer

    # 同步所有主表到知识库
    python kb_sync_tool.py sync-all

    # 显示知识库映射信息
    python kb_sync_tool.py info
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='命令')
    
    # 验证配置命令
    validate_parser = subparsers.add_parser('validate', help='验证知识库配置')
    
    # 同步单表命令
    sync_table_parser = subparsers.add_parser('sync-table', help='同步单个表到知识库')
    sync_table_parser.add_argument('table_name', help='要同步的表名')
    
    # 同步所有表命令
    sync_all_parser = subparsers.add_parser('sync-all', help='同步所有主表到知识库')
    sync_all_parser.add_argument('--quiet', '-q', action='store_true', help='静默模式，只输出关键信息')
    
    # 显示信息命令
    info_parser = subparsers.add_parser('info', help='显示知识库映射信息')
    
    # 通用参数
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                       default='INFO', help='日志级别')
    parser.add_argument('--output', '-o', help='输出结果到文件（JSON格式）')
    
    return parser


def print_result(result: dict, output_file: str = None, quiet: bool = False):
    """
    打印结果
    
    Args:
        result: 结果字典
        output_file: 输出文件路径
        quiet: 是否静默模式
    """
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        if not quiet:
            print(f"结果已保存到: {output_file}")
    
    if not quiet:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def validate_config(kb_manager: KnowledgeBaseManager, args) -> dict:
    """验证知识库配置"""
    print("验证知识库配置...")
    
    validation_result = kb_manager.validate_configuration()
    
    if validation_result['valid']:
        print("✅ 知识库配置验证通过")
    else:
        print("❌ 知识库配置验证失败")
        for error in validation_result['errors']:
            print(f"  错误: {error}")
    
    if validation_result['warnings']:
        print("⚠️  警告:")
        for warning in validation_result['warnings']:
            print(f"  警告: {warning}")
    
    return validation_result


def sync_single_table(kb_manager: KnowledgeBaseManager, args) -> dict:
    """同步单个表到知识库"""
    table_name = args.table_name
    print(f"开始同步表 {table_name} 到知识库...")
    
    result = kb_manager.sync_table_to_kb(table_name)
    
    if result['success']:
        print(f"✅ 表 {table_name} 同步成功")
        summary = result.get('summary', {})
        print(f"  知识库ID: {summary.get('kb_id')}")
        print(f"  导出文件数: {summary.get('exported_file_count', 0)}")
        print(f"  上传文件数: {summary.get('uploaded_file_count', 0)}")
        print(f"  创建数据集数: {summary.get('created_dataset_count', 0)}")
    else:
        print(f"❌ 表 {table_name} 同步失败: {result.get('error')}")
    
    return result


def sync_all_tables(kb_manager: KnowledgeBaseManager, args) -> dict:
    """同步所有主表到知识库"""
    if not args.quiet:
        print("开始同步所有主表到知识库...")
    
    result = kb_manager.sync_all_tables_to_kb()
    
    if result['success']:
        if not args.quiet:
            print("✅ 所有主表同步成功")
        summary = result.get('summary', {})
        print(f"  总表数: {summary.get('total_tables', 0)}")
        print(f"  成功表数: {summary.get('successful_tables', 0)}")
        print(f"  失败表数: {summary.get('failed_tables', 0)}")
        print(f"  总导出文件数: {summary.get('total_files_exported', 0)}")
        print(f"  总上传文件数: {summary.get('total_files_uploaded', 0)}")
        print(f"  总创建数据集数: {summary.get('total_datasets_created', 0)}")
        print(f"  耗时: {summary.get('duration_seconds', 0):.2f} 秒")
        
        if summary.get('failed_tables', 0) > 0:
            print("❌ 失败的表:")
            for table_name in summary.get('failed_table_names', []):
                print(f"    - {table_name}")
    else:
        print(f"❌ 主表同步失败: {result.get('error')}")
    
    return result


def show_info(kb_manager: KnowledgeBaseManager, args) -> dict:
    """显示知识库映射信息"""
    print("知识库映射信息:")
    
    info = kb_manager.get_kb_mapping_info()
    
    print(f"  总表数: {info['total_tables']}")
    print(f"  知识库ID列表: {info['kb_ids']}")
    print()
    print("表名与知识库ID映射:")
    for table_name, kb_id in info['kb_mapping'].items():
        print(f"  {table_name:30} -> {kb_id}")
    
    print()
    print("导出配置:")
    export_config = info['export_config']
    print(f"  输出目录: {export_config.get('output_dir')}")
    print(f"  文件格式: {export_config.get('file_format')}")
    print(f"  每文件最大行数: {export_config.get('max_rows_per_file')}")
    print(f"  解析类型: {export_config.get('parser_type')}")
    
    return info


def main():
    """主函数"""
    parser = setup_argparse()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # 设置日志
    log_config = {
        'logging': {
            'level': args.log_level,
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        }
    }
    setup_logging(log_config)
    logger = get_logger(__name__)
    
    try:
        # 初始化知识库管理器
        logger.info("初始化知识库管理器...")
        kb_manager = KnowledgeBaseManager()
        
        # 执行命令
        result = None
        
        if args.command == 'validate':
            result = validate_config(kb_manager, args)
        elif args.command == 'sync-table':
            result = sync_single_table(kb_manager, args)
        elif args.command == 'sync-all':
            result = sync_all_tables(kb_manager, args)
        elif args.command == 'info':
            result = show_info(kb_manager, args)
        else:
            print(f"未知命令: {args.command}")
            parser.print_help()
            return 1
        
        # 输出结果
        if result and args.output:
            print_result(result, args.output, getattr(args, 'quiet', False))
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("用户中断操作")
        return 130
    except Exception as e:
        logger.error(f"执行失败: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
