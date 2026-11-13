"""
基础响应模型和工具

提供统一的API响应格式
"""

from typing import Generic, TypeVar, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


DataT = TypeVar('DataT')


class BaseResponse(BaseModel):
    """基础响应模型"""
    code: int = Field(..., description="响应状态码")
    message: str = Field(..., description="响应消息")
    trace_id: Optional[str] = Field(None, description="请求追踪ID")
    timestamp: Optional[str] = Field(None, description="响应时间戳")


class ApiResponse(BaseResponse, Generic[DataT]):
    """通用API响应模型（泛型）"""
    data: DataT = Field(..., description="响应数据")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "code": 200,
                "message": "success",
                "trace_id": "trace_20251107100001",
                "timestamp": "2025-11-07T10:00:00Z",
                "data": {}
            }
        }
    }


class ErrorDetail(BaseModel):
    """错误详情"""
    field: Optional[str] = Field(None, description="错误字段")
    message: str = Field(..., description="错误消息")


class ErrorInfo(BaseModel):
    """错误信息"""
    error_code: str = Field(..., description="业务错误码")
    error_message: str = Field(..., description="错误详细信息")
    details: Optional[list[ErrorDetail]] = Field(None, description="错误详情列表")


class ErrorResponse(BaseResponse):
    """错误响应模型"""
    error: ErrorInfo = Field(..., description="错误信息")


def success_response(
    data: DataT,
    message: str = "success",
    code: int = 200,
    trace_id: Optional[str] = None
) -> dict:
    """
    创建成功响应
    
    Args:
        data: 响应数据
        message: 响应消息
        code: 状态码
        trace_id: 追踪ID
        
    Returns:
        dict: 格式化的响应字典
    """
    return {
        "code": code,
        "message": message,
        "trace_id": trace_id or f"trace_{uuid.uuid4().hex[:16]}",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "data": data
    }


def error_response(
    error_code: str,
    error_message: str,
    message: str = "error",
    code: int = 500,
    details: Optional[list[dict]] = None,
    trace_id: Optional[str] = None
) -> dict:
    """
    创建错误响应
    
    Args:
        error_code: 业务错误码
        error_message: 错误详细信息
        message: 响应消息
        code: HTTP状态码
        details: 错误详情列表
        trace_id: 追踪ID
        
    Returns:
        dict: 格式化的错误响应字典
    """
    return {
        "code": code,
        "message": message,
        "trace_id": trace_id or f"trace_{uuid.uuid4().hex[:16]}",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "error": {
            "error_code": error_code,
            "error_message": error_message,
            "details": details
        }
    }



