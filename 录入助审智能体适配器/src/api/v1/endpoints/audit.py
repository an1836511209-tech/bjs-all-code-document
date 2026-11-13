"""
字段审核API端点

提供同步字段审核接口
"""

from fastapi import APIRouter, HTTPException, status
from loguru import logger
import asyncio
import time

from src.schemas.audit import (
    AuditRequest,
    AuditResponse,
    AuditData,
    AuditStatus,
    AuditSummary,
)
from src.schemas.base import success_response
from src.services.audit.service import get_audit_service
from src.api.v1.utils.task_handler import (
    generate_task_id_with_prefix,
    convert_timeout_to_seconds,
    wait_for_task_with_timeout,
    replace_task_id_in_response
)
from src.services.task_store import get_task_store
from src.schemas.task import TaskType, TaskStatus
from src.services.rule_config_service import RuleConfigService
from src.utils.extraction_type_mapper import map_extraction_type_to_business_type


router = APIRouter(prefix="/audit", tags=["规则审核"])


# 获取审核服务单例
def get_service():
    return get_audit_service()


audit_service = get_service()


@router.post(
    "/sync",
    response_model=AuditResponse,
    summary="同步规则审核",
    description="""
    对用户确认的字段和附件进行规则审核，返回完整审核结果。
    支持数据交叉验证、字段值内容审核、字段值交叉验证等多种审核类型。
    
    **处理流程：**
    1. 根据audit_type查找规则配置
    2. 检查附件是否已解析（哈希缓存）
    3. 如未解析，执行字段提取和溯源
    4. 遍历审核规则，构建LLM请求参数
    5. 调用LLM审核agent
    6. 返回审核结果和汇总
    
    **缓存机制：**
    - 系统会自动检查相同附件是否已解析过
    - 如果已解析，直接复用提取结果，加速审核
    
    **超时控制：**
    - 如果处理时间超过timeout，将返回taskId供后续查询
    - 任务会继续在后台执行，结果会保存到任务存储中
    """
)
async def audit_fields_sync(request: AuditRequest) -> AuditResponse:
    """
    同步字段审核
    
    Args:
        request: 审核请求
        
    Returns:
        AuditResponse: 审核响应
        
    Raises:
        HTTPException: 审核失败时抛出异常
    """
    try:
        logger.info(f"收到同步审核请求: audit_type={request.audit_type}, "
                   f"fields_count={len(request.confirmed_fields)}, "
                   f"files_count={len(request.files)}, "
                   f"timeout={request.timeout}ms")
        
        # 将超时时间从毫秒转换为秒
        timeout_seconds = convert_timeout_to_seconds(request.timeout)
        
        # 生成任务ID（确保在创建任务前就有ID）
        # 为审核任务添加前缀，避免与提取任务冲突
        task_id, base_task_id = generate_task_id_with_prefix(
            prefix="audit_",
            task_id=request.task_id,
            request_id=request.request_id
        )
        
        # 检查是否有正在执行的同 task_id 任务，避免重复执行
        task_store = get_task_store()
        existing_task = await task_store.get_task(task_id)
        if existing_task and existing_task.status in [TaskStatus.PENDING, TaskStatus.PROCESSING]:
            logger.info(f"任务正在执行中，跳过重复请求: task_id={task_id}, status={existing_task.status}")
            # 返回当前任务状态，保持与正常超时返回相同的数据结构
            pending_data = AuditData(
                request_id=request.request_id,
                task_id=base_task_id,
                status=AuditStatus.PROCESSING,
                audit_type=request.audit_type,
                confirmed_fields=request.confirmed_fields,
                audit_results=[],
                summary=AuditSummary(
                    total=existing_task.context.get("total_rules", 0),
                    passed=0,
                    failed=0,
                    pending=0,
                    manual_review=0
                ),
                processing_time_ms=request.timeout,
                trigger_type=request.trigger_type
            )
            return success_response(
                data=pending_data.model_dump(),
                message="任务处理中，请稍后查询结果"
        )
        
        # 提前加载规则配置，获取总规则数（用于任务进度显示）
        # 这是一个轻量操作（只读取本地 JSON 文件），不会影响性能
        rule_service = RuleConfigService()
        total_rules = 0
        config_id = request.rule_config_id
        
        try:
            if request.rule_config_id:
                config = rule_service.get_config(request.rule_config_id)
                if config:
                    total_rules = len(config.audit_rules)
                    config_id = config.id
            else:
                # 根据 audit_type 查找默认规则配置
                business_type = map_extraction_type_to_business_type(request.audit_type)
                if business_type:
                    config = rule_service.get_default_config_by_business_type(business_type)
                    if config:
                        total_rules = len(config.audit_rules)
                        config_id = config.id
        except Exception as e:
            logger.warning(f"提前加载规则配置失败（不影响任务执行）: {e}")
        
        # 创建带task_id的请求对象（任务将在Service层创建）
        request_with_task = AuditRequest(
            task_id=task_id,
            audit_type=request.audit_type,
            confirmed_fields=request.confirmed_fields,
            files=request.files,
            rule_config_id=request.rule_config_id,
            timeout=request.timeout,
            request_id=request.request_id,
            trigger_type=request.trigger_type
        )
        
        # 预先创建 PENDING 状态的任务，避免用户查询时返回404
        # 如果任务已存在（已完成状态），reset_if_exists=True 会重置状态并清除旧数据
        await task_store.create_task(
            task_id=task_id,
            task_type=TaskType.AUDIT,
            context={
                "audit_type": request.audit_type,
                "rule_config_id": config_id,
                "total_rules": total_rules  # 提前设置正确的总规则数
            },
            status_message="等待处理",
            reset_if_exists=True  # 重新执行时清除旧的result和error_message
        )
        
        # 创建任务（不使用 wait_for，避免超时后被取消）
        audit_task = asyncio.create_task(
            audit_service.audit_fields(request_with_task, enable_cache=True)
        )
        
        # 定义创建pending数据的工厂函数
        def create_pending_data():
            return AuditData(
                task_id=base_task_id,  # 返回原始task_id，不带前缀
                status=AuditStatus.PROCESSING,
                audit_type=request.audit_type,
                confirmed_fields=request.confirmed_fields,
                audit_results=[],
                summary=AuditSummary(
                    total=0,
                    passed=0,
                    failed=0,
                    pending=0,
                    manual_review=0
                ),
                processing_time_ms=int(timeout_seconds * 1000),
                trigger_type=request.trigger_type
            )
        
        # 等待任务完成或超时
        is_done, result_data = await wait_for_task_with_timeout(
            task=audit_task,
            timeout_seconds=timeout_seconds,
            base_task_id=base_task_id,
            full_task_id=task_id,
            pending_data_factory=create_pending_data,
            task_name="字段审核"
        )
        
        if is_done:
            # 任务在超时前完成
            audit_data = result_data
            
            logger.info(f"审核完成: request_id={request.request_id}, "
            f"total={audit_data.summary.total}, "
            f"passed={audit_data.summary.passed}, "
            f"failed={audit_data.summary.failed}, "
            f"pending={audit_data.summary.pending}, "
            f"manual_review={audit_data.summary.manual_review}")
            # 替换task_id为原始ID（不带前缀）
            audit_data_dict = audit_data.model_dump()
            audit_data_dict = replace_task_id_in_response(audit_data_dict, base_task_id)
            
            # 包装响应
            return success_response(
                data=audit_data_dict,
                message="success"
            )
        else:
            # 超时，但任务继续在后台运行
            pending_data = result_data
            
            return success_response(
                data=pending_data.model_dump(),
                message="任务处理中，请稍后查询结果"
            )
        
    except ValueError as e:
        logger.error(f"审核参数错误: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"审核失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"审核失败: {str(e)}"
        )

