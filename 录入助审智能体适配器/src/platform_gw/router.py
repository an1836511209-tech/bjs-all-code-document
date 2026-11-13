"""
平台接入路由：隔离前缀下复用既有业务 endpoint，不复制业务逻辑。

未纳入：规则配置 CRUD/Web、文件预览、健康检查、Swagger 等。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile, status

from config.platform_gw_config import PLATFORM_GW_PREFIX
from src.api.v1.endpoints.audit import audit_fields_sync
from src.api.v1.endpoints.classification import classify_files
from src.api.v1.endpoints.extraction import extract_fields_sync
from src.api.v1.endpoints.file import check_file_quality
from src.api.v1.endpoints.minio_upload import minio_upload
from src.api.v1.endpoints.task import cancel_task, get_task_status
from src.schemas.audit import AuditRequest, AuditResponse
from src.schemas.classification import ClassificationRequest, ClassificationResponse
from src.schemas.extraction import ExtractionRequest, ExtractionResponse
from src.schemas.file import FileQualityCheckRequest, FileQualityCheckResponse
from src.schemas.task import TaskCancelResponse, TaskStatusResponse, TaskType


def build_platform_router() -> APIRouter:
    router = APIRouter(
        prefix=PLATFORM_GW_PREFIX,
        tags=["平台接入-服务提供方"],
    )

    @router.post(
        "/file/quality-check",
        response_model=FileQualityCheckResponse,
        status_code=status.HTTP_200_OK,
        summary="[平台] 文件质量检测",
    )
    async def platform_check_file_quality(
        request: FileQualityCheckRequest,
        background_tasks: BackgroundTasks,
    ):
        return await check_file_quality(request, background_tasks)

    @router.post(
        "/file/classification",
        response_model=ClassificationResponse,
        status_code=status.HTTP_200_OK,
        summary="[平台] 文件分类",
    )
    async def platform_classify_files(request: ClassificationRequest):
        return await classify_files(request)

    @router.post(
        "/file/minio/upload",
        summary="[平台] 上传文件到 Agent MinIO",
    )
    async def platform_minio_upload(
        file: UploadFile = File(...),
        file_type: Optional[str] = Form(None),
        request_id: Optional[str] = Form(None),
    ):
        return await minio_upload(file=file, file_type=file_type, request_id=request_id)

    @router.post(
        "/extraction/sync",
        response_model=ExtractionResponse,
        status_code=status.HTTP_200_OK,
        summary="[平台] 同步字段提取",
    )
    async def platform_extract_fields_sync(request: ExtractionRequest):
        return await extract_fields_sync(request)

    @router.post(
        "/audit/sync",
        response_model=AuditResponse,
        summary="[平台] 同步规则审核",
    )
    async def platform_audit_fields_sync(request: AuditRequest):
        return await audit_fields_sync(request)

    @router.get(
        "/task",
        response_model=TaskStatusResponse,
        summary="[平台] 查询任务状态",
    )
    async def platform_get_task_status(
        task_id: str = Query(..., description="任务ID"),
        task_type: Optional[TaskType] = Query(
            default=None,
            alias="type",
            description="任务类型（extraction、audit 或 classification）",
        ),
        include_details: bool = Query(default=True, description="是否包含详细结果"),
    ):
        return await get_task_status(
            task_id=task_id,
            task_type=task_type,
            include_details=include_details,
        )

    @router.post(
        "/task/cancel",
        response_model=TaskCancelResponse,
        summary="[平台] 取消任务",
    )
    async def platform_cancel_task(
        task_id: str = Query(..., description="任务ID"),
        task_type: Optional[TaskType] = Query(
            default=None,
            alias="type",
            description="任务类型（extraction、audit 或 classification）",
        ),
    ):
        return await cancel_task(task_id=task_id, task_type=task_type)

    return router
