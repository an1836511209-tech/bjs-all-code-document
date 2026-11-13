"""
级联提取配置常量

定义所有级联提取场景的配置，包括链式级联和选择性级联。
支持按业务类型（audit_type/extraction_type）分组获取配置。
"""

from src.schemas.cascade_config import (
    ChainCascadeConfig,
    ConditionalCascadeConfig,
    CascadeConfig
)
from typing import List, Dict


# ========== 链式级联配置 ==========

# 省市区级联配置组
REGION_CASCADE_CONFIGS: List[ChainCascadeConfig] = [
    ChainCascadeConfig(
        field_names=["BDSZDS", "BDSZDSHI", "BDSZDQX"],
        cascade_name="标的所在地"
    ),
    ChainCascadeConfig(
        field_names=["PROVINCE", "CITY", "QX"],
        cascade_name="转让方住所"
    ),
]


# ========== 选择性级联配置 ==========

# 资产类别级联配置
ASSET_TYPE_CASCADE_CONFIG = ConditionalCascadeConfig(
    master_field="ZCLB",
    field_mapping={
        "房屋建筑物": "FWJZW",
        "土地": "TD",
        "机械设备": "JXSB",
        "存货": "CH",
        "交通运输工具": "JTYSGJ",
        "在建工程": "ZJGC",
        "其他": "QT",
        "技术类无形资产": "JSLWXZC",
        "债权": "ZQ"
    },
    cascade_name="资产类别级联"
)

# 转让方类型级联配置
TRANSFEROR_TYPE_CASCADE_CONFIG = ConditionalCascadeConfig(
    master_field="ZRFLX",
    field_mapping={
        "自然人": ["ZJLX", "ZJHM", "ZCD"],
        "法人或其他经济组织": [
            "ZCD", "FDDBR", "ZCZB",
            "ZCZBBZ", "TYSHXYDM", "NBJCWJLX",
            "PZDWMC", "PZRQ", "PZLX", "PZWH"
        ]
    },
    cascade_name="转让方类型级联"
)

# 交易方式级联配置
TRANSACTION_METHOD_CASCADE_CONFIG = ConditionalCascadeConfig(
    master_field="ZRFS",
    field_mapping={
        "集中报价": "JJFS",
        "动态报价": [
            "ZYBJQ", "DTBJJSSJ", "QPJBJ", "XSBJZQ",
            "JJFD", "JJCCMC", "QDGZR"
        ],
        "拍卖转让": ["PMKSRQ", "PMJSRQ"]
    },
    cascade_name="交易方式级联"
)

# 未征集到意向受让方选项级联配置
# 注意：两个不同的值都映射到同一个子字段（多对一）
INTENTION_RECEIVER_CASCADE_CONFIG = ConditionalCascadeConfig(
    master_field="WYXSRF",
    field_mapping={
        "按约定工作日为周期延期延长信息披露": "YDGZR",
        "按约定工作日为周期延期延长信息披露，直至征集到意向受让方": "YDGZR"
    },
    cascade_name="未征集到意向受让方级联"
)

# 信息披露起始时间选项级联配置
INFO_DISCLOSURE_TIME_CASCADE_CONFIG = ConditionalCascadeConfig(
    master_field="XXPLQSSJXX",
    field_mapping={
        "指定信息披露起始时间": ["PLKSRQ", "PLKSSJ"]
    },
    cascade_name="信息披露起始时间级联"
)

# 受让方是否需人工审核级联配置（大宗实物）
MANUAL_AUDIT_CASCADE_CONFIG = ConditionalCascadeConfig(
    master_field="SFXRGSH",
    field_mapping={
        "是": "SRFRGSHYY"
    },
    cascade_name="受让方人工审核级联"
)


# ========== 小宗实物选择性级联配置 ==========

SMALL_MANUAL_AUDIT_CASCADE_CONFIG = ConditionalCascadeConfig(
    master_field="SRFSFRGSH",
    field_mapping={
        "是": "SRFRGSHYY"
    },
    cascade_name="受让方人工审核级联"
)

SMALL_PRICING_METHOD_CASCADE_CONFIG = ConditionalCascadeConfig(
    master_field="ZRDJQDYJ",
    field_mapping={
        "市场询价": "ZRDJSCXJFS"
    },
    cascade_name="转让底价确定依据级联"
)

SMALL_DEPOSIT_METHOD_CASCADE_CONFIG = ConditionalCascadeConfig(
    master_field="BZJ_JNFS",
    field_mapping={
        "单项目保证金": "BZJJNJZSJ"
    },
    cascade_name="保证金缴纳方式级联"
)


# ========== 所有级联配置 ==========

# 汇总所有级联配置，用于统一识别和处理
ALL_CASCADE_CONFIGS: List[CascadeConfig] = [
    *REGION_CASCADE_CONFIGS,
    ASSET_TYPE_CASCADE_CONFIG,
    TRANSFEROR_TYPE_CASCADE_CONFIG,
    TRANSACTION_METHOD_CASCADE_CONFIG,
    INTENTION_RECEIVER_CASCADE_CONFIG,
    INFO_DISCLOSURE_TIME_CASCADE_CONFIG,
    MANUAL_AUDIT_CASCADE_CONFIG,
    SMALL_MANUAL_AUDIT_CASCADE_CONFIG,
    SMALL_PRICING_METHOD_CASCADE_CONFIG,
    SMALL_DEPOSIT_METHOD_CASCADE_CONFIG
]


# ========== 按业务类型分组的选择性级联配置 ==========

# 大宗实物选择性级联配置（有纸大宗实物、无纸大宗实物）
BULK_CONDITIONAL_CASCADE_CONFIGS: List[ConditionalCascadeConfig] = [
    ASSET_TYPE_CASCADE_CONFIG,
    TRANSFEROR_TYPE_CASCADE_CONFIG,
    TRANSACTION_METHOD_CASCADE_CONFIG,
    INTENTION_RECEIVER_CASCADE_CONFIG,
    INFO_DISCLOSURE_TIME_CASCADE_CONFIG,
    MANUAL_AUDIT_CASCADE_CONFIG,
]

# 小宗实物选择性级联配置（有纸小宗实物、无纸小宗实物）
SMALL_CONDITIONAL_CASCADE_CONFIGS: List[ConditionalCascadeConfig] = [
    SMALL_MANUAL_AUDIT_CASCADE_CONFIG,
    SMALL_PRICING_METHOD_CASCADE_CONFIG,
    SMALL_DEPOSIT_METHOD_CASCADE_CONFIG
]

# 按业务类型（audit_type/extraction_type）映射选择性级联配置
CASCADE_CONFIGS_BY_AUDIT_TYPE: Dict[str, List[ConditionalCascadeConfig]] = {
    "有纸大宗实物": BULK_CONDITIONAL_CASCADE_CONFIGS,
    "无纸大宗实物": BULK_CONDITIONAL_CASCADE_CONFIGS,
    "有纸小宗实物": SMALL_CONDITIONAL_CASCADE_CONFIGS,
    "无纸小宗实物": SMALL_CONDITIONAL_CASCADE_CONFIGS,
}


def get_conditional_cascade_configs(audit_type: str) -> List[ConditionalCascadeConfig]:
    """
    根据业务类型获取对应的选择性级联配置
    
    Args:
        audit_type: 业务类型（如"有纸大宗实物"、"无纸大宗实物"等）
        
    Returns:
        List[ConditionalCascadeConfig]: 对应的选择性级联配置列表，
            如果业务类型未配置则返回空列表
    """
    return CASCADE_CONFIGS_BY_AUDIT_TYPE.get(audit_type, [])

