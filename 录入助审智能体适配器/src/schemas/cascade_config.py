"""
级联配置数据结构

定义不同类型的级联提取配置，用于指导级联字段的提取逻辑。
"""

from enum import Enum
from typing import List, Dict, Union
from pydantic import BaseModel, Field


class CascadeType(str, Enum):
    """级联类型"""
    CHAIN = "chain"          # 链式级联（如省市区）
    CONDITIONAL = "conditional"  # 选择性级联（如资产类别）


class ChainCascadeConfig(BaseModel):
    """
    链式级联配置
    
    用于处理有依赖关系的级联字段，每一级的提取结果会影响下一级的提取逻辑。
    例如：省份 → 城市 → 区县
    """
    cascade_type: CascadeType = CascadeType.CHAIN
    field_names: List[str] = Field(
        description="按顺序排列的字段名列表，如 ['BDSZDS', 'BDSZDSHI', 'BDSZDQX']"
    )
    cascade_name: str = Field(
        description="级联组名称，用于日志和调试，如 '标的所在地'"
    )


class ConditionalCascadeConfig(BaseModel):
    """
    选择性级联配置
    
    用于处理主字段值决定子字段提取的场景。
    支持一对一、一对多、多对一映射。
    
    示例：
    - 一对一：资产类别="其他" → QT字段
    - 一对多：交易方式="动态报价" → [ZYBJQ, DTBJJSSJ, QPJBJ, ...]
    - 多对一：WYXSRF的两个不同值 → 同一个YDGZR字段
    """
    cascade_type: CascadeType = CascadeType.CONDITIONAL
    master_field: str = Field(
        description="主字段名，其值决定要提取哪些子字段，如 'ZCLB'"
    )
    field_mapping: Dict[str, Union[str, List[str]]] = Field(
        description="""主字段值到子字段名的映射
        
        支持两种格式：
        - 一对一：{"值": "字段名"}
        - 一对多：{"值": ["字段1", "字段2", "字段3"]}
        
        示例：
        {
            "自然人": ["ZJLX", "ZJHM", "ZCD"],
            "法人或其他经济组织": ["ZCD", "YYZZSFCQ", "FDDBR", ...],
            "集中报价": "JJFS"
        }
        
        注意：多个值可以映射到同一个字段（多对一），集合会自动去重
        """
    )
    cascade_name: str = Field(
        description="级联组名称，用于日志和调试，如 '资产类别级联'"
    )


# 级联配置联合类型
CascadeConfig = Union[ChainCascadeConfig, ConditionalCascadeConfig]

