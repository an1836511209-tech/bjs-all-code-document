"""
规则配置数据模型

定义提取规则和审核规则的数据结构
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field, HttpUrl, validator


class BusinessType(str, Enum):
    """业务类型枚举"""
    BULK_PHYSICAL_PAPER = "有纸大宗实物"
    BULK_PHYSICAL_PAPERLESS = "无纸大宗实物"
    SMALL_PHYSICAL_PAPER = "有纸小宗实物"
    SMALL_PHYSICAL_PAPERLESS = "无纸小宗实物"
    PROPERTY_TRANSFER_PRE = "产权转让-预披露"
    PROPERTY_TRANSFER_FORMAL = "产权转让-正式披露"
    CAPITAL_INCREASE_PRE = "企业增资-预披露"
    CAPITAL_INCREASE_FORMAL = "企业增资-正式披露"


class FieldType(str, Enum):
    """字段类型枚举"""
    TEXT = "text"  # 文本
    SINGLE_CHOICE = "single_choice"  # 单选
    MULTIPLE_CHOICE = "multiple_choice"  # 多选


class HttpMethod(str, Enum):
    """HTTP请求方法枚举"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"


class AuditResult(str, Enum):
    """审核结果枚举"""
    PASS = "通过"
    FAIL = "不通过"
    PENDING = "待确认"


class AuditType(str, Enum):
    """审核类型枚举"""
    FIELD_AUDIT = "字段审核"
    FILE_AUDIT = "文件审核"


class MappingType(str, Enum):
    """数据映射类型枚举"""
    AUTO = "auto"  # 自动映射：从提取规则自动获取数据源
    MANUAL = "manual"  # 自定义映射：手动配置数据源


# ===========================
# 提取规则相关模型
# ===========================

class ApiConfig(BaseModel):
    """接口配置模型"""
    url: str = Field(..., description="接口URL地址")
    method: HttpMethod = Field(default=HttpMethod.GET, description="HTTP请求方法")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="请求参数")
    headers: Optional[Dict[str, str]] = Field(default_factory=dict, description="请求头")
    timeout: int = Field(default=30, description="超时时间（秒）", ge=1, le=300)
    description: Optional[str] = Field(None, description="接口说明")

    class Config:
        json_schema_extra = {
            "example": {
                "url": "http://api.example.com/dict/location",
                "method": "GET",
                "params": {"type": "location"},
                "headers": {"Authorization": "Bearer token"},
                "timeout": 30,
                "description": "获取地理位置字典值"
            }
        }


class DisclosureField(BaseModel):
    """中台披露接口的字段映射。"""

    code: str
    label: str
    platform_type: str
    logic: str
    options: Dict[str, str] = Field(default_factory=dict)
    dictionary: Optional[str] = None
    multiple: bool = False
    missing_flag: Optional[str] = None
    approval_field: Optional[str] = None
    cover_label: Optional[str] = None
    unconfirmed_options: List[str] = Field(default_factory=list)


class ExtractionRule(BaseModel):
    """提取规则模型"""
    id: Optional[str] = Field(None, description="规则ID（自动生成）")
    field_name: str = Field(..., description="字段名称", min_length=1, max_length=100)
    field_type: FieldType = Field(default=FieldType.TEXT, description="字段类型")
    reference_materials: List[str] = Field(
        ..., 
        description="录入参考材料列表",
        min_items=1
    )
    extraction_logic: str = Field(
        ..., 
        description="提取逻辑（自然语言描述）",
        min_length=1,
        max_length=20000
    )
    api_config: Optional[ApiConfig] = Field(
        None, 
        description="接口配置（可选，用于获取字典值等参考数据）"
    )
    choices: Optional[List[str]] = Field(
        None,
        description="选项列表（当field_type为single_choice或multiple_choice时使用）"
    )
    enabled: bool = Field(default=True, description="是否启用")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")
    notes: Optional[str] = Field(None, description="备注信息", max_length=500)

    platform_interface: Optional[str] = None
    disclosure_rows: bool = False
    disclosure_row_keys: List[str] = Field(default_factory=list)
    disclosure_fields: List[DisclosureField] = Field(default_factory=list)

    @validator('choices')
    def validate_choices(cls, v, values):
        """验证选项列表"""
        field_type = values.get('field_type')
        if field_type in [FieldType.SINGLE_CHOICE, FieldType.MULTIPLE_CHOICE]:
            if not v or len(v) == 0:
                raise ValueError(f"字段类型为{field_type.value}时，必须提供choices选项")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "field_name": "坐落位置",
                "field_type": "text",
                "reference_materials": ["《信息披露申请书》"],
                "extraction_logic": "从《信息披露申请书》中提取坐落位置字段的值，按原文录入",
                "api_config": None,
                "enabled": True,
                "notes": "必填字段"
            }
        }


