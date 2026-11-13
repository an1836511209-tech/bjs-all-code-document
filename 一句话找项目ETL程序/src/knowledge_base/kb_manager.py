"""
知识库管理器

协调数据导出和知识库上传的主要接口
"""

import os
from typing import Dict, List, Any, Optional
from datetime import datetime
from src.core.logger import get_logger
from src.core.config import get_config
from .kb_client import KnowledgeBaseClient
from .kb_exporter import DataExporter

logger = get_logger(__name__)


class KnowledgeBaseManager:
    """知识库管理器"""
    
    def __init__(self):
        """初始化管理器"""
        self.config = get_config()
        self.kb_config = self.config.get('knowledge_base', {})
        self.kb_mapping = self.kb_config.get('kb_mapping', {})
        self.export_config = self.kb_config.get('export', {})
        
        # 初始化组件
        self.client = KnowledgeBaseClient()
        self.exporter = DataExporter()
        
        logger.info("知识库管理器初始化完成")
    
    def _get_dataset_name(self, table_name: str, file_index: int = 0) -> str:
        """
        生成数据集名称
        
        Args:
            table_name: 表名
            file_index: 文件索引（用于分割文件）
            
        Returns:
            数据集名称
        """
        if file_index == 0:
            return f"{table_name}_dataset"
        else:
            return f"{table_name}_part{file_index+1}_dataset"
    
    def _get_kb_id_for_table(self, table_name: str) -> Optional[int]:
        """
        根据表名获取知识库ID
        
        Args:
            table_name: 表名
            
        Returns:
            知识库ID，如果未找到返回None
        """
        return self.kb_mapping.get(table_name)
    
    def sync_table_to_kb(self, table_name: str) -> Dict[str, Any]:
        """
        同步单个表到知识库
        
        Args:
            table_name: 表名
            
        Returns:
            同步结果
        """
        result = {
            'table_name': table_name,
            'success': False,
            'exported_files': [],
            'uploaded_files': [],
            'created_datasets': [],
            'error': None,
            'summary': {}
        }
        
        try:
            # 获取知识库ID
            kb_id = self._get_kb_id_for_table(table_name)
            if not kb_id:
                raise ValueError(f"表 {table_name} 未配置知识库ID")
            
            logger.info(f"开始同步表到知识库: {table_name} -> KB#{kb_id}")
            
            # 1. 导出数据
            logger.info(f"步骤1: 导出表数据 {table_name}")
            exported_files = self.exporter.export_table(table_name)
            result['exported_files'] = exported_files
            
            if not exported_files:
                raise ValueError(f"表 {table_name} 数据导出失败或无数据")
            
            logger.info(f"数据导出完成，文件数: {len(exported_files)}")
            
            # 2. 上传文件并创建数据集
            logger.info(f"步骤2: 上传文件并创建数据集")
            uploaded_files = []
            created_datasets = []
            
            for i, file_path in enumerate(exported_files):
                try:
                    # 生成数据集名称
                    dataset_name = self._get_dataset_name(table_name, i)
                    
                    # 上传文件并创建数据集
                    file_id, dataset_id = self.client.upload_and_create_dataset(
                        file_path=file_path,
                        kb_id=kb_id,
                        dataset_name=dataset_name,
                        parser_type=self.export_config.get('parser_type', 'table')
                    )
                    
                    uploaded_files.append({
                        'file_path': file_path,
                        'file_id': file_id,
                        'dataset_name': dataset_name,
                        'dataset_id': dataset_id
                    })
                    created_datasets.append(dataset_id)
                    
                    logger.info(f"文件上传和数据集创建成功: {file_path} -> DS#{dataset_id}")
                    
                except Exception as e:
                    logger.error(f"处理文件失败 {file_path}: {e}")
                    continue
            
            result['uploaded_files'] = uploaded_files
            result['created_datasets'] = created_datasets
            
            if not uploaded_files:
                raise ValueError(f"表 {table_name} 所有文件上传失败")
            
            # 3. 清理导出文件（可选）
            self._cleanup_exported_files(exported_files)
            
            # 设置成功状态和摘要
            result['success'] = True
            result['summary'] = {
                'kb_id': kb_id,
                'exported_file_count': len(exported_files),
                'uploaded_file_count': len(uploaded_files),
                'created_dataset_count': len(created_datasets),
                'sync_time': datetime.now().isoformat()
            }
            
            logger.info(f"表同步完成: {table_name}, 成功上传 {len(uploaded_files)}/{len(exported_files)} 个文件")
            
        except Exception as e:
            error_msg = str(e)
            result['error'] = error_msg
            logger.error(f"表同步失败 {table_name}: {error_msg}")
        
        return result
    
    def sync_all_tables_to_kb(self) -> Dict[str, Any]:
        """
        同步所有主表到知识库
        
        Returns:
            同步结果摘要
        """
        logger.info("开始同步所有主表到知识库")
        
        start_time = datetime.now()
        all_results = {}
        
        # 获取所有需要同步的表
        tables_to_sync = list(self.kb_mapping.keys())
        
        if not tables_to_sync:
            logger.warning("没有配置需要同步的表")
            return {
                'success': False,
                'error': '没有配置需要同步的表',
                'results': {},
                'summary': {}
            }
        
        logger.info(f"需要同步的表数量: {len(tables_to_sync)}")
        
        # 逐个同步表
        for table_name in tables_to_sync:
            logger.info(f"开始同步表: {table_name}")
            result = self.sync_table_to_kb(table_name)
            all_results[table_name] = result
        
        # 生成总体摘要
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        successful_tables = [name for name, result in all_results.items() if result['success']]
        failed_tables = [name for name, result in all_results.items() if not result['success']]
        
        total_files_exported = sum(len(result['exported_files']) for result in all_results.values())
        total_files_uploaded = sum(len(result['uploaded_files']) for result in all_results.values())
        total_datasets_created = sum(len(result['created_datasets']) for result in all_results.values())
        
        summary = {
            'total_tables': len(tables_to_sync),
            'successful_tables': len(successful_tables),
            'failed_tables': len(failed_tables),
            'successful_table_names': successful_tables,
            'failed_table_names': failed_tables,
            'total_files_exported': total_files_exported,
            'total_files_uploaded': total_files_uploaded,
            'total_datasets_created': total_datasets_created,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'duration_seconds': round(duration, 2)
        }
        
        overall_success = len(successful_tables) > 0
        
        logger.info(f"所有表同步完成: 成功 {len(successful_tables)}/{len(tables_to_sync)} 个表, 耗时 {duration:.2f} 秒")
        
        return {
            'success': overall_success,
            'results': all_results,
            'summary': summary
        }
    
    def _cleanup_exported_files(self, file_paths: List[str], keep_files: bool = False):
        """
        清理导出的文件
        
        Args:
            file_paths: 文件路径列表
            keep_files: 是否保留文件，默认False（删除）
        """
        if keep_files:
            logger.info("配置为保留导出文件，跳过清理")
            return
        
        for file_path in file_paths:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.debug(f"清理导出文件: {file_path}")
            except Exception as e:
                logger.warning(f"清理文件失败 {file_path}: {e}")
    
    def get_kb_mapping_info(self) -> Dict[str, Any]:
        """
        获取知识库映射信息
        
        Returns:
            映射信息
        """
        return {
            'kb_mapping': self.kb_mapping,
            'total_tables': len(self.kb_mapping),
            'kb_ids': list(set(self.kb_mapping.values())),
            'export_config': self.export_config
        }
    
    def validate_configuration(self) -> Dict[str, Any]:
        """
        验证知识库配置
        
        Returns:
            验证结果
        """
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': []
        }
        
        # 检查基本配置
        if not self.kb_config:
            validation_result['valid'] = False
            validation_result['errors'].append('未找到知识库配置')
            return validation_result
        
        # 检查认证信息
        auth_key = self.kb_config.get('auth_key')
        auth_secret = self.kb_config.get('auth_secret')
        
        if not auth_key:
            validation_result['valid'] = False
            validation_result['errors'].append('未配置auth_key')
        
        if not auth_secret:
            validation_result['valid'] = False
            validation_result['errors'].append('未配置auth_secret')
        
        # 检查知识库映射
        if not self.kb_mapping:
            validation_result['valid'] = False
            validation_result['errors'].append('未配置知识库映射')
        else:
            # 检查知识库ID是否有效
            for table_name, kb_id in self.kb_mapping.items():
                if not isinstance(kb_id, int) or kb_id <= 0:
                    validation_result['warnings'].append(f'表 {table_name} 的知识库ID无效: {kb_id}')
        
        # 检查导出目录
        output_dir = self.export_config.get('output_dir', 'exports')
        if not os.path.exists(output_dir):
            validation_result['warnings'].append(f'导出目录不存在，将自动创建: {output_dir}')
        
        return validation_result
