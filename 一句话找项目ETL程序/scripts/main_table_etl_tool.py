#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主表ETL管理工具
提供主表ETL配置管理和测试的命令行工具
"""

import sys
import argparse
import logging
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.main_table_config import MainTableConfigManager, print_config_report
from src.sync.main_table_sync import MainTableSyncManager
from src.core.logger import get_logger


def setup_logging(verbose: bool = False):
    """设置日志"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def cmd_list_tables(args):
    """列出所有可用的主表"""
    print("🔍 扫描主表配置...")
    manager = MainTableConfigManager()
    tables = manager.get_available_main_tables()
    
    if tables:
        print(f"\n✅ 发现 {len(tables)} 个主表:")
        for i, table in enumerate(tables, 1):
            print(f"  {i}. {table}")
    else:
        print("\n❌ 未发现任何主表配置")
    
    print()


def cmd_validate_config(args):
    """验证主表配置"""
    table_name = args.table
    
    print(f"🔍 验证主表配置: {table_name}")
    manager = MainTableConfigManager()
    
    if table_name == "all":
        # 验证所有主表
        tables = manager.get_available_main_tables()
        if not tables:
            print("❌ 未发现任何主表配置")
            return
        
        print(f"\n开始验证 {len(tables)} 个主表...")
        for table in tables:
            result = manager.validate_main_table_config(table)
            status = "✅" if result['valid'] else "❌"
            print(f"\n{status} {table}:")
            
            if result['errors']:
                for error in result['errors']:
                    print(f"    ❌ 错误: {error}")
            
            if result['warnings']:
                for warning in result['warnings']:
                    print(f"    ⚠️  警告: {warning}")
    else:
        # 验证指定主表
        result = manager.validate_main_table_config(table_name)
        status = "✅" if result['valid'] else "❌"
        print(f"\n{status} 验证结果:")
        
        if result['errors']:
            print("  错误:")
            for error in result['errors']:
                print(f"    - {error}")
        
        if result['warnings']:
            print("  警告:")
            for warning in result['warnings']:
                print(f"    - {warning}")
        
        if result['valid']:
            print("  🎉 配置验证通过!")
    
    print()


def cmd_show_config_report(args):
    """显示配置报告"""
    print("📊 生成主表ETL配置报告...\n")
    print_config_report()


def cmd_test_etl(args):
    """测试主表ETL处理"""
    table_name = args.table
    dry_run = args.dry_run
    
    print(f"🧪 测试主表ETL: {table_name}")
    
    if dry_run:
        print("⚠️  干运行模式 - 不会实际写入数据库")
    
    try:
        # 设置日志
        logger = get_logger(__name__)
        
        # 创建同步管理器
        sync_manager = MainTableSyncManager()
        
        if table_name == "all":
            # 测试所有主表
            print("\n开始测试所有主表...")
            result = sync_manager.sync_all_main_tables()
        else:
            # 测试指定主表
            print(f"\n开始测试主表: {table_name}")
            result = sync_manager.sync_main_table(table_name)
        
        # 显示结果
        if result.get('success'):
            print(f"✅ ETL测试成功!")
            if 'synced_count' in result:
                print(f"   处理记录数: {result['synced_count']}")
            if 'summary' in result:
                summary = result['summary']
                print(f"   总表数: {summary['total_tables']}")
                print(f"   成功表数: {summary['success_tables']}")
                print(f"   总记录数: {summary['total_synced']}")
        else:
            print(f"❌ ETL测试失败: {result.get('error', '未知错误')}")
        
        # 关闭连接
        sync_manager.close()
        
    except Exception as e:
        print(f"❌ ETL测试发生异常: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
    
    print()


def cmd_sync_tables(args):
    """执行主表同步"""
    table_name = args.table
    
    print(f"🚀 执行主表同步: {table_name}")
    
    try:
        # 设置日志
        logger = get_logger(__name__)
        
        # 创建同步管理器
        sync_manager = MainTableSyncManager()
        
        if table_name == "all":
            # 同步所有主表
            print("\n开始同步所有主表...")
            result = sync_manager.sync_all_main_tables()
        else:
            # 同步指定主表
            print(f"\n开始同步主表: {table_name}")
            result = sync_manager.sync_main_table(table_name)
        
        # 显示结果
        if result.get('success'):
            print(f"✅ 主表同步成功!")
            if 'synced_count' in result:
                print(f"   同步记录数: {result['synced_count']}")
            if 'summary' in result:
                summary = result['summary']
                print(f"   总表数: {summary['total_tables']}")
                print(f"   成功表数: {summary['success_tables']}")
                print(f"   总记录数: {summary['total_synced']}")
        else:
            print(f"❌ 主表同步失败: {result.get('error', '未知错误')}")
        
        # 关闭连接
        sync_manager.close()
        
    except Exception as e:
        print(f"❌ 主表同步发生异常: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
    
    print()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="主表ETL管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 列出所有可用主表
  python main_table_etl_tool.py list
  
  # 验证所有主表配置
  python main_table_etl_tool.py validate --table all
  
  # 验证指定主表配置
  python main_table_etl_tool.py validate --table equity_increase
  
  # 显示配置报告
  python main_table_etl_tool.py report
  
  # 测试主表ETL（干运行）
  python main_table_etl_tool.py test --table equity_increase --dry-run
  
  # 执行主表同步
  python main_table_etl_tool.py sync --table equity_increase
  
  # 同步所有主表
  python main_table_etl_tool.py sync --table all
        """
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='启用详细日志输出'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # list 命令
    list_parser = subparsers.add_parser('list', help='列出所有可用的主表')
    list_parser.set_defaults(func=cmd_list_tables)
    
    # validate 命令
    validate_parser = subparsers.add_parser('validate', help='验证主表配置')
    validate_parser.add_argument(
        '--table', '-t',
        required=True,
        help='主表名称，使用 "all" 验证所有主表'
    )
    validate_parser.set_defaults(func=cmd_validate_config)
    
    # report 命令
    report_parser = subparsers.add_parser('report', help='显示配置报告')
    report_parser.set_defaults(func=cmd_show_config_report)
    
    # test 命令
    test_parser = subparsers.add_parser('test', help='测试主表ETL处理')
    test_parser.add_argument(
        '--table', '-t',
        required=True,
        help='主表名称，使用 "all" 测试所有主表'
    )
    test_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='干运行模式（不实际写入数据库）'
    )
    test_parser.set_defaults(func=cmd_test_etl)
    
    # sync 命令
    sync_parser = subparsers.add_parser('sync', help='执行主表同步')
    sync_parser.add_argument(
        '--table', '-t',
        required=True,
        help='主表名称，使用 "all" 同步所有主表'
    )
    sync_parser.set_defaults(func=cmd_sync_tables)
    
    # 解析参数
    args = parser.parse_args()
    
    # 设置日志
    setup_logging(args.verbose)
    
    # 检查是否指定了命令
    if not args.command:
        parser.print_help()
        return
    
    # 执行命令
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n⚠️  操作被用户中断")
    except Exception as e:
        print(f"\n❌ 执行命令时发生错误: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()

