"""
文件分类请求/响应模型

提供文件分类 API 的数据模型定义
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

from src.schemas.base import BaseResponse


class ClassificationStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    PENDING = "pending"


class ClassificationFileInput(BaseModel):
    """文件分类输入"""
    file_url: str = Field(..., description="文件URL地址")
    file_name: str = Field(..., description="文件名称")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "file_url": "https://example.com/files/document.pdf",
                "file_name": "信息披露申请书.pdf"
            }
        }
    }


class ClassificationRequest(BaseModel):
    """文件分类请求"""
    files: List[ClassificationFileInput] = Field(
        ..., 
        description="待分类的文件列表",
        min_length=1
    )
    request_id: Optional[str] = Field(
        None, 
        description="请求唯一标识，用于幂等性控制"
    )
    task_id: Optional[str] = Field(None, description="任务ID（可选，用于继续未完成的任务）")
    timeout: Optional[int] = Field(default=300000, description="超时时间（毫秒）", ge=1000)
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "files": [
                    {
                        "file_url": "https://example.com/files/doc1.pdf",
                        "file_name": "信息披露申请书.pdf"
                    },
                    {
                        "file_url": "https://example.com/files/doc2.docx",
                        "file_name": "内部决议.docx"
                    }
                ],
                "request_id": "req_20251114100001",
                "task_id": "task_20251114100001",
                "timeout": 300000
            }
        }
    }


class ClassificationResultItem(BaseModel):
    """单个文件分类结果"""
    file_name: str = Field(..., description="文件名称")
    file_url: str = Field(..., description="文件URL地址")
    file_type: str = Field(..., description="分类后的文件类型枚举值")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "file_name": "信息披露申请书.pdf",
                "file_url": "https://example.com/files/doc1.pdf",
                "file_type": "info_disclosure_application"
            }
        }
    }


class ClassificationData(BaseModel):
    """文件分类响应数据"""
    request_id: str = Field(..., description="请求ID")
    task_id: Optional[str] = Field(None, description="任务ID（异步处理时返回）")
    status: ClassificationStatus = Field(..., description="任务整体状态")
    results: List[ClassificationResultItem] = Field(default_factory=list, description="文件分类结果列表")
    total_files: int = Field(0, description="总文件数")
    success_count: int = Field(0, description="无异常完成的文件数")
    failed_count: int = Field(0, description="异常兜底文件数")
    processing_time_ms: int = Field(..., description="处理时间（毫秒）")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "request_id": "req_20251114100001",
                "task_id": "task_20251114100001",
                "status": "success",
                "results": [
                    {
                        "file_name": "信息披露申请书.pdf",
                        "file_url": "https://example.com/files/doc1.pdf",
                        "file_type": "info_disclosure_application"
                    },
                    {
                        "file_name": "内部决议.docx",
                        "file_url": "https://example.com/files/doc2.docx",
                        "file_type": "internal_decision"
                    }
                ],
                "total_files": 2,
                "success_count": 2,
                "failed_count": 0,
                "processing_time_ms": 1500
            }
        }
    }


class ClassificationResponse(BaseResponse):
    """文件分类响应"""
    data: ClassificationData = Field(..., description="分类结果数据")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "code": 200,
                "message": "success",
                "trace_id": "trace_20251114100001",
                "timestamp": "2025-11-14T10:00:00Z",
                "data": {
                    "request_id": "req_20251114100001",
                    "task_id": "task_20251114100001",
                    "status": "success",
                    "results": [
                        {
                            "file_name": "信息披露申请书.pdf",
                            "file_url": "https://example.com/files/doc1.pdf",
                            "file_type": "info_disclosure_application"
                        }
                    ],
                    "total_files": 1,
                    "success_count": 1,
                    "failed_count": 0,
                    "processing_time_ms": 1500
                }
            }
        }
    }
