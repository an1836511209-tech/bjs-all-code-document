"""
文件质量检测相关的数据模型

根据 API 规范定义的 Pydantic 模型
"""

from enum import Enum
from typing import List, Optional, Union
from pydantic import BaseModel, Field, validator

from src.schemas.base import BaseResponse, ApiResponse


class FileType(str, Enum):
    """业务文件类型枚举"""
    INFO_DISCLOSURE_APPLICATION = "info_disclosure_application"    # 信息披露申请书
    EVALUATION_REPORT = "evaluation_report"                       # 评估报告或其他定价文件
    EVALUATION_FILING = "evaluation_filing"                       # 评估备案表/核准文件
    INTERNAL_DECISION = "internal_decision"                       # 内部决议或有权批准机构决策文件
    BUSINESS_LICENSE = "business_license"                         # 营业执照/事业单位法人证书/身份证
    ASSET_LIST = "asset_list"                                     # 资产清单
    INSPECTION_COMMITMENT = "inspection_management"               # 踏勘承诺函
    PROPERTY_CERTIFICATE = "property_certificate"                 # 房屋产权所有证/不动产权证
    LAND_USE_CERTIFICATE = "land_use_certificate"                 # 国有土地使用证
    LAND_USE_CONTRACT = "land_use_contract"                       # 国有建设用地使用权出让合同
    VEHICLE_CERTIFICATE = "vehicle_certificate"                   # 行驶证/机动车登记证书（限机动车）
    SHIP_CERTIFICATE = "ship_certificate"                         # 船舶所有权证书/船舶检验证书/船舶国籍证明（限船舶）
    AIRCRAFT_CERTIFICATE = "aircraft_certificate"                 # 适航证/电台执照/国籍登记证（限飞机）
    PATENT_CERTIFICATE = "patent_certificate"                     # 专利证书
    CENTRAL_ASSET_DISPOSAL_AUTHORIZATION = "central_asset_disposal_authorization"  # 中央行政事业单位国有资产处置委托书
    CENTRAL_ASSET_TRANSFER_APPLICATION = "central_asset_transfer_application"      # 中央行政事业单位国有资产转让申请表
    CENTRAL_ASSET_RECEIPT = "central_asset_receipt"                               # 中央行政事业单位国有资产接收单
    ASSET_DISPOSAL_APPLICATION = "asset_disposal_application"                     # 行政事业单位国有资产处置申请表
    ASSET_RECEIPT_CONFIRMATION = "asset_receipt_confirmation"                     # 行政事业单位国有资产接收确认书
    ASSET_CONFIRMATION_FORM = "asset_confirmation_form"                           # 行政事业单位国有资产确认单
    PROJECT_PROGRESS_RECORD = "project_progress_record"                           # 项目进度记录表
    OTHER_DOCUMENTS = "other_documents"                                           # 其他文件（无法识别的文件）


# 文件类型中文名称映射
FILE_TYPE_LABELS = {
    FileType.INFO_DISCLOSURE_APPLICATION: "《信息披露申请书》",
    FileType.EVALUATION_REPORT: "《评估报告或其他定价文件》",
    FileType.EVALUATION_FILING: "《评估备案表/核准文件》",
    FileType.INTERNAL_DECISION: "《内部决议或有权批准机构决策文件》",
    FileType.BUSINESS_LICENSE: "《营业执照/事业单位法人证书/身份证》",
    FileType.ASSET_LIST: "《资产清单》",
    FileType.INSPECTION_COMMITMENT: "《踏勘承诺函》",
    FileType.PROPERTY_CERTIFICATE: "《房屋产权所有证/不动产权证》",
    FileType.LAND_USE_CERTIFICATE: "《国有土地使用证》",
    FileType.LAND_USE_CONTRACT: "《国有建设用地使用权出让合同》",
    FileType.VEHICLE_CERTIFICATE: "《行驶证/机动车登记证书（限机动车）》",
    FileType.SHIP_CERTIFICATE: "《船舶所有权证书/船舶检验证书/船舶国籍证明（限船舶）》",
    FileType.AIRCRAFT_CERTIFICATE: "《适航证/电台执照/国籍登记证（限飞机）》",
    FileType.PATENT_CERTIFICATE: "《专利证书》",
    FileType.CENTRAL_ASSET_DISPOSAL_AUTHORIZATION: "《中央行政事业单位国有资产处置委托书》",
    FileType.CENTRAL_ASSET_TRANSFER_APPLICATION: "《中央行政事业单位国有资产转让申请表》",
    FileType.CENTRAL_ASSET_RECEIPT: "《中央行政事业单位国有资产接收单》",
    FileType.ASSET_DISPOSAL_APPLICATION: "《行政事业单位国有资产处置申请表》",
    FileType.ASSET_RECEIPT_CONFIRMATION: "《行政事业单位国有资产接收确认书》",
    FileType.ASSET_CONFIRMATION_FORM: "《行政事业单位国有资产确认单》",
    FileType.PROJECT_PROGRESS_RECORD: "《项目进度记录表》",
    FileType.OTHER_DOCUMENTS: "《其他文件》",
}