# ===========================
# 审核规则相关模型
# ===========================

class AuditDataSource(BaseModel):
    """审核数据源配置"""
    material_name: str = Field(..., description="材料名称，如《信息披露申请书》", max_length=100)
    field_name: Optional[str] = Field(
        None, 
        description="字段名称。如果为None、空字符串或'全文'，则表示获取整个材料内容",
        max_length=100
    )
    description: Optional[str] = Field(None, description="数据源说明", max_length=200)
    
    class Config:
        json_schema_extra = {
            "example": {
                "material_name": "《信息披露申请书》",
                "field_name": "转让方名称",
                "description": "从信息披露申请书中提取转让方名称"
            }
        }


class AuditRule(BaseModel):
    """审核规则模型"""
    id: Optional[str] = Field(None, description="规则ID（自动生成）")
    audit_type: AuditType = Field(..., description="审核类型：字段审核或文件审核")
    field_name: str = Field(..., description="审核字段/文件名称", min_length=1, max_length=100)
    
    # 数据映射配置（仅字段审核时使用）
    mapping_type: Optional[MappingType] = Field(
        None,
        description="数据映射类型（仅字段审核时有效）：auto-自动映射，manual-自定义映射。文件审核时此字段无意义"
    )
    source_field_name: Optional[str] = Field(
        None,
        description="源字段名称（字段审核+自动映射时必填）：指定要引用的提取规则字段名",
        max_length=100
    )
    include_user_input: bool = Field(
        default=True,
        description="是否包含用户表单数据（字段审核时有效）：系统会根据field_name自动匹配用户填写的数据"
    )
    
    # 审核数据源（自定义映射或文件审核时使用）
    audit_data_sources: Optional[List[AuditDataSource]] = Field(
        None,
        description="审核数据源列表（字段审核+自定义映射 或 文件审核时必填）",
        min_items=1
    )
    
    # 审核规则配置
    audit_content: str = Field(
        ..., 
        description="审核内容描述",
        min_length=1,
        max_length=20000
    )
    auto_process_rules: str = Field(
        ...,
        description="自动审核处理规则（描述不同情况的处理方式）",
        min_length=1,
        max_length=20000
    )
    
    # 简单对比模式（用于字段一致性校验）
    use_simple_comparison: bool = Field(
        default=False,
        description="是否使用简单对比模式：启用后直接进行字符串对比，不调用LLM审核agent。适用于简单的字段一致性校验"
    )
    
    # 材料缺失时自动通过（用于无纸项目等场景）
    auto_pass_when_missing: bool = Field(
        default=False,
        description="当参考材料缺失时是否自动通过（适用于无纸项目等场景）"
    )
    
    # 主要关联文件类型（仅文件审核时使用）
    primary_file_type: Optional[str] = Field(
        None,
        description="主要关联的文件类型枚举值（仅文件审核时使用），用于精确指定返回哪个文件。对应 FileType 枚举值"
    )
    
    # 元数据
    enabled: bool = Field(default=True, description="是否启用")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")
    notes: Optional[str] = Field(None, description="备注信息", max_length=500)
    
    @validator('mapping_type', always=True)
    def validate_mapping_type(cls, v, values):
        """验证映射类型"""
        audit_type = values.get('audit_type')
        if audit_type == AuditType.FIELD_AUDIT:
            # 字段审核时，如果没有指定mapping_type，默认为自动映射
            return v if v is not None else MappingType.AUTO
        # 文件审核时，mapping_type无意义，设为None
        return None
    
    @validator('source_field_name')
    def validate_source_field_name(cls, v, values):
        """验证源字段名称"""
        audit_type = values.get('audit_type')
        mapping_type = values.get('mapping_type')
        
        if audit_type == AuditType.FIELD_AUDIT and mapping_type == MappingType.AUTO:
            if not v:
                raise ValueError("字段审核+自动映射时，必须指定source_field_name")
        return v
    
    @validator('audit_data_sources')
    def validate_audit_data_sources(cls, v, values):
        """验证审核数据源"""
        audit_type = values.get('audit_type')
        mapping_type = values.get('mapping_type')
        
        # 文件审核必须提供audit_data_sources
        if audit_type == AuditType.FILE_AUDIT:
            if not v or len(v) == 0:
                raise ValueError("文件审核时，必须提供audit_data_sources")
        
        # 字段审核+自定义映射也必须提供audit_data_sources
        if audit_type == AuditType.FIELD_AUDIT and mapping_type == MappingType.MANUAL:
            if not v or len(v) == 0:
                raise ValueError("字段审核+自定义映射时，必须提供audit_data_sources")
        
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "audit_type": "字段审核",
                "field_name": "转让方名称",
                "mapping_type": "auto",
                "source_field_name": "转让方名称",
                "include_user_input": True,
                "audit_content": "转让方类型需与转让方名称体现的类型一致；且与附件中的转让方证件类型一致",
                "auto_process_rules": "若无法成功提取对应字段中的任一数值或无法做出判断，则审核结果为待确认。若可正常提取对应全部字段值，且符合上述审核要求，则审核通过。若可正常提取对应全部字段值，但不符合上述审核要求，则审核不通过。",
                "enabled": True,
                "notes": "自动映射示例"
            }
        }


