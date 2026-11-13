"""
字段提取API数据模型

定义字段提取接口的请求和响应模型
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum

from src.schemas.file import FileType
from src.schemas.base import ApiResponse


class ExtractionFileInput(BaseModel):
    """提取请求的文件输入"""
    file_url: str = Field(..., description="文件URL（本地路径或远程URL）")
    file_name: str = Field(..., description="文件名称")
    file_type: FileType = Field(..., description="文件类型")
    file_content_hash: Optional[str] = Field(None, description="文件内容哈希（MD5，用于唯一标识文件内容）")
    file_size: Optional[int] = Field(None, description="文件大小（字节）")


class ExtractionRequest(BaseModel):
    """字段提取请求"""
    task_id: Optional[str] = Field(None, description="任务ID（可选，用于继续未完成的任务）")
    extraction_type: str = Field(..., description="提取类型（业务类型）", example="有纸大宗实物")
    files: List[ExtractionFileInput] = Field(default_factory=list, description="要提取的文件列表（通常需要至少1个文件，但审核场景可能为空）")
    rule_config_id: Optional[str] = Field(None, description="规则配置ID（可选，不传则使用extraction_type的默认规则）")
    timeout: Optional[int] = Field(default=1000, description="超时时间（毫秒）", ge=1000)
    request_id: Optional[str] = Field(None, description="请求唯一标识，用于幂等性控制")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "extraction_type": "有纸大宗实物",
                "files": [
                    {
                        "file_url": "https://example.com/files/application.pdf",
                        "file_name": "信息披露申请书.pdf",
                        "file_type": "info_disclosure_application",
                        "file_content_hash": "5d41402abc4b2a76b9719d911017c592",
                        "file_size": 1024000
                    },
                    {
                        "file_url": "https://example.com/files/certificate.pdf",
                        "file_name": "房屋所有权证.pdf",
                        "file_type": "property_certificate",
                        "file_content_hash": "7b8f3d4e9c1a2f5b6e0d8c7a4f3e2d1b",
                        "file_size": 2048000
                    }
                ],
                "rule_config_id": "rule_dzswv10",
                "timeout": 1000,
                "request_id": "req_20251022100002"
            }
        }
    }


class ExtractStatus(str, Enum):
    """单个来源的提取状态"""
    SUCCESS = "success"          # 提取成功
    FAILED = "failed"            # 提取失败（发生错误）


class FieldExtractionStatus(str, Enum):
    """字段提取状态（字段级别，综合多来源后的状态）"""
    SUCCESS = "success"          # 提取成功（有值且一致）
    PENDING = "pending"          # 待确认（无值或多来源值不一致）
    FAILED = "failed"            # 提取失败（发生错误）


class TaskExtractionStatus(str, Enum):
    """任务提取状态（整体任务级别）"""
    SUCCESS = "success"          # 所有字段都成功
    PARTIAL = "partial"          # 部分成功（有成功、有待确认或失败）
    PENDING = "pending"          # 所有字段都待确认
    FAILED = "failed"            # 所有字段都失败


# 为了向后兼容，保留 ExtractionStatus 别名（映射到 TaskExtractionStatus）
ExtractionStatus = TaskExtractionStatus


class RegionInfo(BaseModel):
    """单个高亮区域信息"""
    page_idx: int = Field(..., description="页面索引（从0开始）；Excel 时为 sheet 索引")
    bbox: List[float] = Field(..., description="边界框坐标 [x0, y0, x1, y1]")
    file_index: Optional[int] = Field(None, description="文件索引（多 Excel 文件时）")
    sheet_name: Optional[str] = Field(None, description="Sheet 名称（Excel）")
    cell_ref: Optional[str] = Field(None, description="单元格引用，如 Sheet1!B5（Excel）")


class SourceInfo(BaseModel):
    """详细溯源信息"""
    source_file_type: str = Field(..., description="来源文件类型")
    source_file_name: str = Field(..., description="来源文件名")
    source_field: str = Field(..., description="来源字段名")
    source_content: str = Field("", description="来源内容")
    preview_image_url: str = Field("", description="文档原文预览图片URL（跨页时为合并后的图片）")
    page_number: Optional[int] = Field(None, description="页面号（从1开始，PDF/Word 展示用）")
    coordinates: Dict[str, int] = Field(default_factory=lambda: {"x": 0, "y": 0, "width": 0, "height": 0}, description="坐标信息")
    confidence: float = Field(..., description="置信度", ge=0, le=1)
    trace_supported: bool = Field(True, description="是否支持溯源/高亮")
    document_type: Optional[str] = Field(None, description="文档类型：pdf / excel / text 等")
    sheet_name: Optional[str] = Field(None, description="Sheet 名称（Excel 溯源）")
    sheet_index: Optional[int] = Field(None, description="Sheet 索引（从0开始，Excel 溯源）")
    cell_ref: Optional[str] = Field(None, description="主单元格引用，如 Sheet1!B5（Excel）")
    cell_refs: Optional[List[str]] = Field(None, description="全部单元格引用（Excel 多区域溯源）")
    
    # 跨页信息（可选）
    cross_page_info: Optional[Dict[str, Any]] = Field(None, description="跨页信息（如果内容跨页）")
    
    # 所有高亮区域（用于批量生成高亮图）
    regions: Optional[List[RegionInfo]] = Field(None, description="所有高亮区域列表（内部使用）")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "source_file_type": "info_disclosure_application",
                "source_file_name": "信息披露申请书.pdf",
                "source_field": "标的名称",
                "source_content": "北京市朝阳区望京西路48号院5号楼2层204",
                "preview_image_url": "https://minio.example.com/preview/merged_xxx.png",
                "page_number": 3,
                "coordinates": {"x": 100, "y": 200, "width": 300, "height": 50},
                "confidence": 0.95,
                "cross_page_info": {
                    "is_cross_page": True,
                    "pages": [3, 4],
                    "main_page": 3
                }
            }
        }
    }


class ExtractedFieldValue(BaseModel):
    """字段的单个来源提取值"""
    source_file_type: str = Field(..., description="来源文件类型")
    source_file_name: str = Field(..., description="来源文件名")
    source_field_name: str = Field(..., description="来源字段名（原文件中的字段名）")
    extracted_value: Optional[Any] = Field(None, description="提取的值（根据field_type不同，类型不同）")
    extract_status: ExtractStatus = Field(..., description="单个来源的提取状态（success=成功, failed=失败）")
    confidence: float = Field(..., description="置信度", ge=0, le=1)
    sources: List[SourceInfo] = Field(default_factory=list, description="详细溯源信息列表")


class FieldExtractionResult(BaseModel):
    """单个字段的提取结果（支持多来源）"""
    field_id: str = Field(..., description="字段ID")
    field_name: str = Field(..., description="字段名称（系统字段名）")
    field_type: str = Field(..., description="字段类型：text/single_choice/multiple_choice等")
    field_status: FieldExtractionStatus = Field(..., description="字段提取状态（综合多来源后的状态）")
    values: List[ExtractedFieldValue] = Field(default_factory=list, description="从不同来源提取的值列表")
    error_message: Optional[str] = Field(None, description="错误信息（如果失败）")
    inconsistent_values: Optional[List[str]] = Field(None, description="不一致的值列表（当多来源值不一致时）")
    
    # 提取规则信息
    extraction_rule: Optional[Dict[str, Any]] = Field(None, description="对应的提取规则信息")


class ExtractionData(BaseModel):
    """字段提取响应数据（data字段内容）"""
    request_id: str = Field(..., description="请求ID")
    task_id: Optional[str] = Field(None, description="任务ID（异步处理时返回）")
    status: TaskExtractionStatus = Field(..., description="任务整体状态（success/partial/pending/failed）")
    extraction_type: str = Field(..., description="提取类型")
    rule_config_id: Optional[str] = Field(None, description="规则配置ID（实际使用的配置ID）")
    from_cache: bool = Field(default=False, description="是否从缓存中获取的结果")
    cached_task_id: Optional[str] = Field(None, description="缓存来源的任务ID（如果from_cache=True）")
    results: List[FieldExtractionResult] = Field(..., description="字段提取结果列表")
    total_fields: int = Field(..., description="总字段数")
    success_count: int = Field(..., description="成功提取的字段数（field_status=success）")
    pending_count: int = Field(default=0, description="待确认的字段数（field_status=pending）")
    failed_count: int = Field(..., description="失败的字段数（field_status=failed）")
    processing_time_ms: Optional[int] = Field(None, description="处理时间（毫秒）")
    parsed_files: Optional[Dict[str, Any]] = Field(
        default=None,
        description="解析文件内容快照，按file_type存储文件名、标签和md_content等信息"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "request_id": "req_20251022100002",
                "task_id": None,
                "status": "success",
                "extraction_type": "大宗实物",
                "rule_config_id": "rule_dzswv10",
                "results": [
                    {
                        "field_id": "field_001",
                        "field_name": "坐落位置",
                        "field_type": "text",
                        "values": [
                            {
                                "source_file_type": "info_disclosure_application",
                                "source_file_name": "信息披露申请书.pdf",
                                "source_field_name": "坐落位置",
                                "extracted_value": "北京市朝阳区xxx",
                                "extract_status": "success",
                                "confidence": 0.95,
                                "sources": [
                                    {
                                        "source_file_type": "pdf",
                                        "source_file_name": "信息披露申请书.pdf",
                                        "source_field": "坐落位置",
                                        "source_content": "坐落位置为北京市朝阳区xxx",
                                        "preview_image_url": "base64_encoded_image...",
                                        "coordinates": {
                                            "x": 52,
                                            "y": 61,
                                            "width": 242,
                                            "height": 21
                                        },
                                        "confidence": 0.95
                                    }
                                ]
                            }
                        ],
                        "error_message": None
                    }
                ],
                "total_fields": 10,
                "success_count": 10,
                "failed_count": 0,
                "processing_time_ms": 5230
            }
        }
    }


class ExtractionResponse(ApiResponse[ExtractionData]):
    """字段提取完整响应（包含code、message等包装字段）"""
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "code": 200,
                "message": "success",
                "trace_id": "trace_20251107100001",
                "timestamp": "2025-11-07T10:00:00Z",
                "data": {
                    "request_id": "req_20251022100002",
                    "task_id": None,
                    "status": "success",
                    "extraction_type": "有纸大宗实物",
                    "rule_config_id": "rule_dzswv10",
                    "results": [
                        {
                            "field_id": "field_001",
                            "field_name": "坐落位置",
                            "field_type": "text",
                            "values": [
                                {
                                    "source_file_type": "info_disclosure_application",
                                    "source_file_name": "信息披露申请书.pdf",
                                    "source_field_name": "坐落位置",
                                    "extracted_value": "北京市朝阳区xxx",
                                    "extract_status": "success",
                                    "confidence": 0.95,
                                    "sources": []
                                }
                            ],
                            "error_message": None
                        }
                    ],
                    "total_fields": 10,
                    "success_count": 10,
                    "failed_count": 0,
                    "processing_time_ms": 5230
                }
            }
        }
    }


# 为了向后兼容，保留旧的导出名称
__all__ = [
    'ExtractionFileInput',
    'ExtractionRequest',
    'FieldExtractionStatus',
    'TaskExtractionStatus',
    'ExtractionStatus',  # 向后兼容别名
    'RegionInfo',
    'SourceInfo',
    'ExtractedFieldValue',
    'FieldExtractionResult',
    'ExtractionData',
    'ExtractionResponse',
]