# 反向映射：中文名称 -> FileType
LABEL_TO_FILE_TYPE = {label: file_type for file_type, label in FILE_TYPE_LABELS.items()}


class QualityStatus(str, Enum):
    """质量状态枚举"""
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class QualityResultStatus(str, Enum):
    """质量检测结果状态"""
    PASSED = "passed"
    WARNING = "warning"  
    FAILED = "failed"


class FileInput(BaseModel):
    """文件输入模型"""
    file_url: Optional[str] = Field(None, description="文件URL地址（fileUrl和fileStream二选一）")
    file_stream: Optional[str] = Field(None, description="文件流（Base64编码或Data URI）")
    file_name: str = Field(..., description="文件名称")
    file_type: Optional[FileType] = Field(None, description="业务文件类型（可选，未传时响应回显为 null）")
    
    @validator('file_url', 'file_stream', pre=True)
    def validate_file_input(cls, v, values):
        """验证至少提供一种文件输入方式"""
        if 'file_url' in values or 'file_stream' in values:
            if not values.get('file_url') and not values.get('file_stream'):
                raise ValueError('必须提供 file_url 或 file_stream 中的一个')
        return v
    
    class Config:
        use_enum_values = True


class FileQualityResult(BaseModel):
    """文件质量检测结果"""
    clarity: QualityResultStatus = Field(..., description="清晰度检测结果")
    clarity_score: float = Field(..., description="清晰度分数（拉普拉斯方差：越高越好，通常>500为良好）", ge=0)
    resolution: QualityResultStatus = Field(..., description="分辨率检测结果")
    resolution_value: str = Field(..., description="分辨率值", example="1920x1080")
    occlusion: QualityResultStatus = Field(..., description="遮挡检测结果")
    occlusion_score: float = Field(..., description="遮挡分数（0-1，越低越好）", ge=0, le=1)


class FileQualityCheckItem(BaseModel):
    """单个文件质量检测结果项"""
    file_id: str = Field(..., description="文件ID")
    file_name: str = Field(..., description="文件名称")
    file_type: Optional[FileType] = Field(None, description="业务文件类型（请求未传时为 null）")
    file_url: Optional[str] = Field(None, description="文件URL地址")
    quality_status: QualityStatus = Field(..., description="质量状态")
    quality_result: FileQualityResult = Field(..., description="质量检测详细结果")
    message: str = Field(..., description="检测结果消息", example="文件质量校验通过")


class FileQualityCheckRequest(BaseModel):
    """文件质量检测请求"""
    files: List[FileInput] = Field(..., description="待检测的文件列表", min_items=1)
    request_id: Optional[str] = Field(None, description="请求唯一标识，用于幂等性控制")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "files": [
                    {
                        "file_url": "https://example.com/files/application.pdf",
                        "file_name": "信息披露申请书.pdf",
                        "file_type": "info_disclosure_application"
                    },
                    {
                        "file_stream": "data:image/png;base64,iVBORw0KGgoAAAANS...",
                        "file_name": "房屋所有权证.png",
                        "file_type": "property_certificate"
                    }
                ],
                "request_id": "req_20251022100001"
            }
        }
    }




class FileQualityCheckResponse(BaseResponse):
    """文件质量检测响应"""
    data: List[FileQualityCheckItem] = Field(..., description="检测结果列表")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "code": 200,
                "message": "success",
                "trace_id": "trace_20251022100001",
                "timestamp": "2025-10-22T10:00:00Z",
                "data": [
                    {
                        "file_id": "file_20251022100001",
                        "file_name": "信息披露申请书.pdf",
                        "file_type": "info_disclosure_application",
                        "quality_status": "passed",
                        "quality_result": {
                            "clarity": "passed",
                            "clarity_score": 725.5,
                            "resolution": "passed",
                            "resolution_value": "1920x1080",
                            "occlusion": "passed",
                            "occlusion_score": 0.02
                        },
                        "message": "文件质量校验通过"
                    }
                ]
            }
        }
    }
