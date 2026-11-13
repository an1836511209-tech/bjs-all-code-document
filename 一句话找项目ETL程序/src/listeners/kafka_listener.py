#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kafka监听器模块
负责监听房源信息运营通知，实时更新数据库
"""

import logging
import json
import yaml
import signal
import sys
import os
from typing import Dict, Any, Optional, List
from datetime import datetime
import threading
import time
import traceback

try:
    from kafka import KafkaConsumer
    from kafka.errors import KafkaError
except ImportError:
    print("kafka-python库未安装，请运行: pip install kafka-python")
    sys.exit(1)

# 导入自定义模块
from database import DatabaseManager, DataSyncDAO
from api_client import OperationalAPIClient
from data_processor import DataProcessor


class KafkaMessageHandler:
    """
    Kafka消息处理器
    负责处理房源信息运营通知消息
    """
    
    def __init__(self, config_path: str = 'config.yaml'):
        """
        初始化消息处理器
        
        Args:
            config_path: 配置文件路径
        """
        self.logger = logging.getLogger(__name__)
        self.config = self._load_config(config_path)
        
        # 初始化组件
        self.db_manager = DatabaseManager(config_path)
        self.data_sync_dao = DataSyncDAO(self.db_manager)
        self.operational_api_client = OperationalAPIClient(config_path)
        self.data_processor = DataProcessor(config_path)
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """
        加载配置文件
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            配置字典
        """
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            return config
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
            raise
    
    def handle_message(self, message: Dict[str, Any]) -> bool:
        """
        处理Kafka消息
        
        Args:
            message: Kafka消息内容
            
        Returns:
            处理是否成功
        """
        try:
            self.logger.info(f"收到Kafka消息: {message}")
            
            # 解析消息内容
            project_id = message.get('projectId')
            status = message.get('status', 'insert')  # insert 或 update
            
            if not project_id:
                self.logger.warning("消息中缺少projectId，跳过处理")
                return False
            
            # 转换projectId为整数
            try:
                project_id_int = int(project_id)
            except (ValueError, TypeError):
                self.logger.warning(f"无法转换projectId为整数: {project_id}")
                return False
            
            if status == 'insert' or status == 'update':
                # 获取房源运营信息
                try:
                    response = self.operational_api_client.get_operational_data([project_id_int])
                    operational_data = response.get('data', [])
                    
                    if not operational_data:
                        self.logger.warning(f"未获取到项目 {project_id} 的房源运营信息")
                        return True  # 不算失败，可能是项目已删除等正常情况
                    
                    # 处理数据
                    processed_data = self.data_processor.process_operational_data(operational_data)
                    
                    if processed_data:
                        # 根据status决定操作类型
                        if status == 'update':
                            # 先删除原有数据
                            self._delete_existing_data(project_id)
                        
                        # 插入新数据
                        synced_count = self.data_sync_dao.sync_table_data('bjdc_lease_house', processed_data)
                        self.logger.info(f"项目 {project_id} 房源运营信息同步完成，记录数: {synced_count}")
                    else:
                        self.logger.warning(f"项目 {project_id} 数据处理后无有效记录")
                    
                    return True
                    
                except Exception as e:
                    self.logger.error(f"处理项目 {project_id} 失败: {e}")
                    return False
            
            elif status == 'delete':
                # 删除数据
                try:
                    self._delete_existing_data(project_id)
                    self.logger.info(f"项目 {project_id} 数据删除完成")
                    return True
                except Exception as e:
                    self.logger.error(f"删除项目 {project_id} 数据失败: {e}")
                    return False
            else:
                self.logger.warning(f"未知的消息状态: {status}")
                return False
            
        except Exception as e:
            self.logger.error(f"处理Kafka消息失败: {e}")
            self.logger.error(traceback.format_exc())
            return False
    
    def _delete_existing_data(self, project_id: str) -> None:
        """
        删除指定项目的现有数据
        
        Args:
            project_id: 项目ID
        """
        try:
            sql = "DELETE FROM `bjdc_lease_house` WHERE `projectId` = :project_id"
            affected_rows = self.db_manager.execute_non_query(sql, {'project_id': project_id})
            self.logger.info(f"删除项目 {project_id} 的现有数据，影响行数: {affected_rows}")
        except Exception as e:
            self.logger.error(f"删除项目 {project_id} 现有数据失败: {e}")
            raise
    
    def close(self):
        """
        关闭所有连接
        """
        try:
            if self.operational_api_client:
                self.operational_api_client.close()
            if self.db_manager:
                self.db_manager.close()
            self.logger.info("消息处理器连接已关闭")
        except Exception as e:
            self.logger.error(f"关闭消息处理器连接失败: {e}")


class KafkaListener:
    """
    Kafka监听器
    负责监听Kafka消息并处理
    """
    
    def __init__(self, config_path: str = 'config.yaml'):
        """
        初始化Kafka监听器
        
        Args:
            config_path: 配置文件路径
        """
        self.logger = logging.getLogger(__name__)
        self.config = self._load_config(config_path)
        self.kafka_config = self.config['kafka']
        
        # 初始化消息处理器
        self.message_handler = KafkaMessageHandler(config_path)
        
        # 初始化Kafka消费者
        self.consumer = None
        self.running = False
        self.thread = None
        
        # 注册信号处理器
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """
        加载配置文件
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            配置字典
        """
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            return config
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
            raise
    
    def _create_consumer(self) -> KafkaConsumer:
        """
        创建Kafka消费者
        
        Returns:
            KafkaConsumer对象
        """
        try:
            consumer = KafkaConsumer(
                self.kafka_config['topic'],
                bootstrap_servers=self.kafka_config['bootstrap_servers'],
                group_id=self.kafka_config['group_id'],
                auto_offset_reset=self.kafka_config.get('auto_offset_reset', 'earliest'),
                enable_auto_commit=self.kafka_config.get('enable_auto_commit', True),
                auto_commit_interval_ms=self.kafka_config.get('auto_commit_interval_ms', 1000),
                session_timeout_ms=self.kafka_config.get('session_timeout_ms', 30000),
                max_poll_records=self.kafka_config.get('max_poll_records', 100),
                value_deserializer=lambda m: json.loads(m.decode('utf-8')) if m else None,
                consumer_timeout_ms=5000  # 5秒超时，允许检查停止信号
            )
            
            self.logger.info(f"Kafka消费者创建成功，主题: {self.kafka_config['topic']}, "
                           f"组ID: {self.kafka_config['group_id']}")
            return consumer
            
        except Exception as e:
            self.logger.error(f"创建Kafka消费者失败: {e}")
            raise
    
    def _signal_handler(self, signum, frame):
        """
        信号处理器
        
        Args:
            signum: 信号编号
            frame: 当前栈帧
        """
        self.logger.info(f"收到信号 {signum}，准备停止监听...")
        self.stop()
    
    def start(self) -> None:
        """
        开始监听Kafka消息
        """
        try:
            self.logger.info("开始启动Kafka监听器...")
            
            # 创建消费者
            self.consumer = self._create_consumer()
            
            # 设置运行标志
            self.running = True
            
            # 在单独线程中运行监听循环
            self.thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.thread.start()
            
            self.logger.info("Kafka监听器启动成功")
            
            # 主线程等待
            try:
                while self.running:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.logger.info("收到键盘中断，停止监听...")
                self.stop()
            
        except Exception as e:
            self.logger.error(f"启动Kafka监听器失败: {e}")
            raise
    
    def _listen_loop(self) -> None:
        """
        监听循环
        """
        try:
            self.logger.info("开始监听Kafka消息...")
            
            while self.running:
                try:
                    # 轮询消息
                    message_batch = self.consumer.poll(timeout_ms=1000)
                    
                    if not message_batch:
                        continue
                    
                    # 处理消息批次
                    for topic_partition, messages in message_batch.items():
                        for message in messages:
                            if not self.running:
                                break
                            
                            try:
                                # 解析消息内容
                                if message.value is None:
                                    self.logger.warning("收到空消息，跳过")
                                    continue
                                
                                self.logger.debug(f"收到消息，偏移量: {message.offset}, "
                                                f"时间戳: {message.timestamp}")
                                
                                # 处理消息
                                success = self.message_handler.handle_message(message.value)
                                
                                if success:
                                    self.logger.debug(f"消息处理成功，偏移量: {message.offset}")
                                else:
                                    self.logger.warning(f"消息处理失败，偏移量: {message.offset}")
                                
                            except Exception as e:
                                self.logger.error(f"处理单条消息失败: {e}")
                                self.logger.error(traceback.format_exc())
                                continue
                    
                except Exception as e:
                    if self.running:
                        self.logger.error(f"Kafka消息轮询失败: {e}")
                        self.logger.error(traceback.format_exc())
                        # 短暂休眠后重试
                        time.sleep(5)
                    else:
                        break
            
            self.logger.info("Kafka监听循环结束")
            
        except Exception as e:
            self.logger.error(f"Kafka监听循环异常: {e}")
            self.logger.error(traceback.format_exc())
        finally:
            # 确保消费者被关闭
            if self.consumer:
                try:
                    self.consumer.close()
                except:
                    pass
    
    def stop(self) -> None:
        """
        停止监听
        """
        try:
            self.logger.info("正在停止Kafka监听器...")
            
            # 设置停止标志
            self.running = False
            
            # 关闭消费者
            if self.consumer:
                self.consumer.close()
                self.consumer = None
            
            # 等待线程结束
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=10)
                if self.thread.is_alive():
                    self.logger.warning("监听线程未能正常结束")
            
            # 关闭消息处理器
            if self.message_handler:
                self.message_handler.close()
            
            self.logger.info("Kafka监听器已停止")
            
        except Exception as e:
            self.logger.error(f"停止Kafka监听器失败: {e}")
    
    def test_connection(self) -> bool:
        """
        测试Kafka连接
        
        Returns:
            连接是否成功
        """
        try:
            self.logger.info("测试Kafka连接...")
            
            # 创建临时消费者进行连接测试
            test_consumer = KafkaConsumer(
                bootstrap_servers=self.kafka_config['bootstrap_servers'],
                group_id=f"test_{self.kafka_config['group_id']}",
                consumer_timeout_ms=5000
            )
            
            # 获取主题分区信息
            partitions = test_consumer.partitions_for_topic(self.kafka_config['topic'])
            
            if partitions is not None:
                self.logger.info(f"Kafka连接测试成功，主题 {self.kafka_config['topic']} "
                               f"有 {len(partitions)} 个分区")
                test_consumer.close()
                return True
            else:
                self.logger.error(f"主题 {self.kafka_config['topic']} 不存在")
                test_consumer.close()
                return False
            
        except Exception as e:
            self.logger.error(f"Kafka连接测试失败: {e}")
            return False


def setup_logging(config: Dict[str, Any]) -> None:
    """
    设置日志配置
    
    Args:
        config: 配置字典
    """
    log_config = config.get('logging', {})
    
    # 创建logs目录
    log_file = log_config.get('file', 'logs/kafka_listener.log')
    log_dir = os.path.dirname(log_file) if os.path.dirname(log_file) else 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 配置日志格式
    log_format = log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    log_level = getattr(logging, log_config.get('level', 'INFO').upper())
    
    # 配置根日志记录器
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )


def main():
    """
    主函数
    """
    import os
    import argparse
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='Kafka房源信息监听器')
    parser.add_argument('--config', '-c', default='config.yaml', help='配置文件路径')
    parser.add_argument('--test', action='store_true', help='仅测试连接')
    args = parser.parse_args()
    
    # 检查配置文件
    if not os.path.exists(args.config):
        print(f"错误: 配置文件 '{args.config}' 不存在")
        sys.exit(1)
    
    # 加载配置
    try:
        with open(args.config, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"加载配置文件失败: {e}")
        sys.exit(1)
    
    # 设置日志
    setup_logging(config)
    logger = logging.getLogger(__name__)
    
    # 初始化监听器
    try:
        listener = KafkaListener(args.config)
        
        if args.test:
            # 仅测试连接
            if listener.test_connection():
                print("Kafka连接测试成功")
                sys.exit(0)
            else:
                print("Kafka连接测试失败")
                sys.exit(1)
        else:
            # 启动监听
            logger.info("启动Kafka房源信息监听器")
            listener.start()
            
    except KeyboardInterrupt:
        logger.info("收到中断信号，程序退出")
    except Exception as e:
        logger.error(f"程序执行失败: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == '__main__':
    main()
