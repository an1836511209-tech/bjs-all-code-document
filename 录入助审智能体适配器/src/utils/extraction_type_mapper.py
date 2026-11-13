"""
提取类型映射工具

将extraction_type映射到BusinessType，用于自动查找规则配置
"""

from typing import Optional
from loguru import logger

from src.schemas.rule_config import BusinessType


# extraction_type 到 BusinessType 的映射表
EXTRACTION_TYPE_TO_BUSINESS_TYPE = {business_type.value: business_type for business_type in BusinessType}


def map_extraction_type_to_business_type(extraction_type: str) -> Optional[BusinessType]:
    """
    将extraction_type映射到BusinessType
    
    Args:
        extraction_type: 提取类型字符串
        
    Returns:
        Optional[BusinessType]: 对应的业务类型，如果无法映射返回None
        
    Examples:
        >>> map_extraction_type_to_business_type("有纸大宗实物")
        BusinessType.BULK_PHYSICAL_PAPER

        >>> map_extraction_type_to_business_type("无纸大宗实物")
        BusinessType.BULK_PHYSICAL_PAPERLESS
        
        >>> map_extraction_type_to_business_type("有纸小宗实物")
        BusinessType.SMALL_PHYSICAL_PAPER
        
        >>> map_extraction_type_to_business_type("无纸小宗实物")
        BusinessType.SMALL_PHYSICAL_PAPERLESS
    """
    business_type = EXTRACTION_TYPE_TO_BUSINESS_TYPE.get(extraction_type)
    
    if business_type:
        logger.debug(f"映射 extraction_type '{extraction_type}' -> business_type '{business_type.value}'")
        return business_type
    else:
        logger.warning(f"无法映射 extraction_type: {extraction_type}")
        return None


def get_available_extraction_types() -> list[str]:
    """
    获取所有支持的extraction_type
    
    Returns:
        list[str]: 支持的extraction_type列表
    """
    return list(EXTRACTION_TYPE_TO_BUSINESS_TYPE.keys())