# ===========================
# 规则配置集合模型
# ===========================

class RuleConfig(BaseModel):
    """规则配置集合模型"""
    id: Optional[str] = Field(None, description="配置ID（自动生成）")
    name: str = Field(..., description="配置名称", min_length=1, max_length=100)
    business_type: BusinessType = Field(..., description="业务类型")
    extraction_rules: List[ExtractionRule] = Field(
        default_factory=list,
        description="提取规则列表"
    )
    audit_rules: List[AuditRule] = Field(
        default_factory=list,
        description="审核规则列表"
    )
    description: Optional[str] = Field(None, description="配置描述", max_length=500)
    version: str = Field(default="1.0.0", description="配置版本号")
    enabled: bool = Field(default=True, description="是否启用")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "大宗实物-房产交易规则",
                "business_type": "大宗实物",
                "extraction_rules": [],
                "audit_rules": [],
                "description": "大宗实物房产交易的提取和审核规则配置",
                "version": "1.0.0",
                "enabled": True
            }
        }


# ===========================
# API请求/响应模型
# ===========================

class RuleConfigCreate(BaseModel):
    """创建规则配置请求模型"""
    name: str = Field(..., description="配置名称", min_length=1, max_length=100)
    business_type: BusinessType = Field(..., description="业务类型")
    description: Optional[str] = Field(None, description="配置描述", max_length=500)


class RuleConfigUpdate(BaseModel):
    """更新规则配置请求模型"""
    name: Optional[str] = Field(None, description="配置名称", min_length=1, max_length=100)
    description: Optional[str] = Field(None, description="配置描述", max_length=500)
    enabled: Optional[bool] = Field(None, description="是否启用")


class ExtractionRuleCreate(BaseModel):
    """创建提取规则请求模型"""
    field_name: str = Field(..., description="字段名称", min_length=1, max_length=100)
    field_type: FieldType = Field(default=FieldType.TEXT, description="字段类型")
    reference_materials: List[str] = Field(..., description="录入参考材料列表", min_items=1)
    extraction_logic: str = Field(..., description="提取逻辑", min_length=1, max_length=20000)
    api_config: Optional[ApiConfig] = Field(None, description="接口配置")
    choices: Optional[List[str]] = Field(None, description="选项列表")
    notes: Optional[str] = Field(None, description="备注信息", max_length=500)


class ExtractionRuleUpdate(BaseModel):
    """更新提取规则请求模型"""
    field_name: Optional[str] = Field(None, description="字段名称", min_length=1, max_length=100)
    field_type: Optional[FieldType] = Field(None, description="字段类型")
    reference_materials: Optional[List[str]] = Field(None, description="录入参考材料列表", min_items=1)
    extraction_logic: Optional[str] = Field(None, description="提取逻辑", min_length=1, max_length=20000)
    api_config: Optional[ApiConfig] = Field(None, description="接口配置")
    choices: Optional[List[str]] = Field(None, description="选项列表")
    enabled: Optional[bool] = Field(None, description="是否启用")
    notes: Optional[str] = Field(None, description="备注信息", max_length=500)


