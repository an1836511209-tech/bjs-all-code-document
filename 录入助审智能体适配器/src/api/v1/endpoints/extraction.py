"""
字段提取API端点

提供字段提取功能的RESTful API
"""

from fastapi import APIRouter, HTTPException, status
from loguru import logger
import asyncio
import time

from src.schemas.extraction import ExtractionRequest, ExtractionResponse, ExtractionData, ExtractionStatus
from src.schemas.base import success_response
from src.services.extraction.service import get_extraction_service
from src.utils.disclosure import DISCLOSURE_TYPES
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

router = APIRouter(prefix="/extraction", tags=["字段提取"])


# 获取提取服务单例
def get_service():
    return get_extraction_service()


extraction_service = get_service()


@router.post(
    "/sync",
    response_model=ExtractionResponse,
    status_code=status.HTTP_200_OK,
    summary="同步字段提取",
    description="""
    从多个附件中同步提取字段信息，返回完整结果。
    如果处理时间超过timeout，将返回taskId供后续查询。
    
    处理流程：
    1. 使用MinerU/paddle解析上传的文件
    2. 根据规则配置提取字段
    3. 对提取结果进行溯源定位
    4. 生成高亮预览图
    """,
    response_description="字段提取结果"
)
async def extract_fields_sync(
    request: ExtractionRequest
) -> ExtractionResponse:
    """
    同步字段提取
    
    Args:
        request: 提取请求
        
    Returns:
        ExtractionResponse: 提取响应
        
    Raises:
        HTTPException: 处理失败时抛出异常
    """
    try:
        logger.info(f"收到字段提取请求: request_id={request.request_id}, "
                   f"type={request.extraction_type}, "
                   f"files={len(request.files)}, "
                   f"rule_config_id={request.rule_config_id}, "
                   f"timeout={request.timeout}ms")
        
        # 将超时时间从毫秒转换为秒
        timeout_seconds = convert_timeout_to_seconds(request.timeout)
        
        # 生成任务ID（确保在创建任务前就有ID）
        # 为提取任务添加前缀，与审核任务保持一致的ID生成方式
        task_id, base_task_id = generate_task_id_with_prefix(
            prefix="extraction_",
            task_id=request.task_id,
            request_id=request.request_id
        )
        
        # 检查是否有正在执行的同 task_id 任务，避免重复执行
        task_store = get_task_store()
        existing_task = await task_store.get_task(task_id)
        if existing_task:
            active_type = existing_task.context.get("extraction_type")
            if request.extraction_type in DISCLOSURE_TYPES or active_type in DISCLOSURE_TYPES:
                active_config = existing_task.context.get("rule_config_id")
                if active_type != request.extraction_type or (
                    request.rule_config_id and active_config != request.rule_config_id
                ):
                    raise ValueError("任务ID已用于其他业务类型或规则配置")
        if existing_task and existing_task.status in [TaskStatus.PENDING, TaskStatus.PROCESSING]:
            logger.info(f"任务正在执行中，跳过重复请求: task_id={task_id}, status={existing_task.status}")
            # 返回当前任务状态，保持与正常超时返回相同的数据结构
            pending_data = ExtractionData(
                request_id=request.request_id or base_task_id or f"req_{int(time.time() * 1000)}",
                task_id=base_task_id,
                status=ExtractionStatus.PENDING,
                extraction_type=request.extraction_type,
                rule_config_id=request.rule_config_id,
                results=[],
                total_fields=existing_task.context.get("total_fields", 0),
                success_count=0,
                failed_count=0,
                processing_time_ms=request.timeout or 0
            )
            return success_response(
                data=pending_data.model_dump(),
                message="任务处理中，请稍后查询结果"
            )
        
        # 提前加载规则配置，获取总字段数（用于任务进度显示）
        # 这是一个轻量操作（只读取本地 JSON 文件），不会影响性能
        rule_service = RuleConfigService()
        total_fields = 0
        config_id = request.rule_config_id
        
        try:
            if request.rule_config_id:
                config = rule_service.get_config(request.rule_config_id)
                if config:
                    total_fields = len(config.extraction_rules)
                    config_id = config.id
            else:
                # 根据 extraction_type 查找默认规则配置
                business_type = map_extraction_type_to_business_type(request.extraction_type)
                if business_type:
                    config = rule_service.get_default_config_by_business_type(business_type)
                    if config:
                        total_fields = len(config.extraction_rules)
                        config_id = config.id
        except Exception as e:
            logger.warning(f"提前加载规则配置失败（不影响任务执行）: {e}")
        
        # 创建带task_id的请求对象
        request_with_task = ExtractionRequest(
            task_id=task_id,
            extraction_type=request.extraction_type,
            files=request.files,
            rule_config_id=request.rule_config_id,
            timeout=request.timeout,
            request_id=request.request_id
        )
        
        # 预先创建 PENDING 状态的任务，避免用户查询时返回404
        # 如果任务已存在（已完成状态），reset_if_exists=True 会重置状态并清除旧数据
        await task_store.create_task(
            task_id=task_id,
            task_type=TaskType.EXTRACTION,
            context={
                "extraction_type": request.extraction_type,
                "rule_config_id": config_id,
                "total_fields": total_fields,  # 提前设置正确的总字段数
                "base_task_id": base_task_id  # 保存原始ID用于关联查询
            },
            status_message="等待处理",
            reset_if_exists=True  # 重新执行时清除旧的result和error_message
        )
        
        # 创建任务（不使用 wait_for，避免超时后被取消）
        extraction_task = asyncio.create_task(
            extraction_service.extract_fields(request_with_task)
        )
        
        # 定义创建pending数据的工厂函数
        def create_pending_data():
            return ExtractionData(
                request_id=request.request_id or base_task_id or f"req_{int(time.time() * 1000)}",  
                task_id=base_task_id,  # 返回原始task_id，不带前缀
                status=ExtractionStatus.PENDING,
                extraction_type=request.extraction_type,
                rule_config_id=request.rule_config_id,  # 可以为None，任务完成后会有实际的配置ID
                results=[],
                total_fields=0,
                success_count=0,
                failed_count=0,
                processing_time_ms=int(timeout_seconds * 1000)
            )
        
        # 等待任务完成或超时
        is_done, result_data = await wait_for_task_with_timeout(
            task=extraction_task,
            timeout_seconds=timeout_seconds,
            base_task_id=base_task_id,
            full_task_id=task_id,
            pending_data_factory=create_pending_data,
            task_name="字段提取"
        )
        
        if is_done:
            # 任务在超时前完成
            response = result_data
            
            logger.info(f"字段提取完成: request_id={request.request_id}, "
                       f"status={response.status}, "
                       f"success={response.success_count}/{response.total_fields}")
            
            # 替换task_id为原始ID（不带前缀）
            response_data = response.model_dump()
            response_data = replace_task_id_in_response(response_data, base_task_id)
            
            # 包装响应
            return success_response(
                data=response_data,
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
        logger.error(f"字段提取参数错误: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"字段提取失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"字段提取失败: {str(e)}"
        )
