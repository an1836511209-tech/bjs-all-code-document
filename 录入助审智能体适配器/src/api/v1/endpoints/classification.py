"""
文件分类 API 路由

提供文件分类相关的 REST API 接口
"""

import asyncio

from fastapi import APIRouter, HTTPException, status
from loguru import logger

from src.schemas.classification import (
    ClassificationRequest,
    ClassificationResponse,
    ClassificationData,
    ClassificationStatus,
)
from src.schemas.base import success_response
from src.services.classification.service import get_classification_api_service
from src.api.v1.utils.task_handler import (
    generate_task_id_with_prefix,
    convert_timeout_to_seconds,
    wait_for_task_with_timeout,
    replace_task_id_in_response,
)
from src.services.task_store import get_task_store
from src.schemas.task import TaskType, TaskStatus


router = APIRouter(prefix="/file", tags=["文件分类"])


@router.post(
    "/classification",
    response_model=ClassificationResponse,
    status_code=status.HTTP_200_OK,
    summary="文件分类",
    description="""
    对上传的文件进行智能分类，返回对应的文件类型枚举值。
    如果处理时间超过 timeout（默认 300000 毫秒），将返回 pending 状态与 task_id，
    后台任务继续执行，不会被取消。请使用 GET /api/v1/task/{task_id}?type=classification 查询结果。
    同一任务处于 pending 或 processing 时重复请求不会重新执行。

    **处理流程：**
    1. 下载文件并判断格式
    2. 解析文件前两页内容（用于减少处理时间）
    3. 使用 LLM 智能分类
    4. 返回分类结果

    **支持的文件格式：**
    - PDF: 使用 OCR 解析
    - Word (.doc, .docx): 转换为 PDF 后解析
    - 图片 (JPG, PNG, BMP, TIFF, WebP): 直接 OCR 解析
    - Excel (.xlsx, .xlsm): 提取文本内容
    - CSV: 提取文本内容

    **分类结果（file_type 枚举值）：**
    - info_disclosure_application: 信息披露申请书
    - evaluation_report: 评估报告或其他定价文件
    - evaluation_filing: 评估备案表/核准文件
    - internal_decision: 内部决议或有权批准机构决策文件
    - business_license: 营业执照/事业单位法人证书/身份证
    - asset_list: 资产清单
    - inspection_management: 踏勘承诺函
    - property_certificate: 房屋产权所有证/不动产权证
    - land_use_certificate: 国有土地使用证
    - land_use_contract: 国有建设用地使用权出让合同
    - vehicle_certificate: 行驶证/机动车登记证书
    - ship_certificate: 船舶所有权证书/船舶检验证书/船舶国籍证明
    - aircraft_certificate: 适航证/电台执照/国籍登记证
    - patent_certificate: 专利证书
    - central_asset_disposal_authorization: 中央行政事业单位国有资产处置委托书
    - central_asset_transfer_application: 中央行政事业单位国有资产转让申请表
    - central_asset_receipt: 中央行政事业单位国有资产接收单
    - asset_disposal_application: 行政事业单位国有资产处置申请表
    - asset_receipt_confirmation: 行政事业单位国有资产接收确认书
    - asset_confirmation_form: 行政事业单位国有资产确认单
    - project_progress_record: 项目进度记录表
    - other_documents: 其他文件（无法识别时的默认类型）
    """,
)
async def classify_files(
    request: ClassificationRequest
) -> ClassificationResponse:
    """
    文件分类接口

    Args:
        request: 分类请求

    Returns:
        ClassificationResponse: 分类结果；超时则返回 pending 与 task_id

    Raises:
        HTTPException: 参数错误返回 400，其它失败返回 500
    """
    try:
        logger.info(
            f"收到文件分类请求: request_id={request.request_id}, "
            f"files={len(request.files)}, timeout={request.timeout}ms"
        )

        timeout_seconds = convert_timeout_to_seconds(request.timeout, default_seconds=300)
        task_id, base_task_id = generate_task_id_with_prefix(
            prefix="classification_",
            task_id=request.task_id,
            request_id=request.request_id,
        )
        task_store = get_task_store()

        existing = await task_store.get_task(task_id)
        if existing and existing.status in (TaskStatus.PENDING, TaskStatus.PROCESSING):
            logger.info(
                f"任务正在执行中，跳过重复请求: task_id={task_id}, status={existing.status}"
            )
            pending = ClassificationData(
                request_id=request.request_id or base_task_id,
                task_id=base_task_id,
                status=ClassificationStatus.PENDING,
                results=[],
                total_files=existing.context.get("total_files", len(request.files)),
                success_count=0,
                failed_count=0,
                processing_time_ms=request.timeout or 300000,
            )
            return success_response(
                data=pending.model_dump(),
                message="任务处理中，请稍后查询结果",
            )

        await task_store.create_task(
            task_id=task_id,
            task_type=TaskType.CLASSIFICATION,
            context={
                "total_files": len(request.files),
                "completed_count": 0,
                "base_task_id": base_task_id,
            },
            status_message="等待处理",
            reset_if_exists=True,
        )

        classification_service = get_classification_api_service()
        classification_task = asyncio.create_task(
            classification_service.classify_files(
                files=request.files,
                task_id=task_id,
                request_id=request.request_id,
                base_task_id=base_task_id,
            )
        )

        def create_pending_data():
            return ClassificationData(
                request_id=request.request_id or base_task_id,
                task_id=base_task_id,
                status=ClassificationStatus.PENDING,
                results=[],
                total_files=len(request.files),
                success_count=0,
                failed_count=0,
                processing_time_ms=int(timeout_seconds * 1000),
            )

        is_done, result_data = await wait_for_task_with_timeout(
            task=classification_task,
            timeout_seconds=timeout_seconds,
            base_task_id=base_task_id,
            full_task_id=task_id,
            pending_data_factory=create_pending_data,
            task_name="文件分类",
        )

        if is_done:
            data = result_data.model_dump() if hasattr(result_data, "model_dump") else result_data
            data = replace_task_id_in_response(data, base_task_id)
            logger.info(
                f"文件分类完成: request_id={request.request_id}, "
                f"task_id={base_task_id}, status={data.get('status')}"
            )
            return success_response(data=data, message="success")

        return success_response(
            data=result_data.model_dump(),
            message="任务处理中，请稍后查询结果",
        )

    except ValueError as e:
        logger.error(f"文件分类参数错误: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"文件分类失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文件分类失败: {str(e)}",
        )
