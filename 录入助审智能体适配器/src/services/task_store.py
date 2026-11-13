"""
任务存储服务（Redis版本）

提供任务的存储、查询和管理功能
使用Redis存储，支持跨节点访问
"""

import json
import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from loguru import logger

from src.schemas.task import Task, TaskType, TaskStatus
from src.services.redis.client import get_redis_client
from src.utils.cache_policy import is_cacheable_extraction_result
from src.utils.json_safe import precheck_json_serializable, safe_json_dumps, TaskSerializationError
from config.redis_config import get_redis_config


class TaskStore:
    """任务存储（基于Redis）"""
    
    _instance = None
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """初始化任务存储"""
        if self._initialized:
            return
        
        self.redis_client = get_redis_client().client
        self.config = get_redis_config()
        self.ttl_seconds = self.config.task_ttl_days * 24 * 3600  # 90天
        self._cleanup_task = None
        self._initialized = True
        
        logger.info(f"任务存储初始化完成（Redis模式，TTL={self.config.task_ttl_days}天）")
    
    def _task_key(self, task_id: str) -> str:
        """生成任务的Redis key"""
        return f"task:{task_id}"
    
    def _cache_index_key(self, files_hash: str) -> str:
        """生成缓存索引的Redis key"""
        return f"cache:hash:{files_hash}"
    
    def _type_index_key(self, task_type: TaskType, status: TaskStatus) -> str:
        """生成任务类型索引的Redis key"""
        return f"tasks:type:{task_type.value}:{status.value}"

    def _prepare_result(self, result: Any) -> Any:
        """写入前预检并清理任务 result"""
        return precheck_json_serializable(result, field_name="result")

    def _prepare_context_patch(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """写入前预检并清理 context 增量"""
        return precheck_json_serializable(context or {}, field_name="context")

    def _serialize_task(self, task: Task) -> Dict:
        """序列化任务为Redis存储格式（result/context 经 JSON 安全处理）"""
        try:
            result_json = safe_json_dumps(task.result, field_name="result") if task.result else ""
            context_json = safe_json_dumps(task.context or {}, field_name="context")
        except TaskSerializationError:
            raise
        except Exception as exc:
            raise TaskSerializationError(
                f"任务 {task.task_id} 序列化失败: {exc}"
            ) from exc

        return {
            "task_id": task.task_id,
            "task_type": task.task_type.value,
            "status": task.status.value,
            "progress": str(task.progress),
            "result": result_json,
            "error_message": task.error_message or "",
            "status_message": task.status_message or "",
            "context": context_json,
            "files_hash": task.files_hash or "",
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
            "completed_at": task.completed_at.isoformat() if task.completed_at else "",
            "cancelled": str(task.cancelled)
        }
    
    def _deserialize_task(self, data: Dict) -> Task:
        """从Redis数据反序列化任务"""
        return Task(
            task_id=data["task_id"],
            task_type=TaskType(data["task_type"]),
            status=TaskStatus(data["status"]),
            progress=float(data["progress"]),
            result=json.loads(data["result"]) if data["result"] else None,
            error_message=data["error_message"] or None,
            status_message=data["status_message"] or None,
            context=json.loads(data["context"]),
            files_hash=data["files_hash"] or None,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data["completed_at"] else None,
            cancelled=data["cancelled"] == "True"
        )
    
    async def create_task(
        self,
        task_id: str,
        task_type: TaskType,
        context: dict = None,
        files_hash: str = None,
        status_message: str = None,
        reset_if_exists: bool = False
    ) -> Task:
        """
        创建新任务
        
        Args:
            task_id: 任务ID
            task_type: 任务类型
            context: 任务上下文数据
            files_hash: 附件哈希值（用于缓存查询）
            status_message: 状态消息（如：等待处理）
            reset_if_exists: 如果任务已存在，是否重置状态（清除旧结果和错误）
            
        Returns:
            Task: 创建的任务
        """
        task_key = self._task_key(task_id)
        
        # 检查任务是否已存在
        existing_data = self.redis_client.hgetall(task_key)
        
        if existing_data:
            existing_task = self._deserialize_task(existing_data)
            logger.warning(f"任务已存在: {task_id}")
            
            now = datetime.now()
            
            # 更新 files_hash（如果提供了新的且与现有不同）
            if files_hash and existing_task.files_hash != files_hash:
                old_hash = existing_task.files_hash[:16] + "..." if existing_task.files_hash else "None"
                new_hash = files_hash[:16] + "..."
                logger.info(f"更新任务的 files_hash: {task_id}, 旧={old_hash}, 新={new_hash}")
                existing_task.files_hash = files_hash
            
            # 如果需要重置状态（用于重新执行任务的场景）
            if reset_if_exists:
                existing_task.status = TaskStatus.PENDING
                existing_task.progress = 0.0
                existing_task.result = None
                existing_task.error_message = None
                existing_task.completed_at = None
                if context:
                    existing_task.context.update(self._prepare_context_patch(context))
                if status_message:
                    existing_task.status_message = status_message
                logger.info(f"重置任务状态: {task_id}")
            
            existing_task.updated_at = now
            
            # 保存到Redis
            task_data = self._serialize_task(existing_task)
            self.redis_client.hset(task_key, mapping=task_data)
            self.redis_client.expire(task_key, self.ttl_seconds)
            
            return existing_task
        
        # 创建新任务
        now = datetime.now()
        task = Task(
            task_id=task_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            progress=0.0,
            created_at=now,
            updated_at=now,
            context=self._prepare_context_patch(context or {}),
            files_hash=files_hash,
            status_message=status_message
        )
        
        # 保存到Redis
        task_data = self._serialize_task(task)
        self.redis_client.hset(task_key, mapping=task_data)
        self.redis_client.expire(task_key, self.ttl_seconds)
        
        # 添加到类型索引
        index_key = self._type_index_key(task_type, TaskStatus.PENDING)
        self.redis_client.zadd(index_key, {task_id: now.timestamp()})
        self.redis_client.expire(index_key, self.ttl_seconds)
        
        if files_hash:
            logger.info(f"创建任务: {task_id}, 类型: {task_type}, 文件哈希: {files_hash[:16]}...")
        else:
            logger.info(f"创建任务: {task_id}, 类型: {task_type}")
        
        return task
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """
        获取任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            Optional[Task]: 任务对象，不存在返回None
        """
        task_key = self._task_key(task_id)
        data = self.redis_client.hgetall(task_key)
        
        if not data:
            return None
        
        return self._deserialize_task(data)
    
    async def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[float] = None,
        result: Optional[any] = None,
        error_message: Optional[str] = None,
        context: Optional[dict] = None,
        status_message: Optional[str] = None,
        clear_result: bool = False,
        clear_error_message: bool = False,
        files_hash: Optional[str] = None,
        cancelled: Optional[bool] = None,
        index_cache: Optional[bool] = None
    ) -> Optional[Task]:
        """
        更新任务状态
        
        Args:
            task_id: 任务ID
            status: 新状态
            progress: 新进度
            result: 任务结果
            error_message: 错误信息
            context: 任务上下文数据（会合并到现有context中）
            status_message: 当前进度阶段描述（如：正在解析文件...）
            clear_result: 是否清除任务结果（result设置为None）
            clear_error_message: 是否清除错误信息（error_message设置为None）
            files_hash: 附件哈希值（用于缓存查询）
            cancelled: 是否取消任务
            index_cache: 是否写入 files_hash 缓存索引；None 时按提取结果质量自动判定
            
        Returns:
            Optional[Task]: 更新后的任务，不存在返回None
        """
        task = await self.get_task(task_id)
        if not task:
            logger.warning(f"任务不存在: {task_id}")
            return None
        
        # 如果任务已取消，不允许更新
        if task.cancelled and status != TaskStatus.CANCELLED:
            logger.warning(f"任务已取消，不允许更新: {task_id}")
            return task
        
        now = datetime.now()
        old_status = task.status
        
        if status is not None:
            task.status = status
            # 如果任务状态从终态重新变回PENDING或PROCESSING，清除completed_at
            if status in [TaskStatus.PENDING, TaskStatus.PROCESSING]:
                task.completed_at = None
        
        if progress is not None:
            task.progress = progress
        
        if clear_result:
            task.result = None
        elif result is not None:
            task.result = self._prepare_result(result)
        
        if clear_error_message:
            task.error_message = None
        elif error_message is not None:
            task.error_message = error_message
        
        if context is not None:
            # 合并 context（不覆盖，而是更新）；写入前预检增量
            task.context.update(self._prepare_context_patch(context))
        
        if status_message is not None:
            task.status_message = status_message
        
        if files_hash is not None:
            task.files_hash = files_hash
        
        if cancelled is not None:
            task.cancelled = cancelled
        
        task.updated_at = now
        
        # 如果任务完成或失败，设置完成时间
        if status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED]:
            if task.completed_at is None:
                task.completed_at = now
        
        # 保存到Redis
        task_key = self._task_key(task_id)
        task_data = self._serialize_task(task)
        self.redis_client.hset(task_key, mapping=task_data)
        self.redis_client.expire(task_key, self.ttl_seconds)
        
        # 如果状态变更，更新类型索引
        if status is not None and status != old_status:
            # 从旧状态索引中移除
            old_index_key = self._type_index_key(task.task_type, old_status)
            self.redis_client.zrem(old_index_key, task_id)
            
            # 添加到新状态索引
            new_index_key = self._type_index_key(task.task_type, status)
            self.redis_client.zadd(new_index_key, {task_id: now.timestamp()})
            self.redis_client.expire(new_index_key, self.ttl_seconds)
        
        # 如果任务完成，且是提取任务，按质量策略更新缓存索引
        if status == TaskStatus.COMPLETED and task.task_type == TaskType.EXTRACTION and task.files_hash:
            should_index = (
                index_cache
                if index_cache is not None
                else is_cacheable_extraction_result(task.result)
            )
            if should_index:
                cache_key = self._cache_index_key(task.files_hash)
                self.redis_client.set(cache_key, task_id, ex=self.ttl_seconds)
                logger.debug(f"更新缓存索引: {task.files_hash[:16]}... -> {task_id}")
            else:
                logger.debug(
                    f"提取结果未达缓存质量阈值 (success+pending > failed)，"
                    f"跳过缓存索引: {task.files_hash[:16]}..."
                )
        
        logger.debug(f"更新任务: {task_id}, 状态: {status}, 进度: {progress}, 阶段: {status_message}")
        
        return task
    
    async def cancel_task(self, task_id: str) -> bool:
        """
        取消任务并通过Pub/Sub通知执行节点
        
        Args:
            task_id: 任务ID
            
        Returns:
            bool: 是否成功取消
        """
        task = await self.get_task(task_id)
        if not task:
            logger.warning(f"任务不存在: {task_id}")
            return False
        
        # 只有进行中或等待中的任务可以取消
        if task.status not in [TaskStatus.PENDING, TaskStatus.PROCESSING]:
            logger.warning(f"任务状态为 {task.status}，无法取消: {task_id}")
            return False
        
        # 更新任务状态
        await self.update_task(
            task_id,
            status=TaskStatus.CANCELLED,
            cancelled=True
        )
        
        # 发布取消通知
        self.redis_client.publish("cancel:task", f"{task_id}:{int(time.time())}")
        logger.info(f"已发布任务取消通知: {task_id}")
        
        return True
    
    async def delete_task(self, task_id: str) -> bool:
        """
        删除任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            bool: 是否成功删除
        """
        task = await self.get_task(task_id)
        if not task:
            return False
        
        task_key = self._task_key(task_id)
        
        # 从类型索引中移除
        index_key = self._type_index_key(task.task_type, task.status)
        self.redis_client.zrem(index_key, task_id)
        
        # 如果有files_hash，删除缓存索引
        if task.files_hash:
            cache_key = self._cache_index_key(task.files_hash)
            # 只有当缓存索引指向当前任务时才删除
            cached_task_id = self.redis_client.get(cache_key)
            if cached_task_id == task_id:
                self.redis_client.delete(cache_key)
        
        # 删除任务数据
        result = self.redis_client.delete(task_key)
        
        if result:
            logger.info(f"删除任务: {task_id}")
            return True
        return False
    
    async def list_tasks(
        self,
        task_type: Optional[TaskType] = None,
        status: Optional[TaskStatus] = None,
        limit: int = 100
    ) -> List[Task]:
        """
        列出任务
        
        Args:
            task_type: 任务类型过滤
            status: 状态过滤
            limit: 最大返回数量
            
        Returns:
            List[Task]: 任务列表
        """
        tasks = []
        
        if task_type and status:
            # 使用类型索引查询
            index_key = self._type_index_key(task_type, status)
            # 按时间倒序获取任务ID
            task_ids = self.redis_client.zrevrange(index_key, 0, limit - 1)
            
            for task_id in task_ids:
                task = await self.get_task(task_id)
                if task:
                    tasks.append(task)
        else:
            # 扫描所有任务（性能较低，仅在必要时使用）
            cursor = 0
            while True:
                cursor, keys = self.redis_client.scan(cursor, match="task:*", count=100)
                
                for key in keys:
                    task_id = key.replace("task:", "")
                    task = await self.get_task(task_id)
                    
                    if not task:
                        continue
                    
                    # 应用过滤条件
                    if task_type and task.task_type != task_type:
                        continue
                    if status and task.status != status:
                        continue
                    
                    tasks.append(task)
                    
                    if len(tasks) >= limit:
                        break
                
                if cursor == 0 or len(tasks) >= limit:
                    break
            
            # 按创建时间倒序排序
            tasks.sort(key=lambda t: t.created_at, reverse=True)
        
        return tasks[:limit]
    
    async def get_queue_position(self, task_id: str) -> int:
        """
        获取任务在队列中的位置
        
        Args:
            task_id: 任务ID
            
        Returns:
            int: 排队位置（从1开始），0表示不在队列中
        """
        task = await self.get_task(task_id)
        if not task or task.status != TaskStatus.PENDING:
            return 0
        
        # 使用类型索引查询
        index_key = self._type_index_key(task.task_type, TaskStatus.PENDING)
        
        # 获取任务在有序集合中的排名
        rank = self.redis_client.zrank(index_key, task_id)
        
        if rank is None:
            return 0
        
        return rank + 1  # 排名从0开始，位置从1开始
    
    async def get_pending_queue_count(self, task_type: Optional[TaskType] = None) -> int:
        """
        获取当前排队等待的任务总数
        
        Args:
            task_type: 可选的任务类型过滤器
        
        Returns:
            int: 排队中的任务总数
        """
        if task_type:
            index_key = self._type_index_key(task_type, TaskStatus.PENDING)
            return self.redis_client.zcard(index_key)
        else:
            # 统计所有类型的PENDING任务
            total = 0
            for tt in TaskType:
                index_key = self._type_index_key(tt, TaskStatus.PENDING)
                total += self.redis_client.zcard(index_key)
            return total
    
    async def get_processing_count(self, task_type: Optional[TaskType] = None) -> int:
        """
        获取当前正在处理的任务总数
        
        Args:
            task_type: 可选的任务类型过滤器
        
        Returns:
            int: 正在处理的任务总数
        """
        if task_type:
            index_key = self._type_index_key(task_type, TaskStatus.PROCESSING)
            return self.redis_client.zcard(index_key)
        else:
            # 统计所有类型的PROCESSING任务
            total = 0
            for tt in TaskType:
                index_key = self._type_index_key(tt, TaskStatus.PROCESSING)
                total += self.redis_client.zcard(index_key)
            return total
    
    async def find_task_by_files_hash(
        self,
        files_hash: str,
        only_completed: bool = True
    ) -> Optional[Task]:
        """
        根据附件哈希查找历史提取任务（跨节点共享）
        
        Args:
            files_hash: 附件哈希值
            only_completed: 是否只返回已完成的任务
            
        Returns:
            Optional[Task]: 找到的任务，未找到返回None
        """
        if not files_hash:
            return None
        
        # 从缓存索引查找
        cache_key = self._cache_index_key(files_hash)
        cached_task_id = self.redis_client.get(cache_key)
        
        if cached_task_id:
            task = await self.get_task(cached_task_id)
            if task and task.task_type == TaskType.EXTRACTION:
                if not only_completed or task.status == TaskStatus.COMPLETED:
                    logger.info(
                        f"找到文件哈希 {files_hash[:16]}... 的历史任务: {task.task_id}, "
                        f"状态: {task.status}, 创建时间: {task.created_at}"
                    )
                    return task
        
        logger.debug(f"未找到文件哈希为 {files_hash[:16]}... 的历史任务")
        return None
    
    async def cleanup_old_tasks(self, max_age_days: int = 90):
        """
        清理旧任务（仅清理已完成状态的任务）
        
        Args:
            max_age_days: 最大保留天数（默认90天）
            
        Returns:
            int: 清理的任务数量
        """
        now = datetime.now()
        cutoff_time = now - timedelta(days=max_age_days)
        cutoff_timestamp = cutoff_time.timestamp()
        
        deleted_count = 0
        status_count = {}
        
        # 对每种任务类型和终态状态进行清理
        terminal_statuses = [
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.TIMEOUT,
            TaskStatus.CANCELLED
        ]
        
        for task_type in TaskType:
            for status in terminal_statuses:
                index_key = self._type_index_key(task_type, status)
                
                # 获取超过保留期的任务ID
                old_task_ids = self.redis_client.zrangebyscore(
                    index_key,
                    '-inf',
                    cutoff_timestamp
                )
                
                for task_id in old_task_ids:
                    success = await self.delete_task(task_id)
                    if success:
                        deleted_count += 1
                        status_name = status.value
                        status_count[status_name] = status_count.get(status_name, 0) + 1
        
        if deleted_count > 0:
            status_summary = ", ".join([f"{status}={count}" for status, count in status_count.items()])
            logger.info(
                f"清理 {deleted_count} 个超过 {max_age_days} 天的已完成任务 "
                f"| 状态分布: {status_summary}"
            )
        
        return deleted_count
    
    async def _cleanup_loop(self, interval_days: int = 1, max_age_days: int = 90):
        """
        定期清理任务循环
        
        Args:
            interval_days: 清理间隔（天）
            max_age_days: 最大保留天数
        """
        while True:
            try:
                # 等待指定天数
                await asyncio.sleep(interval_days * 24 * 60 * 60)
                
                # 执行清理
                deleted_count = await self.cleanup_old_tasks(max_age_days)
                
                if deleted_count > 0:
                    logger.info(f"定期任务清理完成，删除 {deleted_count} 个任务")
                    
            except asyncio.CancelledError:
                logger.info("任务存储清理任务已停止")
                break
            except Exception as e:
                logger.error(f"任务清理循环异常: {e}", exc_info=True)
    
    def start_cleanup_task(self, interval_days: int = 1, max_age_days: int = 90):
        """
        启动定期清理任务
        
        Args:
            interval_days: 清理间隔（天），默认每天清理一次
            max_age_days: 最大保留天数，默认90天
        """
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(
                self._cleanup_loop(interval_days, max_age_days)
            )
            logger.info(f"任务存储定期清理任务已启动（每{interval_days}天清理一次，保留{max_age_days}天内的任务）")
    
    def stop_cleanup_task(self):
        """停止定期清理任务"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            logger.info("任务存储定期清理任务已停止")


# 全局单例
task_store = TaskStore()


def get_task_store() -> TaskStore:
    """获取任务存储实例"""
    return task_store
