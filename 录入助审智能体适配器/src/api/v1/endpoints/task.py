"""
任务管理API端点

提供任务查询和取消功能
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, status, Query
from loguru import logger

from src.schemas.task import TaskStatusResponse, TaskStatusData, TaskCancelResponse, TaskCancelData, TaskStatus, TaskType
from src.schemas.base import success_response
from src.services.task_store import get_task_store
from src.api.v1.utils.task_handler import resolve_task_by_id


router = APIRouter(prefix="/task", tags=["任务管理"])


# 获取任务存储实例
task_store = get_task_store()


@router.get(
    "/{task_id}",
    response_model=TaskStatusResponse,
    summary="查询任务状态",
    description="""
    查询长时间运行任务的状态和结果。
    支持超时后继续查询完整结果。
    
    任务状态说明：
    - pending: 等待中
    - processing: 处理中
    - completed: 已完成
    - failed: 失败
    - timeout: 超时
    - cancelled: 已取消
    
    任务类型说明：
    - extraction: 字段提取任务
    - audit: 规则审核任务
    - classification: 文件分类任务
    
    注意：如果提供了type参数，系统会验证任务类型是否匹配。
    如果任务存在但类型不匹配，将返回404错误。
    """
)
async def get_task_status(
    task_id: str,
    task_type: Optional[TaskType] = Query(default=None, alias="type", description="任务类型（extraction、audit或classification），用于区分提取、审核和分类任务"),
    include_details: bool = Query(default=True, description="是否包含详细结果")
) -> TaskStatusResponse:
    """
    查询任务状态
    
    Args:
        task_id: 任务ID
        task_type: 任务类型（可选），用于区分提取、审核和分类任务
        include_details: 是否包含详细结果
        
    Returns:
        TaskStatusResponse: 任务状态响应
        
    Raises:
        HTTPException: 任务不存在或类型不匹配时抛出404错误
    """
    try:
        logger.info(f"查询任务状态: {task_id}, type={task_type}")

        task, internal_task_id, external_task_id = await resolve_task_by_id(
            task_store, task_id, task_type
        )

        if not task:
            logger.warning(f"任务不存在: {task_id} (内部ID: {internal_task_id})")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"任务不存在: {task_id}"
            )
        
        # 任务类型验证（通过前缀已经保证了类型匹配）
        if task_type is not None and task.task_type != task_type:
            logger.warning(f"任务类型不匹配: {task_id}, 期望类型: {task_type}, 实际类型: {task.task_type}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"任务不存在或类型不匹配: {task_id}"
            )
        
        # 从 result 或 context 中提取 total_count 和 completed_count
        total_count = None
        completed_count = None
        
        if task.result and isinstance(task.result, dict):
            # 任务已完成，根据任务类型获取统计信息
            if task.task_type == TaskType.EXTRACTION:
                # 提取任务：优先从 context 获取进度统计（保持与处理中进度一致）
                # context 中的 total_fields 反映了实际工作量（包含多来源展开）
                ctx_total = task.context.get("total_fields") if task.context else None
                ctx_completed = task.context.get("completed_count") if task.context else None
                
                if ctx_total and ctx_total > 0:
                    # 使用 context 中的进度统计，保持与处理中进度一致
                    total_count = ctx_total
                    completed_count = ctx_completed if ctx_completed is not None else ctx_total
                else:
                    # 兜底：从 result 中获取唯一字段数
                    total_count = task.result.get("total_fields")
                    success_count = task.result.get("success_count", 0)
                    pending_count = task.result.get("pending_count", 0)
                    failed_count = task.result.get("failed_count", 0)
                    completed_count = success_count + pending_count + failed_count
            elif task.task_type == TaskType.AUDIT:
                # 审核任务：从 context 获取 total_rules，保持与处理中进度一致
                # 注意：summary.total 只统计字段审核结果，不包含文件审核规则
                ctx_total = task.context.get("total_rules") if task.context else None
                
                if ctx_total and ctx_total > 0:
                    total_count = ctx_total
                else:
                    # 兜底：从 audit_results 统计实际执行的规则数
                    audit_results = task.result.get("audit_results", [])
                    if isinstance(audit_results, list):
                        # 排除 MANUAL_REVIEW（人工审核项是后加的，不是规则执行）
                        total_count = sum(
                            1 for r in audit_results 
                            if isinstance(r, dict) and r.get("audit_type") != "人工审核"
                        )
                    else:
                        total_count = 0
                
                # 任务完成后，所有规则都已执行完毕，completed_count = total_count
                completed_count = total_count
            elif task.task_type == TaskType.CLASSIFICATION:
                # 分类任务：优先 context 进度，与处理中保持一致
                ctx_total = task.context.get("total_files") if task.context else None
                ctx_completed = task.context.get("completed_count") if task.context else None

                if ctx_total and ctx_total > 0:
                    total_count = ctx_total
                    completed_count = ctx_completed if ctx_completed is not None else ctx_total
                else:
                    total_count = task.result.get("total_files")
                    success_count = task.result.get("success_count", 0)
                    failed_count = task.result.get("failed_count", 0)
                    completed_count = success_count + failed_count
        else:
            # 任务处理中，从 context 中获取总数和已完成数
            if task.context and isinstance(task.context, dict):
                if task.task_type == TaskType.EXTRACTION:
                    # 提取任务：从 context 中获取 total_fields 和 completed_count
                    ctx_total = task.context.get("total_fields")
                    ctx_completed = task.context.get("completed_count")
                    # 如果 total_fields 为 0 或 None，说明还在初始化阶段，返回 None 表示"尚未确定"
                    if ctx_total and ctx_total > 0:
                        total_count = ctx_total
                        # 优先使用 context 中的 completed_count，如果没有则根据进度估算
                        if ctx_completed is not None:
                            completed_count = ctx_completed
                        elif task.progress is not None:
                            # 根据进度估算已完成数（兜底逻辑）
                            completed_count = int(total_count * task.progress)
                elif task.task_type == TaskType.AUDIT:
                    # 审核任务：从 context 中获取 total_rules
                    ctx_total = task.context.get("total_rules")
                    # 如果 total_rules 为 0 或 None，说明还在初始化阶段（如文件分类），
                    # 返回 None 表示"尚未确定"，避免误导用户以为没有任务
                    if ctx_total and ctx_total > 0:
                        total_count = ctx_total
                        if task.progress is not None:
                            # 根据进度估算已完成数
                            completed_count = int(total_count * task.progress)
                elif task.task_type == TaskType.CLASSIFICATION:
                    # 分类任务：从 context 获取 total_files 与 completed_count
                    ctx_total = task.context.get("total_files")
                    ctx_completed = task.context.get("completed_count")
                    if ctx_total and ctx_total > 0:
                        total_count = ctx_total
                        if ctx_completed is not None:
                            completed_count = ctx_completed
                        elif task.progress is not None:
                            completed_count = int(total_count * task.progress)
        
        # 处理result中的task_id（替换为原始ID）
        result_data = task.result
        if include_details and result_data and isinstance(result_data, dict):
            if result_data.get("task_id"):
                result_data = result_data.copy()
                result_data["task_id"] = external_task_id
        
        # 确保进度值在有效范围内[0, 1]，避免Pydantic验证错误
        safe_progress = max(0.0, min(task.progress, 1.0)) if task.progress is not None else 0.0
        
        # 构建响应数据（返回用户传入的原始task_id，不包含前缀）
        data = TaskStatusData(
            task_id=external_task_id,
            task_type=task.task_type,
            status=task.status,
            progress=safe_progress,  # 使用安全的进度值
            status_message=task.status_message,  # 当前进度阶段描述
            result=result_data if include_details else None,
            total_count=total_count,
            completed_count=completed_count,
            error_message=task.error_message,
            created_at=task.created_at,
            updated_at=task.updated_at,
            completed_at=task.completed_at
        )
        
        logger.info(f"任务状态查询成功: {task_id}, 状态: {task.status}, 进度: {task.progress}")
        
        # 包装响应
        return success_response(
            data=data.model_dump(),
            message="success"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询任务状态失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询任务状态失败: {str(e)}"
        )


@router.post(
    "/{task_id}/cancel",
    response_model=TaskCancelResponse,
    summary="取消任务",
    description="""
    取消正在执行的任务。
    
    只有处于以下状态的任务可以取消：
    - pending: 等待中
    - processing: 处理中
    
    已完成、失败或已取消的任务无法再次取消。

    任务类型说明：
    - extraction: 字段提取任务
    - audit: 规则审核任务
    - classification: 文件分类任务

    注意：如果提供了type参数，系统会验证任务类型是否匹配。
    如果任务存在但类型不匹配，将返回404错误。
    """
)
async def cancel_task(
    task_id: str,
    task_type: Optional[TaskType] = Query(default=None, alias="type", description="任务类型（extraction、audit或classification），用于区分提取、审核和分类任务"),
) -> TaskCancelResponse:
    """
    取消任务
    
    Args:
        task_id: 任务ID
        task_type: 任务类型（可选），用于区分提取、审核和分类任务
        
    Returns:
        TaskCancelResponse: 取消响应
        
    Raises:
        HTTPException: 任务不存在或无法取消时抛出错误
    """
    try:
        logger.info(f"尝试取消任务: {task_id}, type={task_type}")

        task, internal_task_id, external_task_id = await resolve_task_by_id(
            task_store, task_id, task_type
        )

        if not task:
            logger.warning(f"任务不存在: {task_id} (内部ID: {internal_task_id})")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"任务不存在: {task_id}"
            )

        if task_type is not None and task.task_type != task_type:
            logger.warning(f"任务类型不匹配: {task_id}, 期望类型: {task_type}, 实际类型: {task.task_type}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"任务不存在或类型不匹配: {task_id}"
            )
        
        # 检查任务状态
        if task.status not in [TaskStatus.PENDING, TaskStatus.PROCESSING]:
            logger.warning(f"任务状态为 {task.status}，无法取消: {internal_task_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"任务状态为 {task.status.value}，无法取消"
            )
        
        # 取消任务（使用内部 ID，确保 Pub/Sub 通知能被执行节点识别）
        success = await task_store.cancel_task(internal_task_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="取消任务失败"
            )
        
        logger.info(f"任务取消成功: {internal_task_id}")
        
        # 构建响应数据
        data = TaskCancelData(
            task_id=external_task_id,
            status=TaskStatus.CANCELLED
        )
        
        # 包装响应
        return success_response(
            data=data.model_dump(),
            message="任务已取消"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消任务失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取消任务失败: {str(e)}"
        )


