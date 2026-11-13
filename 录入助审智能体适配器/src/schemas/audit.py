"""
字段审核API数据模型

定义字段审核接口的请求和响应模型
"""

from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field
from enum import Enum

from src.schemas.file import FileType
from src.schemas.base import ApiResponse
from src.schemas.extraction import FieldExtractionResult


class AuditFileInput(BaseModel):
    """审核请求的文件输入"""
    file_url: str = Field(..., description="文件URL（本地路径或远程URL）")
    file_name: str = Field(..., description="文件名称")
    file_type: str = Field(..., description="文件类型（可以是系统FileType枚举值或中台类型代码）")
    file_content_hash: Optional[str] = Field(None, description="文件内容哈希（MD5，用于唯一标识文件内容）")
    file_size: Optional[int] = Field(None, description="文件大小（字节）")


class ConfirmedField(BaseModel):
    """用户确认的字段"""
    field_name: str = Field(..., description="字段名称")
    field_value: Any = Field(..., description="字段值（支持任意JSON类型：字符串、数字、对象、数组等）")
    field_type: str = Field(default="text", description="字段类型（可选，默认text）", example="text")


class AuditRequest(BaseModel):
    """字段审核请求"""
    task_id: Optional[str] = Field(None, description="任务ID（可选）")
    audit_type: str = Field(..., description="业务类型", example="有纸大宗实物")
    confirmed_fields: List[ConfirmedField] = Field(..., description="用户确认后的字段列表", min_items=1)
    files: List[AuditFileInput] = Field(default_factory=list, description="审核参考文件列表（可选，某些审核类型可能不需要文件）")
    rule_config_id: Optional[str] = Field(None, description="规则配置ID（可选）")
    timeout: Optional[int] = Field(default=1000, description="超时时间（毫秒）", ge=1000)
    request_id: Optional[str] = Field(None, description="请求唯一标识")
    trigger_type: Optional[str] = Field(None, description="触发类型（可选）")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "audit_type": "有纸大宗实物",
                    "confirmed_fields": [
                        {
                            "field_name": "坐落位置",
                            "field_value": "北京市朝阳区建国路1号",
                            "field_type": "text"
                        },
                        {
                            "field_name": "房屋面积",
                            "field_value": 150.5,
                            "field_type": "number"
                        }
                    ],
                    "files": [
                        {
                            "file_url": "https://example.com/files/certificate.pdf",
                            "file_name": "房屋所有权证.pdf",
                            "file_type": "property_certificate"
                        }
                    ],
                    "rule_config_id": "rule_dzswv10",
                    "timeout": 1000
                },
                {
                    "audit_type": "有纸大宗实物",
                    "confirmed_fields": [
                        {
                            "field_name": "房屋面积",
                            "field_value": 150.5,
                            "field_type": "number"
                        },
                        {
                            "field_name": "土地面积",
                            "field_value": 120.0,
                            "field_type": "number"
                        }
                    ],
                    "files": [],
                    "request_id": "req_20251209100001"
                }
            ]
        }
    }


class AuditStatus(str, Enum):
    """审核状态"""
    COMPLETED = "completed"      # 审核完成
    PROCESSING = "processing"    # 处理中
    FAILED = "failed"            # 审核失败


class AuditResult(str, Enum):
    """审核结果"""
    PASSED = "passed"            # 通过
    FAILED = "failed"            # 不通过
    PENDING = "pending"          # 待确认
    MANUAL_REVIEW = "manual_review"  # 需人工审核


class AuditType(str, Enum):
    """审核类型"""
    FIELD_AUDIT = "字段审核"      # 字段审核
    FILE_AUDIT = "文件审核"       # 文件审核
    MANUAL_REVIEW = "人工审核"    # 人工审核


class RelatedFieldInfo(BaseModel):
    """关联字段信息（包含用户确认值和提取数据）"""
    field_name: str = Field(..., description="字段名称")
    field_value: Any = Field(..., description="用户确认的字段值（支持任意JSON类型：字符串、数字、对象、数组等）")
    field_type: str = Field(..., description="字段类型", example="text")
    extraction_data: Optional[FieldExtractionResult] = Field(None, description="提取任务的数据（与提取接口结构一致）")


class UploadedFileInfo(BaseModel):
    """已上传文件信息（用于文件审核）"""
    file_name: str = Field(..., description="文件名称")
    file_url: str = Field(..., description="文件URL")
    file_type: str = Field(..., description="文件类型枚举值")


class AuditPointDetail(BaseModel):
    """单个审核要点的详细结果（用于文件审核）"""
    point_index: int = Field(..., description="审核要点索引（从1开始）")
    point_content: str = Field(..., description="审核要点内容")
    audit_result: Optional[AuditResult] = Field(None, description="该要点的审核结果（文件未上传时为None）")
    audit_explanation: str = Field(..., description="该要点的审核说明")
    confidence: float = Field(..., description="该要点的置信度（0-1）", ge=0, le=1)


