#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kafka监听运行脚本
启动Kafka监听器，实时处理房源运营信息更新
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


def parse_arguments():
    """
    解析命令行参数
    
    Returns:
        解析后的参数
    """
    parser = argparse.ArgumentParser(description='Kafka房源信息监听器')
    
    parser.add_argument(
        '--config', '-c',
        default='config/config.yaml',
        help='配置文件路径 (默认: config/config.yaml)'
    )
    
    parser.add_argument(
        '--test',
        action='store_true',
        help='仅测试Kafka连接'
    )
    
    return parser.parse_args()


def test_kafka_connection():
    """
    测试Kafka连接
    
    Returns:
        测试是否成功
    """
    logger = get_logger(__name__)
    
    try:
        from src.listeners.kafka_listener import KafkaListener
        
        listener = KafkaListener()
        if listener.test_connection():
            logger.info("Kafka连接测试成功")
            return True
        else:
            logger.error("Kafka连接测试失败")
            return False
            
    except ImportError as e:
        logger.error(f"导入Kafka模块失败: {e}")
        logger.error("请确保已安装kafka-python: pip install kafka-python")
        return False
    except Exception as e:
        logger.error(f"Kafka连接测试失败: {e}")
        return False


def start_kafka_listener():
    """
    启动Kafka监听器
    """
    logger = get_logger(__name__)
    
    try:
        from src.listeners.kafka_listener import KafkaListener
        
        logger.info("正在启动Kafka监听器...")
        
        listener = KafkaListener()
        
        print("🚀 Kafka监听器启动成功!")
        print("📡 正在监听房源运营信息更新...")
        print("⚠️  按 Ctrl+C 停止监听")
        print("-" * 50)
        
        # 启动监听
        listener.start()
        
    except ImportError as e:
        logger.error(f"导入Kafka模块失败: {e}")
        print("❌ 启动失败: 缺少kafka-python依赖")
        print("💡 解决方案: pip install kafka-python")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在停止监听器...")
        print("\n⚠️  正在停止Kafka监听器...")
    except Exception as e:
        logger.error(f"Kafka监听器运行失败: {e}")
        print(f"❌ 监听器运行失败: {e}")
        sys.exit(1)


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
        # 为Kafka监听器设置专门的日志文件
        log_config['file'] = 'logs/kafka_listener.log'
        setup_logging(log_config)
        
        logger = get_logger(__name__)
        
        logger.info("=" * 50)
        logger.info("Kafka房源信息监听器启动")
        logger.info("=" * 50)
        
        # 测试连接
        if args.test:
            if test_kafka_connection():
                print("✅ Kafka连接测试成功")
                sys.exit(0)
            else:
                print("❌ Kafka连接测试失败")
                sys.exit(1)
        
        # 启动监听器
        start_kafka_listener()
        
        print("✅ Kafka监听器已正常停止")
        
    except KeyboardInterrupt:
        print("\n⚠️  用户中断程序")
        sys.exit(1)
    except Exception as e:
        print(f"💥 程序执行失败: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
