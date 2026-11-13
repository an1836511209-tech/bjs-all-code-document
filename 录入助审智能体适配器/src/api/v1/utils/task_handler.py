"""
任务处理公共工具

提供API层的任务处理公共逻辑，避免代码重复
"""

import asyncio
import uuid
import time
from typing import Tuple, Optional, Callable, Any, TYPE_CHECKING
from loguru import logger

if TYPE_CHECKING:
    from src.schemas.task import Task, TaskType
    from src.services.task_store import TaskStore


def generate_task_id_with_prefix(
    prefix: str,
    task_id: Optional[str] = None,
    request_id: Optional[str] = None
) -> Tuple[str, str]:
    """
    生成带前缀的任务ID
    
    Args:
        prefix: 任务ID前缀（如 "extraction_" 或 "audit_"）
        task_id: 用户提供的task_id（可选）
        request_id: 用户提供的request_id（可选）
        
    Returns:
        Tuple[str, str]: (完整task_id, 原始base_task_id)
        
    Examples:
        >>> generate_task_id_with_prefix("extraction_", request_id="req_123")
        ("extraction_req_123", "req_123")
        
        >>> generate_task_id_with_prefix("audit_")
        ("audit_task_abc123...", "task_abc123...")
    """
    # 生成基础任务ID
    base_task_id = task_id or request_id or f"task_{uuid.uuid4().hex[:16]}"
    
    # 添加前缀
    full_task_id = f"{prefix}{base_task_id}"
    
    return full_task_id, base_task_id


def convert_timeout_to_seconds(timeout_ms: Optional[int], default_seconds: float = 1) -> float:
    """
    将毫秒超时转换为秒
    
    Args:
        timeout_ms: 超时时间（毫秒），None表示使用默认值
        default_seconds: 默认超时时间（秒），默认1秒（对应 1000ms）
        
    Returns:
        float: 超时时间（秒）
        
    Examples:
        >>> convert_timeout_to_seconds(5000)
        5.0
        
        >>> convert_timeout_to_seconds(None)
        1.0
    """
    if timeout_ms is None:
        return default_seconds
    return timeout_ms / 1000


async def wait_for_task_with_timeout(
    task: asyncio.Task,
    timeout_seconds: float,
    base_task_id: str,
    full_task_id: str,
    pending_data_factory: Callable[[], Any],
    task_name: str = "任务"
) -> Tuple[bool, Any]:
    """
    等待任务完成或超时
    
    使用 asyncio.wait 而不是 wait_for，以避免超时后取消任务。
    任务会继续在后台执行。
    
    Args:
        task: 异步任务
        timeout_seconds: 超时时间（秒）
        base_task_id: 原始任务ID（不带前缀）
        full_task_id: 完整任务ID（带前缀）
        pending_data_factory: 创建pending状态数据的工厂函数
        task_name: 任务名称（用于日志），默认"任务"
        
    Returns:
        Tuple[bool, Any]: (是否完成, 结果数据)
            - 如果完成: (True, task.result())
            - 如果超时: (False, pending_data)
            
    Examples:
        >>> def create_pending_data():
        ...     return {"task_id": "123", "status": "pending"}
        >>> 
        >>> is_done, result = await wait_for_task_with_timeout(
        ...     task=my_task,
        ...     timeout_seconds=30,
        ...     base_task_id="req_123",
        ...     full_task_id="extraction_req_123",
        ...     pending_data_factory=create_pending_data
        ... )
    """
    # 使用 wait 等待任务完成或超时，但不取消任务
    done, pending = await asyncio.wait(
        {task},
        timeout=timeout_seconds,
        return_when=asyncio.FIRST_COMPLETED
    )
    
    if done:
        # 任务在超时前完成
        result = task.result()
        logger.info(f"{task_name}完成: task_id={full_task_id}")
        return True, result
    else:
        # 超时，但任务继续在后台运行
        logger.warning(
            f"{task_name}超时，任务转为后台继续执行: task_id={full_task_id}, "
            f"timeout={timeout_seconds}s"
        )
        
        # 创建pending状态的响应数据
        pending_data = pending_data_factory()
        return False, pending_data


def external_task_id(task_id: str) -> str:
    """将内部任务 ID 转为对外 ID（去掉 extraction_/audit_/classification_ 前缀）。"""
    for prefix in ("extraction_", "audit_", "classification_"):
        if task_id.startswith(prefix):
            return task_id[len(prefix):]
    return task_id


async def resolve_task_by_id(
    task_store: "TaskStore",
    task_id: str,
    task_type: Optional["TaskType"] = None,
) -> Tuple[Optional["Task"], str, str]:
    """
    根据对外 task_id 解析 Redis 中的任务。

    与查询/取消接口一致：可按 type 指定 extraction、audit 或 classification；
    未指定时依次查 extraction_、audit_、classification_ 前缀。

    Returns:
        (task, internal_task_id, external_task_id)
    """
    from src.schemas.task import TaskType

    external_id = external_task_id(task_id)

    if task_id != external_id:
        task = await task_store.get_task(task_id)
        if task:
            return task, task_id, external_id

    if task_type == TaskType.EXTRACTION:
        internal_task_id = f"extraction_{external_id}"
        task = await task_store.get_task(internal_task_id)
    elif task_type == TaskType.AUDIT:
        internal_task_id = f"audit_{external_id}"
        task = await task_store.get_task(internal_task_id)
    elif task_type == TaskType.CLASSIFICATION:
        internal_task_id = f"classification_{external_id}"
        task = await task_store.get_task(internal_task_id)
    else:
        internal_task_id = f"extraction_{external_id}"
        task = await task_store.get_task(internal_task_id)
        if not task:
            internal_task_id = f"audit_{external_id}"
            task = await task_store.get_task(internal_task_id)
        if not task:
            internal_task_id = f"classification_{external_id}"
            task = await task_store.get_task(internal_task_id)

    return task, internal_task_id, external_id


def replace_task_id_in_response(
    response_data: dict,
    base_task_id: str
) -> dict:
    """
    替换响应数据中的task_id为原始ID（不带前缀）
    
    Args:
        response_data: 响应数据字典
        base_task_id: 原始任务ID（不带前缀）
        
    Returns:
        dict: 更新后的响应数据
        
    Examples:
        >>> data = {"task_id": "extraction_req_123", "status": "completed"}
        >>> replace_task_id_in_response(data, "req_123")
        {"task_id": "req_123", "status": "completed"}
    """
    if "task_id" in response_data:
        response_data["task_id"] = base_task_id
    return response_data