class AuditRuleResult(BaseModel):
    """单条审核规则的完整结果（按规则维度组织）"""
    audit_id: str = Field(..., description="审核ID")
    audit_rule_id: Optional[str] = Field(None, description="审核规则ID（来自规则配置）")
    audit_rule_name: str = Field(..., description="审核规则名称")
    audit_type: AuditType = Field(..., description="审核类型：字段审核、文件审核或人工审核")
    audit_result: Optional[AuditResult] = Field(None, description="审核结果（文件审核时为None，查看audit_point_details）")
    audit_status: AuditStatus = Field(..., description="审核状态")
    audit_explanation: Optional[str] = Field(None, description="审核说明（字段审核时有值，文件审核时为None）")
    confidence: Optional[float] = Field(None, description="审核置信度（0-1，文件审核时为None）", ge=0, le=1)
    
    # 字段审核专用字段
    related_fields: List[RelatedFieldInfo] = Field(default_factory=list, description="关联的字段列表（仅字段审核和人工审核有值）")
    
    # 文件审核专用字段
    file_type: Optional[str] = Field(None, description="文件类型（仅文件审核有值，来自规则配置的material_name）")
    audit_points: Optional[str] = Field(None, description="审核要点（仅文件审核有值，来自规则配置的audit_content）")
    uploaded_files: Optional[List[UploadedFileInfo]] = Field(None, description="已上传的相关文件列表（仅文件审核有值）")
    audit_details: Optional[str] = Field(None, description="审核详情（仅文件审核有值，已废弃，使用audit_point_details）")
    audit_point_details: Optional[List[AuditPointDetail]] = Field(None, description="审核要点详情列表（仅文件审核有值，每个要点独立审核结果）")
    
    # 审核规则信息
    audit_rule: Optional[Dict[str, Any]] = Field(None, description="对应的审核规则信息")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "audit_id": "audit_20251118100001",
                "audit_rule_id": "rule_001",
                "audit_rule_name": "坐落位置一致性校验",
                "audit_type": "字段审核",
                "audit_result": "passed",
                "audit_status": "completed",
                "audit_explanation": None,
                "confidence": 0.95,
                "related_fields": [
                    {
                        "field_name": "坐落位置",
                        "field_value": "北京市朝阳区建国路1号",
                        "field_type": "text",
                        "extraction_data": {
                            "field_id": "field_001",
                            "field_name": "坐落位置",
                            "field_type": "text",
                            "values": [],
                            "error_message": None
                        }
                    }
                ],
                "file_type": None,
                "audit_points": None,
                "uploaded_files": None,
                "audit_details": None
            }
        }
    }


class AuditSummary(BaseModel):
    """审核结果汇总"""
    total: int = Field(..., description="总数")
    passed: int = Field(..., description="通过数量")
    failed: int = Field(..., description="不通过数量")
    pending: int = Field(..., description="待确认数量")
    manual_review: int = Field(default=0, description="需人工审核数量")


class AuditData(BaseModel):
    """审核响应数据"""
    request_id: Optional[str] = Field(None, description="请求ID")
    task_id: Optional[str] = Field(None, description="任务ID")
    status: str = Field(..., description="整体状态", example="completed")
    audit_type: str = Field(..., description="业务类型")
    confirmed_fields: List[ConfirmedField] = Field(..., description="用户确认的字段列表（请求入参）")
    audit_results: List[AuditRuleResult] = Field(..., description="审核结果列表（包含agent审核结果和人工审核项）")
    summary: AuditSummary = Field(..., description="审核结果汇总")
    processing_time_ms: int = Field(..., description="处理时间（毫秒）")
    trigger_type: Optional[str] = Field(None, description="触发类型（请求入参）")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "request_id": "req_20251118100003",
                "task_id": "task_audit_123",
                "status": "completed",
                "audit_type": "有纸大宗实物",
                "confirmed_fields": [
                    {
                        "field_name": "坐落位置",
                        "field_value": "北京市朝阳区建国路1号",
                        "field_type": "text"
                    }
                ],
                "audit_results": [
                    {
                        "audit_id": "audit_001",
                        "audit_rule_id": "rule_001",
                        "audit_rule_name": "坐落位置一致性校验",
                        "audit_type": "字段审核",
                        "audit_result": "passed",
                        "audit_status": "completed",
                        "audit_explanation": None,
                        "confidence": 0.95,
                        "related_fields": [
                            {
                                "field_name": "坐落位置",
                                "field_value": "北京市朝阳区建国路1号",
                                "field_type": "text",
                                "extraction_data": None
                            }
                        ]
                    }
                ],
                "summary": {
                    "total": 3,
                    "passed": 2,
                    "failed": 0,
                    "pending": 0,
                    "manual_review": 1
                },
                "processing_time_ms": 3500
            }
        }
    }


class AuditResponse(ApiResponse):
    """审核响应"""
    data: AuditData


