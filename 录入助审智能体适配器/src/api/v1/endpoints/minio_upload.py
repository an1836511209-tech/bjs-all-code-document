"""
Agent MinIO 文件上传接口

对方将文件字节流推送到本接口，写入 Agent 自己的 MinIO。
不访问对方 MinIO；不影响现有 highlights 溯源路径。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse
from loguru import logger

from src.schemas.base import error_response, success_response
from src.schemas.minio_upload import MinioUploadData
from src.utils.minio.client import MinIOClientError, get_minio_client

router = APIRouter(prefix="/file", tags=["文件上传"])

ALLOWED_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "xlsm", "csv",
    "jpg", "jpeg", "png", "bmp", "tiff", "webp",
}
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB


def _extract_extension(filename: Optional[str]) -> Optional[str]:
    if not filename or "." not in filename:
        return None
    return filename.rsplit(".", 1)[-1].lower()


@router.post(
    "/minio/upload",
    summary="上传文件到 Agent MinIO",
    description="接收 multipart 文件流，写入 Agent MinIO，返回 url / file_url 等字段。",
)
async def minio_upload(
    file: UploadFile = File(...),
    file_type: Optional[str] = Form(None),
    request_id: Optional[str] = Form(None),
):
    trace_id = f"trace_{uuid.uuid4().hex[:16]}"
    resolved_request_id = request_id or f"req_{uuid.uuid4().hex[:16]}"

    original_name = file.filename or ""
    if not original_name.strip():
        return JSONResponse(
            status_code=400,
            content=error_response(
                error_code="FILE_001",
                error_message="文件不能为空",
                message="Bad Request",
                code=400,
                details=[{"field": "file", "message": "请上传文件"}],
                trace_id=trace_id,
            ),
        )

    ext = _extract_extension(original_name)
    if not ext or ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content=error_response(
                error_code="FILE_003",
                error_message="不支持的扩展名",
                message="Bad Request",
                code=400,
                details=[{"field": "file", "message": f"不支持的扩展名: {ext or '(无)'}"}],
                trace_id=trace_id,
            ),
        )

    file_bytes = await file.read()
    if not file_bytes:
        return JSONResponse(
            status_code=400,
            content=error_response(
                error_code="FILE_001",
                error_message="文件不能为空",
                message="Bad Request",
                code=400,
                details=[{"field": "file", "message": "请上传文件"}],
                trace_id=trace_id,
            ),
        )

    if len(file_bytes) > MAX_FILE_SIZE:
        return JSONResponse(
            status_code=400,
            content=error_response(
                error_code="FILE_002",
                error_message="文件过大",
                message="Bad Request",
                code=400,
                details=[{
                    "field": "file",
                    "message": f"文件大小超过上限 200MB，当前 {len(file_bytes)} 字节",
                }],
                trace_id=trace_id,
            ),
        )

    content_type = file.content_type or "application/octet-stream"
    object_key = f"{datetime.now().strftime('%Y/%m/%d')}/{uuid.uuid4().hex}.{ext}"
    file_hash = hashlib.md5(file_bytes).hexdigest()

    logger.info(
        f"[{trace_id}] MinIO 上传开始 | file={original_name} | "
        f"size={len(file_bytes)} | file_type={file_type} | request_id={resolved_request_id}"
    )

    try:
        minio_client = get_minio_client()
        minio_client.upload_bytes(
            data=file_bytes,
            object_name=object_key,
            content_type=content_type,
        )
        public_url = minio_client.get_public_url(object_key)
        bucket = minio_client.bucket_name
    except MinIOClientError as e:
        logger.error(f"[{trace_id}] MinIO 写入失败: {e}")
        return JSONResponse(
            status_code=500,
            content=error_response(
                error_code="FILE_005",
                error_message="写入 Agent MinIO 失败",
                message="Internal Server Error",
                code=500,
                details=[{"field": "file", "message": str(e)}],
                trace_id=trace_id,
            ),
        )
    except Exception as e:
        logger.error(f"[{trace_id}] MinIO 上传异常: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=error_response(
                error_code="FILE_005",
                error_message="写入 Agent MinIO 失败",
                message="Internal Server Error",
                code=500,
                details=[{"field": "file", "message": str(e)}],
                trace_id=trace_id,
            ),
        )

    data = MinioUploadData(
        url=public_url,
        file_name=original_name,
        file_url=f"/aiFileApi/{bucket}/{object_key}",
        object_key=object_key,
        file_size=len(file_bytes),
        content_type=content_type,
        file_content_hash=file_hash,
        request_id=resolved_request_id,
    )

    logger.info(
        f"[{trace_id}] MinIO 上传成功 | object_key={object_key} | file_url={data.file_url}"
    )

    return success_response(data=data.model_dump(), trace_id=trace_id)
