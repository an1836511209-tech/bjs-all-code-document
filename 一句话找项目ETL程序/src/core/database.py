#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库连接和操作模块
提供MySQL数据库连接池管理和基础CRUD操作
"""

import logging
import pymysql
from pymysql.cursors import DictCursor
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
import yaml
from .config import get_config

class DatabaseManager:
    """
    数据库管理器
    负责数据库连接池管理和基础操作
    """
    
    def __init__(self, config_path: str = None):
        """
        初始化数据库管理器
        
        Args:
            config_path: 配置文件路径（可选，默认使用ConfigManager）
        """
        self.logger = logging.getLogger(__name__)
        if config_path:
            self.config = self._load_config(config_path)
        else:
            # 使用统一的配置管理器
            self.config = get_config()
        self.engine = None
        self.Session = None
        self._init_database()
    
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
    
    def _init_database(self):
        """
        初始化数据库连接池
        """
        try:
            db_config = self.config['database']
            
            # 构建数据库连接URL
            db_url = (
                f"mysql+pymysql://{db_config['user']}:{db_config['password']}"
                f"@{db_config['host']}:{db_config['port']}/{db_config['database']}"
                f"?charset={db_config['charset']}"
            )
            
            # 创建数据库引擎
            self.engine = create_engine(
                db_url,
                poolclass=QueuePool,
                pool_size=db_config.get('pool_size', 10),
                pool_recycle=db_config.get('pool_recycle', 3600),
                echo=False,
                connect_args={
                    'connect_timeout': 60,
                    'read_timeout': 60,
                    'write_timeout': 60
                }
            )
            
            # 创建Session工厂
            self.Session = sessionmaker(bind=self.engine)
            
            self.logger.info("数据库连接池初始化成功")
            
        except Exception as e:
            self.logger.error(f"数据库连接池初始化失败: {e}")
            raise
    
    @contextmanager
    def get_session(self):
        """
        获取数据库会话上下文管理器
        
        Yields:
            数据库会话对象
        """
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            self.logger.error(f"数据库操作失败: {e}")
            raise
        finally:
            session.close()
    
    def execute_query(self, sql: str, params: Optional[Dict] = None) -> List[Dict]:
        """
        执行查询SQL
        
        Args:
            sql: SQL语句
            params: 参数字典
            
        Returns:
            查询结果列表
        """
        try:
            with self.get_session() as session:
                result = session.execute(text(sql), params or {})
                return [dict(row._mapping) for row in result.fetchall()]
        except Exception as e:
            self.logger.error(f"执行查询失败: {sql}, 错误: {e}")
            raise
    
    def execute_non_query(self, sql: str, params: Optional[Dict] = None) -> int:
        """
        执行非查询SQL（INSERT, UPDATE, DELETE）
        
        Args:
            sql: SQL语句
            params: 参数字典
            
        Returns:
            影响的行数
        """
        try:
            with self.get_session() as session:
                result = session.execute(text(sql), params or {})
                return result.rowcount
        except Exception as e:
            self.logger.error(f"执行非查询失败: {sql}, 错误: {e}")
            raise
    
    def batch_insert(self, table_name: str, data_list: List[Dict[str, Any]], 
                    on_duplicate_update: bool = True) -> int:
        """
        批量插入数据
        
        Args:
            table_name: 表名
            data_list: 数据列表
            on_duplicate_update: 是否在重复时更新
            
        Returns:
            插入的行数
        """
        if not data_list:
            return 0
        
        try:
            # 过滤掉id字段，避免主键冲突
            cleaned_data_list = []
            for data in data_list:
                cleaned_data = {k: v for k, v in data.items() if k != 'id'}
                cleaned_data_list.append(cleaned_data)
            
            # 获取字段名（已过滤id字段）
            fields = list(cleaned_data_list[0].keys())
            placeholders = ', '.join([f':{field}' for field in fields])
            fields_str = ', '.join([f'`{field}`' for field in fields])
            
            # 构建SQL
            if on_duplicate_update:
                update_fields = ', '.join([
                    f'`{field}` = VALUES(`{field}`)' 
                    for field in fields if field not in ['created_at']
                ])
                sql = f"""
                    INSERT INTO `{table_name}` ({fields_str}) 
                    VALUES ({placeholders})
                    ON DUPLICATE KEY UPDATE {update_fields}
                """
            else:
                sql = f"INSERT INTO `{table_name}` ({fields_str}) VALUES ({placeholders})"
            
            with self.get_session() as session:
                result = session.execute(text(sql), cleaned_data_list)
                affected_rows = result.rowcount
                
            self.logger.info(f"批量插入完成，表: {table_name}, 数据量: {len(data_list)}, 影响行数: {affected_rows}")
            return affected_rows
            
        except Exception as e:
            self.logger.error(f"批量插入失败，表: {table_name}, 错误: {e}")
            raise
    
    def check_record_exists(self, table_name: str, condition: Dict[str, Any]) -> bool:
        """
        检查记录是否存在
        
        Args:
            table_name: 表名
            condition: 查询条件
            
        Returns:
            是否存在
        """
        try:
            where_clause = ' AND '.join([f"`{k}` = :{k}" for k in condition.keys()])
            sql = f"SELECT 1 FROM `{table_name}` WHERE {where_clause} LIMIT 1"
            
            result = self.execute_query(sql, condition)
            return len(result) > 0
            
        except Exception as e:
            self.logger.error(f"检查记录存在性失败，表: {table_name}, 条件: {condition}, 错误: {e}")
            raise
    
    def get_max_update_time(self, table_name: str, time_field: str = 'updated_at') -> Optional[str]:
        """
        获取表中最大的更新时间
        
        Args:
            table_name: 表名
            time_field: 时间字段名
            
        Returns:
            最大更新时间字符串
        """
        try:
            sql = f"SELECT MAX(`{time_field}`) as max_time FROM `{table_name}`"
            result = self.execute_query(sql)
            
            if result and result[0]['max_time']:
                return result[0]['max_time'].strftime('%Y-%m-%d %H:%M:%S')
            return None
            
        except Exception as e:
            self.logger.error(f"获取最大更新时间失败，表: {table_name}, 错误: {e}")
            raise
    
    def get_table_info(self, table_name: str) -> List[Dict[str, Any]]:
        """
        获取表结构信息
        
        Args:
            table_name: 表名
            
        Returns:
            表结构信息列表
        """
        try:
            sql = f"DESCRIBE `{table_name}`"
            result = self.execute_query(sql)
            
            # 转换为统一格式
            table_info = []
            for row in result:
                table_info.append({
                    'column_name': row['Field'],
                    'data_type': row['Type'],
                    'is_nullable': row['Null'] == 'YES',
                    'column_default': row['Default'],
                    'extra': row['Extra']
                })
            
            return table_info
            
        except Exception as e:
            self.logger.error(f"获取表结构失败，表: {table_name}, 错误: {e}")
            raise
    
    def batch_update(self, table_name: str, data_list: List[Dict[str, Any]], 
                    key_fields: List[str]) -> int:
        """
        批量更新数据
        
        Args:
            table_name: 表名
            data_list: 数据列表，每个字典包含要更新的字段和主键字段
            key_fields: 用作WHERE条件的主键字段列表
            
        Returns:
            影响的行数
        """
        if not data_list:
            return 0
        
        try:
            affected_rows = 0
            
            # 分批处理，避免单次操作过大
            batch_size = 1000
            for i in range(0, len(data_list), batch_size):
                batch_data = data_list[i:i + batch_size]
                
                # 构建批量更新的CASE语句
                # 获取所有要更新的字段（除了主键字段）
                update_fields = set()
                for data in batch_data:
                    update_fields.update(k for k in data.keys() if k not in key_fields)
                
                if not update_fields:
                    continue
                
                # 构建主键条件
                key_conditions = []
                for key_field in key_fields:
                    key_values = [str(data[key_field]) for data in batch_data if key_field in data]
                    if key_values:
                        escaped_values = [f"'{v}'" for v in key_values]
                        key_conditions.append(f"`{key_field}` IN ({','.join(escaped_values)})")
                
                if not key_conditions:
                    continue
                
                # 为每个字段构建CASE WHEN语句
                case_statements = []
                for field in update_fields:
                    cases = []
                    for data in batch_data:
                        if field in data:
                            # 构建WHERE条件
                            where_parts = []
                            for key_field in key_fields:
                                if key_field in data:
                                    where_parts.append(f"`{key_field}` = '{data[key_field]}'")
                            
                            if where_parts:
                                where_condition = " AND ".join(where_parts)
                                value = data[field]
                                if value is None:
                                    cases.append(f"WHEN {where_condition} THEN NULL")
                                else:
                                    escaped_value = str(value).replace("'", "''")
                                    cases.append(f"WHEN {where_condition} THEN '{escaped_value}'")
                    
                    if cases:
                        case_statement = f"`{field}` = CASE " + " ".join(cases) + f" ELSE `{field}` END"
                        case_statements.append(case_statement)
                
                if case_statements and key_conditions:
                    # 构建完整的UPDATE语句
                    sql = f"""
                        UPDATE `{table_name}` 
                        SET {', '.join(case_statements)}
                        WHERE {' AND '.join(key_conditions)}
                    """
                    
                    with self.get_session() as session:
                        result = session.execute(text(sql))
                        affected_rows += result.rowcount
            
            self.logger.info(f"批量更新完成，表: {table_name}, 数据量: {len(data_list)}, 影响行数: {affected_rows}")
            return affected_rows
            
        except Exception as e:
            self.logger.error(f"批量更新失败，表: {table_name}, 错误: {e}")
            raise

    def close(self):
        """
        关闭数据库连接池
        """
        if self.engine:
            self.engine.dispose()
            self.logger.info("数据库连接池已关闭")


class DataSyncDAO:
    """
    数据同步专用DAO
    """
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)
    
    def sync_bjhl_info_disclosure(self, data_list: List[Dict[str, Any]]) -> int:
        """
        同步bjhl_info_disclosure表数据
        
        Args:
            data_list: 数据列表
            
        Returns:
            同步的记录数
        """
        if not data_list:
            return 0
        
        try:
            # 批量插入或更新
            affected_rows = self.db_manager.batch_insert(
                'bjhl_info_disclosure', 
                data_list, 
                on_duplicate_update=True
            )
            
            self.logger.info(f"bjhl_info_disclosure表同步完成，处理记录数: {len(data_list)}, 影响行数: {affected_rows}")
            return affected_rows
            
        except Exception as e:
            self.logger.error(f"bjhl_info_disclosure表同步失败: {e}")
            raise
    
    def sync_bjht_equity_transfer(self, data_list: List[Dict[str, Any]]) -> int:
        """
        同步bjht_equity_transfer表数据
        
        Args:
            data_list: 数据列表
            
        Returns:
            同步的记录数
        """
        if not data_list:
            return 0
        
        try:
            # 批量插入或更新
            affected_rows = self.db_manager.batch_insert(
                'bjht_equity_transfer', 
                data_list, 
                on_duplicate_update=True
            )
            
            self.logger.info(f"bjht_equity_transfer表同步完成，处理记录数: {len(data_list)}, 影响行数: {affected_rows}")
            return affected_rows
            
        except Exception as e:
            self.logger.error(f"bjht_equity_transfer表同步失败: {e}")
            raise
    
    def sync_bjhl_property_transfer(self, data_list: List[Dict[str, Any]]) -> int:
        """
        同步bjhl_property_transfer表数据
        
        Args:
            data_list: 数据列表
            
        Returns:
            同步的记录数
        """
        if not data_list:
            return 0
        
        try:
            # 批量插入或更新
            affected_rows = self.db_manager.batch_insert(
                'bjhl_property_transfer', 
                data_list, 
                on_duplicate_update=True
            )
            
            self.logger.info(f"bjhl_property_transfer表同步完成，处理记录数: {len(data_list)}, 影响行数: {affected_rows}")
            return affected_rows
            
        except Exception as e:
            self.logger.error(f"bjhl_property_transfer表同步失败: {e}")
            raise
    
    def sync_table_data(self, table_name: str, data_list: List[Dict[str, Any]]) -> int:
        """
        通用的表数据同步方法
        
        Args:
            table_name: 表名
            data_list: 数据列表
            
        Returns:
            同步的记录数
        """
        if not data_list:
            return 0
        
        try:
            # 批量插入或更新
            affected_rows = self.db_manager.batch_insert(
                table_name, 
                data_list, 
                on_duplicate_update=True
            )
            
            self.logger.info(f"{table_name}表同步完成，处理记录数: {len(data_list)}, 影响行数: {affected_rows}")
            return affected_rows
            
        except Exception as e:
            self.logger.error(f"{table_name}表同步失败: {e}")
            raise
    
    def get_last_sync_time(self, table_name: str) -> Optional[str]:
        """
        获取最后同步时间
        
        Args:
            table_name: 表名
            
        Returns:
            最后同步时间
        """
        return self.db_manager.get_max_update_time(table_name, 'updated_at')