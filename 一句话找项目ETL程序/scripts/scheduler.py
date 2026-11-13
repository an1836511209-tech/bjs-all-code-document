#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
北交所数据同步调度器
集成定时任务和实时监听，统一管理所有同步服务

默认行为：
- 启动时立即执行一次T+1全量同步
- 然后进入定时任务模式（每天凌晨2点自动同步）
- 确保服务启动后立即有最新数据，无需等到定时任务
"""

import os
import sys
import time
import signal
import schedule
import argparse
import threading
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.logger import setup_logging, get_logger
from src.core.config import get_config
from src.sync.subtable_sync import SubtableSyncManager
from src.sync.operational_sync import OperationalSyncManager
from src.sync.main_table_sync import MainTableSyncManager


class SyncScheduler:
    """数据同步调度器"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.running = False
        self.kafka_listener = None
        self.kafka_thread = None
        
    def start_kafka_listener(self):
        """启动Kafka监听器"""
        # TODO: Kafka实时同步功能暂时注释，专注T+1全量同步
        # 如需重新启用，请取消以下代码注释
        self.logger.info("⚠️  Kafka实时监听功能已禁用，专注T+1全量同步模式")
        return False
        
        # try:
        #     from src.listeners.kafka_listener import KafkaListener
        #     
        #     self.logger.info("正在启动Kafka监听器...")
        #     self.kafka_listener = KafkaListener()
        #     
        #     # 在单独线程中运行Kafka监听器
        #     def run_kafka():
        #         try:
        #             self.kafka_listener.start()
        #         except Exception as e:
        #             self.logger.error(f"Kafka监听器运行失败: {e}")
        #     
        #     self.kafka_thread = threading.Thread(target=run_kafka, daemon=True)
        #     self.kafka_thread.start()
        #     
        #     self.logger.info("✅ Kafka监听器启动成功")
        #     return True
        #     
        # except ImportError as e:
        #     self.logger.error(f"导入Kafka模块失败: {e}")
        #     return False
        # except Exception as e:
        #     self.logger.error(f"启动Kafka监听器失败: {e}")
        #     return False
    
    def sync_all_data_full(self, is_startup=False):
        """执行T+1全量数据同步
        
        Args:
            is_startup (bool): 是否为启动时的同步
        """
        sync_type = "启动时T+1全量数据同步" if is_startup else "定时T+1全量数据同步"
        self.logger.info("=" * 60)
        self.logger.info(f"开始执行{sync_type}")
        self.logger.info("=" * 60)
        
        start_time = datetime.now()
        results = {}
        
        try:
            # 1. 清空旧数据并同步子表（全量）
            self.logger.info("🔄 开始子表全量同步...")
            subtable_manager = SubtableSyncManager()
            try:
                result = subtable_manager.sync_all_subtables(force_full=True, clear_old_data=True)
                results['subtables'] = result
                if result.get('success'):
                    synced_count = result.get('summary', {}).get('total_synced', 0)
                    api_calls_saved = result.get('summary', {}).get('api_calls_saved', 0)
                    self.logger.info(f"✅ 子表同步完成，共同步 {synced_count} 条记录")
                    if api_calls_saved > 0:
                        self.logger.info(f"🚀 优化效果：节省了 {api_calls_saved} 次API调用")
                else:
                    self.logger.error(f"❌ 子表同步失败: {result.get('error')}")
            finally:
                subtable_manager.close()
            
            # 2. 同步房源运营数据（T+1全量模式）
            self.logger.info("🔄 开始房源运营数据同步...")
            operational_manager = OperationalSyncManager()
            try:
                result = operational_manager.sync_operational_data(clear_old_data=True)
                results['operational'] = result
                if result.get('success'):
                    self.logger.info(f"✅ 房源运营数据同步完成，共同步 {result.get('synced_count', 0)} 条记录")
                else:
                    self.logger.error(f"❌ 房源运营数据同步失败: {result.get('error')}")
            finally:
                operational_manager.close()
            
            # 3. 生成主表数据
            self.logger.info("🔄 开始主表数据生成...")
            main_table_manager = MainTableSyncManager()
            try:
                result = main_table_manager.sync_all_main_tables()
                results['main_tables'] = result
                if result.get('success'):
                    self.logger.info(f"✅ 主表数据生成完成")
                else:
                    self.logger.error(f"❌ 主表数据生成失败: {result.get('error')}")
            finally:
                main_table_manager.close()
            
            # 统计总体结果
            end_time = datetime.now()
            duration = end_time - start_time
            
            all_success = all(r.get('success', False) for r in results.values())
            
            self.logger.info("=" * 60)
            if all_success:
                self.logger.info("🎉 T+1全量数据同步完成！")
            else:
                self.logger.warning("⚠️ 部分同步任务失败，请检查日志")
            
            self.logger.info(f"⏱️ 同步耗时: {duration}")
            self.logger.info("=" * 60)
            
            return all_success
            
        except Exception as e:
            self.logger.error(f"T+1全量同步失败: {e}")
            return False
    
    def setup_schedule(self):
        """设置定时任务"""
        # 每天凌晨2点执行T+1全量同步
        schedule.every().day.at("02:00").do(self.sync_all_data_full)
        
        # 每周日凌晨4点清理7天前的日志
        def cleanup_logs():
            try:
                import glob
                log_files = glob.glob("logs/*.log")
                cutoff_time = time.time() - (7 * 24 * 60 * 60)  # 7天前
                
                cleaned_count = 0
                for log_file in log_files:
                    if os.path.getmtime(log_file) < cutoff_time:
                        os.remove(log_file)
                        cleaned_count += 1
                
                self.logger.info(f"📁 日志清理完成，删除了 {cleaned_count} 个旧日志文件")
            except Exception as e:
                self.logger.error(f"日志清理失败: {e}")
        
        schedule.every().sunday.at("04:00").do(cleanup_logs)
        
        self.logger.info("⏰ 定时任务已配置:")
        self.logger.info("   - 每天凌晨2点: T+1全量数据同步")
        self.logger.info("   - 每周日凌晨4点: 清理7天前日志")
    
    def run(self, sync_on_startup=True):
        """运行调度器
        
        Args:
            sync_on_startup (bool): 是否在启动时立即执行一次全量同步
        """
        self.running = True
        
        try:
            # 设置定时任务
            self.setup_schedule()
            
            # 启动Kafka监听器（已禁用，专注T+1全量同步）
            # if not self.start_kafka_listener():
            #     self.logger.warning("Kafka监听器启动失败，继续运行定时任务")
            self.logger.info("🔄 T+1全量同步模式：Kafka实时监听已禁用")
            
            self.logger.info("🚀 调度器启动成功！")
            self.logger.info("🔄 运行模式: T+1全量同步模式（实时监听已禁用）")
            self.logger.info("⏰ 定时同步: 每天凌晨2点T+1全量同步")
            if sync_on_startup:
                self.logger.info("🎯 启动策略: 立即执行一次全量同步，然后进入定时任务模式")
            
            # 启动时立即执行一次全量同步
            if sync_on_startup:
                self.logger.info("🎯 启动时立即执行全量同步...")
                startup_success = self.sync_all_data_full(is_startup=True)
                if startup_success:
                    self.logger.info("✅ 启动同步完成！进入定时任务模式...")
                else:
                    self.logger.warning("⚠️ 启动同步部分失败，但继续运行定时任务...")
                self.logger.info("-" * 60)
            
            self.logger.info("🛑 停止服务: Ctrl+C")
            
            # 主循环
            while self.running:
                schedule.run_pending()
                time.sleep(60)  # 每分钟检查一次定时任务
                
        except KeyboardInterrupt:
            self.logger.info("收到停止信号，正在优雅关闭...")
        except Exception as e:
            self.logger.error(f"调度器运行异常: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """停止调度器"""
        self.running = False
        
        # 停止Kafka监听器
        if self.kafka_listener:
            try:
                self.kafka_listener.stop()
            except:
                pass
        
        self.logger.info("✅ 调度器已停止")


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='北交所数据同步调度器')
    
    parser.add_argument(
        '--config', '-c',
        default='config/config.yaml',
        help='配置文件路径 (默认: config/config.yaml)'
    )
    
    parser.add_argument(
        '--test',
        action='store_true',
        help='仅测试连接，不启动调度器'
    )
    
    parser.add_argument(
        '--sync-now',
        action='store_true',
        help='立即执行一次T+1全量同步'
    )
    
    parser.add_argument(
        '--kafka-only',
        action='store_true',
        help='仅启动Kafka监听器，不执行定时同步'
    )
    
    parser.add_argument(
        '--no-startup-sync',
        action='store_true',
        help='启动时不执行立即同步，直接进入定时任务模式'
    )
    
    return parser.parse_args()


def test_connections():
    """测试所有连接"""
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


def main():
    """主函数"""
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
        
        logger.info("=" * 60)
        logger.info("北交所数据同步调度器启动")
        logger.info("=" * 60)
        
        # 测试连接
        if args.test:
            if test_connections():
                print("✅ 所有连接测试成功")
                sys.exit(0)
            else:
                print("❌ 连接测试失败")
                sys.exit(1)
        
        # 创建调度器
        scheduler = SyncScheduler()
        
        # 注册信号处理器
        def signal_handler(signum, frame):
            logger.info(f"收到信号 {signum}，正在停止调度器...")
            scheduler.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # 立即同步
        if args.sync_now:
            logger.info("立即执行T+1全量同步...")
            success = scheduler.sync_all_data_full(is_startup=False)
            sys.exit(0 if success else 1)
        
        # 仅Kafka监听（已禁用）
        if args.kafka_only:
            logger.warning("⚠️  Kafka监听功能已禁用，当前为T+1全量同步模式")
            logger.info("💡 如需启用Kafka功能，请修改scheduler.py中的相关注释")
            sys.exit(0)
            # logger.info("仅启动Kafka监听器...")
            # if scheduler.start_kafka_listener():
            #     logger.info("Kafka监听器运行中，按Ctrl+C停止...")
            #     while True:
            #         time.sleep(1)
            # else:
            #     logger.error("Kafka监听器启动失败")
            #     sys.exit(1)
        
        # 启动完整调度器
        sync_on_startup = not args.no_startup_sync  # 默认启动时同步，除非指定不同步
        scheduler.run(sync_on_startup=sync_on_startup)
        
    except KeyboardInterrupt:
        print("\n⚠️  用户中断程序")
        sys.exit(1)
    except Exception as e:
        print(f"💥 程序执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
