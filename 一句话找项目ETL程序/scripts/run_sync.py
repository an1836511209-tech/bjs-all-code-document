#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据同步运行脚本
提供完整的数据同步功能，包括子表、房源运营和主表数据同步
"""

import os
import sys
import argparse
import traceback
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.logger import setup_logging, get_logger
from src.core.config import get_config
from src.sync.subtable_sync import SubtableSyncManager
from src.sync.operational_sync import OperationalSyncManager
from src.sync.main_table_sync import MainTableSyncManager


def parse_arguments():
    """
    解析命令行参数
    
    Returns:
        解析后的参数
    """
    parser = argparse.ArgumentParser(description='北交所数据同步程序')
    
    parser.add_argument(
        '--config', '-c',
        default='config/config.yaml',
        help='配置文件路径 (默认: config/config.yaml)'
    )
    
    parser.add_argument(
        '--mode', '-m',
        choices=['subtables', 'operational', 'main', 'all'],
        default='all',
        help='同步模式: subtables(子表), operational(房源运营), main(主表), all(全部)'
    )
    
    parser.add_argument(
        '--table', '-t',
        help='指定要同步的表名或业务系统名称（仅在subtables模式下有效）'
    )
    
    parser.add_argument(
        '--sync-time',
        help='指定同步时间，格式: YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS'
    )
    
    parser.add_argument(
        '--full',
        action='store_true',
        help='强制全量同步'
    )
    
    parser.add_argument(
        '--test',
        action='store_true',
        help='仅测试连接，不执行同步'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='试运行模式，不实际写入数据库'
    )
    
    return parser.parse_args()


def test_connections():
    """
    测试所有连接
    
    Returns:
        测试是否成功
    """
    logger = get_logger(__name__)
    
    try:
        logger.info("开始测试连接...")
        
        # 测试子表同步连接
        subtable_manager = SubtableSyncManager()
        if not subtable_manager.api_client.test_connection():
            logger.error("项目数据API连接测试失败")
            return False
        
        # 测试房源运营API连接
        operational_manager = OperationalSyncManager()
        if not operational_manager.operational_api_client.test_connection():
            logger.error("房源运营信息API连接测试失败")
            return False
        
        # 测试数据库连接
        try:
            test_result = subtable_manager.db_manager.execute_query("SELECT 1 as test")
            if not test_result or test_result[0]['test'] != 1:
                logger.error("数据库连接测试失败")
                return False
        except Exception as e:
            logger.error(f"数据库连接测试失败: {e}")
            return False
        
        logger.info("所有连接测试通过")
        
        # 关闭连接
        subtable_manager.close()
        operational_manager.close()
        
        return True
        
    except Exception as e:
        logger.error(f"连接测试失败: {e}")
        return False


def sync_subtables(table_name=None, sync_time=None, force_full=False):
    """
    执行子表数据同步
    
    Args:
        table_name: 表名或业务系统名称
        sync_time: 同步时间
        force_full: 是否强制全量同步
        
    Returns:
        同步结果
    """
    logger = get_logger(__name__)
    subtable_manager = None
    
    try:
        subtable_manager = SubtableSyncManager()
        
        if table_name:
            # 同步指定表
            # 这里需要根据table_name确定对应的业务系统
            biz_sys_mapping = get_config('biz_sys_mapping', {})
            
            # 检查是否为业务系统名称
            if table_name in biz_sys_mapping:
                biz_sys = table_name
            else:
                # 检查是否为表名，查找对应的业务系统
                biz_sys = None
                for bs, tn in biz_sys_mapping.items():
                    if tn == table_name:
                        biz_sys = bs
                        break
                
                if not biz_sys:
                    raise ValueError(f"未找到表或业务系统: {table_name}")
            
            result = subtable_manager.sync_table_by_biz_sys(
                biz_sys, sync_time, force_full
            )
        else:
            # 同步所有子表
            result = subtable_manager.sync_all_subtables(sync_time, force_full)
        
        return result
        
    except Exception as e:
        logger.error(f"子表数据同步失败: {e}")
        return {'success': False, 'error': str(e)}
    finally:
        if subtable_manager:
            subtable_manager.close()


def sync_operational():
    """
    执行房源运营数据同步
    
    Returns:
        同步结果
    """
    logger = get_logger(__name__)
    operational_manager = None
    
    try:
        operational_manager = OperationalSyncManager()
        result = operational_manager.sync_operational_data()
        return result
        
    except Exception as e:
        logger.error(f"房源运营数据同步失败: {e}")
        return {'success': False, 'error': str(e)}
    finally:
        if operational_manager:
            operational_manager.close()


def sync_main_tables():
    """
    执行主表数据同步
    
    Returns:
        同步结果
    """
    logger = get_logger(__name__)
    main_table_manager = None
    
    try:
        main_table_manager = MainTableSyncManager()
        result = main_table_manager.sync_all_main_tables()
        return result
        
    except Exception as e:
        logger.error(f"主表数据同步失败: {e}")
        return {'success': False, 'error': str(e)}
    finally:
        if main_table_manager:
            main_table_manager.close()


def print_result(result, mode):
    """
    打印同步结果
    
    Args:
        result: 同步结果
        mode: 同步模式
    """
    print(f"\n======== {mode.upper()} 同步结果 ========")
    
    if result.get('success'):
        print("✅ 同步成功")
        
        if 'summary' in result:
            summary = result['summary']
            print(f"📊 统计信息:")
            print(f"   总表数: {summary.get('total_tables', 0)}")
            print(f"   成功表数: {summary.get('success_tables', 0)}")
            print(f"   总同步记录数: {summary.get('total_synced', 0)}")
            
            # 打印各表详细结果
            if 'tables' in result:
                print(f"\n📋 详细结果:")
                for table_name, table_result in result['tables'].items():
                    status = "✅" if table_result.get('success') else "❌"
                    synced = table_result.get('synced_count', 0)
                    print(f"   {status} {table_name}: {synced} 条记录")
        else:
            synced_count = result.get('synced_count', 0)
            print(f"📊 同步记录数: {synced_count}")
    else:
        print("❌ 同步失败")
        error = result.get('error', '未知错误')
        print(f"💥 错误信息: {error}")


def main():
    """
    主函数
    """
    args = parse_arguments()
    
    # 检查配置文件是否存在
    if not os.path.exists(args.config):
        print(f"❌ 错误: 配置文件 '{args.config}' 不存在")
        print(f"💡 提示: 请从 config/config.template.yaml 复制并配置")
        sys.exit(1)
    
    try:
        # 设置日志
        log_config = get_config('logging', {})
        setup_logging(log_config)
        logger = get_logger(__name__)
        
        logger.info("=" * 50)
        logger.info("北交所数据同步程序启动")
        logger.info(f"同步模式: {args.mode}")
        logger.info("=" * 50)
        
        # 测试连接
        if args.test:
            if test_connections():
                print("✅ 所有连接测试成功")
                sys.exit(0)
            else:
                print("❌ 连接测试失败")
                sys.exit(1)
        
        # 执行同步
        results = {}
        
        if args.mode in ['subtables', 'all']:
            print("🔄 开始子表数据同步...")
            result = sync_subtables(args.table, args.sync_time, args.full)
            results['subtables'] = result
            print_result(result, 'subtables')
        
        if args.mode in ['operational', 'all']:
            print("\n🔄 开始房源运营数据同步...")
            result = sync_operational()
            results['operational'] = result
            print_result(result, 'operational')
        
        if args.mode in ['main', 'all']:
            print("\n🔄 开始主表数据同步...")
            result = sync_main_tables()
            results['main'] = result
            print_result(result, 'main')
        
        # 统计总体结果
        all_success = all(r.get('success', False) for r in results.values())
        
        print(f"\n{'=' * 50}")
        if all_success:
            print("🎉 所有同步任务完成！")
        else:
            print("⚠️  部分同步任务失败，请检查日志")
        print(f"{'=' * 50}")
        
        sys.exit(0 if all_success else 1)
    
    except KeyboardInterrupt:
        print("\n⚠️  用户中断程序")
        sys.exit(1)
    except Exception as e:
        print(f"💥 程序执行失败: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
