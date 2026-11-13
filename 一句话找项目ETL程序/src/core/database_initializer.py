#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库初始化模块
负责检查和创建数据库、表结构
"""

import os
import logging
import pymysql
from pathlib import Path
from typing import List, Dict, Any, Optional
from .config import get_config


class DatabaseInitializer:
    """数据库初始化器"""
    
    def __init__(self):
        """初始化数据库初始化器"""
        self.logger = logging.getLogger(__name__)
        self.config = get_config()
        self.db_config = self.config['database']
        
    def _get_connection_without_db(self):
        """获取不指定数据库的MySQL连接"""
        try:
            connection = pymysql.connect(
                host=self.db_config['host'],
                port=self.db_config['port'],
                user=self.db_config['user'],
                password=self.db_config['password'],
                charset=self.db_config['charset'],
                connect_timeout=60,
                read_timeout=60,
                write_timeout=60
            )
            return connection
        except Exception as e:
            self.logger.error(f"连接MySQL服务器失败: {e}")
            raise
    
    def _get_connection_with_db(self):
        """获取指定数据库的MySQL连接"""
        try:
            connection = pymysql.connect(
                host=self.db_config['host'],
                port=self.db_config['port'],
                user=self.db_config['user'],
                password=self.db_config['password'],
                database=self.db_config['database'],
                charset=self.db_config['charset'],
                connect_timeout=60,
                read_timeout=60,
                write_timeout=60
            )
            return connection
        except Exception as e:
            self.logger.error(f"连接数据库失败: {e}")
            raise
    
    def check_database_exists(self) -> bool:
        """检查数据库是否存在"""
        try:
            connection = self._get_connection_without_db()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SHOW DATABASES LIKE %s", (self.db_config['database'],))
                    result = cursor.fetchone()
                    return result is not None
            finally:
                connection.close()
        except Exception as e:
            self.logger.error(f"检查数据库是否存在失败: {e}")
            return False
    
    def create_database(self) -> bool:
        """创建数据库"""
        try:
            connection = self._get_connection_without_db()
            try:
                with connection.cursor() as cursor:
                    # 创建数据库
                    sql = f"""
                    CREATE DATABASE IF NOT EXISTS `{self.db_config['database']}`
                    CHARACTER SET utf8mb4
                    COLLATE utf8mb4_unicode_ci
                    """
                    cursor.execute(sql)
                    connection.commit()
                    
                    self.logger.info(f"✅ 数据库 {self.db_config['database']} 创建成功")
                    return True
            finally:
                connection.close()
        except Exception as e:
            self.logger.error(f"创建数据库失败: {e}")
            return False
    
    def get_existing_tables(self) -> List[str]:
        """获取已存在的表列表"""
        try:
            connection = self._get_connection_with_db()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SHOW TABLES")
                    tables = [row[0] for row in cursor.fetchall()]
                    return tables
            finally:
                connection.close()
        except Exception as e:
            self.logger.error(f"获取表列表失败: {e}")
            return []
    
    def _parse_sql_file(self, sql_file_path: str) -> List[str]:
        """解析SQL文件，提取DDL语句"""
        try:
            with open(sql_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 移除注释和空行，分割SQL语句
            statements = []
            current_statement = []
            
            for line in content.split('\n'):
                line = line.strip()
                
                # 跳过注释行和空行
                if not line or line.startswith('--') or line.startswith('#'):
                    continue
                
                current_statement.append(line)
                
                # 如果行以分号结尾，说明是一个完整的SQL语句
                if line.endswith(';'):
                    statement = ' '.join(current_statement).strip()
                    if statement and statement.upper().startswith('CREATE TABLE'):
                        statements.append(statement)
                    current_statement = []
            
            # 处理最后一个语句（如果没有以分号结尾）
            if current_statement:
                statement = ' '.join(current_statement).strip()
                if statement and statement.upper().startswith('CREATE TABLE'):
                    statements.append(statement)
            
            return statements
            
        except Exception as e:
            self.logger.error(f"解析SQL文件失败 {sql_file_path}: {e}")
            return []
    
    def _extract_table_name(self, ddl_statement: str) -> str:
        """从DDL语句中提取表名"""
        try:
            # 查找 CREATE TABLE 后的表名
            statement_upper = ddl_statement.upper()
            start_idx = statement_upper.find('CREATE TABLE')
            if start_idx == -1:
                return ""
            
            # 找到表名部分
            table_part = ddl_statement[start_idx + 12:].strip()
            
            # 处理反引号包围的表名
            if table_part.startswith('`'):
                end_idx = table_part.find('`', 1)
                if end_idx != -1:
                    return table_part[1:end_idx]
            
            # 处理普通表名（空格前的部分）
            space_idx = table_part.find(' ')
            paren_idx = table_part.find('(')
            
            if space_idx != -1 and paren_idx != -1:
                end_idx = min(space_idx, paren_idx)
            elif space_idx != -1:
                end_idx = space_idx
            elif paren_idx != -1:
                end_idx = paren_idx
            else:
                end_idx = len(table_part)
            
            return table_part[:end_idx].strip('`').strip()
            
        except Exception as e:
            self.logger.error(f"提取表名失败: {e}")
            return ""
    
    def create_tables_from_sql_files(self) -> Dict[str, Any]:
        """从SQL文件创建表"""
        result = {
            'success': True,
            'created_tables': [],
            'skipped_tables': [],
            'failed_tables': [],
            'errors': []
        }
        
        # 获取项目根目录
        project_root = Path(__file__).parent.parent.parent
        
        # SQL文件路径
        sql_files = [
            project_root / "表结构信息" / "主表" / "create_table_ddl_all.sql",
            project_root / "表结构信息" / "子表" / "subtables_ddl.sql"
        ]
        
        try:
            # 获取已存在的表
            existing_tables = self.get_existing_tables()
            self.logger.info(f"数据库中已存在 {len(existing_tables)} 个表: {existing_tables}")
            
            connection = self._get_connection_with_db()
            try:
                with connection.cursor() as cursor:
                    for sql_file in sql_files:
                        if not sql_file.exists():
                            self.logger.warning(f"SQL文件不存在: {sql_file}")
                            continue
                        
                        self.logger.info(f"正在处理SQL文件: {sql_file}")
                        statements = self._parse_sql_file(str(sql_file))
                        
                        for statement in statements:
                            table_name = self._extract_table_name(statement)
                            if not table_name:
                                continue
                            
                            if table_name in existing_tables:
                                self.logger.info(f"⏭️  表 {table_name} 已存在，跳过创建")
                                result['skipped_tables'].append(table_name)
                                continue
                            
                            try:
                                cursor.execute(statement)
                                connection.commit()
                                self.logger.info(f"✅ 表 {table_name} 创建成功")
                                result['created_tables'].append(table_name)
                            except Exception as e:
                                error_msg = f"创建表 {table_name} 失败: {e}"
                                self.logger.error(error_msg)
                                result['failed_tables'].append(table_name)
                                result['errors'].append(error_msg)
                                result['success'] = False
            finally:
                connection.close()
                
        except Exception as e:
            error_msg = f"执行SQL文件失败: {e}"
            self.logger.error(error_msg)
            result['success'] = False
            result['errors'].append(error_msg)
        
        return result
    
    def initialize_database(self) -> Dict[str, Any]:
        """初始化数据库（检查并创建数据库和表）"""
        result = {
            'success': True,
            'database_created': False,
            'tables_result': None,
            'errors': []
        }
        
        try:
            self.logger.info("开始数据库初始化检查...")
            
            # 1. 检查数据库是否存在
            if not self.check_database_exists():
                self.logger.info(f"数据库 {self.db_config['database']} 不存在，正在创建...")
                if self.create_database():
                    result['database_created'] = True
                else:
                    result['success'] = False
                    result['errors'].append("创建数据库失败")
                    return result
            else:
                self.logger.info(f"数据库 {self.db_config['database']} 已存在")
            
            # 2. 检查并创建表
            self.logger.info("开始检查和创建表...")
            tables_result = self.create_tables_from_sql_files()
            result['tables_result'] = tables_result
            
            if not tables_result['success']:
                result['success'] = False
                result['errors'].extend(tables_result['errors'])
            
            # 3. 汇总结果
            if result['success']:
                created_count = len(tables_result['created_tables'])
                skipped_count = len(tables_result['skipped_tables'])
                
                self.logger.info("=" * 60)
                self.logger.info("🎉 数据库初始化完成！")
                if result['database_created']:
                    self.logger.info(f"✅ 已创建数据库: {self.db_config['database']}")
                self.logger.info(f"✅ 新建表数量: {created_count}")
                self.logger.info(f"⏭️  跳过表数量: {skipped_count}")
                
                if tables_result['created_tables']:
                    self.logger.info(f"📋 新建的表: {', '.join(tables_result['created_tables'])}")
                
                self.logger.info("=" * 60)
            
        except Exception as e:
            error_msg = f"数据库初始化失败: {e}"
            self.logger.error(error_msg)
            result['success'] = False
            result['errors'].append(error_msg)
        
        return result


def initialize_database() -> bool:
    """
    数据库初始化入口函数
    
    Returns:
        bool: 初始化是否成功
    """
    try:
        initializer = DatabaseInitializer()
        result = initializer.initialize_database()
        return result['success']
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"数据库初始化失败: {e}")
        return False





























