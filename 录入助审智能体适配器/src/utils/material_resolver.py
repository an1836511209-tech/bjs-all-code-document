"""
材料名称解析和文件类型查找工具

提供统一的材料名称解析、文件类型查找功能，避免代码重复
"""

import re
from typing import Optional, Dict, List, Any
from loguru import logger

from src.schemas.file import FileType, FILE_TYPE_LABELS


class MaterialResolver:
    """材料名称解析和文件类型查找工具类"""
    
    @staticmethod
    def normalize_material_name(name: Optional[str]) -> str:
        """
        规范化材料名称，便于匹配
        
        去除书名号、引号、空格、文件扩展名等，转换为小写
        
        Args:
            name: 材料名称
            
        Returns:
            str: 规范化后的名称
            
        Examples:
            >>> MaterialResolver.normalize_material_name("《信息披露申请书》")
            'xinxipilushengqingshu'
            
            >>> MaterialResolver.normalize_material_name("test.pdf")
            'test'
        """
        if not name:
            return ""
        
        # 转换为小写并去除空格
        normalized = name.lower().strip()
        
        # 去除书名号、引号等标点
        normalized = re.sub(r"[《》\"'\s]", "", normalized)
        
        # 去除文件扩展名
        normalized = re.sub(
            r"\.(pdf|docx|doc|txt|rtf|png|jpg|jpeg|bmp|tiff|webp)$", 
            "", 
            normalized
        )
        
        return normalized
    
    @staticmethod
    def build_material_lookup(files: List[Any]) -> Dict[str, str]:
        """
        构建材料名称到文件类型的映射表
        
        包含两部分映射：
        1. FILE_TYPE_LABELS 中的标准映射（文件类型标签 -> 文件类型值）
        2. 用户上传文件的映射（文件名 -> 文件类型值）
        
        Args:
            files: 文件列表（需包含file_type和file_name属性）
            
        Returns:
            Dict[str, str]: 映射表 {规范化的材料名称: file_type值}
            
        Examples:
            >>> files = [
            ...     FileInput(file_name="信息披露申请书.pdf", file_type=FileType.INFO_DISCLOSURE_APPLICATION)
            ... ]
            >>> lookup = MaterialResolver.build_material_lookup(files)
            >>> lookup['xinxipilushengqingshu']
            'info_disclosure_application'
        """
        lookup: Dict[str, str] = {}
        
        # 添加标准文件类型映射
        for file_type_enum, label in FILE_TYPE_LABELS.items():
            normalized_label = MaterialResolver.normalize_material_name(label)
            lookup[normalized_label] = file_type_enum.value
        
        # 添加用户上传文件的映射
        for file_input in files:
            # 获取file_type值
            file_type_value = (
                file_input.file_type.value 
                if isinstance(file_input.file_type, FileType) 
                else str(file_input.file_type)
            )
            
            # 使用file_type本身作为键
            lookup[file_type_value] = file_type_value
            
            # 使用规范化的文件名作为键
            normalized_name = MaterialResolver.normalize_material_name(
                file_input.file_name
            )
            lookup[normalized_name] = file_type_value
        
        logger.debug(f"构建材料查找表，共 {len(lookup)} 个映射")
        return lookup
    
    @staticmethod
    def get_file_label(file_type: Optional[str]) -> str:
        """
        根据文件类型获取展示名称
        
        Args:
            file_type: 文件类型值（如 "info_disclosure_application"）
            
        Returns:
            str: 文件类型的中文标签，未知时返回原值或"未知材料"
            
        Examples:
            >>> MaterialResolver.get_file_label("info_disclosure_application")
            '信息披露申请书'
            
            >>> MaterialResolver.get_file_label(None)
            '未知材料'
        """
        if not file_type:
            return "未知材料"
        
        try:
            enum_value = FileType(file_type)
            return FILE_TYPE_LABELS.get(enum_value, file_type)
        except ValueError:
            return file_type
    
    @staticmethod
    def resolve_file_type(
        material_name: Optional[str],
        material_lookup: Dict[str, str],
        parsed_files: Dict[str, Any]
    ) -> Optional[str]:
        """
        根据材料名称解析对应的文件类型
        
        解析策略：
        1. 规范化材料名称
        2. 在材料查找表中查找
        3. 如果找到，返回对应的file_type值
        
        Args:
            material_name: 材料名称（如 "《信息披露申请书》"）
            material_lookup: 材料查找表（由build_material_lookup生成）
            parsed_files: 已解析文件字典（用于验证文件类型是否存在）
            
        Returns:
            Optional[str]: 文件类型值，未找到返回None
            
        Examples:
            >>> resolve_file_type(
            ...     "《信息披露申请书》",
            ...     {"xinxipilushengqingshu": "info_disclosure_application"},
            ...     {"info_disclosure_application": {...}}
            ... )
            'info_disclosure_application'
        """
        if not material_name:
            return None
        
        # 规范化材料名称
        normalized = MaterialResolver.normalize_material_name(material_name)
        
        # 在查找表中查找
        file_type = material_lookup.get(normalized)
        
        if file_type:
            # 验证该文件类型是否在已解析文件中
            if file_type in parsed_files:
                logger.debug(f"材料名称 '{material_name}' 解析为文件类型 '{file_type}'")
                return file_type
            else:
                logger.warning(
                    f"材料名称 '{material_name}' 解析为 '{file_type}'，"
                    f"但该文件类型不在已解析文件中"
                )
                return None
        
        logger.warning(f"无法解析材料名称: {material_name}")
        return None
    
    @staticmethod
    def get_display_name(
        material_name: Optional[str],
        file_type: Optional[str],
        file_data: Optional[Dict[str, Any]]
    ) -> str:
        """
        获取用于展示的材料名称
        
        优先级：
        1. material_name（用户指定的材料名称）
        2. file_data中的file_label
        3. 从file_type获取标准标签
        4. 默认值"未知材料"
        
        Args:
            material_name: 材料名称（可选）
            file_type: 文件类型值（可选）
            file_data: 文件数据（可选，包含file_label等信息）
            
        Returns:
            str: 展示名称
            
        Examples:
            >>> get_display_name("申请书", None, None)
            '申请书'
            
            >>> get_display_name(None, "info_disclosure_application", None)
            '信息披露申请书'
        """
        # 优先使用用户指定的材料名称
        if material_name:
            return material_name
        
        # 尝试从file_data获取file_label
        if file_data:
            file_label = file_data.get("file_label")
            if file_label:
                return file_label
        
        # 从file_type获取标准标签
        if file_type:
            return MaterialResolver.get_file_label(file_type)
        
        # 默认值
        return "未知材料"