class AuditRuleCreate(BaseModel):
    """创建审核规则请求模型"""
    audit_type: AuditType = Field(default=AuditType.FIELD_AUDIT, description="审核类型")
    field_name: str = Field(..., description="审核字段/文件名称", min_length=1, max_length=100)
    
    # 字段审核配置
    mapping_type: Optional[MappingType] = Field(
        None,
        description="数据映射类型（仅字段审核时有效，默认为auto）"
    )
    source_field_name: Optional[str] = Field(
        None,
        description="源字段名称（字段审核+自动映射时必填）",
        max_length=100
    )
    include_user_input: bool = Field(
        default=True,
        description="是否包含用户表单数据"
    )
    
    # 审核数据源（自定义映射或文件审核时使用）
    audit_data_sources: Optional[List[AuditDataSource]] = Field(
        None,
        description="审核数据源列表（字段审核+自定义映射 或 文件审核时必填）",
        min_items=1
    )
    
    # 审核规则配置
    audit_content: str = Field(..., description="审核内容描述", min_length=1, max_length=20000)
    auto_process_rules: str = Field(..., description="自动审核处理规则", min_length=1, max_length=20000)
    use_simple_comparison: bool = Field(
        default=False,
        description="是否使用简单对比模式"
    )
    auto_pass_when_missing: bool = Field(
        default=False,
        description="当参考材料缺失时是否自动通过（适用于无纸项目等场景）"
    )
    primary_file_type: Optional[str] = Field(
        None,
        description="主要关联的文件类型枚举值（仅文件审核时使用），用于精确指定返回哪个文件"
    )
    notes: Optional[str] = Field(None, description="备注信息", max_length=500)
    
    @validator('mapping_type', always=True)
    def validate_mapping_type(cls, v, values):
        """验证映射类型"""
        audit_type = values.get('audit_type')
        if audit_type == AuditType.FIELD_AUDIT:
            return v if v is not None else MappingType.AUTO
        return None
    
    @validator('source_field_name')
    def validate_source_field_name(cls, v, values):
        """验证源字段名称"""
        audit_type = values.get('audit_type')
        mapping_type = values.get('mapping_type')
        
        if audit_type == AuditType.FIELD_AUDIT and mapping_type == MappingType.AUTO:
            if not v:
                raise ValueError("字段审核+自动映射时，必须指定source_field_name")
        return v
    
    @validator('audit_data_sources')
    def validate_audit_data_sources(cls, v, values):
        """验证审核数据源"""
        audit_type = values.get('audit_type')
        mapping_type = values.get('mapping_type')
        
        if audit_type == AuditType.FILE_AUDIT:
            if not v or len(v) == 0:
                raise ValueError("文件审核时，必须提供audit_data_sources")
        
        if audit_type == AuditType.FIELD_AUDIT and mapping_type == MappingType.MANUAL:
            if not v or len(v) == 0:
                raise ValueError("字段审核+自定义映射时，必须提供audit_data_sources")
        
        return v


class AuditRuleUpdate(BaseModel):
    """更新审核规则请求模型"""
    audit_type: Optional[AuditType] = Field(None, description="审核类型")
    field_name: Optional[str] = Field(None, description="审核字段/文件名称", min_length=1, max_length=100)
    
    # 字段审核配置
    mapping_type: Optional[MappingType] = Field(None, description="数据映射类型")
    source_field_name: Optional[str] = Field(None, description="源字段名称", max_length=100)
    include_user_input: Optional[bool] = Field(None, description="是否包含用户表单数据")
    
    # 审核数据源
    audit_data_sources: Optional[List[AuditDataSource]] = Field(None, description="审核数据源列表", min_items=1)
    
    # 审核规则配置
    audit_content: Optional[str] = Field(None, description="审核内容描述", min_length=1, max_length=20000)
    auto_process_rules: Optional[str] = Field(None, description="自动审核处理规则", min_length=1, max_length=20000)
    use_simple_comparison: Optional[bool] = Field(None, description="是否使用简单对比模式")
    auto_pass_when_missing: Optional[bool] = Field(None, description="当参考材料缺失时是否自动通过")
    primary_file_type: Optional[str] = Field(None, description="主要关联的文件类型枚举值（仅文件审核时使用）")
    
    # 元数据
    enabled: Optional[bool] = Field(None, description="是否启用")
    notes: Optional[str] = Field(None, description="备注信息", max_length=500)


class RuleConfigList(BaseModel):
    """规则配置列表响应模型"""
    total: int = Field(..., description="总数")
    items: List[RuleConfig] = Field(..., description="配置列表")


class RuleConfigResponse(BaseModel):
    """规则配置响应模型"""
    config: RuleConfig = Field(..., description="规则配置详情")

