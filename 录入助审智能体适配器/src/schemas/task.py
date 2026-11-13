"""
任务管理数据模型

定义任务查询和管理接口的数据结构
"""

from typing import Optional, Union, Any, Dict
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, field_serializer

from src.schemas.base import ApiResponse


class TaskType(str, Enum):
    """任务类型"""
    EXTRACTION = "extraction"  # 字段提取
    AUDIT = "audit"           # 规则审核
    CLASSIFICATION = "classification"


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"       # 等待中
    PROCESSING = "processing" # 处理中
    COMPLETED = "completed"   # 已完成
    FAILED = "failed"         # 失败
    TIMEOUT = "timeout"       # 超时
    CANCELLED = "cancelled"   # 已取消


class TaskStatusData(BaseModel):
    """任务状态响应数据（data字段内容）"""
    task_id: str = Field(..., description="任务ID")
    task_type: TaskType = Field(..., description="任务类型")
    status: TaskStatus = Field(..., description="任务状态")
    progress: float = Field(..., description="进度（0-1）", ge=0, le=1)
    status_message: Optional[str] = Field(None, description="当前进度阶段描述（如：正在解析文件...、当前有 2 个智能录入任务排队等待处理，请您稍作等候，系统将按照顺序自动启动任务处理。）")
    result: Optional[Union[Dict[str, Any], Any]] = Field(
        None, 
        description="任务结果（根据task_type不同，结构不同）"
    )
    total_count: Optional[int] = Field(
        None,
        description="总任务数（提取任务为总字段数，审核任务为总规则数，分类任务为总文件数）",
    )
    completed_count: Optional[int] = Field(
        None,
        description="已完成任务数（提取任务为成功字段数，审核任务为通过规则数，分类任务为已完成文件数）",
    )
    error_message: Optional[str] = Field(None, description="错误信息")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
    
    @field_serializer('completed_at', 'created_at', 'updated_at')
    def serialize_datetime(self, value: Optional[datetime], _info) -> Optional[str]:
        """序列化 datetime 为 ISO 8601 格式字符串"""
        if value is None:
            return None
        return value.isoformat()
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "task_id": "task_20251103_001",
                "task_type": "extraction",
                "status": "completed",
                "progress": 1.0,
                "status_message": "处理完成",
                "result": {
                    "status": "success",
                    "total_fields": 10,
                    "success_count": 10,
                    "failed_count": 0
                },
                "total_count": 10,
                "completed_count": 10,
                "error_message": None,
                "created_at": "2025-11-03T10:00:00Z",
                "updated_at": "2025-11-03T10:05:30Z",
                "completed_at": "2025-11-03T10:05:30Z"
            }
        }
    }


class TaskStatusResponse(ApiResponse[TaskStatusData]):
    """任务状态完整响应（包含code、message等包装字段）"""
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "code": 200,
                "message": "success",
                "trace_id": "trace_20251107100001",
                "timestamp": "2025-11-07T10:00:00Z",
                "data": {
                    "task_id": "task_20251103_001",
                    "task_type": "extraction",
                    "status": "completed",
                    "progress": 1.0,
                    "status_message": "处理完成",
                    "result": {
                        "status": "success",
                        "total_fields": 10,
                        "success_count": 10,
                        "failed_count": 0
                    },
                    "total_count": 10,
                    "completed_count": 10,
                    "error_message": None,
                    "created_at": "2025-11-03T10:00:00Z",
                    "updated_at": "2025-11-03T10:05:30Z",
                    "completed_at": "2025-11-03T10:05:30Z"
                }
            }
        }
    }


class TaskCancelData(BaseModel):
    """任务取消响应数据（data字段内容）"""
    task_id: str = Field(..., description="任务ID")
    status: TaskStatus = Field(..., description="任务状态")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "task_id": "task_20251103_001",
                "status": "cancelled"
            }
        }
    }


class TaskCancelResponse(ApiResponse[TaskCancelData]):
    """任务取消完整响应（包含code、message等包装字段）"""
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "code": 200,
                "message": "任务已取消",
                "trace_id": "trace_20251107100001",
                "timestamp": "2025-11-07T10:00:00Z",
                "data": {
                    "task_id": "task_20251103_001",
                    "status": "cancelled"
                }
            }
        }
    }


class Task(BaseModel):
    """任务模型（内部使用）"""
    task_id: str
    task_type: TaskType
    status: TaskStatus
    progress: float = 0.0
    result: Optional[Any] = None
    error_message: Optional[str] = None
    status_message: Optional[str] = Field(None, description="当前进度阶段描述（如：正在解析文件...）")
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    cancelled: bool = False
    
    # 任务上下文数据
    context: dict = Field(default_factory=dict, description="任务上下文数据")
    
    # 附件哈希（用于缓存查询）
    files_hash: Optional[str] = Field(None, description="附件哈希值，用于识别相同附件集合")

