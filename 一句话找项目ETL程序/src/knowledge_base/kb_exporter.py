"""
数据导出器

从数据库导出数据为Excel文件，用于上传到知识库
"""

import os
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy import text
from src.core.logger import get_logger
from src.core.database import DatabaseManager
from src.core.config import get_config
from src.knowledge_base.token_calculator import TokenCalculator
from src.knowledge_base.data_splitter import DataSplitter

logger = get_logger(__name__)


class DataExporter:
    """数据导出器"""
    
    def __init__(self):
        """初始化导出器"""
        self.config = get_config()
        self.kb_config = self.config.get('knowledge_base', {})
        self.export_config = self.kb_config.get('export', {})
        
        # 导出配置
        self.output_dir = self.export_config.get('output_dir', 'exports')
        self.file_format = self.export_config.get('file_format', 'xlsx')
        self.max_rows_per_file = self.export_config.get('max_rows_per_file', 10000)
        
        # Token相关配置
        self.enable_token_validation = self.export_config.get('enable_token_validation', True)
        self.max_tokens_per_row = self.export_config.get('max_tokens_per_row', 30000)
        self.enable_data_splitting = self.export_config.get('enable_data_splitting', True)
        
        # 创建导出目录
        Path(self.output_dir).mkdir(exist_ok=True)
        
        # 数据库管理器
        self.db_manager = DatabaseManager()
        
        # Token计算器和数据切分器
        if self.enable_token_validation:
            self.token_calculator = TokenCalculator()
            if self.enable_data_splitting:
                self.data_splitter = DataSplitter(max_tokens=self.max_tokens_per_row)
    
    def _get_table_columns(self, table_name: str) -> List[str]:
        """
        获取表的所有列名
        
        Args:
            table_name: 表名
            
        Returns:
            列名列表
        """
        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text(f"SHOW COLUMNS FROM {table_name}"))
                columns = [row[0] for row in result.fetchall()]
                return columns
        except Exception as e:
            logger.error(f"获取表列名失败 {table_name}: {e}")
            return []
    
    def _process_data_with_token_validation(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        处理数据，进行token验证和切分
        
        Args:
            df: 原始数据DataFrame
            
        Returns:
            处理后的DataFrame
        """
        if not self.enable_token_validation:
            return df
        
        try:
            logger.info(f"开始进行token验证和数据处理，原始数据行数: {len(df)}")
            
            # 转换DataFrame为字典列表
            rows_data = df.to_dict('records')
            
            # 统计信息
            total_rows = len(rows_data)
            oversized_rows = 0
            split_rows = 0
            
            processed_rows = []
            
            for i, row_data in enumerate(rows_data):
                if i % 100 == 0:
                    logger.info(f"Token验证进度: {i}/{total_rows}")
                
                # 计算当前行的token数
                row_tokens = self.token_calculator.count_row_tokens(row_data)
                
                if row_tokens > self.max_tokens_per_row:
                    oversized_rows += 1
                    logger.debug(f"第{i+1}行数据超过token限制: {row_tokens}/{self.max_tokens_per_row}")
                    
                    if self.enable_data_splitting:
                        # 进行数据切分
                        split_result = self.data_splitter.split_row(row_data)
                        processed_rows.extend(split_result)
                        
                        if len(split_result) > 1:
                            split_rows += 1
                            logger.debug(f"第{i+1}行数据被切分为{len(split_result)}行")
                    else:
                        # 不切分，直接添加（可能超过限制）
                        processed_rows.append(row_data)
                        logger.warning(f"第{i+1}行数据超过token限制但未启用切分功能")
                else:
                    # 正常数据，直接添加
                    processed_rows.append(row_data)
            
            # 转换回DataFrame
            processed_df = pd.DataFrame(processed_rows)
            
            logger.info(f"Token验证完成: 原始{total_rows}行 -> 处理后{len(processed_df)}行")
            logger.info(f"超长行数: {oversized_rows}, 切分行数: {split_rows}")
            
            return processed_df
            
        except Exception as e:
            logger.error(f"Token验证和数据处理失败: {e}")
            return df
    
    def _validate_processed_data(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        验证处理后的数据
        
        Args:
            df: 处理后的DataFrame
            
        Returns:
            验证结果
        """
        if not self.enable_token_validation:
            return {'validation_enabled': False}
        
        try:
            rows_data = df.to_dict('records')
            
            validation_stats = {
                'validation_enabled': True,
                'total_rows': len(rows_data),
                'valid_rows': 0,
                'oversized_rows': 0,
                'max_tokens': 0,
                'min_tokens': float('inf'),
                'avg_tokens': 0,
                'oversized_details': []
            }
            
            total_tokens = 0
            
            for i, row_data in enumerate(rows_data):
                row_tokens = self.token_calculator.count_row_tokens(row_data)
                total_tokens += row_tokens
                
                validation_stats['max_tokens'] = max(validation_stats['max_tokens'], row_tokens)
                validation_stats['min_tokens'] = min(validation_stats['min_tokens'], row_tokens)
                
                if row_tokens > self.max_tokens_per_row:
                    validation_stats['oversized_rows'] += 1
                    validation_stats['oversized_details'].append({
                        'row_index': i + 1,
                        'token_count': row_tokens,
                        'project_code': row_data.get('project_code', 'N/A')
                    })
                else:
                    validation_stats['valid_rows'] += 1
            
            validation_stats['avg_tokens'] = total_tokens / len(rows_data) if rows_data else 0
            
            if validation_stats['min_tokens'] == float('inf'):
                validation_stats['min_tokens'] = 0
            
            return validation_stats
            
        except Exception as e:
            logger.error(f"数据验证失败: {e}")
            return {'validation_enabled': True, 'error': str(e)}
    
    def _export_table_data(self, table_name: str, output_file: str, limit: Optional[int] = None) -> bool:
        """
        导出单个表的数据
        
        Args:
            table_name: 表名
            output_file: 输出文件路径
            limit: 限制行数，None表示不限制
            
        Returns:
            是否成功
        """
        try:
            # 构建查询SQL
            sql = f"SELECT * FROM {table_name}"
            if limit:
                sql += f" LIMIT {limit}"
            
            logger.info(f"开始导出表数据: {table_name}")
            
            # 使用pandas读取数据
            # 构建连接字符串
            db_config = self.config.get('database', {})
            connection_string = f"mysql+pymysql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['database']}?charset={db_config.get('charset', 'utf8mb4')}"
            df = pd.read_sql(sql, connection_string)
            
            if df.empty:
                logger.warning(f"表 {table_name} 没有数据")
                return False
            
            original_rows = len(df)
            
            # 进行token验证和数据处理
            df = self._process_data_with_token_validation(df)
            
            # 验证处理后的数据
            validation_result = self._validate_processed_data(df)
            
            # 记录验证结果
            if validation_result.get('validation_enabled'):
                logger.info(f"数据验证结果 - 总行数: {validation_result['total_rows']}, "
                           f"有效行数: {validation_result['valid_rows']}, "
                           f"超长行数: {validation_result['oversized_rows']}")
                logger.info(f"Token统计 - 最大: {validation_result['max_tokens']}, "
                           f"最小: {validation_result['min_tokens']}, "
                           f"平均: {validation_result['avg_tokens']:.1f}")
                
                if validation_result['oversized_rows'] > 0:
                    logger.warning(f"仍有{validation_result['oversized_rows']}行数据超过token限制")
                    for detail in validation_result['oversized_details'][:5]:  # 只显示前5个
                        logger.warning(f"超长行: 第{detail['row_index']}行, "
                                     f"Tokens: {detail['token_count']}, "
                                     f"项目编码: {detail['project_code']}")
            
            # 导出为Excel
            df.to_excel(output_file, index=False, engine='openpyxl')
            
            processed_rows = len(df)
            logger.info(f"表数据导出成功: {table_name}, 原始行数: {original_rows}, "
                       f"处理后行数: {processed_rows}, 文件: {output_file}")
            return True
            
        except Exception as e:
            logger.error(f"导出表数据失败 {table_name}: {e}")
            return False
    
    def _split_large_table(self, table_name: str) -> List[str]:
        """
        分割大表数据为多个文件
        
        Args:
            table_name: 表名
            
        Returns:
            导出文件路径列表
        """
        try:
            # 获取总行数
            with self.db_manager.get_session() as session:
                result = session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                total_rows = result.fetchone()[0]
            
            if total_rows <= self.max_rows_per_file:
                # 不需要分割
                output_file = os.path.join(
                    self.output_dir, 
                    f"{table_name}.{self.file_format}"
                )
                if self._export_table_data(table_name, output_file):
                    return [output_file]
                else:
                    return []
            
            # 需要分割
            output_files = []
            pages = (total_rows + self.max_rows_per_file - 1) // self.max_rows_per_file
            
            for page in range(pages):
                offset = page * self.max_rows_per_file
                
                output_file = os.path.join(
                    self.output_dir,
                    f"{table_name}_part{page+1}.{self.file_format}"
                )
                
                # 分页查询
                sql = f"SELECT * FROM {table_name} LIMIT {self.max_rows_per_file} OFFSET {offset}"
                
                try:
                    # 构建连接字符串
                    db_config = self.config.get('database', {})
                    connection_string = f"mysql+pymysql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['database']}?charset={db_config.get('charset', 'utf8mb4')}"
                    df = pd.read_sql(sql, connection_string)
                    
                    if not df.empty:
                        original_rows = len(df)
                        
                        # 进行token验证和数据处理
                        df = self._process_data_with_token_validation(df)
                        
                        # 验证处理后的数据
                        validation_result = self._validate_processed_data(df)
                        
                        # 记录验证结果
                        if validation_result.get('validation_enabled'):
                            logger.debug(f"分割文件验证 - 总行数: {validation_result['total_rows']}, "
                                       f"有效行数: {validation_result['valid_rows']}, "
                                       f"超长行数: {validation_result['oversized_rows']}")
                        
                        df.to_excel(output_file, index=False, engine='openpyxl')
                        output_files.append(output_file)
                        
                        processed_rows = len(df)
                        logger.info(f"分割文件导出成功: {output_file}, 原始行数: {original_rows}, 处理后行数: {processed_rows}")
                    
                except Exception as e:
                    logger.error(f"分割文件导出失败 {output_file}: {e}")
                    continue
            
            return output_files
            
        except Exception as e:
            logger.error(f"分割表数据失败 {table_name}: {e}")
            return []
    
    def export_table(self, table_name: str) -> List[str]:
        """
        导出指定表的数据
        
        Args:
            table_name: 表名
            
        Returns:
            导出文件路径列表
        """
        if not table_name:
            logger.error("表名不能为空")
            return []
        
        # 检查表是否存在
        try:
            with self.db_manager.get_session() as session:
                result = session.execute(text(f"SHOW TABLES LIKE '{table_name}'"))
                if not result.fetchone():
                    logger.error(f"表不存在: {table_name}")
                    return []
        except Exception as e:
            logger.error(f"检查表存在性失败 {table_name}: {e}")
            return []
        
        # 导出数据
        return self._split_large_table(table_name)
    
    def export_all_main_tables(self) -> Dict[str, List[str]]:
        """
        导出所有主表数据
        
        Returns:
            {表名: [导出文件路径列表]}
        """
        # 获取知识库映射中的所有表名
        kb_mapping = self.kb_config.get('kb_mapping', {})
        main_tables = list(kb_mapping.keys())
        
        if not main_tables:
            logger.warning("没有配置需要导出的主表")
            return {}
        
        results = {}
        
        for table_name in main_tables:
            logger.info(f"开始导出主表: {table_name}")
            files = self.export_table(table_name)
            results[table_name] = files
            
            if files:
                logger.info(f"主表 {table_name} 导出完成，文件数: {len(files)}")
            else:
                logger.warning(f"主表 {table_name} 导出失败或无数据")
        
        return results
    
    def get_export_summary(self, export_results: Dict[str, List[str]]) -> Dict[str, Any]:
        """
        获取导出摘要信息
        
        Args:
            export_results: 导出结果
            
        Returns:
            摘要信息
        """
        total_tables = len(export_results)
        total_files = sum(len(files) for files in export_results.values())
        successful_tables = len([table for table, files in export_results.items() if files])
        failed_tables = total_tables - successful_tables
        
        # 计算文件大小
        total_size = 0
        for files in export_results.values():
            for file_path in files:
                if os.path.exists(file_path):
                    total_size += os.path.getsize(file_path)
        
        summary = {
            'total_tables': total_tables,
            'successful_tables': successful_tables,
            'failed_tables': failed_tables,
            'total_files': total_files,
            'total_size_mb': round(total_size / 1024 / 1024, 2),
            'export_time': datetime.now().isoformat(),
            'output_directory': os.path.abspath(self.output_dir),
            'token_validation': {
                'enabled': self.enable_token_validation,
                'max_tokens_per_row': self.max_tokens_per_row,
                'data_splitting_enabled': self.enable_data_splitting
            }
        }
        
        return summary
