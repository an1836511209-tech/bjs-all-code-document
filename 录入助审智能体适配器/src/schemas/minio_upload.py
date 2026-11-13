"""MinIO 上传接口响应模型"""

from pydantic import BaseModel, Field


class MinioUploadData(BaseModel):
    """MinIO 上传成功 data"""
    url: str = Field(..., description="Agent MinIO 完整访问地址")
    file_name: str = Field(..., description="原始文件名")
    file_url: str = Field(
        ...,
        description="后续业务使用的相对路径 /aiFileApi/{bucket}/{object_key}",
    )
    object_key: str = Field(..., description="对象路径 yyyy/MM/dd/{uuid}.{ext}")
    file_size: int = Field(..., description="文件字节数")
    content_type: str = Field(..., description="MIME 类型")
    file_content_hash: str = Field(..., description="MD5 哈希")
    request_id: str = Field(..., description="请求 ID（回显或自动生成）")
