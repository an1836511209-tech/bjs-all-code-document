"""
字段提取服务

实现字段提取的主流程：
1. 文件解析（MinerU）
2. 规则匹配
3. LLM字段提取
4. 字段溯源
5. PDF高亮生成
"""

import asyncio
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union, Set, TYPE_CHECKING, Callable
from loguru import logger

if TYPE_CHECKING:
    from src.services.extraction.pipeline import FileTypeParseContext

from config.llm_config import LLMConfig
from config.paddle_config import get_paddle_config
from config.env_config import get_current_env
from src.services.llm.client import LLMClient, UnifiedExtractionAgent
from src.services.llm.models import UnifiedExtractionResult
from src.utils.anchor_markdown_converter import AnchorMarkdownConverter, SegmentInfo
from src.services.mineru.client import MinerUClient
from src.services.paddle.client import PaddleClient, PaddleError
from src.services.tika.client import TikaClient
from src.services.rule_config_service import RuleConfigService
from src.utils.disclosure import (
    DISCLOSURE_TYPES,
    disclosure_prompt,
    format_disclosure_results,
    match_cover_field,
    validate_application,
)
from src.services.task_store import get_task_store
from src.schemas.task import TaskType, TaskStatus
from src.utils.extraction_type_mapper import (
    get_available_extraction_types,
    map_extraction_type_to_business_type,
)
from src.schemas.extraction import (
    ExtractionRequest,
    ExtractionFileInput,
    ExtractionData,
    FieldExtractionResult,
    ExtractedFieldValue,
    SourceInfo,
    ExtractStatus,  # 单个来源的提取状态
    FieldExtractionStatus,  # 字段级别的聚合状态
    TaskExtractionStatus,  # 任务级别的聚合状态
    ExtractionStatus,  # 向后兼容别名
)
from src.schemas.rule_config import ExtractionRule, FieldType
from src.schemas.file import FileType, FILE_TYPE_LABELS
from src.schemas.cascade_config import CascadeConfig, ChainCascadeConfig, ConditionalCascadeConfig, CascadeType
from src.utils.pdf_highlighter import PDFHighlighter
from src.utils.paddle_pdf_highlighter import PaddlePDFHighlighter
from src.utils.file_handler import FileHandler
from src.utils.converters.image_converter import ImageToPDFConverter
from src.utils.converters.word_converter import WordToPDFConverter
from src.utils.file_hash import FileHasher
from src.utils.rag_handler import RagHandler
from src.utils.excel_anchor_context import (
    ExcelAnchorContext,
    build_excel_source_fields,
    resolve_anchor_context,
)
from src.utils.file_processor import download_files_and_compute_hashes
from src.utils.text_normalizer import normalize_number, normalize_for_comparison
from src.utils.cache_policy import is_cacheable_extraction_result


# 全局单例实例
_extraction_service_instance: Optional['ExtractionService'] = None


class ExtractionService:
    """字段提取服务"""
    
    def __init__(self):
        """初始化提取服务"""
        self.rule_service = RuleConfigService()
        
        # 使用单例HTTP客户端
        from src.services.paddle.client import get_paddle_client
        from src.services.mineru.client import get_mineru_client
        from src.services.tika.client import get_tika_client
        
        self.paddle_client = get_paddle_client()
        self.paddle_config = get_paddle_config()
        
        # MinerU 客户端（降级备选）
        self.mineru_client = get_mineru_client()
        
        self.task_store = get_task_store()
        
        # Tika 客户端
        self.tika_client = get_tika_client()
        
        # LLM配置
        self.llm_config = LLMConfig()
        self.concurrency_config = self.llm_config.get_concurrency_config()
        
        # LLM 调用专用 Semaphore（控制实际 LLM 请求的并发数）
        self._llm_semaphore = asyncio.Semaphore(
            self.concurrency_config.unified_extraction_workers
        )
        
        # RAG处理器
        self.rag_handler = RagHandler()
    
    @staticmethod
    def _safe_get(obj, key: str, default=None):
        """安全获取字段值（支持字典和对象）
        
        Args:
            obj: 字典或对象
            key: 字段名
            default: 默认值
            
        Returns:
            字段值或默认值
        """
        if isinstance(obj, dict):
            return obj.get(key, default)
        else:
            return getattr(obj, key, default)
    
    @staticmethod
    def _calculate_field_statistics(results: List) -> Dict[str, int]:
        """从 results 列表计算字段统计信息
        
        统计规则：
        - SUCCESS: 提取成功的字段
        - PENDING: 待确认的字段
        - FAILED: 真正失败的字段，排除：
          1. 材料中不存在的字段（error_message == "未找到提取结果"）
          2. 级联未触发的字段（error_message 以 "级联未触发" 开头）
          3. 参考材料文件不存在的字段（error_message 包含 "未找到参考材料对应的文件"）
          4. 级联首字段依赖的文件不存在（error_message 包含 "级联首字段" 和 "依赖的文件不存在"）
        
        Args:
            results: 字段提取结果列表（可以是字典或对象）
            
        Returns:
            统计信息字典：
            {
                "success_count": int,
                "pending_count": int,
                "failed_count": int,
                "total_fields": int
            }
        """
        if not results:
            return {
                "success_count": 0,
                "pending_count": 0,
                "failed_count": 0,
                "total_fields": 0
            }
        
        # 使用 _safe_get 支持字典和对象
        success_count = sum(
            1 for r in results 
            if ExtractionService._safe_get(r, "field_status") == FieldExtractionStatus.SUCCESS
        )
        pending_count = sum(
            1 for r in results 
            if ExtractionService._safe_get(r, "field_status") == FieldExtractionStatus.PENDING
        )
        
        # 只计算真正提取失败的字段
        failed_count = sum(
            1 for r in results 
            if ExtractionService._safe_get(r, "field_status") == FieldExtractionStatus.FAILED 
            and ExtractionService._safe_get(r, "error_message") != "未找到提取结果"
            and not (ExtractionService._safe_get(r, "error_message") or "").startswith("级联未触发")
            and "未找到参考材料对应的文件" not in (ExtractionService._safe_get(r, "error_message") or "")
            and not (
                "级联首字段" in (ExtractionService._safe_get(r, "error_message") or "") 
                and "依赖的文件不存在" in (ExtractionService._safe_get(r, "error_message") or "")
            )
        )
        
        total_fields = success_count + pending_count + failed_count
        
        return {
            "success_count": success_count,
            "pending_count": pending_count,
            "failed_count": failed_count,
            "total_fields": total_fields
        }
    
    def _get_task_statistics(
        self,
        cached_task: Optional[Any] = None,
        cached_result: Optional[Dict] = None
    ) -> Dict[str, int]:
        """统一获取任务统计信息的方法
        
        优先级：
        1. cached_task.context（最高优先级，包含高亮任务的正确统计）
        2. 从 cached_result["results"] 重新计算（次优先级）
        3. 使用 cached_result 中存储的统计字段（最后降级）
        
        Args:
            cached_task: 缓存的任务对象（可选）
            cached_result: 缓存的结果字典（可选）
            
        Returns:
            统计信息字典：
            {
                "total_fields": int,
                "completed_count": int,
                "success_count": int,
                "pending_count": int,
                "failed_count": int
            }
        """
        # 优先级1：使用 context 中的统计
        if cached_task and cached_task.context:
            ctx_total = cached_task.context.get("total_fields", 0)
            ctx_completed = cached_task.context.get("completed_count", 0)
            if ctx_total > 0:
                # context 中有正确的 total_fields，但可能没有详细的状态统计
                # 尝试从 results 获取详细状态
                if cached_result and "results" in cached_result and isinstance(cached_result.get("results"), list):
                    stats = self._calculate_field_statistics(cached_result["results"])
                    return {
                        "total_fields": ctx_total,  # 使用 context 中的值
                        "completed_count": ctx_completed,  # 使用 context 中的值
                        "success_count": stats["success_count"],
                        "pending_count": stats["pending_count"],
                        "failed_count": stats["failed_count"]
                    }
                else:
                    # 无法获取详细状态，返回基本统计
                    logger.info(f"使用 context 中的统计值：total_fields={ctx_total}, completed_count={ctx_completed}")
                    return {
                        "total_fields": ctx_total,
                        "completed_count": ctx_completed,
                        "success_count": 0,
                        "pending_count": 0,
                        "failed_count": 0
                    }
        
        # 优先级2：从 results 计算
        if cached_result and "results" in cached_result and isinstance(cached_result.get("results"), list):
            stats = self._calculate_field_statistics(cached_result["results"])
            logger.info(f"从 results 计算统计值：total_fields={stats['total_fields']}")
            return {
                "total_fields": stats["total_fields"],
                "completed_count": stats["total_fields"],  # 缓存场景下已全部完成
                "success_count": stats["success_count"],
                "pending_count": stats["pending_count"],
                "failed_count": stats["failed_count"]
            }
        
        # 优先级3：从 cached_result 的统计字段获取
        if cached_result and isinstance(cached_result, dict):
            total_fields = cached_result.get("total_fields", 0)
            success_count = cached_result.get("success_count", 0)
            pending_count = cached_result.get("pending_count", 0)
            failed_count = cached_result.get("failed_count", 0)
            completed_count = success_count + pending_count + failed_count
            logger.warning(f"使用 cached_result 中的统计字段（降级）")
            return {
                "total_fields": total_fields,
                "completed_count": completed_count,
                "success_count": success_count,
                "pending_count": pending_count,
                "failed_count": failed_count
            }
        
        # 默认返回空统计
        logger.warning("无法获取统计信息，返回默认值")
        return {
            "total_fields": 0,
            "completed_count": 0,
            "success_count": 0,
            "pending_count": 0,
            "failed_count": 0
        }
    
    def _strip_extracted_values(
        self,
        field_results: List['FieldExtractionResult']
    ) -> List['FieldExtractionResult']:
        """
        清理所有字段提取值的首尾空格
        
        Args:
            field_results: 字段提取结果列表
            
        Returns:
            处理后的字段提取结果列表（原地修改）
        """
        for result in field_results:
            if result.values:
                for value in result.values:
                    if value.extracted_value is not None and isinstance(value.extracted_value, str):
                        value.extracted_value = value.extracted_value.strip()
        return field_results
    
    async def extract_fields(
        self,
        request: ExtractionRequest,
        enable_cache: Optional[bool] = None,
        parsed_files_cache: Optional[Dict[str, Any]] = None,
        downloaded_files_cache: Optional[Dict[str, bytes]] = None
    ) -> ExtractionData:
        """
        执行字段提取
        
        主流程：
        0. 计算附件哈希，尝试从缓存中获取结果（如果enable_cache=True）
        1. 创建任务（如果提供了task_id或request_id）
        2. 加载规则配置
        3. 解析所有文件（MinerU），可复用预解析的文件缓存
        4. 并发提取字段
        5. 并发溯源字段
        6. 生成PDF高亮
        7. 更新任务状态
        
        Args:
            request: 提取请求
            enable_cache: 是否启用缓存查询（None表示使用全局配置）
            parsed_files_cache: 预解析的文件缓存（key为file_url，value为parse_result），
                用于避免重复解析文件，通常来自审核流程的文件分类阶段
            downloaded_files_cache: 已下载的文件内容缓存（key为file_url，value为bytes），
                用于避免重复下载文件，通常来自审核服务的哈希计算阶段
            
        Returns:
            ExtractionData: 提取响应数据
        """
        from config.env_config import is_extraction_cache_enabled
        from config.api_config import get_rate_limit_config
        from src.api.v1.middleware.rate_limiter import rate_limit_context
        
        # 生成任务ID（在信号量之前就需要知道 task_id）
        task_id = request.task_id or request.request_id
        
        # ============================================================
        # 第一阶段：缓存检查（在获取信号量之前）
        # 这样缓存命中的请求可以快速返回，不会被排队机制阻塞
        # ============================================================
        
        # 确定是否启用缓存
        # 优先级：参数显式指定 > 全局配置
        if enable_cache is None:
            enable_cache = is_extraction_cache_enabled()
        
        is_disclosure = request.extraction_type in DISCLOSURE_TYPES
        if is_disclosure:
            # 披露申请书每次都先校验内容，避免从一期结果缓存跳过校验。
            enable_cache = False

        # 用于存储已下载的文件内容（避免重复下载）
        # 如果调用方已提供缓存，则复用；否则创建新的空字典
        _downloaded_files_cache: Dict[str, bytes] = downloaded_files_cache.copy() if downloaded_files_cache else {}
        
        # 检查是否所有文件都有 file_content_hash
        files_with_hash = request.files
        all_have_hash = all(
            hasattr(f, 'file_content_hash') and f.file_content_hash
            for f in request.files
        )
        
        # 如果有文件没有哈希，需要先下载文件并计算哈希
        if not all_have_hash and enable_cache:
            logger.info("部分文件没有 content_hash，开始下载文件并计算哈希用于缓存查询")
            files_with_hash, new_downloads = await download_files_and_compute_hashes(
                request.files,
                ExtractionFileInput,
                existing_cache=_downloaded_files_cache  # 传入已有缓存，避免重复下载
            )
            # 合并新下载的文件到缓存
            _downloaded_files_cache.update(new_downloads)
            logger.info(f"文件哈希计算完成，已下载 {len(new_downloads)} 个文件（复用 {len(_downloaded_files_cache) - len(new_downloads)} 个）")
        
        # 计算附件哈希（用于缓存查询）
        # 只基于文件内容哈希计算，与 extraction_type/rule_config_id 无关
        files_hash = None if is_disclosure else FileHasher.compute_files_hash(files=files_with_hash)
        
        # 尝试从缓存中获取结果（在获取信号量之前）
        if enable_cache and files_hash:
            cached_task = await self.task_store.find_task_by_files_hash(
                files_hash=files_hash,
                only_completed=True
            )
            
            if cached_task and cached_task.result:
                cached_result_raw = (
                    cached_task.result.copy()
                    if isinstance(cached_task.result, dict)
                    else cached_task.result
                )
                if not is_cacheable_extraction_result(cached_result_raw):
                    logger.info(
                        f"找到历史任务 {cached_task.task_id}，"
                        f"但提取质量未达缓存阈值 (success+pending > failed)，跳过缓存复用"
                    )
                else:
                    logger.info(
                        f"找到缓存结果，直接返回历史任务 {cached_task.task_id} 的结果 "
                        f"(缓存命中，无需排队)"
                    )

                    # 复用历史结果，但更新request_id和task_id
                    cached_result = cached_result_raw
                    if isinstance(cached_result, dict):
                        # 更新请求ID和任务ID
                        if request.request_id:
                            cached_result["request_id"] = request.request_id
                        if task_id:
                            cached_result["task_id"] = task_id
                        cached_result["from_cache"] = True
                        cached_result["cached_task_id"] = cached_task.task_id

                    # 更新当前任务的存储状态和结果，使任务查询接口可以获取到缓存结果
                    if task_id:
                        # 使用统一的统计方法获取字段统计信息
                        stats = self._get_task_statistics(
                            cached_task=cached_task,
                            cached_result=cached_result
                        )

                        total_fields = stats["total_fields"]
                        completed_count = stats["completed_count"]
                        success_count = stats["success_count"]
                        pending_count = stats["pending_count"]
                        failed_count = stats["failed_count"]

                        # 更新缓存结果中的统计值，确保返回给用户的结果也是正确的
                        if isinstance(cached_result, dict):
                            cached_result["total_fields"] = total_fields
                            cached_result["success_count"] = success_count
                            cached_result["pending_count"] = pending_count
                            cached_result["failed_count"] = failed_count

                        await self.task_store.update_task(
                            task_id,
                            status=TaskStatus.COMPLETED,
                            progress=1.0,
                            status_message="缓存命中，已返回历史结果",
                            result=cached_result,
                            files_hash=files_hash,
                            context={
                                "total_fields": total_fields,
                                "completed_count": completed_count
                            }
                        )
                        logger.info(
                            f"已更新任务 {task_id} 的存储状态为 COMPLETED（缓存命中），"
                            f"字段数: {total_fields}, 已完成: {completed_count}"
                        )

                    # 将缓存结果转换为ExtractionData
                    return ExtractionData(**cached_result) if isinstance(cached_result, dict) else cached_result
        
        # ============================================================
        # 第二阶段：缓存未命中，需要实际处理
        # 先设置排队状态，然后获取信号量
        # ============================================================
        
        # 如果没有传task_id，且有files_hash，使用分布式锁防止重复执行
        extraction_lock = None
        if not request.task_id and files_hash:
            from src.services.redis.distributed_lock import create_extraction_lock
            
            extraction_lock = create_extraction_lock(files_hash)
            lock_acquired = await extraction_lock.acquire(timeout=30)
            
            if not lock_acquired:
                # 获取锁失败，说明其他节点正在处理
                logger.info(f"获取分布式锁失败，其他节点可能正在处理相同文件: {files_hash[:16]}...")
                
                # 等待一段时间后再次查询缓存
                await asyncio.sleep(2)
                cached_task = await self.task_store.find_task_by_files_hash(
                    files_hash=files_hash,
                    only_completed=False  # 允许查询正在处理的任务
                )
                
                if cached_task:
                    logger.info(f"等待其他节点处理完成，返回任务ID: {cached_task.task_id}")
                    # 返回任务信息，让客户端轮询查询
                    return ExtractionData(
                        request_id=request.request_id or "",
                        task_id=cached_task.task_id,
                        status=TaskExtractionStatus.PENDING if cached_task.status == TaskStatus.PENDING 
                                else TaskExtractionStatus.PROCESSING if cached_task.status == TaskStatus.PROCESSING
                                else TaskExtractionStatus.COMPLETED if cached_task.status == TaskStatus.COMPLETED
                                else TaskExtractionStatus.FAILED,
                        results=[],
                        total_fields=cached_task.context.get("total_fields", 0),
                        success_count=0,
                        pending_count=0,
                        failed_count=0,
                        status_message=cached_task.status_message or "其他节点正在处理中..."
                    )
                else:
                    from fastapi import HTTPException
                    raise HTTPException(status_code=503, detail="系统繁忙，请稍后重试")
        
        # 如果任务已在 endpoint 层创建，先设置初始状态消息
        if task_id:
            # 先将任务状态更新为 PROCESSING（这样才能被正确统计）
            await self.task_store.update_task(
                task_id, 
                status=TaskStatus.PROCESSING,
                progress=0.0,
                status_message="等待处理",
                files_hash='' if is_disclosure else files_hash  # 同时设置 files_hash
                # 不需要 clear_result/clear_error_message，已在 endpoint 层的 reset_if_exists 中处理
            )
            
            # 获取当前正在处理的任务数（PROCESSING 状态，包括等待信号量和正在执行的）
            processing_count = await self.task_store.get_processing_count(task_type=TaskType.EXTRACTION)
            max_concurrent = get_rate_limit_config().get_limit("extraction_sync")
            # 排队数 = 正在处理的任务数 - 最大并发数（超出并发限制的部分就是在排队）
            queue_count = max(0, processing_count - max_concurrent)
            
            if queue_count > 0:
                status_msg = f"当前有 {queue_count} 个智能录入任务排队等待处理，请您稍作等候，系统将按照顺序自动启动任务处理。"
                await self.task_store.update_task(
                    task_id,
                    status_message=status_msg
                )
                
        # 获取限流信号量（确保在实际处理生命周期内持有）
        # 根据是否启用流式来选择不同的信号量
        # 注意：同步接口使用 extraction_sync，流式接口在各自的方法中管理
        endpoint_name = "extraction_sync"
        
        async with rate_limit_context(endpoint_name):
            from src.services.llm.token_usage import token_usage_scope

            with token_usage_scope("提取", task_id):
                start_time = time.time()
                
                # task_id 已在方法开头生成
                # task_id = request.task_id or request.request_id
                task_created = False
                
                try:
                    # 更新任务状态：已获得信号量，开始实际处理
                    if task_id:
                        await self.task_store.update_task(
                            task_id,
                            status=TaskStatus.PROCESSING,
                            progress=0.0,
                            status_message="正在解析文件..."
                            # files_hash 已在排队阶段设置
                        )
                        task_created = True
                    # 1. 加载规则配置
                    # 注意：endpoint 层已提前加载并设置了 total_fields，这里主要是获取完整配置用于后续处理
                    if request.rule_config_id:
                        logger.info(f"加载规则配置: {request.rule_config_id}")
                        config = self.rule_service.get_config(request.rule_config_id)
                        if not config:
                            raise ValueError(f"规则配置不存在: {request.rule_config_id}")
                    else:
                        # 根据extraction_type查找默认规则配置
                        logger.info(f"未提供rule_config_id，尝试根据extraction_type查找默认规则: {request.extraction_type}")
                        business_type = map_extraction_type_to_business_type(request.extraction_type)
                        
                        if business_type is None:
                            raise ValueError(
                                f"无法识别的extraction_type: {request.extraction_type}。"
                                f"支持的类型: {', '.join(get_available_extraction_types())}"
                            )
                        
                        config = self.rule_service.get_default_config_by_business_type(business_type)
                        
                        if config is None:
                            raise ValueError(
                                f"未找到业务类型 '{business_type.value}' 的启用规则配置。"
                                f"请先在规则配置管理中创建并启用对应的规则配置，或者显式提供rule_config_id参数。"
                            )
                        
                        logger.info(f"使用默认规则配置: {config.id} ({config.name})")
                    
                    if is_disclosure or config.business_type in DISCLOSURE_TYPES:
                        if config.business_type != request.extraction_type or not config.enabled:
                            raise ValueError(f"规则配置 {config.id} 未启用或不适用于 {request.extraction_type}")

                    # 2. 解析所有文件（复用预解析的文件缓存和已下载的文件内容）
                    cache_info = []
                    if parsed_files_cache:
                        cache_info.append(f"复用 {len(parsed_files_cache)} 个预解析文件")
                    if _downloaded_files_cache:
                        cache_info.append(f"复用 {len(_downloaded_files_cache)} 个已下载文件")
                    
                    if cache_info:
                        logger.info(f"开始解析 {len(files_with_hash)} 个文件（{', '.join(cache_info)}）")
                    else:
                        logger.info(f"开始解析 {len(files_with_hash)} 个文件")
                    
                    # ========== 流水线模式：解析和提取并发执行 ==========
                    from src.services.extraction.pipeline import FileTypeParseContext
                    from config.paddle_config import is_pipeline_extraction_enabled
                    
                    use_pipeline = not is_disclosure and is_pipeline_extraction_enabled()
                    
                    if use_pipeline:
                        # 创建 parse_contexts（每个 file_type 一个）
                        file_types = set(f.file_type.value for f in files_with_hash)
                        parse_contexts: Dict[str, FileTypeParseContext] = {
                            ft: FileTypeParseContext(file_type=ft) for ft in file_types
                        }
                        
                        logger.info(f"[流水线] 启用流水线模式，{len(file_types)} 种文件类型并发解析提取")
                        
                        # 同时启动解析任务和提取任务
                        async def parse_task():
                            """解析任务：解析文件并触发事件"""
                            return await self._parse_files(
                                files_with_hash,
                                parsed_files_cache=parsed_files_cache,
                                downloaded_files_cache=_downloaded_files_cache,
                                parse_contexts=parse_contexts
                            )
                        
                        async def extract_task():
                            """提取任务：等待文件解析完成后提取字段"""
                            return await self._extract_all_fields(
                                extraction_rules=config.extraction_rules,
                                parsed_files={},  # 流水线模式下，parsed_files 从 parse_contexts 获取
                                request=request,
                                task_id=task_id,
                                task_created=task_created,
                                parse_contexts=parse_contexts,
                                downloaded_files_cache=_downloaded_files_cache,
                            )
                        
                        # 并发执行解析和提取
                        parsed_files, field_results = await asyncio.gather(
                            parse_task(),
                            extract_task()
                        )
                        
                        # 构建快照（流水线模式下 parse_result_key 已在解析时缓存）
                        parsed_files_snapshot = await self.build_parsed_files_snapshot_async(parsed_files)
                    else:
                        # 串行模式（降级或配置关闭）
                        logger.info("[串行] 使用串行模式")
                        parsed_files = await self._parse_files(
                            files_with_hash,
                            parsed_files_cache=parsed_files_cache,
                            downloaded_files_cache=_downloaded_files_cache
                        )
                        if is_disclosure:
                            application = parsed_files.get(FileType.INFO_DISCLOSURE_APPLICATION.value, {})
                            validate_application(
                                request.extraction_type,
                                [
                                    file.file_name for file in request.files
                                    if file.file_type == FileType.INFO_DISCLOSURE_APPLICATION
                                ],
                                list(zip(
                                    application.get("file_names", []),
                                    [self._merge_md_content([parsed]) for parsed in application.get("parse_results", [])],
                                )),
                            )
                        parsed_files_snapshot = await self.build_parsed_files_snapshot_async(parsed_files)
                        
                        # 3. 提取字段
                        logger.info(f"开始提取 {len(config.extraction_rules)} 个字段")
                        field_results = await self._extract_all_fields(
                            extraction_rules=config.extraction_rules,
                            parsed_files=parsed_files,
                            request=request,
                            task_id=task_id,
                            task_created=task_created,
                            downloaded_files_cache=_downloaded_files_cache,
                        )
                    
                    # 4. 清理提取值的首尾空格
                    field_results = self._strip_extracted_values(field_results)
                    if is_disclosure:
                        format_disclosure_results(config.extraction_rules, field_results)
                    
                    # 5. 统计结果（基于字段状态）
                    # 统计所有FAILED字段的error_message分布（用于调试）
                    all_failed = [r for r in field_results if r.field_status == FieldExtractionStatus.FAILED]
                    error_msg_counts = {}
                    for r in all_failed:
                        msg = r.error_message or "无错误信息"
                        error_msg_counts[msg] = error_msg_counts.get(msg, 0) + 1
                    
                    # 使用统一的统计方法计算字段统计信息
                    stats = self._calculate_field_statistics(field_results)
                    success_count = stats["success_count"]
                    pending_count = stats["pending_count"]
                    failed_count = stats["failed_count"]
                    
                    logger.info(f"字段提取完成统计：总字段数={len(field_results)}, SUCCESS={success_count}, PENDING={pending_count}, FAILED={len(all_failed)}")
                    if error_msg_counts:
                        logger.info(f"FAILED字段的error_message分布:")
                        for msg, count in sorted(error_msg_counts.items(), key=lambda x: -x[1]):
                            logger.info(f"  - [{count}个] {msg[:100]}")  # 只显示前100个字符
                    
                    logger.info(f"过滤后的统计：total_fields={stats['total_fields']} (SUCCESS={success_count}, PENDING={pending_count}, FAILED={failed_count})")
                    
                    # 6. 确定整体任务状态和 total_fields
                    # 重要：优先使用 task.context 中的 total_fields，与任务查询接口保持一致
                    # context 中的值是基于实际工作量（字段数 + 高亮任务）
                    # 而不是配置文件中的规则总数或过滤后的数量
                    if task_created and task_id:
                        task = await self.task_store.get_task(task_id)
                        if task and task.context and task.context.get("total_fields", 0) > 0:
                            # 使用 context 中的统计值，确保与任务查询接口一致
                            total_fields = task.context["total_fields"]
                            logger.info(f"使用 task.context 中的统计值：total_fields={total_fields}")
                        else:
                            # 降级：如果 context 中没有值，使用计算的值
                            total_fields = stats["total_fields"]
                            logger.warning(f"task.context 中没有 total_fields，使用计算值: {total_fields}")
                    else:
                        # 没有创建任务时，使用计算的值
                        total_fields = stats["total_fields"]
                    if success_count == total_fields:
                        # 所有字段都成功 -> 任务成功
                        overall_status = TaskExtractionStatus.SUCCESS
                    elif failed_count == total_fields:
                        # 所有字段都失败 -> 任务失败
                        overall_status = TaskExtractionStatus.FAILED
                    elif pending_count == total_fields:
                        # 所有字段都待确认 -> 任务待确认
                        overall_status = TaskExtractionStatus.PENDING
                    else:
                        # 混合状态 -> 任务部分成功
                        overall_status = TaskExtractionStatus.PARTIAL
                    
                    processing_time = int((time.time() - start_time) * 1000)
                    
                    response = ExtractionData(
                        request_id=request.request_id or task_id or f"req_{int(time.time() * 1000)}",
                        task_id=task_id if task_created else None,
                        status=overall_status,
                        extraction_type=request.extraction_type,
                        rule_config_id=config.id,  # 使用实际使用的配置ID
                        results=field_results,
                        total_fields=total_fields,
                        success_count=success_count,
                        pending_count=pending_count,
                        failed_count=failed_count,
                        processing_time_ms=processing_time,
                        parsed_files=parsed_files_snapshot
                    )
                    
                    # 更新任务状态为完成
                    if task_created and task_id:
                        await self.task_store.update_task(
                            task_id,
                            status=TaskStatus.COMPLETED,
                            progress=1.0,
                            result=response.model_dump(),
                            status_message="处理完成"
                        )
                    
                    return response
                    
                except Exception as e:
                    logger.error(f"字段提取失败: {e}", exc_info=True)
                    
                    # 更新任务状态为失败
                    if task_created and task_id:
                        await self.task_store.update_task(
                            task_id,
                            status=TaskStatus.FAILED,
                            error_message=str(e)
                        )
                    
                    raise
                finally:
                    # 释放分布式锁（如果持有的话）
                    if extraction_lock and extraction_lock._acquired:
                        await extraction_lock.release()
                        logger.debug(f"已释放分布式锁: {files_hash[:16]}...")
    
    async def _parse_files(
        self,
        files: List[Any],
        parsed_files_cache: Optional[Dict[str, Any]] = None,
        downloaded_files_cache: Optional[Dict[str, bytes]] = None,
        parse_contexts: Optional[Dict[str, 'FileTypeParseContext']] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        解析所有文件并按 file_type 分组（支持流水线模式）
        
        处理逻辑：
        1. 所有文件（不同 file_type）一次性并行解析
        2. 对于已在缓存中的文件，直接使用缓存结果，避免重复解析
        3. 如果有已下载的文件内容缓存，复用它避免重复下载
        4. 解析完成后按 file_type 分组结果
        5. 对每个 file_type 组执行合并操作
        
        流水线模式（当 parse_contexts 不为 None）：
        - 每个 file_type 的所有文件解析完成后，立即触发事件
        - 同时增量存入磁盘缓存，减少内存占用
        - 提取任务可以在等待事件后立即开始
        
        合并策略：
           - content_list_json: 合并所有文件的内容列表
           - middle_json: 合并所有文件的页面数据（调整页码）
           - file_names: 记录所有文件名
        
        Args:
            files: 文件列表，每个文件包含 file_type, file_name, file_url
            parsed_files_cache: 预解析的文件缓存（key为file_url，value为parse_result），
                用于避免重复解析
            downloaded_files_cache: 已下载的文件内容缓存（key为file_url，value为bytes），
                用于避免重复下载，通常来自缓存哈希计算阶段
            parse_contexts: 流水线模式的文件类型解析上下文字典，
                {file_type: FileTypeParseContext}，用于触发解析完成事件
            
        Returns:
            Dict: file_type -> 解析结果的映射
                {
                    "info_disclosure_application": {
                        "file_type": "info_disclosure_application",
                        "file_names": ["申请书1.pdf", "申请书2.pdf"],
                        "file_paths": ["url1", "url2"],
                        "parse_results": [ParseResult1, ParseResult2],
                        "md_content": "合并后的内容",
                        "middle_json": "合并后的middle数据",
                        "parse_result_key": "缓存key"  # 流水线模式下会包含此字段
                    }
                }
        """
        from collections import defaultdict
        import asyncio
        
        if not files:
            logger.warning("没有文件需要解析")
            return {}
        
        # 统计缓存命中
        cache_hits = 0
        cache_misses = 0
        
        # 获取文件级并发控制配置（使用 OCR-VL 的并发配置，因为文件解析主要调用 OCR-VL）
        max_concurrent = self.paddle_config.get('performance', {}).get('max_concurrent_requests_ocr_vl', 3)
        file_semaphore = asyncio.Semaphore(max_concurrent)
        
        # 流水线模式：统计每个 file_type 的文件数量
        file_type_counts: Dict[str, int] = defaultdict(int)
        for f in files:
            file_type_counts[f.file_type.value] += 1
        
        # 流水线模式：记录每个 file_type 已完成的文件数和结果
        file_type_completed: Dict[str, int] = defaultdict(int)
        file_type_results: Dict[str, List[Dict]] = defaultdict(list)
        results_lock = asyncio.Lock()
        
        # 最终返回的结果
        parsed_files: Dict[str, Dict[str, Any]] = {}
        
        is_pipeline_mode = parse_contexts is not None
        if is_pipeline_mode:
            logger.info(f"启用流水线模式，共 {len(file_type_counts)} 种文件类型")
        
        logger.info(f"开始并行解析所有文件，总共 {len(files)} 个文件，最大并发数: {max_concurrent}")
        
        async def merge_and_notify_file_type(file_type: str):
            """合并某个 file_type 的所有结果，并触发事件"""
            type_results = file_type_results[file_type]
            
            parse_results = []
            file_names = []
            file_paths = []
            pdf_contents = []  # 转换后的 PDF 内容列表（用于高亮）
            
            for result in type_results:
                parse_results.append(result["parse_result"])
                file_names.append(result["file_name"])
                file_paths.append(result["file_path"])
                # 收集 pdf_content（Word/图片转换后的 PDF 内容）
                pdf_contents.append(result.get("pdf_content"))
            
            # 合并该类型的所有解析结果
            parsed_data = {
                "file_type": file_type,
                "file_names": file_names,
                "file_paths": file_paths,
                "pdf_contents": pdf_contents,  # 转换后的 PDF 内容（用于高亮）
                "file_bytes_list": [
                    self._get_result_file_bytes(r, downloaded_files_cache)
                    for r in type_results
                ],
                "parse_results": parse_results,
                "md_content": self._merge_md_content(parse_results),
                "middle_json": self._merge_middle_json(parse_results)
            }

            excel_ctx = ExcelAnchorContext.build_from_type_results(type_results)
            if excel_ctx.is_excel:
                parsed_data["is_excel"] = True
                parsed_data["excel_trace_supported"] = excel_ctx.trace_supported
                parsed_data["excel_segment_map"] = excel_ctx.segment_map
                if excel_ctx.tagged_markdown:
                    parsed_data["md_content"] = excel_ctx.tagged_markdown

            # PDF 文本层补全（信息披露申请书等：OCR 表格缺行时注入）
            await self._apply_text_layer_supplement_to_parsed_data(
                file_type,
                parsed_data,
                downloaded_files_cache=downloaded_files_cache,
            )
            
            # 流水线模式：增量存入磁盘缓存
            if is_pipeline_mode:
                cache_key = await self._cache_single_file_type(file_type, parsed_data)
                parsed_data["parse_result_key"] = cache_key
            
            # 存入最终结果
            parsed_files[file_type] = parsed_data
            
            logger.info(f"文件类型 {file_type} 合并完成，成功处理 {len(parse_results)} 个文件")
            
            # 流水线模式：触发解析完成事件
            if is_pipeline_mode and file_type in parse_contexts:
                parse_contexts[file_type].mark_completed(parsed_data)
                logger.info(f"[流水线] 文件类型 {file_type} 解析完成，已触发事件")
        
        # 创建并行解析任务的包装函数
        async def parse_with_metadata(file_input):
            """包装解析函数，返回文件信息和解析结果"""
            nonlocal cache_hits, cache_misses
            
            file_type = file_input.file_type.value
            file_url = file_input.file_url
            
            try:
                # 先检查缓存
                if parsed_files_cache and file_url in parsed_files_cache:
                    cache_hits += 1
                    cached_result = parsed_files_cache[file_url]
                    # 从缓存结果中获取 pdf_content（如果是元组则解包，否则为 None）
                    if isinstance(cached_result, tuple):
                        parse_result, pdf_content = cached_result
                    else:
                        parse_result = cached_result
                        pdf_content = None
                    # 兼容旧缓存：如果 pdf_content 为空，检查 parse_result 中的修正后 PDF
                    if pdf_content is None:
                        pdf_content = getattr(parse_result, 'corrected_file_content', None)
                    file_bytes = getattr(parse_result, 'file_bytes', None)
                    if file_bytes is None and downloaded_files_cache:
                        file_bytes = downloaded_files_cache.get(file_url)
                        if file_bytes is None:
                            from src.utils.file_handler import normalize_file_url
                            file_bytes = downloaded_files_cache.get(normalize_file_url(file_url))
                    logger.info(f"文件 {file_input.file_name} 命中缓存，跳过解析")
                    return {
                        "success": True,
                        "file_type": file_type,
                        "file_name": file_input.file_name,
                        "file_path": file_url,
                        "parse_result": parse_result,
                        "pdf_content": pdf_content,  # 旋转修正后/转换后的 PDF 内容（用于高亮）
                        "file_bytes": file_bytes,  # Excel 高亮用
                        "from_cache": True
                    }
                
                # 缓存未命中，执行解析
                cache_misses += 1
                logger.info(f"开始解析文件: {file_input.file_name} (类型: {file_type})")
                
                # 检查是否有已下载的文件内容可复用
                cached_content = None
                if downloaded_files_cache and file_url in downloaded_files_cache:
                    cached_content = downloaded_files_cache[file_url]
                    logger.debug(f"复用已下载的文件内容: {file_input.file_name} ({len(cached_content)} 字节)")
                
                # 根据文件类型选择解析方式
                # 返回值为元组：(parse_result, pdf_content)
                # pdf_content 仅在 Word/图片转换时非空，用于高亮
                parse_result, pdf_content = await self._parse_single_file(file_input, cached_content=cached_content)
                
                if parse_result:
                    logger.info(f"文件解析成功: {file_input.file_name}")
                    return {
                        "success": True,
                        "file_type": file_type,
                        "file_name": file_input.file_name,
                        "file_path": file_url,
                        "parse_result": parse_result,
                        "pdf_content": pdf_content,  # 转换后的 PDF 内容（用于高亮）
                        "file_bytes": getattr(parse_result, 'file_bytes', None),  # Excel 高亮用
                        "from_cache": False
                    }
                else:
                    logger.warning(f"文件解析返回空结果: {file_input.file_name}")
                    return {
                        "success": False,
                        "file_type": file_type,
                        "file_name": file_input.file_name
                    }
                    
            except Exception as e:
                logger.error(f"文件解析失败 {file_input.file_name}: {e}", exc_info=True)
                return {
                    "success": False,
                    "file_type": file_type,
                    "file_name": file_input.file_name,
                    "error": str(e)
                }
        
        async def parse_with_semaphore_and_notify(file_input):
            """使用信号量控制并发，并在 file_type 完成时触发事件"""
            async with file_semaphore:
                logger.debug(f"[并发控制] 获取信号量，开始解析: {file_input.file_name}")
                result = await parse_with_metadata(file_input)
                logger.debug(f"[并发控制] 释放信号量，完成解析: {file_input.file_name}")
                
                file_type = file_input.file_type.value
                
                # 流水线模式：检查该 file_type 是否所有文件都已完成
                async with results_lock:
                    # 记录结果（无论成功失败都计入完成数）
                    file_type_completed[file_type] += 1
                    
                    # 只收集成功的结果
                    if isinstance(result, dict) and result.get("success"):
                        file_type_results[file_type].append(result)
                    
                    # 检查该 file_type 是否所有文件都已处理完
                    if file_type_completed[file_type] == file_type_counts[file_type]:
                        # 该 file_type 全部完成，合并并触发事件
                        if file_type_results[file_type]:
                            await merge_and_notify_file_type(file_type)
                        else:
                            # 该 file_type 没有成功的结果
                            logger.warning(f"文件类型 {file_type} 没有成功解析的文件")
                            if is_pipeline_mode and file_type in parse_contexts:
                                parse_contexts[file_type].mark_failed(f"所有 {file_type} 文件解析失败")
                
                return result
        
        # 使用信号量控制并发，一次性并行解析所有文件
        tasks = [parse_with_semaphore_and_notify(file_input) for file_input in files]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理可能的异常
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"文件解析任务异常: {result}", exc_info=result)
        
        # 输出缓存统计
        if parsed_files_cache:
            logger.info(f"文件解析完成，缓存命中: {cache_hits}/{len(files)}，跳过解析节省时间")
        
        # 统计信息
        total_success = sum(len(r) for r in file_type_results.values())
        logger.info(f"文件解析汇总：总计 {len(files)} 个文件，成功 {total_success} 个，失败 {len(files) - total_success} 个")
        
        return parsed_files
    
    def _serialize_parse_result_obj(self, obj: Any) -> Any:
        """递归序列化解析结果对象，排除二进制内容"""
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        elif isinstance(obj, list):
            return [self._serialize_parse_result_obj(item) for item in obj]
        elif isinstance(obj, dict):
            return {
                k: self._serialize_parse_result_obj(v) 
                for k, v in obj.items() 
                if k not in ("pdf_content", "file_content")  # 排除二进制内容
            }
        elif hasattr(obj, '__dict__'):
            # 处理对象属性
            data = {}
            for k, v in obj.__dict__.items():
                if k not in ("pdf_content", "file_content") and not k.startswith('_'):  # 排除二进制内容和私有属性
                    data[k] = self._serialize_parse_result_obj(v)
            return data
        elif hasattr(obj, 'to_dict'):
            # 优先使用 to_dict
            try:
                data = obj.to_dict()
                if isinstance(data, dict):
                    if "pdf_content" in data:
                        del data["pdf_content"]
                    if "file_content" in data:
                        del data["file_content"]
                    return self._serialize_parse_result_obj(data)
                return str(data)
            except Exception:
                return str(obj)
        else:
            # 其他不可序列化对象，尝试转字符串
            return str(obj)

    async def _cache_single_file_type(
        self,
        file_type: str,
        parsed_data: Dict[str, Any]
    ) -> str:
        """
        将单个 file_type 的解析结果存入磁盘缓存
        
        用于流水线模式下增量缓存，每个 file_type 解析完成后立即存入磁盘，
        减少内存占用。
        
        注意：当前已禁用此二级缓存，因为文件标识不够可靠（可能导致缓存冲突）
        仅保留接口兼容性，实际不会缓存数据。
        
        Args:
            file_type: 文件类型
            parsed_data: 解析数据，包含 file_names, parse_results 等
            
        Returns:
            str: 缓存的 key（parse_result_key），当前返回一个不会被使用的占位符
        """
        import hashlib
        from src.services.storage.cache_service import get_disk_cache
        
        file_names = parsed_data.get("file_names", [])
        file_paths = parsed_data.get("file_paths", [])
        
        # 生成唯一的 key：优先使用文件路径（包含哈希），避免重名问题
        # 文件路径格式示例：/api/v1/preview/files/d4223b6f5899f31c.../评估报告.pdf
        identifiers = []
        if file_paths:
            # 从路径中提取哈希部分作为唯一标识
            for path in file_paths:
                # 提取路径中的哈希（通常在文件名前）
                identifiers.append(path)
        elif file_names:
            # 降级：仅使用文件名（不推荐，可能重复）
            identifiers = file_names
        
        identifiers_str = str(sorted(identifiers))
        key_hash = hashlib.md5(identifiers_str.encode()).hexdigest()[:16]
        cache_key = f"parse_result_{file_type}_{key_hash}_disabled"
        
        # 二级缓存已禁用：不再存入磁盘缓存
        logger.debug(f"二级缓存已禁用，跳过 {file_type} 的缓存: {cache_key}")
        
        return cache_key

    async def build_parsed_files_snapshot_async(self, parsed_files: Dict[str, Any]) -> Dict[str, Any]:
        """
        [Async] 构建解析文件的快照数据，并将 parse_results 存入磁盘缓存
        
        兼容流水线模式：如果 parsed_data 中已有 parse_result_key，则跳过缓存，
        直接使用已缓存的 key。
        """
        snapshot: Dict[str, Any] = {}

        for file_type, data in parsed_files.items():
            if not isinstance(data, dict):
                continue

            file_names = data.get("file_names", [])
            md_content = data.get("md_content", "")
            
            # 检查是否已有缓存 key（流水线模式下已增量缓存）
            if "parse_result_key" in data:
                # 流水线模式已缓存，直接使用
                cache_key = data["parse_result_key"]
                logger.debug(f"复用已缓存的 {file_type} 解析结果: {cache_key}")
            else:
                # 串行模式或未缓存，调用增量缓存方法
                cache_key = await self._cache_single_file_type(file_type, data)

            file_label = ""
            try:
                file_label = FILE_TYPE_LABELS.get(FileType(file_type), "")
            except ValueError:
                file_label = data.get("file_label", "")

            snapshot_data = {
                "file_names": file_names,
                "file_label": file_label,
                "md_content": md_content,
                "parse_result_key": cache_key
            }
            
            # 🔧 修复：如果二级缓存被禁用（key以_disabled结尾），保留parse_results到快照
            # 这样审核阶段的RAG检索才能正常工作
            if cache_key.endswith("_disabled") and "parse_results" in data:
                # 清除不可JSON序列化的字段（如 bytes 类型的 corrected_file_content）
                sanitized_results = self._sanitize_parse_results_for_snapshot(data["parse_results"])
                snapshot_data["parse_results"] = sanitized_results
                logger.debug(f"二级缓存已禁用，将 {file_type} 的 parse_results 保留到快照中（支持RAG检索）")
            
            snapshot[file_type] = snapshot_data

        return snapshot

    def _sanitize_parse_results_for_snapshot(self, parse_results: List[Any]) -> List[Dict[str, Any]]:
        """
        清理 parse_results 中不可 JSON 序列化的字段（如 bytes），
        使其可以安全地存入 Redis（通过 json.dumps 序列化）。

        主要处理 PaddleParseResult.corrected_file_content (bytes) 字段。
        """
        sanitized = []
        for result in parse_results or []:
            if hasattr(result, '__dataclass_fields__'):
                # dataclass 实例 → 转为 dict 并移除 bytes 字段
                from dataclasses import asdict
                result_dict = asdict(result)
            elif isinstance(result, dict):
                result_dict = dict(result)
            else:
                # SimpleNamespace（Tika 文本文档路径）等对象 → 递归转为 dict
                result_dict = self._serialize_parse_result_obj(result)

            # 移除不可序列化的 bytes 字段
            if isinstance(result_dict, dict):
                result_dict.pop("corrected_file_content", None)
                # 递归清理 pages 中可能存在的 bytes
                if "pages" in result_dict and isinstance(result_dict["pages"], list):
                    for page in result_dict["pages"]:
                        if isinstance(page, dict):
                            page.pop("corrected_file_content", None)

            sanitized.append(result_dict)
        return sanitized

    async def _resolve_pdf_bytes_for_text_layer(
        self,
        file_paths: List[str],
        pdf_contents: List[Optional[bytes]],
        downloaded_files_cache: Optional[Dict[str, bytes]] = None,
    ) -> Optional[bytes]:
        """
        获取用于文本层补全的 PDF 字节（优先转换后的 PDF，其次缓存/路径）

        路径读取与 Paddle parse_file 一致：http(s) 下载，本地路径（如 C:/...）直读。
        """
        for pdf in pdf_contents or []:
            if pdf and pdf[:4] == b"%PDF":
                return pdf

        from pathlib import Path
        from src.utils.file_handler import FileHandler, normalize_file_url

        candidates: List[str] = []
        if downloaded_files_cache:
            candidates.extend(downloaded_files_cache.keys())
        candidates.extend(file_paths or [])

        seen: Set[str] = set()
        for path in candidates:
            if not path or path in seen:
                continue
            seen.add(path)
            try:
                if downloaded_files_cache and path in downloaded_files_cache:
                    content = downloaded_files_cache[path]
                else:
                    url = normalize_file_url(path)
                    if downloaded_files_cache and url in downloaded_files_cache:
                        content = downloaded_files_cache[url]
                    else:
                        # 与 Paddle parse_file 一致：http(s) 下载，本地路径直读
                        content, _ = await FileHandler.read_file_bytes(
                            file_url=path,
                            file_name=Path(path).name,
                        )
                if content and content[:4] == b"%PDF":
                    return content
            except Exception as e:
                logger.debug(f"获取 PDF 字节失败 {path}: {e}")
        return None

    async def _apply_text_layer_supplement_to_parsed_data(
        self,
        file_type: str,
        parsed_data: Dict[str, Any],
        downloaded_files_cache: Optional[Dict[str, bytes]] = None,
    ) -> None:
        """
        对信息披露申请书等类型，用 PDF 文本层补全 OCR 丢失的表格字段行

        注意：当 PDF 页面被本地 RotationDetector 纠正了旋转时，
        文本层坐标与 Paddle OCR bbox 可能不在同一坐标系。
        但默认 highlight_full_page=True 使用整页 bbox（旋转无关），因此仅记录警告。
        """
        from src.utils.pdf_text_layer_supplement import (
            apply_supplement_to_parse_results,
            serialize_supplement_segments,
            should_apply_for_file_type,
        )

        if not should_apply_for_file_type(file_type):
            return

        parse_results = parsed_data.get("parse_results") or []
        if not parse_results:
            return

        # 检测是否有页面被本地旋转检测模型纠正过
        has_local_rotation = False
        for result in parse_results:
            for page in getattr(result, 'pages', []) or []:
                if getattr(page, 'local_rotation_angle', 0) != 0:
                    has_local_rotation = True
                    break
            if has_local_rotation:
                break

        if has_local_rotation:
            logger.info(
                f"文件类型 {file_type}: 存在本地旋转纠正，"
                f"文本层补全默认使用整页 bbox（旋转无关），不影响溯源精度"
            )

        pdf_bytes = await self._resolve_pdf_bytes_for_text_layer(
            file_paths=parsed_data.get("file_paths") or [],
            pdf_contents=parsed_data.get("pdf_contents") or [],
            downloaded_files_cache=downloaded_files_cache,
        )
        if not pdf_bytes:
            logger.warning(
                f"文件类型 {file_type} 未获取到 PDF 字节，跳过文本层补全"
            )
            return

        logger.info(f"开始对 {file_type} 应用 PDF 文本层补全")
        page_supplements, supplement_segments, page_paddle_bboxes = (
            apply_supplement_to_parse_results(parse_results, pdf_bytes)
        )
        if not page_supplements:
            logger.info(f"文件类型 {file_type} 文本层补全：无需注入")
            return

        parsed_data["md_content"] = self._merge_md_content(parse_results)
        parsed_data["text_layer_page_supplements"] = page_supplements
        parsed_data["text_layer_supplement_segments"] = serialize_supplement_segments(
            supplement_segments
        )
        if page_paddle_bboxes:
            parsed_data["text_layer_page_paddle_bboxes"] = page_paddle_bboxes
        traceable = sum(len(v) for v in supplement_segments.values())
        logger.info(
            f"文件类型 {file_type} 文本层补全完成 | 补全页数: {len(page_supplements)} | "
            f"可溯源片段: {traceable}"
        )

    def build_parsed_files_snapshot(self, parsed_files: Dict[str, Any]) -> Dict[str, Any]:
        """
        [Deprecated] 同步版本的构建快照，不推荐使用，因为无法异步写磁盘。
        保留是为了兼容旧代码，但不再包含 parse_results 以防内存溢出。
        建议上层改用 build_parsed_files_snapshot_async
        """
        logger.warning("调用了同步的 build_parsed_files_snapshot，无法使用磁盘缓存且不包含 parse_results")
        
        snapshot: Dict[str, Any] = {}
        for file_type, data in parsed_files.items():
            if not isinstance(data, dict):
                continue

            file_names = data.get("file_names", [])
            md_content = data.get("md_content", "")
            
            file_label = ""
            try:
                file_label = FILE_TYPE_LABELS.get(FileType(file_type), "")
            except ValueError:
                file_label = data.get("file_label", "")

            snapshot[file_type] = {
                "file_names": file_names,
                "file_label": file_label,
                "md_content": md_content,
                # 不再包含 parse_results，避免内存溢出
            }
        return snapshot

    async def _parse_single_file(
        self, 
        file_input: Any, 
        cached_content: Optional[bytes] = None
    ) -> Tuple[Optional[Any], Optional[bytes]]:
        """
        解析单个文件，根据文件类型选择不同的解析方式
        
        处理策略：
        1. Word 文档：使用 Tika 提取文本用于 LLM 提取，同时转换为 PDF 用于溯源
        2. 文本文档（txt/rtf等）：使用 Tika 提取文本，创建简单的解析结果（不支持溯源）
        3. 图片文件：转换为 PDF，然后优先使用 Paddle 解析，失败则降级到 MinerU
        4. PDF 文件：优先使用 Paddle 解析，失败则降级到 MinerU
        
        解析引擎优先级：
        - 优先使用 Paddle（PaddleOCR-VL + 印章识别）
        - Paddle 服务故障时自动降级到 MinerU
        
        Args:
            file_input: 文件输入对象，包含 file_name, file_url
            cached_content: 已下载的文件内容（可选），如果提供则跳过下载
            
        Returns:
            Tuple[Optional[Any], Optional[bytes]]: (解析结果对象, 转换后的PDF内容)
                - 对于 Word/图片文件，返回转换后的 PDF 内容用于高亮
                - 对于 PDF 文件或不需要转换的文件，pdf_content 为 None
        """
        from pathlib import Path
        from io import BytesIO
        import tempfile
        from src.utils.file_handler import normalize_file_url
        
        # 获取文件扩展名
        file_extension = Path(file_input.file_name).suffix.lower()
        
        # 标准化 URL：将相对路径（如 /aiFileApi/bjs-file/...）转换为完整 URL
        normalized_file_url = normalize_file_url(file_input.file_url)
        
        # 辅助函数：获取文件内容（优先使用缓存）
        async def get_file_content() -> bytes:
            if cached_content is not None:
                logger.debug(f"使用缓存的文件内容: {file_input.file_name}")
                return cached_content
            content, _ = await FileHandler.process_file_input(
                file_url=normalized_file_url,
                file_name=file_input.file_name
            )
            return content
        
        # 1. 检查是否为 Word 格式（转换为 PDF 后走正常流程）
        if FileHandler.is_word_format(file_extension):
            logger.info(f"检测到 Word 格式: {file_extension}，转换为 PDF 后解析")
            
            try:
                # 获取文件内容（优先使用缓存）
                file_content = await get_file_content()
                
                # 使用 Gotenberg 转换为 PDF
                pdf_content = await WordToPDFConverter.convert_to_pdf_async(
                    word_content=file_content,
                    file_name=file_input.file_name
                )
                
                # 保存为临时文件，供 Paddle 解析
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                    tmp_file.write(pdf_content)
                    tmp_pdf_path = tmp_file.name
                
                try:
                    # 优先使用 Paddle 解析 PDF
                    try:
                        logger.info(f"优先使用 Paddle 解析 Word 转换的 PDF: {file_input.file_name}")
                        parse_result = await self.paddle_client.parse_file(
                            file_path=tmp_pdf_path
                        )
                        
                        if parse_result and parse_result.success:
                            logger.info(f"Paddle 解析 Word 成功: {file_input.file_name}")
                            # 优先使用旋转修正后的 PDF（如果 RotationDetector 修改了 /Rotate）
                            corrected_pdf = getattr(parse_result, 'corrected_file_content', None) or pdf_content
                            return parse_result, corrected_pdf
                        else:
                            raise PaddleError("Paddle 解析返回失败")
                            
                    except (PaddleError, Exception) as e:
                        logger.warning(f"Paddle 解析失败: {e}，降级到 MinerU")
                        
                        if self.paddle_config['error']['fallback_to_mineru']:
                            parse_result = await self.mineru_client.parse_file(
                                file_path=tmp_pdf_path
                            )
                            logger.info(f"MinerU 解析 Word 成功（降级）: {file_input.file_name}")
                            # 返回解析结果和转换后的 PDF 内容（用于高亮）
                            return parse_result, pdf_content
                        else:
                            raise
                            
                finally:
                    # 清理临时 PDF 文件
                    try:
                        Path(tmp_pdf_path).unlink(missing_ok=True)
                    except Exception as e:
                        logger.warning(f"清理临时文件失败 {tmp_pdf_path}: {e}")
                        
            except Exception as e:
                logger.error(f"Word 转 PDF 失败: {e}")
                raise
        
        # 1.5. 检查是否为 Excel 格式（使用 openpyxl，支持溯源）
        elif file_extension in FileHandler.SUPPORTED_EXCEL_FORMATS:
            logger.info(f"检测到 Excel 格式: {file_extension}，使用 openpyxl 提取（支持溯源）")

            try:
                # 获取文件内容
                file_content = await get_file_content()

                # 用 ExcelAnchorConverter 生成 Anchor Markdown + segment_map
                from src.utils.excel_anchor_converter import ExcelAnchorConverter
                anchor_markdown, segment_map, sheet_count = ExcelAnchorConverter.convert(
                    file_content, file_input.file_name
                )

                if not anchor_markdown:
                    logger.warning(f"Excel 锚点转换结果为空，降级到 Tika 文本提取（不支持溯源）")
                    tika_result = await self.tika_client.extract_text(
                        file_content=file_content,
                        file_name=file_input.file_name
                    )
                    parse_result = self._create_text_parse_result(
                        text_content=tika_result["text"],
                        file_name=file_input.file_name
                    )
                    parse_result.trace_supported = False
                    return parse_result, None

                # 构建模拟的 parse_result（兼容现有流程）
                parse_result = self._create_excel_parse_result(
                    anchor_markdown=anchor_markdown,
                    segment_map=segment_map,
                    file_name=file_input.file_name,
                    sheet_count=sheet_count,
                )

                # Excel 需要 file_bytes 用于高亮渲染，存入 parse_result
                parse_result.file_bytes = file_content

                return parse_result, None  # Excel 不需要 PDF 文件

            except Exception as e:
                logger.error(f"Excel 提取失败: {e}")
                raise

        # 2. 检查是否为文本文档格式（使用 Tika，不支持溯源）
        elif FileHandler.is_text_document_format(file_extension):
            logger.info(f"检测到文本文档格式: {file_extension}，使用 Tika 提取文本（不支持溯源）")
            
            try:
                # 获取文件内容（优先使用缓存）
                file_content = await get_file_content()
                
                # 使用 Tika 提取文本
                tika_result = await self.tika_client.extract_text(
                    file_content=file_content,
                    file_name=file_input.file_name
                )
                
                # 创建简单的解析结果（模拟 MinerU 的结构）
                parse_result = self._create_text_parse_result(
                    text_content=tika_result["text"],
                    file_name=file_input.file_name
                )
                
                # 文本文档不需要 PDF，返回 None
                return parse_result, None
                
            except Exception as e:
                logger.error(f"Tika 提取文本失败: {e}")
                raise
        
        # 3. 检查是否为图片格式（需要转换为 PDF）
        elif FileHandler.is_image_format(file_extension):
            logger.info(f"检测到图片格式: {file_extension}，转换为 PDF 后解析")
            
            try:
                # 获取文件内容（优先使用缓存）
                file_content = await get_file_content()
                
                # 转换为 PDF
                pdf_content = ImageToPDFConverter.convert_single_image(
                    image_content=file_content,
                    file_name=file_input.file_name
                )
                
                # 保存为临时文件，供 MinerU 解析
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                    tmp_file.write(pdf_content)
                    tmp_path = tmp_file.name
                
                try:
                    # 优先使用 Paddle 解析 PDF
                    try:
                        logger.info(f"优先使用 Paddle 解析图片转换的 PDF: {file_input.file_name}")
                        parse_result = await self.paddle_client.parse_file(
                            file_path=tmp_path
                        )
                        
                        if parse_result and parse_result.success:
                            logger.info(f"Paddle 解析成功: {file_input.file_name}")
                            # 优先使用旋转修正后的 PDF（如果 RotationDetector 修改了 /Rotate）
                            corrected_pdf = getattr(parse_result, 'corrected_file_content', None) or pdf_content
                            return parse_result, corrected_pdf
                        else:
                            raise PaddleError("Paddle 解析返回失败")
                            
                    except (PaddleError, Exception) as e:
                        logger.warning(f"Paddle 解析失败: {e}，降级到 MinerU")
                        
                        if self.paddle_config['error']['fallback_to_mineru']:
                            parse_result = await self.mineru_client.parse_file(
                                file_path=tmp_path
                            )
                            logger.info(f"MinerU 解析成功（降级）: {file_input.file_name}")
                            # 返回解析结果和转换后的 PDF 内容（用于高亮）
                            return parse_result, pdf_content
                        else:
                            raise
                            
                finally:
                    # 清理临时文件
                    try:
                        Path(tmp_path).unlink(missing_ok=True)
                    except Exception as e:
                        logger.warning(f"清理临时文件失败 {tmp_path}: {e}")
                        
            except Exception as e:
                logger.error(f"图片转 PDF 失败: {e}")
                raise
        
        # 4. PDF 或其他支持的格式，优先使用 Paddle 解析，失败则降级到 MinerU
        else:
            logger.info(f"开始解析文件: {file_extension}")
            
            # 优先使用 Paddle 解析
            try:
                logger.info(f"优先使用 Paddle 解析文件: {file_input.file_name}")
                
                # 获取业务文件类型（用于选择解析策略）
                business_file_type = file_input.file_type if hasattr(file_input, 'file_type') else None
                
                if cached_content:
                    parse_result = await self.paddle_client.parse_file_with_strategy(
                        file_content=cached_content,
                        file_name=file_input.file_name,
                        business_file_type=business_file_type
                    )
                else:
                    parse_result = await self.paddle_client.parse_file_with_strategy(
                        file_path=normalized_file_url,
                        file_name=file_input.file_name,
                        business_file_type=business_file_type
                    )
                
                if parse_result and parse_result.success:
                    logger.info(f"Paddle 解析成功: {file_input.file_name}")
                    # 如果 Paddle 解析时本地 RotationDetector 修改了 PDF，
                    # 返回修正后的文件内容供高亮器使用（保证坐标系一致）
                    corrected_pdf = getattr(parse_result, 'corrected_file_content', None)
                    if corrected_pdf:
                        logger.info(
                            f"返回旋转修正后的 PDF 内容供高亮器使用: {file_input.file_name}"
                        )
                    return parse_result, corrected_pdf
                else:
                    error_msg = parse_result.error_message if parse_result else "未知错误"
                    logger.warning(f"Paddle 解析返回失败: {error_msg}，降级到 MinerU")
                    raise PaddleError(error_msg)

            except PaddleError as e:
                logger.warning(f"Paddle 服务故障: {e}，降级到 MinerU")

                # 检查是否启用降级
                if self.paddle_config['error']['fallback_to_mineru']:
                    logger.info(f"使用 MinerU 解析文件: {file_input.file_name}")
                    try:
                        if cached_content:
                            parse_result = await self.mineru_client.parse_file(
                                file_content=cached_content,
                                file_name=file_input.file_name
                            )
                        else:
                            parse_result = await self.mineru_client.parse_file(
                                file_path=normalized_file_url,
                                file_name=file_input.file_name
                            )

                        logger.info(f"MinerU 解析成功（降级）: {file_input.file_name}")
                        # MinerU 降级路径无旋转修正，返回 None
                        return parse_result, None
                    except Exception as mineru_error:
                        logger.error(f"MinerU 解析也失败: {mineru_error}")
                        raise
                else:
                    logger.error(f"Paddle 解析失败且未启用降级策略")
                    raise

            except Exception as e:
                logger.error(f"文件解析异常: {e}，尝试降级到 MinerU")

                # 尝试降级到 MinerU
                if self.paddle_config['error']['fallback_to_mineru']:
                    try:
                        if cached_content:
                            parse_result = await self.mineru_client.parse_file(
                                file_content=cached_content,
                                file_name=file_input.file_name
                            )
                        else:
                            parse_result = await self.mineru_client.parse_file(
                                file_path=normalized_file_url,
                                file_name=file_input.file_name
                            )

                        logger.info(f"MinerU 解析成功（降级）: {file_input.file_name}")
                        # MinerU 降级路径无旋转修正，返回 None
                        return parse_result, None
                    except Exception as mineru_error:
                        logger.error(f"MinerU 解析也失败: {mineru_error}")
                        raise
                else:
                    raise
    
    def _create_text_parse_result(self, text_content: str, file_name: str) -> Any:
        """
        为纯文本创建解析结果对象（模拟 MinerU 的结构）
        
        Args:
            text_content: 提取的文本内容
            file_name: 文件名
            
        Returns:
            解析结果对象
        """
        from types import SimpleNamespace
        
        # 创建模拟的 content 对象
        mock_content = SimpleNamespace(
            type="text",
            text=text_content
        )
        
        # 创建模拟的 layout_block 对象（用于 middle_json）
        mock_layout_block = SimpleNamespace(
            bbox=SimpleNamespace(x0=0, y0=0, x1=100, y1=100),
            category_type="text",
            lines=[
                SimpleNamespace(
                    spans=[
                        SimpleNamespace(text=text_content)
                    ]
                )
            ]
        )
        
        # 创建模拟的 page 对象（兼容 MinerU 的结构）
        mock_page = SimpleNamespace(
            page_num=0,  # 注意：这里是 page_num，不是 page_idx
            text=text_content,
            width=0,
            height=0,
            contents=[mock_content],  # 添加 contents 属性
            layout_blocks=[mock_layout_block]  # 添加 layout_blocks 属性
        )
        
        # 创建一个简单的命名空间对象来模拟 MinerU 的 ParseResult
        parse_result = SimpleNamespace(
            pages=[mock_page],
            file_name=file_name,
            total_pages=1,
            # 标记为文本提取模式（不支持溯源）
            is_text_only=True,
            trace_supported=False,
            raw_text=text_content,
            # 设置 md_content 以便后续合并使用
            md_content=text_content
        )
        
        return parse_result

    def _create_excel_parse_result(
        self,
        anchor_markdown: str,
        segment_map: Dict[str, Any],
        file_name: str,
        sheet_count: int,
    ) -> Any:
        """
        为 Excel 文件创建解析结果对象（支持溯源）

        与 _create_text_parse_result 的区别：
        - is_text_only=False（启用溯源）
        - is_excel=True（标记为 Excel，高亮时路由到 Excel 高亮器）
        - excel_segment_map 存储单元格级 segment_map

        Args:
            anchor_markdown: 带锚点的 Markdown 文本
            segment_map: 单元格级 segment_map
            file_name: 文件名
            sheet_count: Sheet 数量

        Returns:
            模拟 MinerU 的 ParseResult 对象
        """
        from types import SimpleNamespace

        # 创建模拟的 layout_block
        mock_layout_block = SimpleNamespace(
            bbox=SimpleNamespace(x0=0, y0=0, x1=100, y1=100),
            category_type="text",
            lines=[SimpleNamespace(spans=[SimpleNamespace(text=anchor_markdown)])]
        )

        # 创建模拟的 page
        mock_page = SimpleNamespace(
            page_num=0,
            text=anchor_markdown,
            width=0,
            height=0,
            contents=[SimpleNamespace(type="text", text=anchor_markdown)],
            layout_blocks=[mock_layout_block],
        )

        # 创建 parse_result
        parse_result = SimpleNamespace(
            pages=[mock_page],
            file_name=file_name,
            total_pages=sheet_count,
            is_text_only=False,
            is_excel=True,
            trace_supported=True,
            excel_segment_map=segment_map,
            raw_text=anchor_markdown,
            md_content=anchor_markdown,
        )

        return parse_result

    def _merge_md_content(self, parse_results: List[Any]) -> str:
        """
        合并多个文件的 Markdown 内容
        
        Args:
            parse_results: ParseResult 对象列表
            
        Returns:
            str: 合并后的 Markdown 内容
        """
        try:
            md_contents = []
            
            for i, parse_result in enumerate(parse_results):
                # 提取 md_content
                md = getattr(parse_result, 'md_content', None)
                
                if md:
                    # 如果有多个文件，添加分隔符标识不同文件
                    if len(parse_results) > 1:
                        file_name = getattr(parse_result, 'file_name', f'文件{i+1}')
                        md_contents.append(f"# === {file_name} ===\n\n{md}")
                    else:
                        md_contents.append(md)
                else:
                    logger.warning(f"解析结果 {i} 没有 md_content，尝试从其他属性提取文本")
                    # 尝试多种方式获取文本内容
                    text = ""
                    
                    # 1. 尝试调用 get_all_text 方法
                    if hasattr(parse_result, 'get_all_text'):
                        text = parse_result.get_all_text()
                    # 2. 尝试从 raw_text 属性获取
                    elif hasattr(parse_result, 'raw_text'):
                        text = getattr(parse_result, 'raw_text', "")
                    # 3. 尝试从 pages 中提取
                    elif hasattr(parse_result, 'pages'):
                        page_texts = []
                        for page in parse_result.pages:
                            if hasattr(page, 'text'):
                                page_texts.append(page.text)
                        text = "\n".join(page_texts)
                    
                    if text:
                        md_contents.append(text)
                    else:
                        logger.warning(f"解析结果 {i} 无法提取任何文本内容")
            
            merged_md = "\n\n---\n\n".join(md_contents)
            logger.info(f"合并 md_content：共 {len(merged_md)} 字符，来自 {len(parse_results)} 个文件")
            return merged_md
            
        except Exception as e:
            logger.error(f"合并 md_content 失败: {e}", exc_info=True)
            return ""
    
    def _merge_middle_json(self, parse_results: List[Any]) -> str:
        """
        合并多个文件的 middle.json 内容
        
        Args:
            parse_results: ParseResult 对象列表
            
        Returns:
            str: 合并后的 middle.json JSON 字符串
        """
        try:
            all_pages = []
            page_offset = 0
            
            for parse_result in parse_results:
                # 提取单个文件的 middle 数据
                pages = self._extract_middle_from_single(parse_result, page_offset)
                all_pages.extend(pages)
                
                # 更新页码偏移量
                page_offset += len(parse_result.pages)
            
            logger.info(f"合并 middle_json：共 {len(all_pages)} 页，来自 {len(parse_results)} 个文件")
            return json.dumps(all_pages, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"合并 middle_json 失败: {e}", exc_info=True)
            return "[]"
    
    def _extract_content_list_from_single(self, parse_result: Any, page_offset: int = 0) -> List[Dict]:
        """
        从单个解析结果中提取 content_list 内容
        
        Args:
            parse_result: MinerU解析结果或纯文本解析结果
            page_offset: 页码偏移量（用于合并多个文件时调整页码）
            
        Returns:
            List[Dict]: content_list 数组
        """
        try:
            # 检查是否为纯文本模式
            is_text_only = getattr(parse_result, "is_text_only", False)
            
            if is_text_only:
                logger.debug("检测到纯文本模式，使用简化的内容提取")
                # 纯文本模式：直接返回简化的内容列表
                raw_text = getattr(parse_result, "raw_text", "")
                if raw_text:
                    return [{
                        "type": "text",
                        "text": raw_text,
                        "page_idx": page_offset
                    }]
                return []
            
            content_list = []
            
            for page in parse_result.pages:
                # 应用页码偏移量
                page_idx = page.page_num + page_offset
                
                # 遍历页面内容
                for content in page.contents:
                    # 基础字段
                    content_item = {
                        "type": content.type,
                        "page_idx": page_idx
                    }
                    
                    # 根据内容类型添加特定字段
                    if content.type == "text":
                        content_item["text"] = content.text if hasattr(content, 'text') else ""
                        # 如果有 text_level，添加标题级别
                        if hasattr(content, 'text_level'):
                            content_item["text_level"] = content.text_level
                    
                    elif content.type == "table":
                        # 表格内容
                        if hasattr(content, 'table_body'):
                            content_item["table_body"] = content.table_body
                        elif hasattr(content, 'html'):
                            content_item["table_body"] = content.html
                        elif hasattr(content, 'text'):
                            content_item["table_body"] = content.text
                        
                        # 可选字段
                        if hasattr(content, 'img_path'):
                            content_item["img_path"] = content.img_path
                        if hasattr(content, 'table_caption') and content.table_caption:
                            content_item["table_caption"] = content.table_caption
                        else:
                            content_item["table_caption"] = []
                        if hasattr(content, 'table_footnote') and content.table_footnote:
                            content_item["table_footnote"] = content.table_footnote
                        else:
                            content_item["table_footnote"] = []
                    
                    elif content.type in ["image", "figure"]:
                        # 图片内容
                        if hasattr(content, 'img_path'):
                            content_item["img_path"] = content.img_path
                        if hasattr(content, 'image_caption') and content.image_caption:
                            content_item["image_caption"] = content.image_caption
                        else:
                            content_item["image_caption"] = []
                        if hasattr(content, 'image_footnote') and content.image_footnote:
                            content_item["image_footnote"] = content.image_footnote
                        else:
                            content_item["image_footnote"] = []
                    
                    else:
                        # 其他类型（formula, list, code等）
                        if hasattr(content, 'text'):
                            content_item["text"] = content.text
                        elif hasattr(content, 'html'):
                            content_item["text"] = content.html
                    
                    # 只添加有实际内容的项
                    if content_item.get("text") or content_item.get("table_body") or content_item.get("img_path"):
                        content_list.append(content_item)
            
            return content_list
            
        except Exception as e:
            logger.error(f"提取 content_list 失败: {e}", exc_info=True)
            return []
    
    def _extract_middle_from_single(self, parse_result: Any, page_offset: int = 0) -> List[Dict]:
        """
        从单个解析结果中提取 middle.json 内容
        
        Args:
            parse_result: MinerU解析结果或纯文本解析结果
            page_offset: 页码偏移量（用于合并多个文件时调整页码）
            
        Returns:
            List[Dict]: middle 数据数组
        """
        try:
            # 检查是否为纯文本模式
            is_text_only = getattr(parse_result, "is_text_only", False)
            
            if is_text_only:
                logger.debug("检测到纯文本模式，使用简化的 middle 数据")
                # 纯文本模式：返回空的 middle 数据（因为没有位置信息）
                # 或者返回一个简化的结构
                return [{
                    "page_idx": page_offset,
                    "layout_dets": []  # 纯文本没有布局信息
                }]
            
            middle_data = []
            
            for page in parse_result.pages:
                # 应用页码偏移量
                page_data = {
                    "page_idx": page.page_num + page_offset,
                    "layout_dets": []
                }
                
                # 添加布局检测数据（包含完整的 lines 和 spans 结构）
                for block in page.layout_blocks:
                    # 兼容处理：支持 bbox 为对象或列表
                    if hasattr(block.bbox, 'x0'):
                        # MinerU 格式：bbox 是对象
                        bbox = [block.bbox.x0, block.bbox.y0, block.bbox.x1, block.bbox.y1]
                    elif isinstance(block.bbox, (list, tuple)) and len(block.bbox) == 4:
                        # Paddle 格式：bbox 是列表
                        bbox = list(block.bbox)
                    else:
                        logger.warning(f"无法识别的 bbox 格式: {type(block.bbox)}")
                        bbox = [0, 0, 0, 0]
                    
                    # ✅ 构建完整的 lines 和 spans 结构
                    lines_data = []
                    all_texts = []
                    
                    for line in block.lines:
                        # 提取 line 的 bbox
                        line_bbox = [0, 0, 0, 0]
                        if hasattr(line, 'bbox'):
                            if hasattr(line.bbox, 'x0'):
                                line_bbox = [line.bbox.x0, line.bbox.y0, line.bbox.x1, line.bbox.y1]
                            elif isinstance(line.bbox, (list, tuple)) and len(line.bbox) == 4:
                                line_bbox = list(line.bbox)
                        
                        # 提取 spans
                        spans_data = []
                        line_texts = []
                        
                        for span in line.spans:
                            # 提取 span 的 bbox
                            span_bbox = [0, 0, 0, 0]
                            if hasattr(span, 'bbox'):
                                if hasattr(span.bbox, 'x0'):
                                    span_bbox = [span.bbox.x0, span.bbox.y0, span.bbox.x1, span.bbox.y1]
                                elif isinstance(span.bbox, (list, tuple)) and len(span.bbox) == 4:
                                    span_bbox = list(span.bbox)
                            
                            span_text = span.text if hasattr(span, 'text') else ""
                            
                            if span_text:  # 只添加有文本的 span
                                spans_data.append({
                                    "bbox": span_bbox,
                                    "content": span_text,  # ⚠️ 使用 'content' 字段，与溯源提示词保持一致
                                    "type": getattr(span, 'type', 'text')
                                })
                                line_texts.append(span_text)
                        
                        # 只添加有内容的 line
                        if spans_data:
                            lines_data.append({
                                "bbox": line_bbox,
                                "spans": spans_data
                            })
                            all_texts.extend(line_texts)
                    
                    # ✅ 构建完整的 layout_det 结构
                    layout_det = {
                        "bbox": bbox,
                        "text": " ".join(all_texts),  # 保留文本字段用于快速搜索
                        "category_type": block.category_type,
                        "lines": lines_data  # ⚠️ 新增：保留完整的 lines 和 spans 结构
                    }
                    
                    page_data["layout_dets"].append(layout_det)
                
                middle_data.append(page_data)
            
            return middle_data
            
        except Exception as e:
            logger.error(f"提取 middle 失败: {e}")
            return []
    
    def _get_file_type_from_material(self, material: str) -> Optional[str]:
        """
        从参考材料名称获取对应的 file_type
        
        Args:
            material: 参考材料名称（如"《信息披露申请书》"）
            
        Returns:
            Optional[str]: file_type 字符串（如 "info_disclosure_application"），未找到返回 None
        """
        from src.schemas.file import LABEL_TO_FILE_TYPE
        file_type = LABEL_TO_FILE_TYPE.get(material)
        return file_type.value if file_type else None

    def _group_rules_by_reference_material(
        self,
        rules: List[ExtractionRule]
    ) -> Dict[str, List[ExtractionRule]]:
        """
        按参考材料（reference_materials）分组规则
        
        Args:
            rules: 提取规则列表
            
        Returns:
            Dict: {参考材料名: [规则列表], ...}
                例如: {"《信息披露申请书》": [rule1, rule2], "《房屋所有权证》": [rule3]}
        """
        from collections import defaultdict
        
        groups = defaultdict(list)
        
        for rule in rules:
            # 每个规则可能有多个 reference_materials
            for material in rule.reference_materials:
                groups[material].append(rule)
        
        return dict(groups)
    
    def _chunk_rules(
        self,
        rules: List[ExtractionRule],
        chunk_size: Optional[int] = None
    ) -> List[List[ExtractionRule]]:
        """
        将规则列表分批
        
        Args:
            rules: 规则列表
            chunk_size: 每批的大小（默认从配置读取）
            
        Returns:
            List[List[ExtractionRule]]: 分批后的规则列表
                例如: [[rule1, rule2], [rule3, rule4, rule5]]
        """
        if not rules:
            return []
        
        # 使用配置的批量大小
        if chunk_size is None:
            chunk_size = self.concurrency_config.batch_size
        
        chunks = []
        for i in range(0, len(rules), chunk_size):
            chunks.append(rules[i:i + chunk_size])
        
        return chunks
    
    def _identify_cascade_groups(
        self, 
        rules: List[ExtractionRule]
    ) -> Tuple[List[Tuple['CascadeConfig', List[ExtractionRule]]], List[ExtractionRule]]:
        """
        识别并分组所有级联字段（通用方法）
        
        支持：
        - 链式级联：如省市区（BDSZDS → BDSZDSHI → BDSZDQX）
        - 选择性级联：如资产类别（ZCLB → FWJZW/TD/JXSB/...）
        
        Args:
            rules: 提取规则列表
            
        Returns:
            tuple: (cascade_groups, normal_rules)
                - cascade_groups: [(配置, 规则列表), ...] 级联字段组列表
                - normal_rules: 非级联字段的规则列表
        """
        from src.services.extraction.cascade_configs import ALL_CASCADE_CONFIGS
        from src.schemas.cascade_config import CascadeType, ChainCascadeConfig, ConditionalCascadeConfig
        
        # 构建字段名到规则的映射
        field_name_to_rule = {rule.field_name: rule for rule in rules}
        
        # 收集级联字段组
        cascade_groups: List[Tuple['CascadeConfig', List[ExtractionRule]]] = []
        cascade_field_names = set()
        
        for config in ALL_CASCADE_CONFIGS:
            if config.cascade_type == CascadeType.CHAIN:
                # 链式级联：检查所有字段是否都存在
                group_rules = []
                all_exist = True
                
                for field_name in config.field_names:
                    if field_name in field_name_to_rule:
                        group_rules.append(field_name_to_rule[field_name])
                        cascade_field_names.add(field_name)
                    else:
                        all_exist = False
                        break
                
                # 只有当所有字段都存在时，才加入级联组
                if all_exist and len(group_rules) == len(config.field_names):
                    cascade_groups.append((config, group_rules))
                    logger.info(
                        f"识别到链式级联组: {config.cascade_name} | "
                        f"字段: {' → '.join(config.field_names)}"
                    )
            
            elif config.cascade_type == CascadeType.CONDITIONAL:
                # 选择性级联：检查主字段和所有子字段是否存在
                group_rules = []
                
                # 检查主字段
                if config.master_field not in field_name_to_rule:
                    logger.debug(f"选择性级联 {config.cascade_name} 的主字段 {config.master_field} 不存在，跳过")
                    continue
                
                master_rule = field_name_to_rule[config.master_field]
                group_rules.append(master_rule)
                # 注意：不在这里添加主字段到 cascade_field_names，等确认有子字段后再添加
                
                # 检查所有子字段（支持一对多映射）
                child_fields_exist = []
                all_child_fields = set()  # 收集所有唯一的子字段名
                
                for mapped_value in config.field_mapping.values():
                    # 处理一对多映射：mapped_value 可能是字符串或列表
                    if isinstance(mapped_value, list):
                        for child_field in mapped_value:
                            all_child_fields.add(child_field)
                    else:
                        all_child_fields.add(mapped_value)
                
                # 检查每个子字段是否存在于规则中
                for child_field in all_child_fields:
                    if child_field in field_name_to_rule:
                        group_rules.append(field_name_to_rule[child_field])
                        child_fields_exist.append(child_field)
                
                # 只要主字段存在且至少有一个子字段存在，就加入级联组
                if child_fields_exist:
                    # 只有确认级联生效时，才将主字段和子字段加入 cascade_field_names
                    cascade_field_names.add(config.master_field)
                    for child_field in child_fields_exist:
                        cascade_field_names.add(child_field)
                    cascade_groups.append((config, group_rules))
                    logger.info(
                        f"识别到选择性级联组: {config.cascade_name} | "
                        f"主字段: {config.master_field} | "
                        f"子字段: {len(child_fields_exist)}/{len(all_child_fields)} 个"
                    )
        
        # 收集非级联字段
        normal_rules = [
            rule for rule in rules 
            if rule.field_name not in cascade_field_names
        ]
        
        if cascade_groups:
            logger.info(
                f"级联字段分组完成: {len(cascade_groups)} 组级联, "
                f"{len(normal_rules)} 个普通字段"
            )
        
        return cascade_groups, normal_rules
    
    async def _extract_chain_cascade(
        self,
        cascade_config: 'ChainCascadeConfig',
        cascade_rules: List[ExtractionRule],
        parsed_files: Dict[str, Any],
        request: ExtractionRequest,
        skip_highlight: bool = False,
        anchor_markdown_cache: Optional[Dict[str, Tuple[str, Dict[str, Any]]]] = None,
        parse_contexts: Optional[Dict[str, 'FileTypeParseContext']] = None,
        on_field_completed: Optional[Callable] = None
    ) -> List[FieldExtractionResult]:
        """
        链式级联提取（如省→市→区）
        
        每次提取时，根据上一级的结果注入可选值到 extraction_logic，
        提高模型提取的准确率。
        
        处理流程：
        1. 提取第一级，注入所有可选值（如所有省份列表）
        2. 根据提取到的第一级结果，注入第二级的可选值（如该省的城市列表），提取第二级
        3. 根据提取到的前两级结果，注入第三级的可选值（如该市的区县列表），提取第三级
        
        Args:
            cascade_config: 链式级联配置
            cascade_rules: 按级联顺序排列的规则列表
            parsed_files: 解析后的文件数据
            request: 提取请求
            skip_highlight: 是否跳过高亮生成
            anchor_markdown_cache: Anchor Markdown 缓存
            parse_contexts: 流水线模式下的解析上下文（链式级联暂不使用）
            
        Returns:
            List[FieldExtractionResult]: 所有字段的提取结果
        """
        from src.utils.region_data_helper import get_region_helper
        
        helper = get_region_helper()
        results = []
        extracted_province = None
        extracted_city = None
        
        logger.info(
            f"开始链式级联提取: {cascade_config.cascade_name} | "
            f"字段: {[r.field_name for r in cascade_rules]}"
        )
        
        for idx, rule in enumerate(cascade_rules):
            # 构建增强的 extraction_logic
            enhanced_logic = rule.extraction_logic
            
            if idx == 0:
                # 第一级（省份）：注入所有省份
                provinces = helper.get_all_provinces()
                if provinces:
                    provinces_str = ', '.join(provinces)
                    enhanced_logic += f"\n\n【可选省份】：{provinces_str}"
                    logger.debug(f"注入 {len(provinces)} 个省份选项")
            
            elif idx == 1:
                # 第二级（市）：根据省份注入城市
                if extracted_province:
                    cities = helper.get_cities_by_province(extracted_province)
                    if cities:
                        cities_str = ', '.join(cities)
                        enhanced_logic += f"\n\n【{extracted_province} 的可选城市】：{cities_str}"
                        logger.debug(f"注入 {len(cities)} 个城市选项（基于省份: {extracted_province}）")
                    else:
                        logger.warning(f"未找到 {extracted_province} 的城市列表，使用原始提取逻辑")
                else:
                    logger.warning("省份提取失败或为空，市字段使用原始提取逻辑")
            
            elif idx == 2:
                # 第三级（区县）：根据省市注入区县
                if extracted_province and extracted_city:
                    districts = helper.get_districts_by_city(extracted_province, extracted_city)
                    if districts:
                        districts_str = ', '.join(districts)
                        enhanced_logic += f"\n\n【{extracted_city} 的可选区县】：{districts_str}"
                        logger.debug(
                            f"注入 {len(districts)} 个区县选项（基于省市: {extracted_province}/{extracted_city}）"
                        )
                    else:
                        logger.warning(
                            f"未找到 {extracted_province} {extracted_city} 的区县列表，使用原始提取逻辑"
                        )
                else:
                    logger.warning("省份或城市提取失败，区县字段使用原始提取逻辑")
            
            # 创建临时规则对象（修改 extraction_logic）
            temp_rule = rule.model_copy(update={'extraction_logic': enhanced_logic})
            
            # 调用现有的单字段提取逻辑
            logger.info(f"提取链式级联字段 [{idx+1}/{len(cascade_rules)}]: {rule.field_name}")
            result = await self._extract_single_field(
                rule=temp_rule,
                parsed_files=parsed_files,
                request=request,
                skip_highlight=skip_highlight,
                anchor_markdown_cache=anchor_markdown_cache
            )
            
            results.append(result)
            
            # 每完成一个字段，立即更新进度
            if on_field_completed:
                await on_field_completed()
            
            # 提取成功的值供下一级使用
            if result.values and len(result.values) > 0:
                extracted_value = result.values[0].extracted_value
                if extracted_value:
                    if idx == 0:
                        extracted_province = extracted_value
                        logger.info(f"第一级提取结果: {extracted_province}")
                    elif idx == 1:
                        extracted_city = extracted_value
                        logger.info(f"第二级提取结果: {extracted_city}")
                    elif idx == 2:
                        logger.info(f"第三级提取结果: {extracted_value}")
                else:
                    logger.warning(f"字段 {rule.field_name} 提取结果为空")
            else:
                logger.warning(f"字段 {rule.field_name} 提取失败，无 values")
        
        logger.info(f"链式级联提取完成: {cascade_config.cascade_name} | {len(results)} 个字段")
        return results
    
    def _determine_child_fields(
        self,
        master_result: FieldExtractionResult,
        cascade_config: 'ConditionalCascadeConfig'
    ) -> Set[str]:
        """
        根据主字段提取结果，确定需要提取的子字段集合
        
        Args:
            master_result: 主字段的提取结果
            cascade_config: 选择性级联配置
            
        Returns:
            Set[str]: 需要提取的子字段名称集合
        """
        fields_to_extract = set()
        
        if master_result.values and len(master_result.values) > 0:
            master_value = master_result.values[0].extracted_value
            
            if master_value:
                logger.debug(f"解析主字段 {cascade_config.master_field} 的值: {master_value}")
                
                # 尝试解析为 JSON 数组
                try:
                    import json
                    parsed_values = json.loads(master_value)
                    if isinstance(parsed_values, list):
                        master_values = parsed_values
                    else:
                        master_values = [master_value]
                except (json.JSONDecodeError, TypeError):
                    # 不是 JSON，按逗号分割或单个值
                    if ',' in master_value:
                        master_values = [v.strip() for v in master_value.split(',')]
                    else:
                        master_values = [master_value]
                
                # 根据主字段值，查找对应的子字段（支持一对多和多对一映射）
                for value in master_values:
                    value_clean = value.strip()
                    if value_clean in cascade_config.field_mapping:
                        mapped = cascade_config.field_mapping[value_clean]
                        
                        # 处理一对多映射：一个值映射到多个字段
                        if isinstance(mapped, list):
                            for child_field in mapped:
                                fields_to_extract.add(child_field)
                                logger.debug(f"主字段值 '{value_clean}' → 需要提取子字段 '{child_field}'")
                        else:
                            # 处理一对一映射：一个值映射到一个字段
                            fields_to_extract.add(mapped)
                            logger.debug(f"主字段值 '{value_clean}' → 需要提取子字段 '{mapped}'")
                    else:
                        logger.debug(f"主字段值 '{value_clean}' 在映射表中未找到对应的子字段")
        
        return fields_to_extract
    
    async def _create_failed_field_result_async(
        self,
        rule: ExtractionRule,
        error_message: str
    ) -> FieldExtractionResult:
        """
        创建失败的字段提取结果（异步版本，用于兼容任务列表）
        
        Args:
            rule: 提取规则
            error_message: 错误信息
            
        Returns:
            FieldExtractionResult: 失败的字段提取结果
        """
        return FieldExtractionResult(
            field_id=rule.id,
            field_name=rule.field_name,
            field_type=rule.field_type.value,
            field_status=FieldExtractionStatus.FAILED,
            values=[],
            error_message=error_message,
            inconsistent_values=None,
            extraction_rule={
                "rule_id": rule.id,
                "field_name": rule.field_name,
                "field_type": rule.field_type.value,
                "extraction_logic": rule.extraction_logic,
                "reference_materials": rule.reference_materials,
                "enabled": rule.enabled
            }
        )
    
    def _merge_multi_source_results(
        self,
        rule: ExtractionRule,
        field_result_list: List[FieldExtractionResult]
    ) -> FieldExtractionResult:
        """
        合并多个来源的字段提取结果
        
        当一个字段有多个 reference_materials 时，会从多个文件中提取，
        这个方法将它们聚合成一个 FieldExtractionResult。
        
        聚合逻辑：
        1. 按照 reference_materials 配置顺序重新排序结果
        2. 合并所有来源的 values（每个 value 代表一个来源的提取结果）
        3. 重新计算字段状态：
           - 所有来源值一致（包括都是空值）-> SUCCESS
           - 值不一致（如来源1有值，来源2空值）-> PENDING
           - 有错误 -> FAILED
        
        Args:
            rule: 提取规则
            field_result_list: 来自不同文件的提取结果列表
            
        Returns:
            FieldExtractionResult: 聚合后的结果
        """
        # 按照 reference_materials 配置顺序重新排序 field_result_list
        # 这样确保 values 数组顺序与配置文件中的顺序一致
        sorted_field_results = self._sort_field_results_by_reference_order(
            rule.reference_materials,
            field_result_list
        )
        
        # 合并所有来源的 values
        all_values = []
        all_errors = []
        
        for field_result in sorted_field_results:
            if field_result.values:
                all_values.extend(field_result.values)
            if field_result.error_message:
                all_errors.append(field_result.error_message)
        
        # 输出聚合详情
        logger.debug(f"聚合字段 {rule.field_name}:")
        for i, val in enumerate(all_values):
            value_preview = str(val.extracted_value)[:50] if val.extracted_value else "(空)"
            logger.debug(
                f"  来源{i+1}: {val.source_file_type} | "
                f"值: {value_preview} | "
                f"sources数: {len(val.sources)}"
            )
        
        # 重新计算字段状态（基于所有来源的值）
        # 注意：只有在完全没有成功提取的值时，才传递 error_message
        # 如果有至少一个来源成功提取，就忽略其他来源的错误（如缺少文件）
        error_message = None
        if not all_values and all_errors:
            # 所有来源都失败了，合并错误信息
            error_message = "; ".join(all_errors)
        
        field_status, inconsistent_values = self._calculate_field_status(
            all_values,
            error_message=error_message
        )
        
        # 输出聚合后的状态
        logger.debug(
            f"聚合结果: {rule.field_name} | "
            f"总values数: {len(all_values)} | "
            f"最终状态: {field_status} | "
            f"不一致值: {inconsistent_values or '无'}"
        )
        
        # 按优先级排序 values：有值的排前面，空值的排后面
        # 传入 reference_materials 以便在排序时保持配置顺序
        sorted_values = self._sort_values_by_priority(all_values, rule.reference_materials)
        
        # 构建聚合后的结果
        return FieldExtractionResult(
            field_id=rule.id,
            field_name=rule.field_name,
            field_type=rule.field_type.value,
            field_status=field_status,
            values=sorted_values,
            error_message=error_message,
            inconsistent_values=inconsistent_values,
            extraction_rule={
                "rule_id": rule.id,
                "field_name": rule.field_name,
                "field_type": rule.field_type.value,
                "extraction_logic": rule.extraction_logic,
                "reference_materials": rule.reference_materials,
                "enabled": rule.enabled
            }
        )
    
    def _sort_values_by_priority(
        self,
        values: List[ExtractedFieldValue],
        reference_materials: List[str]
    ) -> List[ExtractedFieldValue]:
        """
        对 values 列表按优先级排序：有值的排前面，空值的排后面
        
        排序规则（多级排序）：
        1. 首先按有值/无值排序（有值的排前面）
        2. 在有值组内，按 reference_materials 配置顺序排序
        3. 在无值组内，也按 reference_materials 配置顺序排序
        
        Args:
            values: 提取值列表
            reference_materials: 参考材料列表（配置顺序）
            
        Returns:
            排序后的提取值列表
        """
        from src.schemas.file import LABEL_TO_FILE_TYPE
        
        # 构建 reference_material -> 优先级索引 的映射
        material_priority = {material: idx for idx, material in enumerate(reference_materials)}
        
        def has_value(v: ExtractedFieldValue) -> bool:
            """判断是否有有效值：非 None 且非空字符串"""
            return v.extracted_value is not None and v.extracted_value != ""
        
        def get_config_priority(v: ExtractedFieldValue) -> int:
            """获取该 value 在配置中的优先级索引"""
            source_file_type = v.source_file_type
            
            # 遍历 reference_materials，找到匹配的
            for material, priority in material_priority.items():
                if material in LABEL_TO_FILE_TYPE:
                    expected_file_type = LABEL_TO_FILE_TYPE[material].value
                    if expected_file_type == source_file_type:
                        return priority
            
            # 无法匹配，放最后
            return len(reference_materials)
        
        # 多级排序：先按有值/无值，再按配置顺序
        # has_value() 返回 True/False，转换为 0/1，False(0) < True(1)，所以用 not has_value()
        return sorted(values, key=lambda v: (0 if has_value(v) else 1, get_config_priority(v)))
    
    def _sort_field_results_by_reference_order(
        self,
        reference_materials: List[str],
        field_results: List[FieldExtractionResult]
    ) -> List[FieldExtractionResult]:
        """
        按照 reference_materials 的配置顺序对字段提取结果进行排序
        
        这样确保最终的 values 数组顺序与配置文件中 reference_materials 的顺序一致。
        对于无法匹配到 reference_material 的结果，放在最后。
        
        Args:
            reference_materials: 参考材料列表（配置顺序）
            field_results: 字段提取结果列表
            
        Returns:
            排序后的字段提取结果列表
        """
        from src.schemas.file import LABEL_TO_FILE_TYPE
        
        # 构建 reference_material -> 优先级索引 的映射
        material_priority = {material: idx for idx, material in enumerate(reference_materials)}
        
        def get_result_priority(result: FieldExtractionResult) -> int:
            """
            获取结果的优先级索引
            通过 values[0].source_file_type 反推 reference_material
            """
            if not result.values or len(result.values) == 0:
                return len(reference_materials)  # 没有值的放最后
            
            # 从第一个 value 的 source_file_type 获取文件类型
            source_file_type = result.values[0].source_file_type
            
            # 遍历 reference_materials，找到匹配的
            for material, priority in material_priority.items():
                # 通过 LABEL_TO_FILE_TYPE 查找对应的 file_type
                if material in LABEL_TO_FILE_TYPE:
                    expected_file_type = LABEL_TO_FILE_TYPE[material].value
                    if expected_file_type == source_file_type:
                        return priority
            
            # 无法匹配，放最后
            return len(reference_materials)
        
        # 按优先级排序
        return sorted(field_results, key=get_result_priority)
    
    def _build_batch_extraction_logic(
        self,
        rules: List[ExtractionRule],
        reference_material: str,
        retry_errors: Optional[Dict[str, str]] = None
    ) -> str:
        """
        构建批量提取的 extraction_logic 字符串
        
        格式：
        请从《XXX》中批量提取以下字段：
        
        【字段1：字段名】
        提取逻辑：...
        Tips：您上次输出的JSON结果下游解析失败了，失败的原因是...（可选，仅重试时）
        
        【字段2：字段名】
        提取逻辑：...
        
        Args:
            rules: 提取规则列表
            reference_material: 参考材料名称
            retry_errors: 重试错误信息字典 {field_name: error_message}
            
        Returns:
            str: 完整的批量提取逻辑
        """
        parts = [f"请从{reference_material}中批量提取以下字段：\n"]
        
        for rule in rules:
            # 构建单个字段的提取逻辑
            field_section = f"\n【字段：{rule.field_name}】\n"
            
            # 添加提取逻辑（包含字段类型信息）
            extraction_logic = self._build_extraction_logic(rule)
            field_section += f"提取逻辑：{extraction_logic}"
            
            # 如果有重试错误信息，添加 Tips
            if retry_errors and rule.field_name in retry_errors:
                error_msg = retry_errors[rule.field_name]
                field_section += f"\nTips：您上次输出的JSON结果下游解析失败了，失败的原因是{error_msg}"
            
            parts.append(field_section)
        
        return "\n".join(parts)
    
    async def _extract_batch_fields(
        self,
        rules: List[ExtractionRule],
        file_data: Dict[str, Any],
        reference_material: str,
        skip_highlight: bool = False,
        anchor_markdown_cache: Optional[Dict[str, Tuple[str, Dict[str, Any]]]] = None,
        on_field_completed: Optional[Callable] = None
    ) -> List[FieldExtractionResult]:
        """
        批量提取多个字段（核心方法，含重试机制）
        
        Args:
            rules: 提取规则列表（同一文件的多个字段）
            file_data: 文件数据字典
            reference_material: 参考材料名称
            skip_highlight: 是否跳过高亮生成
            anchor_markdown_cache: Anchor Markdown 缓存
            
        Returns:
            List[FieldExtractionResult]: 字段提取结果列表
        """
        field_names = [rule.field_name for rule in rules]
        logger.info(f"批量提取 {len(rules)} 个字段: {field_names}")
        
        # 获取文件类型用于缓存查找
        file_type = file_data.get("file_type", "")
        
        # 获取或生成 Anchor Markdown（Excel 与 PDF/Word 统一入口）
        tagged_markdown, segment_map, is_excel = resolve_anchor_context(
            file_data, anchor_markdown_cache
        )
        if is_excel:
            logger.debug(
                f"使用 Excel 锚点上下文 | 锚点数: {len(segment_map)} | "
                f"trace_supported: {file_data.get('excel_trace_supported', True)}"
            )
        elif anchor_markdown_cache and file_type in anchor_markdown_cache:
            logger.debug(f"使用缓存的 Anchor Markdown | 文件类型: {file_type}")
        elif tagged_markdown:
            logger.info(
                f"Anchor Markdown 转换完成 | 长度: {len(tagged_markdown)} 字符 | "
                f"片段数: {len(segment_map)}"
            )
        
        # === DEBUG: 输出 Anchor Markdown 调试信息 ===
        logger.debug(f"=== Anchor Markdown 调试信息 [{file_type}] ===")
        logger.debug(f"segment_map 锚点数量: {len(segment_map)}")
        
        # 输出完整的 tagged_markdown（截断到前 5000 字符避免日志过长）
        if len(tagged_markdown) > 5000:
            logger.debug(f"tagged_markdown (前5000字符):\n{tagged_markdown[:5000]}\n... [截断，总长度: {len(tagged_markdown)}]")
        else:
            logger.debug(f"tagged_markdown:\n{tagged_markdown}")
        
        # 输出所有锚点的详细信息（按页码和锚点ID排序）
        if segment_map:
            sorted_anchors = sorted(segment_map.items(), key=lambda x: (x[1].page_idx, x[0]))
            logger.debug(f"=== segment_map 详细内容 ===")
            for anchor_id, segment in sorted_anchors:
                bbox_str = f"[{segment.bbox[0]:.0f}, {segment.bbox[1]:.0f}, {segment.bbox[2]:.0f}, {segment.bbox[3]:.0f}]" if segment.bbox else "None"
                text_preview = segment.text[:50] + "..." if segment.text and len(segment.text) > 50 else segment.text
                logger.debug(
                    f"  锚点 {anchor_id}: page={segment.page_idx}, "
                    f"bbox={bbox_str}, type={segment.segment_type}, "
                    f"text='{text_preview}'"
                )
        logger.debug(f"=== Anchor Markdown 调试信息结束 ===")
        
        direct_results = {}
        for rule in rules:
            match = match_cover_field(rule, segment_map)
            if match:
                value, anchors = match
                direct_results[rule.field_name] = UnifiedExtractionResult(
                    extracted_value=value, anchor_ids=anchors, confidence=1.0, success=True
                )
        semantic_rules = [rule for rule in rules if rule.field_name not in direct_results]

        # 优化的重试机制：解析失败时快速降级
        retry_errors: Optional[Dict[str, str]] = None
        last_exception: Optional[Exception] = None
        max_retries = self.concurrency_config.batch_max_retry_times
        should_fallback = False  # 是否应该降级到单字段模式
        
        for attempt in range(max_retries):
            try:
                batch_results = []
                if semantic_rules:
                    batch_extraction_logic = self._build_batch_extraction_logic(
                        semantic_rules, reference_material, retry_errors
                    )
                    fields_info = [{
                        "field_name": rule.field_name,
                        "extraction_logic": batch_extraction_logic,
                    } for rule in semantic_rules]

                    unified_config = self.llm_config.get_unified_extraction_agent_config()
                    async with self._llm_semaphore:
                        async with LLMClient(unified_config) as client:
                            agent = UnifiedExtractionAgent(client)
                            batch_results = await agent.extract_batch(
                                file_content=tagged_markdown,
                                fields_info=fields_info,
                                reference_materials=reference_material
                            )

                if direct_results and len(batch_results) == len(semantic_rules):
                    semantic_results = iter(batch_results)
                    batch_results = [
                        direct_results[rule.field_name] if rule.field_name in direct_results else next(semantic_results)
                        for rule in rules
                    ]
                
                # 检查返回结果数量
                if len(batch_results) != len(rules):
                    error_msg = f"批量提取返回结果数量不匹配：期望 {len(rules)}，实际 {len(batch_results)}"
                    logger.warning(error_msg)
                    if attempt == 0:
                        # 第一次失败，给一次重试机会
                        retry_errors = {rule.field_name: error_msg for rule in rules}
                        continue
                    else:
                        # 第二次仍失败，直接降级到单字段模式
                        logger.warning(f"批量提取重试后仍返回数量不匹配，降级到单字段模式")
                        should_fallback = True
                        break
                
                # 检测是否全部因解析失败或异常而失败
                all_parse_failed = bool(semantic_rules) and all(
                    not r.success and (
                        r.error == "无法解析批量提取结果" or 
                        r.error == "批量提取异常，需要重试"
                    )
                    for rule, r in zip(rules, batch_results)
                    if rule.field_name not in direct_results
                )
                if all_parse_failed:
                    if attempt == 0:
                        # 第一次失败，给 LLM 一次纠正格式的机会或重试
                        error_msg = "批量提取失败，请返回标准JSON数组格式"
                        retry_errors = {rule.field_name: error_msg for rule in rules}
                        logger.warning(f"批量提取全部失败 (尝试 {attempt + 1}/{max_retries})，将重试1次")
                        continue
                    else:
                        # 第二次仍失败，直接降级到单字段模式
                        logger.warning(f"批量提取重试后仍失败，降级到单字段模式")
                        should_fallback = True
                        break
                
                # 构建 FieldExtractionResult 列表
                field_results = []
                
                for i, (rule, unified_result) in enumerate(zip(rules, batch_results)):
                    try:
                        if not unified_result.success:
                            # 提取失败（解析错误等真正的失败，不包括空值）
                            field_results.append(FieldExtractionResult(
                                field_id=rule.id,
                                field_name=rule.field_name,
                                field_type=rule.field_type.value,
                                field_status=FieldExtractionStatus.FAILED,
                                values=[],
                                error_message=unified_result.error or "提取失败",
                                inconsistent_values=None,
                                extraction_rule={
                                    "rule_id": rule.id,
                                    "field_name": rule.field_name,
                                    "field_type": rule.field_type.value,
                                    "extraction_logic": rule.extraction_logic,
                                    "reference_materials": rule.reference_materials,
                                    "enabled": rule.enabled
                                }
                            ))
                            continue
                        
                        # 提取成功，处理溯源（空值也可能有溯源）
                        anchor_ids = unified_result.anchor_ids
                        bbox_infos = AnchorMarkdownConverter.lookup_bboxes_by_anchors(anchor_ids, segment_map)
                        
                        regions = self._build_regions_from_bbox_infos(bbox_infos, is_excel=is_excel)
                        
                        # 如果没有找到坐标但有锚点，记录详细警告（与单字段提取保持一致）
                        if anchor_ids and not regions:
                            missing_ids = []
                            invalid_bbox_ids = []
                            for aid in anchor_ids:
                                if aid in segment_map:
                                    invalid_bbox_ids.append(aid)
                                else:
                                    missing_ids.append(aid)
                            
                            if missing_ids:
                                logger.warning(
                                    f"[{rule.field_name}] 锚点 {missing_ids} 在映射表中不存在 "
                                    f"(segment_map 大小: {len(segment_map)})"
                                )
                            if invalid_bbox_ids:
                                logger.warning(
                                    f"[{rule.field_name}] 锚点 {invalid_bbox_ids} 存在但 bbox 无效"
                                )
                        
                        # 构建溯源信息（即使是空值，只要有 regions 就创建溯源）
                        # 这样用户可以看到 LLM 找到的位置，即使该位置内容为空
                        sources = []
                        if regions:
                            sources.append(self._build_source_info_from_regions(
                                file_data=file_data,
                                rule=rule,
                                unified_result=unified_result,
                                regions=regions,
                                segment_map=segment_map,
                                preview_image="",
                                is_excel=is_excel,
                            ))
                        
                        # 构建 ExtractedFieldValue（即使是空值也要创建）
                        # 注意：空值（extracted_value=""）也算有效的提取结果，表示"未找到"
                        extracted_values = [ExtractedFieldValue(
                            source_file_type=file_data["file_type"],
                            source_file_name=", ".join(file_data["file_names"]),
                            source_field_name=rule.field_name,
                            extracted_value=unified_result.extracted_value if unified_result.extracted_value is not None else "",
                            extract_status=ExtractStatus.SUCCESS,
                            confidence=unified_result.confidence or 0.8,
                            sources=sources  # 空值时 sources 为空列表
                        )]
                        
                        # 计算字段状态
                        field_status, inconsistent_values = self._calculate_field_status(
                            extracted_values, error_message=None
                        )
                        
                        # 构建提取规则信息
                        extraction_rule_info = {
                            "rule_id": rule.id,
                            "field_name": rule.field_name,
                            "field_type": rule.field_type.value,
                            "extraction_logic": rule.extraction_logic,
                            "reference_materials": rule.reference_materials,
                            "enabled": rule.enabled
                        }
                        
                        field_results.append(FieldExtractionResult(
                            field_id=rule.id,
                            field_name=rule.field_name,
                            field_type=rule.field_type.value,
                            field_status=field_status,
                            values=extracted_values,
                            error_message=None,
                            inconsistent_values=inconsistent_values,
                            extraction_rule=extraction_rule_info
                        ))
                        
                    except Exception as e:
                        logger.error(f"处理字段 {rule.field_name} 的提取结果失败: {e}", exc_info=True)
                        field_results.append(FieldExtractionResult(
                            field_id=rule.id,
                            field_name=rule.field_name,
                            field_type=rule.field_type.value,
                            field_status=FieldExtractionStatus.FAILED,
                            values=[],
                            error_message=str(e),
                            inconsistent_values=None,
                            extraction_rule={
                                "rule_id": rule.id,
                                "field_name": rule.field_name,
                                "field_type": rule.field_type.value,
                                "extraction_logic": rule.extraction_logic,
                                "reference_materials": rule.reference_materials,
                                "enabled": rule.enabled
                            }
                        ))
                
                logger.info(f"批量提取完成: {len(field_results)} 个字段")
                
                # 每个字段完成后更新进度
                if on_field_completed:
                    for _ in field_results:
                        await on_field_completed()
                
                return field_results
                
            except json.JSONDecodeError as e:
                # JSON 解析失败，准备重试或降级
                error_msg = f"JSON格式错误: {str(e)}"
                logger.warning(f"批量提取JSON解析失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}")
                last_exception = e
                
                if attempt == 0:
                    # 第一次失败，给一次重试机会
                    retry_errors = {rule.field_name: error_msg for rule in rules}
                else:
                    # 第二次仍失败，直接降级到单字段模式
                    logger.warning(f"批量提取重试后仍JSON解析失败，降级到单字段模式")
                    should_fallback = True
                    break
                    
            except Exception as e:
                # 其他异常
                error_msg = str(e) or repr(e) or type(e).__name__
                logger.error(f"批量提取异常 (尝试 {attempt + 1}/{max_retries}): {error_msg}", exc_info=True)
                last_exception = e
                
                if attempt == 0:
                    # 第一次失败，给一次重试机会
                    retry_errors = {rule.field_name: f"提取失败: {error_msg}" for rule in rules}
                else:
                    # 第二次仍失败，直接降级到单字段模式
                    logger.warning(f"批量提取重试后仍异常，降级到单字段模式")
                    should_fallback = True
                    break
        
        # 降级：逐个字段提取（快速降级策略：1次重试后失败则拆分）
        if should_fallback:
            logger.warning(f"批量提取重试1次后仍失败，降级为单字段模式提取 {len(rules)} 个字段（快速降级策略）")
        else:
            logger.warning(f"批量提取失败，降级为单字段模式提取 {len(rules)} 个字段")
        field_results = []
        
        for rule in rules:
            try:
                # 降级时需要构造 parsed_files 参数
                parsed_files_for_single = {file_type: file_data}
                
                result = await self._extract_single_field(
                    rule=rule,
                    parsed_files=parsed_files_for_single,
                    request=None,  # 降级模式不需要 request
                    skip_highlight=skip_highlight,
                    anchor_markdown_cache=anchor_markdown_cache
                )
                field_results.append(result)
                
                # 每个字段完成后更新进度
                if on_field_completed:
                    await on_field_completed()
                    
            except Exception as e:
                logger.error(f"单字段提取失败 {rule.field_name}: {e}", exc_info=True)
                field_results.append(FieldExtractionResult(
                    field_id=rule.id,
                    field_name=rule.field_name,
                    field_type=rule.field_type.value,
                    field_status=FieldExtractionStatus.FAILED,
                    values=[],
                    error_message=str(e),
                    inconsistent_values=None,
                    extraction_rule={
                        "rule_id": rule.id,
                        "field_name": rule.field_name,
                        "field_type": rule.field_type.value,
                        "extraction_logic": rule.extraction_logic,
                        "reference_materials": rule.reference_materials,
                        "enabled": rule.enabled
                    }
                ))
                
                # 即使失败也要更新进度
                if on_field_completed:
                    await on_field_completed()
        
        return field_results
    
    async def _extract_all_fields(
        self,
        extraction_rules: List[ExtractionRule],
        parsed_files: Dict[str, Dict[str, Any]],
        request: ExtractionRequest,
        task_id: Optional[str] = None,
        task_created: bool = False,
        parse_contexts: Optional[Dict[str, 'FileTypeParseContext']] = None,
        downloaded_files_cache: Optional[Dict[str, bytes]] = None,
    ) -> List[FieldExtractionResult]:
        """
        提取所有字段（优化版：分离提取和高亮图生成，支持流水线模式）
        
        注意：LLM 一次调用就返回了提取值和锚点ID，通过查表获取坐标。
        这里的"分离"指的是将高亮图片生成（PDF处理+MinIO上传）延后批量处理。
        
        优化流程：
        1. 预处理：为每个文件预先生成 Anchor Markdown（避免重复转换）
        2. 阶段1：并发提取所有字段（LLM调用+坐标查表，跳过高亮图生成）
        3. 阶段2：批量并发生成高亮图（PDF处理+MinIO上传）
        
        流水线模式（parse_contexts 不为 None）：
        - 解析和提取任务并发执行，边解析边提取
        - 减少总耗时
        
        性能提升：
        - Anchor Markdown 只转换一次，多字段复用
        - 避免每个字段提取时都等待高亮图生成
        - 高亮图生成阶段可以批量并发处理
        
        Args:
            extraction_rules: 提取规则列表
            parsed_files: 解析后的文件数据（串行模式使用）
            request: 原始请求
            task_id: 任务ID（可选）
            task_created: 是否已创建任务
            parse_contexts: 流水线模式的文件类型解析上下文字典
            
        Returns:
            List[FieldExtractionResult]: 字段提取结果列表
        """
        # ========== 流水线模式：真正的边解析边提取 ==========
        # 流水线模式标记
        is_pipeline_mode = parse_contexts is not None
        
        if is_pipeline_mode:
            logger.info(f"[流水线] 启用真正的边解析边提取模式，{len(parse_contexts)} 种文件类型")
            # 不再等待所有文件解析完成，而是在后面按需等待每个 file_type
            # parsed_files 初始化为空，后面按需填充
            parsed_files = {}
        
        # 筛选启用的规则
        enabled_rules = [rule for rule in extraction_rules if rule.enabled]
        total_fields = len(enabled_rules)
        
        if total_fields == 0:
            return []
        
        logger.info(f"开始提取 {total_fields} 个字段（批量模式 + 级联优化 + 分离溯源和高亮）")
        
        # ========== 新增：识别并分离所有级联字段 ==========
        if request.extraction_type in DISCLOSURE_TYPES:
            cascade_groups, normal_rules = [], enabled_rules
        else:
            cascade_groups, normal_rules = self._identify_cascade_groups(enabled_rules)
        
        # ========== 预处理：生成 Anchor Markdown 缓存 ==========
        anchor_markdown_cache: Dict[str, Tuple[str, Dict[str, Any]]] = {}
        for file_type, file_data in parsed_files.items():
            if not file_data:
                continue
            tagged_markdown, segment_map, is_excel = resolve_anchor_context(file_data)
            if tagged_markdown:
                anchor_markdown_cache[file_type] = (tagged_markdown, segment_map)
                source = "Excel" if is_excel else "PDF/Word"
                logger.info(
                    f"预生成 Anchor Markdown ({source}) | 文件类型: {file_type} | "
                    f"长度: {len(tagged_markdown)} 字符 | 片段数: {len(segment_map)}"
                )
        
        # ========== 定义字段级别进度回调（占位）==========
        # 注意：真正的回调逻辑将在计算完总任务数后重新定义
        # 这里先定义一个占位回调，供任务创建时引用
        completed_field_count = 0
        total_tasks_for_progress = 0  # 占位，后面会更新
        real_total_fields = 0  # 占位，后面会更新
        
        async def on_field_completed():
            """字段提取完成回调 - 每完成一个字段调用一次"""
            nonlocal completed_field_count
            completed_field_count += 1
            
            # 检查任务是否已取消
            if task_created and task_id:
                from src.services.redis.task_cancel_subscriber import get_task_cancel_subscriber
                if get_task_cancel_subscriber().is_cancelled(task_id):
                    logger.warning(f"检测到任务取消信号: {task_id}")
                    raise asyncio.CancelledError("任务已取消")
            
            if task_created and task_id and total_tasks_for_progress > 0:
                # 直接用完成数/总数，不再使用百分比权重
                progress = min(completed_field_count / total_tasks_for_progress, 0.99)
                await self.task_store.update_task(
                    task_id,
                    progress=progress,
                    status_message="正在提取字段...",
                    context={
                        "completed_count": completed_field_count,
                        "total_fields": total_tasks_for_progress
                    }
                )
                logger.debug(f"字段提取进度: {completed_field_count}/{total_tasks_for_progress} ({progress:.1%})")
        
        # ========== 性能优化：两阶段提取 - 主字段并行，子字段并行 ==========
        # 第一阶段任务列表：普通字段 + 链式级联 + 选择性级联主字段
        phase1_tasks = []
        phase1_metadata = []
        
        # 保存选择性级联的上下文，用于第二阶段
        conditional_cascade_contexts = []
        
        # ========== 批量优化：收集所有选择性级联主字段信息 ==========
        # 用于后续按材料分组批量提取
        all_conditional_master_info = []  # 存储 {master_rule, config, child_rules_map, first_field_file_types}
        
        # 导入级联类型用于判断
        from src.schemas.cascade_config import CascadeType
        
        # 1. 添加级联字段提取任务
        for config, rules in cascade_groups:
            # 1.1 预检查：确定首个字段/主字段，判断依赖文件是否存在
            # 根据级联类型确定首个字段名
            if config.cascade_type == CascadeType.CHAIN:
                # 链式级联：使用第一个字段作为首个字段
                first_field_name = config.field_names[0] if config.field_names else None
            else:
                # 选择性级联：使用 master_field
                first_field_name = config.master_field
            
            # 找到首个字段的规则
            first_rule = None
            if first_field_name:
                for r in rules:
                    if r.field_name == first_field_name:
                        first_rule = r
                        break
            
            # 检查首个字段依赖的文件是否存在
            should_skip_cascade = False
            skip_reason = ""
            first_field_file_types = set()
            
            if first_rule:
                if is_pipeline_mode and parse_contexts:
                    # 流水线模式：收集首个字段依赖的 file_type
                    for mat in first_rule.reference_materials:
                        ft = self._get_file_type_from_material(mat)
                        if ft and ft in parse_contexts:
                            first_field_file_types.add(ft)
                    
                    # 如果没有找到任何有效的 file_type，说明依赖的文件都缺失
                    if not first_field_file_types:
                        should_skip_cascade = True
                        skip_reason = f"级联首字段 {first_field_name} 依赖的文件不存在: {first_rule.reference_materials}"
                else:
                    # 非流水线模式：检查 parsed_files 中是否有对应文件且内容不为空
                    has_valid_file = False
                    missing_materials = []
                    
                    for mat in first_rule.reference_materials:
                        file_data = self._find_file_by_material(mat, parsed_files)
                        if file_data:
                            # 检查内容是否为空
                            ft_val = file_data.get("file_type", "")
                            if ft_val in anchor_markdown_cache:
                                md, _ = anchor_markdown_cache[ft_val]
                            else:
                                md = file_data.get("md_content", "")
                            
                            if md and len(md.strip()) > 0:
                                has_valid_file = True
                                break
                        missing_materials.append(mat)
                    
                    if not has_valid_file:
                        should_skip_cascade = True
                        skip_reason = f"级联首字段 {first_field_name} 依赖的文件缺失或为空: {missing_materials}"
            
            # 如果判定跳过，创建直接返回失败的任务，并标记 skipped
            if should_skip_cascade:
                logger.warning(f"{skip_reason}，跳过级联组 {config.cascade_name}")
                
                async def create_failed_cascade_task(c_rules=rules, reason=skip_reason):
                    """创建失败的级联任务，不调用 on_field_completed（因为已标记 skipped）"""
                    results = []
                    for r in c_rules:
                        results.append(await self._create_failed_field_result_async(
                            r, reason
                        ))
                    return results
                
                phase1_tasks.append(create_failed_cascade_task())
                phase1_metadata.append({
                    'type': 'cascade',
                    'cascade_type': config.cascade_type,
                    'config': config,
                    'field_count': len(rules),
                    'field_names': [r.field_name for r in rules],
                    'skipped': True  # 关键：标记为跳过，不计入进度统计
                })
                continue
            
            # 1.2 正常创建级联任务（文件存在）
            # 区分链式级联和选择性级联
            if config.cascade_type == CascadeType.CHAIN:
                # 链式级联：保持原有逻辑，作为完整任务
                if is_pipeline_mode and parse_contexts:
                    # 流水线模式优化：只等待首个字段依赖的文件类型，后续字段按需等待
                    async def create_chain_cascade_pipeline_task(
                        cfg=config,
                        cascade_rules=rules,
                        first_fts=first_field_file_types,
                        first_field=first_field_name,
                        all_parse_contexts=parse_contexts
                    ):
                        """流水线模式优化：只等待首个字段依赖的文件类型，后续字段按需等待"""
                        # 只等待首个字段依赖的文件类型解析完成
                        wait_tasks = [all_parse_contexts[ft].wait() for ft in first_fts if ft in all_parse_contexts]
                        if wait_tasks:
                            await asyncio.gather(*wait_tasks)
                        
                        # 从 parse_contexts 构建首个字段需要的 parsed_files
                        first_parsed_files = {}
                        for ft in first_fts:
                            if ft in all_parse_contexts:
                                ctx = all_parse_contexts[ft]
                                if ctx.is_success and ctx.parse_result:
                                    first_parsed_files[ft] = ctx.parse_result
                                    # 动态生成 Anchor Markdown
                                    if ft not in anchor_markdown_cache:
                                        tagged_md, seg_map = AnchorMarkdownConverter.convert(ctx.parse_result)
                                        if tagged_md:
                                            anchor_markdown_cache[ft] = (tagged_md, seg_map)
                        
                        logger.info(f"[流水线优化] 链式级联 {cfg.cascade_name} 首个字段 {first_field} 依赖的 {len(first_fts)} 种文件类型解析完成，开始级联提取")
                        
                        # 执行链式级联字段提取
                        return await self._extract_chain_cascade(
                            cascade_config=cfg,
                            cascade_rules=cascade_rules,
                            parsed_files=first_parsed_files,
                            request=request,
                            skip_highlight=True,
                            anchor_markdown_cache=anchor_markdown_cache,
                            parse_contexts=all_parse_contexts,
                            on_field_completed=on_field_completed
                        )
                    
                    task = create_chain_cascade_pipeline_task()
                else:
                    # 非流水线模式：原有逻辑
                    task = self._extract_chain_cascade(
                        cascade_config=config,
                        cascade_rules=rules,
                        parsed_files=parsed_files,
                        request=request,
                        skip_highlight=True,
                        anchor_markdown_cache=anchor_markdown_cache,
                        on_field_completed=on_field_completed
                    )
                
                phase1_tasks.append(task)
                phase1_metadata.append({
                    'type': 'cascade',
                    'cascade_type': CascadeType.CHAIN,
                    'config': config,
                    'field_count': len(rules),
                    'field_names': [r.field_name for r in rules]
                })
                
            elif config.cascade_type == CascadeType.CONDITIONAL:
                # 选择性级联：收集主字段信息，后续按材料分组批量提取
                # 分离主字段和子字段规则
                master_rule = None
                child_rules_map = {}
                for rule in rules:
                    if rule.field_name == config.master_field:
                        master_rule = rule
                    else:
                        child_rules_map[rule.field_name] = rule
                
                if not master_rule:
                    logger.error(f"未找到选择性级联 {config.cascade_name} 的主字段规则: {config.master_field}")
                    continue
                
                # 收集主字段信息（不立即创建任务，后续按材料分组批量提取）
                all_conditional_master_info.append({
                    'master_rule': master_rule,
                    'config': config,
                    'rules': rules,
                    'child_rules_map': child_rules_map,
                    'first_field_file_types': first_field_file_types if is_pipeline_mode else None
                })
        
        # ========== 1.3 批量优化：按材料分组选择性级联主字段 ==========
        if all_conditional_master_info:
            # 提取所有主字段规则
            all_master_rules = [info['master_rule'] for info in all_conditional_master_info]
            
            # 按引用材料分组
            master_groups = self._group_rules_by_reference_material(all_master_rules)
            logger.info(
                f"[主字段批量优化] 收集到 {len(all_conditional_master_info)} 个选择性级联主字段，"
                f"按 {len(master_groups)} 个引用材料分组"
            )
            
            # 构建主字段规则到信息的映射（用于后续结果处理）
            master_rule_to_info = {info['master_rule'].id: info for info in all_conditional_master_info}
            
            # 构建主字段索引映射（用于多来源聚合）
            master_field_index_map = {rule.id: idx for idx, rule in enumerate(all_master_rules)}
            master_task_to_field_indices = {}
            
            for material, material_master_rules in master_groups.items():
                # 获取 material 对应的 file_type
                file_type = self._get_file_type_from_material(material)
                
                if is_pipeline_mode and file_type and file_type in parse_contexts:
                    # 流水线模式：创建等待+批量提取的包装协程
                    async def create_master_batch_pipeline_task(
                        mat=material,
                        rules=material_master_rules,
                        ft=file_type,
                        ctx=parse_contexts[file_type]
                    ):
                        """流水线模式：等待文件解析后批量提取主字段"""
                        success = await ctx.wait()
                        
                        if not success or not ctx.parse_result:
                            logger.warning(f"[主字段批量] 文件类型 {ft} 解析失败，跳过 {mat} 的主字段提取")
                            results = []
                            for r in rules:
                                results.append(await self._create_failed_field_result_async(
                                    r, f"文件解析失败: {ctx.error or '未知错误'}"
                                ))
                                if on_field_completed:
                                    await on_field_completed()
                            return results
                        
                        file_data = ctx.parse_result
                        logger.info(f"[主字段批量] {ft} 解析完成，开始批量提取 {len(rules)} 个主字段")
                        
                        # 生成 Anchor Markdown（如果尚未缓存）
                        if ft not in anchor_markdown_cache:
                            tagged_md, seg_map = AnchorMarkdownConverter.convert(file_data)
                            if tagged_md:
                                anchor_markdown_cache[ft] = (tagged_md, seg_map)
                        
                        # 批量提取主字段
                        if len(rules) > 1:
                            # 多个主字段：使用批量提取
                            batches = self._chunk_rules(rules)
                            batch_tasks = []
                            for batch in batches:
                                task = self._extract_batch_fields(
                                    rules=batch,
                                    file_data=file_data,
                                    reference_material=mat,
                                    skip_highlight=True,
                                    anchor_markdown_cache=anchor_markdown_cache,
                                    on_field_completed=on_field_completed
                                )
                                batch_tasks.append(task)
                            
                            batch_results_list = await asyncio.gather(*batch_tasks)
                            results = []
                            for batch_results in batch_results_list:
                                if isinstance(batch_results, list):
                                    results.extend(batch_results)
                                else:
                                    results.append(batch_results)
                            return results
                        else:
                            # 单个主字段：使用单字段提取
                            result = await self._extract_single_field(
                                rule=rules[0],
                                parsed_files={ft: file_data},
                                request=request,
                                skip_highlight=True,
                                anchor_markdown_cache=anchor_markdown_cache
                            )
                            if on_field_completed:
                                await on_field_completed()
                            return [result]
                    
                    task_idx = len(phase1_tasks)
                    phase1_tasks.append(create_master_batch_pipeline_task())
                    phase1_metadata.append({
                        'type': 'conditional_master_batch',
                        'cascade_type': CascadeType.CONDITIONAL,
                        'material': material,
                        'field_count': len(material_master_rules),
                        'field_names': [r.field_name for r in material_master_rules],
                        'master_rule_ids': [r.id for r in material_master_rules]
                    })
                    # 记录主字段任务对应的字段索引
                    batch_field_indices = [master_field_index_map[rule.id] for rule in material_master_rules if rule.id in master_field_index_map]
                    master_task_to_field_indices[task_idx] = batch_field_indices
                else:
                    # 非流水线模式：直接批量提取
                    file_data = self._find_file_by_material(material, parsed_files)
                    if not file_data:
                        logger.warning(f"[主字段批量] 未找到参考材料对应的文件: {material}")
                        async def create_failed_master_results(rules=material_master_rules, mat=material):
                            """创建失败的主字段结果，不调用 on_field_completed（因为已标记 skipped）"""
                            results = []
                            for r in rules:
                                results.append(await self._create_failed_field_result_async(
                                    r, f"未找到参考材料对应的文件: {mat}"
                                ))
                            return results
                        task_idx = len(phase1_tasks)
                        phase1_tasks.append(create_failed_master_results())
                        phase1_metadata.append({
                            'type': 'conditional_master_batch',
                            'cascade_type': CascadeType.CONDITIONAL,
                            'material': material,
                            'field_count': len(material_master_rules),
                            'field_names': [r.field_name for r in material_master_rules],
                            'master_rule_ids': [r.id for r in material_master_rules],
                            'skipped': True
                        })
                        # 记录主字段任务对应的字段索引
                        batch_field_indices = [master_field_index_map[rule.id] for rule in material_master_rules if rule.id in master_field_index_map]
                        master_task_to_field_indices[task_idx] = batch_field_indices
                        continue
                    
                    # 批量提取主字段
                    if len(material_master_rules) > 1:
                        # 多个主字段：使用批量提取
                        async def extract_master_batch(rules=material_master_rules, fd=file_data, mat=material):
                            batches = self._chunk_rules(rules)
                            batch_tasks = []
                            for batch in batches:
                                task = self._extract_batch_fields(
                                    rules=batch,
                                    file_data=fd,
                                    reference_material=mat,
                                    skip_highlight=True,
                                    anchor_markdown_cache=anchor_markdown_cache,
                                    on_field_completed=on_field_completed
                                )
                                batch_tasks.append(task)
                            
                            batch_results_list = await asyncio.gather(*batch_tasks)
                            results = []
                            for batch_results in batch_results_list:
                                if isinstance(batch_results, list):
                                    results.extend(batch_results)
                                else:
                                    results.append(batch_results)
                            return results
                        
                        task_idx = len(phase1_tasks)
                        phase1_tasks.append(extract_master_batch())
                    else:
                        # 单个主字段：使用单字段提取
                        async def extract_single_master(rule=material_master_rules[0]):
                            result = await self._extract_single_field(
                                rule=rule,
                                parsed_files=parsed_files,
                                request=request,
                                skip_highlight=True,
                                anchor_markdown_cache=anchor_markdown_cache
                            )
                            if on_field_completed:
                                await on_field_completed()
                            return [result]
                        
                        task_idx = len(phase1_tasks)
                        phase1_tasks.append(extract_single_master())
                    
                    phase1_metadata.append({
                        'type': 'conditional_master_batch',
                        'cascade_type': CascadeType.CONDITIONAL,
                        'material': material,
                        'field_count': len(material_master_rules),
                        'field_names': [r.field_name for r in material_master_rules],
                        'master_rule_ids': [r.id for r in material_master_rules]
                    })
                    # 记录主字段任务对应的字段索引
                    batch_field_indices = [master_field_index_map[rule.id] for rule in material_master_rules if rule.id in master_field_index_map]
                    master_task_to_field_indices[task_idx] = batch_field_indices
            
            # 保存选择性级联上下文供第二阶段使用
            for info in all_conditional_master_info:
                conditional_cascade_contexts.append({
                    'config': info['config'],
                    'rules': info['rules'],
                    'master_rule': info['master_rule'],
                    'child_rules_map': info['child_rules_map'],
                    'first_field_file_types': info['first_field_file_types']
                })
        
        # 2. 按参考材料分组普通字段规则（第一阶段：普通字段）
        groups = self._group_rules_by_reference_material(normal_rules)
        
        # 3. 统计字段数量
        total_normal_fields = len(normal_rules)
        total_extractions = sum(len(rules) for rules in groups.values())
        multi_source_count = total_extractions - total_normal_fields
        total_cascade_fields = sum(len(rules) for config, rules in cascade_groups)
        
        logger.info(
            f"字段分组完成: "
            f"{len(cascade_groups)} 组级联字段({total_cascade_fields}个) + "
            f"{len(groups)} 个文件类型({total_normal_fields}个普通字段) | "
            f"总提取任务: {total_extractions} 个 | "
            f"多来源字段: {multi_source_count} 个"
        )
        
        # 输出每个分组的详细信息
        for material, material_rules in groups.items():
            logger.debug(f"  {material}: {len(material_rules)} 个字段")
            logger.debug(f"    字段列表: {[r.field_name for r in material_rules]}")
        
        # 4. 构建普通字段的提取任务并添加到第一阶段任务列表
        # 记录普通字段任务对应的字段索引列表 {task_idx: [field_idx1, field_idx2, ...]}
        task_to_field_indices = {}
        
        # 构建字段索引映射（规则在 normal_rules 列表中的位置）
        field_index_map = {rule.id: idx for idx, rule in enumerate(normal_rules)}
        
        for material, material_rules in groups.items():
            # 获取 material 对应的 file_type
            file_type = self._get_file_type_from_material(material)
            
            # ========== 流水线模式：创建等待+提取的包装协程 ==========
            if is_pipeline_mode and file_type and file_type in parse_contexts:
                async def create_pipeline_extraction_task(
                    mat=material, 
                    mat_rules=material_rules, 
                    ft=file_type,
                    ctx=parse_contexts[file_type]
                ):
                    """流水线模式：等待 file_type 解析完成后执行提取"""
                    # 等待该 file_type 解析完成
                    success = await ctx.wait()
                    
                    if not success or not ctx.parse_result:
                        logger.warning(f"[流水线] 文件类型 {ft} 解析失败，跳过 {mat} 的提取")
                        
                        # 返回失败结果列表
                        results = []
                        for r in mat_rules:
                            results.append(await self._create_failed_field_result_async(
                                r, f"文件解析失败: {ctx.error or '未知错误'}"
                            ))
                            # 失败的字段也需要计数
                            if on_field_completed:
                                await on_field_completed()
                        return results
                    
                    file_data = ctx.parse_result
                    logger.info(f"[流水线] {ft} 解析完成，立即开始提取 {mat} 的 {len(mat_rules)} 个字段")
                    
                    # 生成 Anchor Markdown（如果尚未缓存）
                    if ft not in anchor_markdown_cache:
                        tagged_md, seg_map = AnchorMarkdownConverter.convert(file_data)
                        if tagged_md:
                            anchor_markdown_cache[ft] = (tagged_md, seg_map)
                            logger.info(f"[流水线] 动态生成 Anchor Markdown | {ft} | 长度: {len(tagged_md)}")
                    
                    if ft in anchor_markdown_cache:
                        tagged_markdown, _ = anchor_markdown_cache[ft]
                    else:
                        tagged_markdown = file_data.get("md_content", "")
                    
                    # 判断是否需要 RAG
                    need_rag = self.rag_handler.should_use_rag(len(tagged_markdown))
                    
                    results = []
                    if need_rag:
                        # RAG 模式：单字段提取 - 改为并发执行
                        logger.info(f"[流水线] {mat} 触发 RAG，使用单字段模式，共 {len(mat_rules)} 个字段将并发提取")
                        single_parsed = {ft: file_data}
                        
                        # 创建所有字段的并发任务
                        field_tasks = []
                        for r in mat_rules:
                            # 包装单字段任务以调用回调
                            async def single_field_with_callback(rule=r):
                                result = await self._extract_single_field(
                                    rule=rule,
                                    parsed_files=single_parsed,
                                    request=request,
                                    skip_highlight=True,
                                    anchor_markdown_cache=anchor_markdown_cache,
                                    target_material=mat
                                )
                                # 单字段完成后调用回调
                                if on_field_completed:
                                    await on_field_completed()
                                return result
                            field_tasks.append(single_field_with_callback())
                        
                        # 并发执行所有字段提取
                        results = await asyncio.gather(*field_tasks)
                    else:
                        # 批量模式 - 改为并发执行
                        logger.info(f"[流水线] {mat} 使用批量模式，字段数: {len(mat_rules)}")
                        batches = self._chunk_rules(mat_rules)
                        logger.info(f"[流水线] {mat} 分为 {len(batches)} 批，将并发执行")
                        
                        # 创建所有批次的并发任务
                        batch_tasks = []
                        for batch_idx, batch in enumerate(batches):
                            task = self._extract_batch_fields(
                                rules=batch,
                                file_data=file_data,
                                reference_material=mat,
                                skip_highlight=True,
                                anchor_markdown_cache=anchor_markdown_cache,
                                on_field_completed=on_field_completed
                            )
                            batch_tasks.append(task)
                        
                        # 并发执行所有批次
                        batch_results_list = await asyncio.gather(*batch_tasks)
                        
                        # 展平结果
                        for batch_results in batch_results_list:
                            if isinstance(batch_results, list):
                                results.extend(batch_results)
                            else:
                                results.append(batch_results)
                    
                    return results
                
                # 添加流水线任务到第一阶段
                task_idx = len(phase1_tasks)
                phase1_tasks.append(create_pipeline_extraction_task())
                phase1_metadata.append({
                    'type': 'pipeline_normal',
                    'material': material,
                    'file_type': file_type,
                    'field_count': len(material_rules)
                })
                # 记录这一批字段的索引列表
                batch_field_indices = [field_index_map[rule.id] for rule in material_rules]
                task_to_field_indices[task_idx] = batch_field_indices
                continue
            
            # ========== 非流水线模式：原有逻辑 ==========
            # 查找对应的文件数据
            file_data = self._find_file_by_material(material, parsed_files)
            if not file_data:
                logger.warning(f"未找到参考材料对应的文件: {material}，跳过")
                # 为这些字段创建失败结果
                for rule in material_rules:
                    # 创建一个返回失败结果的协程
                    async def create_failed_result(r=rule, msg=material):
                        return await self._create_failed_field_result_async(
                            r, f"未找到参考材料对应的文件: {msg}"
                        )
                    task_idx = len(phase1_tasks)
                    phase1_tasks.append(create_failed_result())
                    phase1_metadata.append({
                        'type': 'normal',
                        'material': material,
                        'field_count': 1,
                        'skipped': True  # 标记为跳过的任务，不计入进度统计
                    })
                    # 记录这个任务对应的字段索引
                    task_to_field_indices[task_idx] = [field_index_map[rule.id]]
                continue
            
            # 获取 Anchor Markdown
            ft_value = file_data.get("file_type", "")
            if ft_value in anchor_markdown_cache:
                tagged_markdown, _ = anchor_markdown_cache[ft_value]
            else:
                tagged_markdown = file_data.get("md_content", "")
            
            # 判断是否需要 RAG（如果需要，回退单字段模式）
            need_rag = self.rag_handler.should_use_rag(len(tagged_markdown))
            
            if need_rag:
                # RAG 模式：使用单字段提取，但只传入当前 material 的文件
                # 这样可以利用 _extract_single_field 内部的 RAG 处理逻辑，同时避免重复提取
                # 关键：构造只包含当前 material 文件的 parsed_files，防止遍历所有 reference_materials
                logger.info(f"文件 {material} 触发 RAG（长度: {len(tagged_markdown)}），使用单字段模式")
                
                # 构造只包含当前 material 的 parsed_files
                single_material_parsed_files = {ft_value: file_data}
                
                for rule in material_rules:
                    # 包装单字段任务以调用回调
                    async def single_field_with_callback(r=rule, mat=material):
                        result = await self._extract_single_field(
                            rule=r,
                            parsed_files=single_material_parsed_files,
                            request=request,
                            skip_highlight=True,
                            anchor_markdown_cache=anchor_markdown_cache,
                            target_material=mat
                        )
                        # 单字段完成后调用回调
                        if on_field_completed:
                            await on_field_completed()
                        return result
                    
                    task_idx = len(phase1_tasks)
                    phase1_tasks.append(single_field_with_callback())
                    phase1_metadata.append({
                        'type': 'normal',
                        'material': material,
                        'field_count': 1
                    })
                    # 记录这个任务对应的字段索引
                    task_to_field_indices[task_idx] = [field_index_map[rule.id]]
            else:
                # 批量模式：分批提取
                logger.info(f"文件 {material} 使用批量模式，字段数: {len(material_rules)}")
                batches = self._chunk_rules(material_rules)  # 使用配置的默认 batch_size
                batch_size = self.concurrency_config.batch_size
                logger.info(f"分批完成: {len(batches)} 批（每批最多 {batch_size} 个字段）")
                
                for batch_idx, batch_rules in enumerate(batches):
                    # 批量提取任务
                    task = self._extract_batch_fields(
                        rules=batch_rules,
                        file_data=file_data,
                        reference_material=material,
                        skip_highlight=True,
                        anchor_markdown_cache=anchor_markdown_cache,
                        on_field_completed=on_field_completed
                    )
                    task_idx = len(phase1_tasks)
                    phase1_tasks.append(task)
                    phase1_metadata.append({
                        'type': 'normal',
                        'material': material,
                        'field_count': len(batch_rules)
                    })
                    # 记录这一批字段的索引列表
                    batch_field_indices = [field_index_map[rule.id] for rule in batch_rules]
                    task_to_field_indices[task_idx] = batch_field_indices
        
        # ========== 计算总字段数（包括第二阶段的子字段）==========
        # 统计第一阶段任务的字段数
        phase1_field_count = sum(
            meta.get('field_count', 1) 
            for meta in phase1_metadata 
            if not meta.get('skipped', False)
        )
        
        # 统计选择性级联的子字段总数（考虑多来源展开）
        # 注意：每个子字段可能有多个 reference_materials，会被按来源分组提取多次
        conditional_child_field_count = 0
        conditional_child_unique_count = 0  # 用于日志的唯一子字段数
        for ctx in conditional_cascade_contexts:
            for rule in ctx['child_rules_map'].values():
                # 每个子字段按 reference_materials 展开
                materials_count = len(rule.reference_materials) if rule.reference_materials else 1
                conditional_child_field_count += materials_count
                conditional_child_unique_count += 1
        
        # 真正的总字段数 = 第一阶段字段数 + 选择性级联子字段数（展开后）
        real_total_fields = phase1_field_count + conditional_child_field_count
        # 加上高亮任务（视为1个额外任务）
        total_tasks_for_progress = real_total_fields + 1
        
        # 计算多来源展开数
        multi_source_in_children = conditional_child_field_count - conditional_child_unique_count
        
        logger.info(
            f"两阶段提取任务统计: "
            f"第一阶段 {len(phase1_tasks)} 个任务({phase1_field_count}个字段) + "
            f"第二阶段子字段({conditional_child_unique_count}个唯一, 展开后{conditional_child_field_count}个) = "
            f"总计 {real_total_fields} 个字段 + 1个高亮任务 = {total_tasks_for_progress}"
            + (f" (含{multi_source_in_children}个多来源展开)" if multi_source_in_children > 0 else "")
        )
        
        # 初始化任务 context 中的 total_fields 和 completed_count
        if task_created and task_id:
            await self.task_store.update_task(
                task_id,
                context={
                    "total_fields": total_tasks_for_progress,
                    "completed_count": 0
                }
            )
        
        # ========== 第一阶段：并发执行普通字段 + 链式级联 + 选择性级联主字段 ==========
        logger.info(
            f"[第一阶段] 启动并发提取: {len(cascade_groups)} 组级联 + "
            f"{len(groups)} 组普通字段 = {len(phase1_tasks)} 个任务"
        )
        
        async def indexed_task(idx: int, task):
            """包装提取任务，返回索引和结果"""
            result = await task
            return idx, result
        
        # 创建带索引的任务
        indexed_tasks = [
            indexed_task(idx, task) 
            for idx, task in enumerate(phase1_tasks)
        ]
        
        # 并发执行第一阶段所有任务
        phase1_results = []
        
        for coro in asyncio.as_completed(indexed_tasks):
            idx, result = await coro
            phase1_results.append((idx, result))
        
        phase1_results.sort(key=lambda x: x[0])  # 按任务索引排序
        
        # 收集第一阶段的结果
        cascade_results = []
        master_field_results_map: Dict[int, List[FieldExtractionResult]] = {}  # 主字段多来源结果映射
        field_results_map: Dict[int, List[FieldExtractionResult]] = {}  # 普通字段多来源结果映射
        
        for task_idx, task_result in phase1_results:
            metadata = phase1_metadata[task_idx]
            
            # 处理所有类型的级联任务（包括跳过的）
            if metadata['type'] == 'cascade':
                # 级联任务结果（可能是跳过的失败结果，也可能是正常的链式级联结果）
                if isinstance(task_result, list):
                    cascade_results.extend(task_result)
                    if metadata.get('skipped'):
                        logger.debug(f"跳过的级联任务 {task_idx} 返回 {len(task_result)} 个失败结果")
                    else:
                        logger.debug(f"链式级联任务 {task_idx} 返回 {len(task_result)} 个字段结果")
                else:
                    if task_result:
                        cascade_results.append(task_result)
            
            elif metadata['type'] == 'conditional_master_batch':
                # 选择性级联主字段批量结果：收集到 map 中用于聚合
                field_indices = master_task_to_field_indices.get(task_idx, [])
                
                if isinstance(task_result, list):
                    for i, field_result in enumerate(task_result):
                        if isinstance(field_result, FieldExtractionResult) and i < len(field_indices):
                            field_idx = field_indices[i]
                            if field_idx not in master_field_results_map:
                                master_field_results_map[field_idx] = []
                            master_field_results_map[field_idx].append(field_result)
                    logger.debug(f"主字段批量任务 {task_idx} 返回 {len(task_result)} 个主字段结果: {metadata.get('field_names', [])}")
                else:
                    logger.warning(f"主字段批量任务 {task_idx} 返回了非列表结果")
            
            elif metadata['type'] in ('normal', 'pipeline_normal'):
                # 普通字段任务结果：按字段索引聚合
                field_indices = task_to_field_indices.get(task_idx, [])
                
                if isinstance(task_result, list):
                    for i, field_result in enumerate(task_result):
                        if i < len(field_indices):
                            field_idx = field_indices[i]
                            if field_idx not in field_results_map:
                                field_results_map[field_idx] = []
                            field_results_map[field_idx].append(field_result)
                else:
                    # 单字段任务结果
                    if len(field_indices) > 0:
                        field_idx = field_indices[0]
                        if field_idx not in field_results_map:
                            field_results_map[field_idx] = []
                        field_results_map[field_idx].append(task_result)
                    else:
                        logger.warning(f"任务 {task_idx} 没有对应的字段索引")
        
        logger.info(f"[第一阶段完成] 级联结果: {len(cascade_results)} 个，主字段待聚合: {len(master_field_results_map)} 个，普通字段待聚合: {len(field_results_map)} 个")
        
        # ========== 聚合主字段的多来源结果 ==========
        conditional_master_results = {}  # 聚合后的主字段结果，用于第二阶段判断子字段
        
        if master_field_results_map:
            logger.info(f"[主字段聚合] 开始聚合 {len(all_master_rules)} 个主字段的多来源结果")
            
            for field_idx in range(len(all_master_rules)):
                if field_idx in master_field_results_map:
                    field_result_list = master_field_results_map[field_idx]
                    rule = all_master_rules[field_idx]
                    
                    if len(field_result_list) == 1:
                        # 单来源，直接使用
                        merged_result = field_result_list[0]
                        logger.debug(
                            f"主字段 {rule.field_name} (索引{field_idx}) | "
                            f"单来源 | values数: {len(merged_result.values)}"
                        )
                    else:
                        # 多来源，需要聚合
                        logger.info(
                            f"聚合主字段 {rule.field_name} (索引{field_idx}) | "
                            f"来源数: {len(field_result_list)} | "
                            f"参考材料: {rule.reference_materials}"
                        )
                        
                        # 输出每个来源的详细信息
                        for i, fr in enumerate(field_result_list):
                            logger.debug(
                                f"  来源 {i+1}: values数={len(fr.values)}, "
                                f"status={fr.field_status}, "
                                f"error={fr.error_message}"
                            )
                        
                        merged_result = self._merge_multi_source_results(rule, field_result_list)
                        
                        # 输出聚合后的结果
                        logger.info(
                            f"聚合完成: {merged_result.field_name} | "
                            f"总values数: {len(merged_result.values)} | "
                            f"最终状态: {merged_result.field_status}"
                        )
                    
                    # 保存聚合后的结果
                    conditional_master_results[merged_result.field_name] = merged_result
                    cascade_results.append(merged_result)
                else:
                    # 这个主字段没有任何结果（不应该发生）
                    logger.warning(f"主字段索引 {field_idx} 没有提取结果")
                    rule = all_master_rules[field_idx]
                    failed_result = await self._create_failed_field_result_async(
                        rule, "未找到提取结果"
                    )
                    conditional_master_results[failed_result.field_name] = failed_result
                    cascade_results.append(failed_result)
            
            logger.info(f"[主字段聚合完成] 聚合后共 {len(conditional_master_results)} 个主字段结果")
        
        # ========== 第二阶段：根据主字段结果批量提取所有选择性级联的子字段 ==========
        if conditional_cascade_contexts:
            logger.info(f"[第二阶段] 开始提取 {len(conditional_cascade_contexts)} 个选择性级联的子字段")
            
            # 收集所有需要提取的子字段，按引用材料分组以便批量提取
            all_child_rules_to_extract = []  # 所有需要提取的子字段规则
            
            for ctx in conditional_cascade_contexts:
                config = ctx['config']
                master_rule = ctx['master_rule']
                child_rules_map = ctx['child_rules_map']
                
                # 获取主字段结果
                master_result = conditional_master_results.get(config.master_field)
                
                if not master_result:
                    logger.warning(f"选择性级联 {config.cascade_name} 的主字段 {config.master_field} 结果缺失，跳过子字段提取")
                    # 为所有子字段创建失败结果并计入进度
                    # 注意：每个子字段可能有多个 reference_materials，需要按展开后的数量计算进度
                    total_progress_count = 0
                    for field_name, rule in child_rules_map.items():
                        failed_result = FieldExtractionResult(
                            field_id=rule.id,
                            field_name=rule.field_name,
                            field_type=rule.field_type.value,
                            field_status=FieldExtractionStatus.FAILED,
                            values=[],
                            error_message=f"级联失败：主字段 {config.master_field} 结果缺失",
                            inconsistent_values=None,
                            extraction_rule={
                                "rule_id": rule.id,
                                "field_name": rule.field_name,
                                "field_type": rule.field_type.value,
                                "extraction_logic": rule.extraction_logic,
                                "reference_materials": rule.reference_materials,
                                "enabled": rule.enabled
                            }
                        )
                        cascade_results.append(failed_result)
                        # 子字段失败也计入进度（按 reference_materials 数量）
                        materials_count = len(rule.reference_materials) if rule.reference_materials else 1
                        total_progress_count += materials_count
                        for _ in range(materials_count):
                            await on_field_completed()
                    logger.info(f"[第二阶段] 级联 {config.cascade_name}：{len(child_rules_map)} 个子字段因主字段失败而标记完成，进度+{total_progress_count}")
                    continue
                
                # 解析主字段值，确定需要提取的子字段
                fields_to_extract = self._determine_child_fields(master_result, config)
                
                # 计算未触发的子字段
                untriggered_fields = set(child_rules_map.keys()) - fields_to_extract
                
                # 将未触发的子字段标记为完成（进度+n）
                # 注意：每个未触发的子字段可能有多个 reference_materials，需要按展开后的数量计算
                if untriggered_fields:
                    untriggered_progress_count = 0
                    for field_name in untriggered_fields:
                        if field_name in child_rules_map:
                            rule = child_rules_map[field_name]
                            # 按 reference_materials 数量计算进度增量
                            materials_count = len(rule.reference_materials) if rule.reference_materials else 1
                            untriggered_progress_count += materials_count
                            for _ in range(materials_count):
                                await on_field_completed()
                    logger.info(f"[第二阶段] 级联 {config.cascade_name}：{len(untriggered_fields)} 个未触发子字段标记为完成，进度+{untriggered_progress_count}")
                
                if fields_to_extract:
                    logger.info(f"[第二阶段] 级联 {config.cascade_name} 需要提取 {len(fields_to_extract)} 个子字段: {list(fields_to_extract)}")
                    
                    # 收集需要提取的子字段规则
                    for field_name in fields_to_extract:
                        if field_name in child_rules_map:
                            all_child_rules_to_extract.append(child_rules_map[field_name])
                        else:
                            logger.warning(f"需要提取的子字段 {field_name} 在规则中未找到")
                    
                    # 为未触发的子字段创建失败结果
                    for field_name in untriggered_fields:
                        if field_name in child_rules_map:
                            rule = child_rules_map[field_name]
                            failed_result = FieldExtractionResult(
                                field_id=rule.id,
                                field_name=rule.field_name,
                                field_type=rule.field_type.value,
                                field_status=FieldExtractionStatus.FAILED,
                                values=[],
                                error_message=f"级联未触发：主字段 {config.master_field} 的值不需要提取此子字段",
                                inconsistent_values=None,
                                extraction_rule={
                                    "rule_id": rule.id,
                                    "field_name": rule.field_name,
                                    "field_type": rule.field_type.value,
                                    "extraction_logic": rule.extraction_logic,
                                    "reference_materials": rule.reference_materials,
                                    "enabled": rule.enabled
                                }
                            )
                            cascade_results.append(failed_result)
                else:
                    # 没有需要提取的子字段，所有子字段标记为 FAILED
                    logger.info(f"[第二阶段] 级联 {config.cascade_name} 主字段未触发任何子字段")
                    for field_name, rule in child_rules_map.items():
                        failed_result = FieldExtractionResult(
                            field_id=rule.id,
                            field_name=rule.field_name,
                            field_type=rule.field_type.value,
                            field_status=FieldExtractionStatus.FAILED,
                            values=[],
                            error_message=f"级联未触发：主字段 {config.master_field} 未能触发此子字段的提取",
                            inconsistent_values=None,
                            extraction_rule={
                                "rule_id": rule.id,
                                "field_name": rule.field_name,
                                "field_type": rule.field_type.value,
                                "extraction_logic": rule.extraction_logic,
                                "reference_materials": rule.reference_materials,
                                "enabled": rule.enabled
                            }
                        )
                        cascade_results.append(failed_result)
            
            # 按引用材料分组子字段规则，以便批量提取
            if all_child_rules_to_extract:
                child_groups = self._group_rules_by_reference_material(all_child_rules_to_extract)
                logger.info(
                    f"[第二阶段批量优化] 收集到 {len(all_child_rules_to_extract)} 个子字段，"
                    f"按 {len(child_groups)} 个引用材料分组"
                )
                
                # 构建子字段索引映射（用于多来源聚合）
                child_field_index_map = {rule.id: idx for idx, rule in enumerate(all_child_rules_to_extract)}
                child_task_to_field_indices = {}
                
                phase2_tasks = []
                
                for material, material_child_rules in child_groups.items():
                    # 获取 material 对应的 file_type
                    file_type = self._get_file_type_from_material(material)
                    
                    # 流水线模式：创建等待+提取的包装协程
                    if is_pipeline_mode and file_type and file_type in parse_contexts:
                        async def create_child_batch_pipeline_task(
                            mat=material,
                            rules=material_child_rules,
                            ft=file_type,
                            ctx=parse_contexts[file_type]
                        ):
                            """流水线模式：等待文件解析后批量提取子字段"""
                            # 等待该 file_type 解析完成
                            success = await ctx.wait()
                            
                            if not success or not ctx.parse_result:
                                logger.warning(f"[第二阶段流水线] 文件类型 {ft} 解析失败，跳过 {mat} 的子字段提取")
                                # 返回失败结果列表
                                results = []
                                for r in rules:
                                    results.append(await self._create_failed_field_result_async(
                                        r, f"文件解析失败: {ctx.error or '未知错误'}"
                                    ))
                                    # 失败的字段也需要计数
                                    if on_field_completed:
                                        await on_field_completed()
                                return results
                            
                            file_data = ctx.parse_result
                            logger.info(f"[第二阶段流水线] {ft} 解析完成，开始批量提取 {mat} 的 {len(rules)} 个子字段")
                            
                            # 生成 Anchor Markdown（如果尚未缓存）
                            if ft not in anchor_markdown_cache:
                                tagged_md, seg_map = AnchorMarkdownConverter.convert(file_data)
                                if tagged_md:
                                    anchor_markdown_cache[ft] = (tagged_md, seg_map)
                            
                            # 批量提取子字段
                            batches = self._chunk_rules(rules)
                            logger.info(f"[第二阶段批量] {mat} 的子字段分为 {len(batches)} 批（batch_size={self.concurrency_config.batch_size}）")
                            
                            batch_tasks = []
                            for batch in batches:
                                task = self._extract_batch_fields(
                                    rules=batch,
                                    file_data=file_data,
                                    reference_material=mat,
                                    skip_highlight=True,
                                    anchor_markdown_cache=anchor_markdown_cache,
                                    on_field_completed=on_field_completed
                                )
                                batch_tasks.append(task)
                            
                            # 并发执行所有批次
                            batch_results_list = await asyncio.gather(*batch_tasks)
                            
                            # 展平结果
                            results = []
                            for batch_results in batch_results_list:
                                if isinstance(batch_results, list):
                                    results.extend(batch_results)
                                else:
                                    results.append(batch_results)
                            
                            return results
                        
                        task_idx = len(phase2_tasks)
                        phase2_tasks.append(create_child_batch_pipeline_task())
                        # 记录任务对应的字段索引
                        batch_field_indices = [child_field_index_map[rule.id] for rule in material_child_rules if rule.id in child_field_index_map]
                        child_task_to_field_indices[task_idx] = batch_field_indices
                    else:
                        # 非流水线模式：直接批量提取
                        file_data = self._find_file_by_material(material, parsed_files)
                        if not file_data:
                            logger.warning(f"[第二阶段] 未找到参考材料对应的文件: {material}，跳过子字段提取")
                            # 创建失败结果
                            async def create_failed_children_results(rules=material_child_rules, mat=material):
                                results = []
                                for r in rules:
                                    results.append(await self._create_failed_field_result_async(
                                        r, f"未找到参考材料对应的文件: {mat}"
                                    ))
                                    if on_field_completed:
                                        await on_field_completed()
                                return results
                            task_idx = len(phase2_tasks)
                            phase2_tasks.append(create_failed_children_results())
                            # 记录任务对应的字段索引
                            batch_field_indices = [child_field_index_map[rule.id] for rule in material_child_rules if rule.id in child_field_index_map]
                            child_task_to_field_indices[task_idx] = batch_field_indices
                            continue
                        
                        # 批量提取子字段
                        batches = self._chunk_rules(material_child_rules)
                        logger.info(f"[第二阶段批量] {material} 的子字段分为 {len(batches)} 批（batch_size={self.concurrency_config.batch_size}）")
                        
                        for batch in batches:
                            task = self._extract_batch_fields(
                                rules=batch,
                                file_data=file_data,
                                reference_material=material,
                                skip_highlight=True,
                                anchor_markdown_cache=anchor_markdown_cache,
                                on_field_completed=on_field_completed
                            )
                            task_idx = len(phase2_tasks)
                            phase2_tasks.append(task)
                            # 记录任务对应的字段索引
                            batch_field_indices = [child_field_index_map[rule.id] for rule in batch if rule.id in child_field_index_map]
                            child_task_to_field_indices[task_idx] = batch_field_indices
                
                # 并发执行第二阶段所有批量任务
                if phase2_tasks:
                    logger.info(f"[第二阶段] 并发执行 {len(phase2_tasks)} 个批量提取任务")
                    phase2_results_list = await asyncio.gather(*phase2_tasks)
                    
                    # 收集子字段结果到 map 中（用于多来源聚合）
                    child_field_results_map: Dict[int, List[FieldExtractionResult]] = {}
                    
                    for task_idx, batch_results in enumerate(phase2_results_list):
                        field_indices = child_task_to_field_indices.get(task_idx, [])
                        
                        if isinstance(batch_results, list):
                            for i, field_result in enumerate(batch_results):
                                if i < len(field_indices):
                                    field_idx = field_indices[i]
                                    if field_idx not in child_field_results_map:
                                        child_field_results_map[field_idx] = []
                                    child_field_results_map[field_idx].append(field_result)
                        else:
                            # 单字段任务结果
                            if len(field_indices) > 0:
                                field_idx = field_indices[0]
                                if field_idx not in child_field_results_map:
                                    child_field_results_map[field_idx] = []
                                child_field_results_map[field_idx].append(batch_results)
                    
                    # 聚合子字段的多来源结果
                    logger.info(f"[第二阶段] 开始聚合 {len(all_child_rules_to_extract)} 个子字段的多来源结果")
                    for field_idx in range(len(all_child_rules_to_extract)):
                        if field_idx in child_field_results_map:
                            field_result_list = child_field_results_map[field_idx]
                            rule = all_child_rules_to_extract[field_idx]
                            
                            if len(field_result_list) == 1:
                                # 单来源，直接使用
                                cascade_results.append(field_result_list[0])
                                logger.debug(
                                    f"子字段 {rule.field_name} (索引{field_idx}) | "
                                    f"单来源 | values数: {len(field_result_list[0].values)}"
                                )
                            else:
                                # 多来源，需要聚合
                                logger.info(
                                    f"聚合子字段 {rule.field_name} (索引{field_idx}) | "
                                    f"来源数: {len(field_result_list)} | "
                                    f"参考材料: {rule.reference_materials}"
                                )
                                
                                # 输出每个来源的详细信息
                                for i, fr in enumerate(field_result_list):
                                    logger.debug(
                                        f"  来源 {i+1}: values数={len(fr.values)}, "
                                        f"status={fr.field_status}, "
                                        f"error={fr.error_message}"
                                    )
                                
                                merged_result = self._merge_multi_source_results(rule, field_result_list)
                                cascade_results.append(merged_result)
                                
                                # 输出聚合后的结果
                                logger.info(
                                    f"聚合完成: {merged_result.field_name} | "
                                    f"总values数: {len(merged_result.values)} | "
                                    f"最终状态: {merged_result.field_status}"
                                )
                        else:
                            # 这个子字段没有任何结果（不应该发生）
                            logger.warning(f"子字段索引 {field_idx} 没有提取结果")
                            rule = all_child_rules_to_extract[field_idx]
                            failed_result = await self._create_failed_field_result_async(
                                rule, "未找到提取结果"
                            )
                            cascade_results.append(failed_result)
                    
                    logger.info(f"[第二阶段完成] 子字段批量提取和聚合完成")
                else:
                    logger.info(f"[第二阶段] 没有批量提取任务")
            else:
                logger.info(f"[第二阶段] 没有需要提取的子字段")
        
        logger.info(f"两阶段提取完成，级联字段总结果: {len(cascade_results)} 个")
        
        # 聚合多来源的结果（仅处理普通字段）
        logger.debug(f"开始聚合普通字段结果，共 {len(normal_rules)} 个字段")
        results = [None] * len(normal_rules)
        
        for field_idx in range(len(normal_rules)):
            if field_idx in field_results_map:
                field_result_list = field_results_map[field_idx]
                
                if len(field_result_list) == 1:
                    # 单来源，直接使用
                    result = field_result_list[0]
                    logger.debug(
                        f"字段 {result.field_name} (索引{field_idx}) | "
                        f"单来源 | values数: {len(result.values)}"
                    )
                    results[field_idx] = result
                else:
                    # 多来源，需要聚合
                    rule = normal_rules[field_idx]
                    logger.info(
                        f"聚合字段 {rule.field_name} (索引{field_idx}) | "
                        f"来源数: {len(field_result_list)} | "
                        f"参考材料: {rule.reference_materials}"
                    )
                    
                    # 输出每个来源的详细信息
                    for i, fr in enumerate(field_result_list):
                        logger.debug(
                            f"  来源 {i+1}: values数={len(fr.values)}, "
                            f"status={fr.field_status}, "
                            f"error={fr.error_message}"
                        )
                    
                    results[field_idx] = self._merge_multi_source_results(
                        rule,
                        field_result_list
                    )
                    
                    # 输出聚合后的结果
                    merged = results[field_idx]
                    logger.info(
                        f"聚合完成: {merged.field_name} | "
                        f"总values数: {len(merged.values)} | "
                        f"最终状态: {merged.field_status}"
                    )
            else:
                # 这个字段没有任何结果（可能是文件缺失或提取失败）
                logger.warning(f"普通字段索引 {field_idx} 没有提取结果")
                rule = normal_rules[field_idx]
                results[field_idx] = await self._create_failed_field_result_async(
                    rule, "未找到提取结果"
                )
        
        logger.info(f"普通字段提取和溯源完成")
        
        # ========== 合并级联字段结果和普通字段结果 ==========
        # 按照 enabled_rules 的原始顺序合并结果
        final_results = []
        
        # 创建字段名到结果的映射（过滤掉 None 值）
        cascade_results_map = {r.field_name: r for r in cascade_results if r is not None}
        normal_results_map = {r.field_name: r for r in results if r is not None}
        
        for rule in enabled_rules:
            if rule.field_name in cascade_results_map:
                final_results.append(cascade_results_map[rule.field_name])
            elif rule.field_name in normal_results_map:
                final_results.append(normal_results_map[rule.field_name])
            else:
                # 字段没有提取结果（可能是正常情况，如可选字段在材料中不存在）
                logger.debug(f"字段 {rule.field_name} 没有提取结果，创建失败标记")
                # 创建失败结果
                failed_result = await self._create_failed_field_result_async(
                    rule, "未找到提取结果"
                )
                final_results.append(failed_result)
        
        logger.info(
            f"结果合并完成: 级联字段 {len(cascade_results)} 个 + "
            f"普通字段 {len(results)} 个 = 总计 {len(final_results)} 个"
        )
        
        # ========== 流水线模式：从 parse_contexts 收集解析结果用于高亮生成 ==========
        if is_pipeline_mode and parse_contexts:
            # 所有提取任务完成后，parse_contexts 中已有完整的解析结果
            for file_type, ctx in parse_contexts.items():
                if ctx.is_success and ctx.parse_result:
                    parsed_files[file_type] = ctx.parse_result
            logger.info(f"[流水线] 从 parse_contexts 收集到 {len(parsed_files)} 种文件类型的解析结果用于高亮生成")
        
        # ========== 阶段2：批量并发生成高亮 ==========
        logger.info("开始批量生成高亮")
        
        if task_created and task_id:
            # 高亮开始时的进度 = 已完成字段数 / 总任务数
            progress = completed_field_count / total_tasks_for_progress if total_tasks_for_progress > 0 else 0.0
            await self.task_store.update_task(
                task_id, 
                progress=progress,
                status_message="正在生成溯源高亮...",
                context={
                    "completed_count": completed_field_count,
                    "total_fields": total_tasks_for_progress
                }
            )
        
        await self._batch_generate_highlights(
            final_results, parsed_files, downloaded_files_cache=downloaded_files_cache
        )
        
        # 高亮完成，进度 +1（高亮视为1个任务）
        completed_field_count += 1
        
        if task_created and task_id:
            await self.task_store.update_task(
                task_id, 
                progress=1.0,
                status_message="处理完成",
                context={
                    "completed_count": completed_field_count,
                    "total_fields": total_tasks_for_progress
                }
            )
            logger.info(f"所有任务完成: {completed_field_count}/{total_tasks_for_progress} (100%)")
        
        logger.info(f"所有字段处理完成（包含高亮生成）")
        
        return final_results
    
    async def _batch_generate_highlights(
        self,
        field_results: List[FieldExtractionResult],
        parsed_files: Dict[str, Dict[str, Any]],
        downloaded_files_cache: Optional[Dict[str, bytes]] = None,
    ):
        """
        批量并发生成所有字段的高亮图（优化版：先全部生成，再批量上传）
        
        处理流程：
        1. 遍历所有提取结果，收集需要生成高亮的信息
        2. 并发生成所有高亮图片（不上传，只生成 bytes）
        3. 批量上传所有图片到 MinIO
        4. 更新结果中的 preview_image_url
        
        性能优化：
        - 高亮生成和上传分离，减少网络往返
        - 批量上传减少 MinIO 连接开销
        - 使用信号量控制并发数，避免资源耗尽
        
        Args:
            field_results: 字段提取结果列表（已包含溯源信息）
            parsed_files: 解析后的文件数据
        """
        # 调试日志：检查 parsed_files 结构
        for ft, fd in parsed_files.items():
            prs = fd.get("parse_results", []) if isinstance(fd, dict) else []
            if prs:
                first_pr = prs[0]
                logger.debug(f"[高亮调试] file_type: {ft} | parse_results[0] 类型: {type(first_pr).__name__} | backend: {getattr(first_pr, 'backend', 'N/A')}")
                if hasattr(first_pr, 'pages') and first_pr.pages:
                    first_page = first_pr.pages[0]
                    logger.debug(f"[高亮调试] 页面0 rotation_angle: {getattr(first_page, 'rotation_angle', 'N/A')}")
        
        # 收集所有需要生成高亮的任务
        highlight_tasks = []
        
        for result_idx, field_result in enumerate(field_results):
            for value_idx, extracted_value in enumerate(field_result.values):
                # 检查是否有溯源信息但没有预览图
                if extracted_value.sources and len(extracted_value.sources) > 0:
                    source = extracted_value.sources[0]
                    
                    # 如果已经有预览图，跳过
                    if source.preview_image_url:
                        continue
                    
                    if not self._should_include_highlight_task(source):
                        continue
                    
                    file_data = parsed_files.get(source.source_file_type)
                    if not file_data:
                        continue

                    is_excel_task = (
                        source.document_type == "excel"
                        or source.sheet_index is not None
                        or bool(file_data.get("is_excel"))
                    )
                    highlight_tasks.append({
                        'result_idx': result_idx,
                        'value_idx': value_idx,
                        'source_idx': 0,
                        'file_data': file_data,
                        'page_number': source.page_number,
                        'coordinates': source.coordinates,
                        'cross_page_info': source.cross_page_info,
                        'regions': source.regions,
                        'is_excel': is_excel_task,
                    })
        
        if not highlight_tasks:
            logger.info("没有需要生成的高亮图")
            return
        
        logger.info(f"开始批量生成 {len(highlight_tasks)} 个高亮图（并发数: {self.concurrency_config.highlight_workers}）")
        
        # ========== 阶段1：并发生成所有高亮图片（不上传）==========
        gen_start_time = time.time()
        semaphore = asyncio.Semaphore(self.concurrency_config.highlight_workers)
        
        async def generate_highlight_image_only(task_info):
            """生成高亮图片（不上传），返回图片字节数据"""
            # 强制让出控制权，避免57个任务的同步初始化代码阻塞事件循环
            await asyncio.sleep(0)
            
            async with semaphore:
                try:
                    file_data = task_info['file_data']
                    regions = task_info.get('regions')
                    page_number = task_info['page_number']
                    coordinates = task_info['coordinates']
                    
                    parse_results = file_data.get("parse_results", [])
                    file_paths = file_data.get("file_paths", [])
                    # 获取转换后的 PDF 内容列表（Word/图片文件转换后的 PDF）
                    pdf_contents = file_data.get("pdf_contents", [])
                    # Excel 文件原始字节
                    file_bytes_list = await self._ensure_excel_file_bytes_list(
                        file_data, downloaded_files_cache=downloaded_files_cache
                    )

                    logger.debug(f"[高亮调试] 开始生成高亮 | regions: {bool(regions)} | parse_results数量: {len(parse_results)}")

                    # Excel 路由：按 file_index / sheet 分组渲染
                    is_excel = task_info.get("is_excel") or bool(file_data.get("is_excel")) or any(
                        getattr(pr, "is_excel", False) for pr in parse_results
                    )
                    if is_excel and regions:
                        from src.utils.excel_cell_highlighter import ExcelCellHighlighter

                        region_payloads = [
                            {
                                "page_idx": r.page_idx,
                                "bbox": r.bbox,
                                "file_index": getattr(r, "file_index", None),
                            }
                            for r in regions
                        ]

                        if not any(fb for fb in file_bytes_list if fb):
                            logger.warning(
                                "Excel 高亮失败: file_bytes_list 为空，无法渲染 | "
                                f"file_type={file_data.get('file_type')}"
                            )
                            return None

                        img_bytes = await asyncio.get_running_loop().run_in_executor(
                            None,
                            ExcelCellHighlighter.render_regions,
                            file_bytes_list,
                            region_payloads,
                        )

                        if img_bytes:
                            return {
                                **task_info,
                                'image_bytes': img_bytes,
                                'is_excel': True,
                            }
                        return None

                    if regions:
                        # 按文件分组 regions
                        file_regions_map: Dict[int, List[Tuple[int, List[float]]]] = {}
                        
                        for region in regions:
                            _, region_file_index = self._locate_file_by_page(file_data, region.page_idx)
                            if region_file_index < 0:
                                continue
                            
                            actual_page_idx = self._calculate_actual_page_idx(
                                file_data, region_file_index, region.page_idx
                            )
                            
                            if region_file_index not in file_regions_map:
                                file_regions_map[region_file_index] = []
                            file_regions_map[region_file_index].append((actual_page_idx, region.bbox))
                        
                        if not file_regions_map:
                            return None
                        
                        # 生成高亮图片（不上传）
                        if len(file_regions_map) == 1:
                            file_index = list(file_regions_map.keys())[0]
                            page_bboxes = file_regions_map[file_index]
                            
                            file_path = file_paths[file_index] if file_index < len(file_paths) else None
                            if file_path is None:
                                return None
                            
                            # 优先使用转换后的 PDF 内容（Word/图片文件）
                            # 如果 pdf_contents 中有对应的内容，使用它；否则使用原始文件路径
                            pdf_content = pdf_contents[file_index] if file_index < len(pdf_contents) else None
                            if pdf_content is not None:
                                logger.debug(f"高亮使用转换后的 PDF 内容（{len(pdf_content)} 字节）")
                            pdf_input = pdf_content if pdf_content is not None else file_path
                            
                            backend = "mineru"
                            page_rotation_angles = {}
                            if file_index < len(parse_results):
                                backend = getattr(parse_results[file_index], "backend", "mineru")
                                logger.debug(f"[高亮调试] 单文件模式 | file_index: {file_index} | backend: {backend}")
                                # 获取页面旋转角度（Paddle 后端需要，包括 paddle、paddle_structure 等）
                                if backend.startswith("paddle"):
                                    page_indices = [p[0] for p in page_bboxes]
                                    # 使用修正后的 PDF 时，/Rotate 已由渲染器自动应用，
                                    # bbox 无需逆变换 → skip_local_rotation=True
                                    _skip_local = pdf_content is not None
                                    page_rotation_angles = self._get_page_rotation_angles(
                                        parse_results[file_index], page_indices,
                                        skip_local_rotation=_skip_local,
                                    )
                                    logger.debug(
                                        f"[高亮调试] 获取旋转角度: {page_rotation_angles}"
                                        f" | skip_local={_skip_local}"
                                    )

                            # 生成图片字节（不上传）
                            img_bytes = await self._generate_highlight_image_bytes(
                                file_path=pdf_input,
                                page_bboxes=page_bboxes,
                                backend=backend,
                                page_rotation_angles=page_rotation_angles
                            )
                        else:
                            # 多文件情况
                            img_bytes = await self._generate_multi_file_highlight_bytes(
                                file_data=file_data,
                                file_regions_map=file_regions_map,
                                parse_results=parse_results,
                                file_paths=file_paths,
                                pdf_contents=pdf_contents
                            )
                    else:
                        # 降级：使用 coordinates
                        page_idx = page_number - 1
                        file_path, file_index = self._locate_file_by_page(file_data, page_idx)
                        
                        if file_path is None:
                            return None
                        
                        actual_page_idx = self._calculate_actual_page_idx(
                            file_data, file_index, page_idx
                        )
                        bbox = [
                            coordinates['x'],
                            coordinates['y'],
                            coordinates['x'] + coordinates['width'],
                            coordinates['y'] + coordinates['height']
                        ]
                        page_bboxes = [(actual_page_idx, bbox)]
                        
                        # 优先使用转换后的 PDF 内容（Word/图片文件）
                        pdf_content = pdf_contents[file_index] if file_index >= 0 and file_index < len(pdf_contents) else None
                        if pdf_content is not None:
                            logger.debug(f"高亮（降级模式）使用转换后的 PDF 内容（{len(pdf_content)} 字节）")
                        pdf_input = pdf_content if pdf_content is not None else file_path
                        
                        backend = "mineru"
                        page_rotation_angles = {}
                        if file_index >= 0 and file_index < len(parse_results):
                            backend = getattr(parse_results[file_index], "backend", "mineru")
                            logger.debug(f"[高亮调试] 降级模式 | file_index: {file_index} | backend: {backend}")
                            # 获取页面旋转角度（Paddle 后端需要，包括 paddle、paddle_structure 等）
                            if backend.startswith("paddle"):
                                _skip_local = pdf_content is not None
                                page_rotation_angles = self._get_page_rotation_angles(
                                    parse_results[file_index], [actual_page_idx],
                                    skip_local_rotation=_skip_local,
                                )
                                logger.debug(
                                    f"[高亮调试] 降级模式旋转角度: {page_rotation_angles}"
                                    f" | skip_local={_skip_local}"
                                )

                        img_bytes = await self._generate_highlight_image_bytes(
                            file_path=pdf_input,
                            page_bboxes=page_bboxes,
                            backend=backend,
                            page_rotation_angles=page_rotation_angles
                        )
                    
                    if img_bytes:
                        return {
                            **task_info,
                            'image_bytes': img_bytes
                        }
                    return None
                    
                except Exception as e:
                    logger.error(f"生成高亮图片失败: {e}", exc_info=True)
                    return None
        
        # 并发生成所有高亮图片
        image_results = await asyncio.gather(
            *[generate_highlight_image_only(task) for task in highlight_tasks],
            return_exceptions=True
        )
        
        # 收集成功生成的图片
        images_to_upload = []
        for result in image_results:
            if isinstance(result, Exception):
                logger.error(f"高亮生成异常: {result}")
                continue
            if result and result.get('image_bytes'):
                images_to_upload.append(result)
        
        gen_elapsed = time.time() - gen_start_time
        logger.info(f"高亮图片生成完成: {len(images_to_upload)}/{len(highlight_tasks)} 成功，耗时 {gen_elapsed:.2f}s，开始批量上传")
        
        if not images_to_upload:
            logger.warning("没有成功生成任何高亮图片")
            return
        
        # ========== 阶段2：批量上传所有图片到 MinIO ==========
        from src.utils.minio.client import get_minio_client
        import hashlib
        
        minio_client = get_minio_client()
        
        # 准备批量上传数据（Excel 为 PNG，PDF 为 JPEG）
        upload_data = []
        for item in images_to_upload:
            img_bytes = item['image_bytes']
            file_hash = hashlib.md5(img_bytes).hexdigest()[:8]
            timestamp = int(time.time() * 1000)
            is_excel_image = item.get("is_excel") or img_bytes.startswith(b"\x89PNG\r\n\x1a\n")
            if is_excel_image:
                ext, content_type = "png", "image/png"
            else:
                ext, content_type = "jpg", "image/jpeg"
            object_name = f"highlights/batch_{timestamp}_{file_hash}.{ext}"
            
            upload_data.append({
                'data': img_bytes,
                'object_name': object_name,
                'content_type': content_type,
                'task_info': item
            })
        
        # 使用 MinIO 批量上传
        upload_start_time = time.time()
        logger.info(f"开始批量上传 {len(upload_data)} 张高亮图片到 MinIO")
        
        upload_results = await minio_client.upload_bytes_batch(
            files_data=[{
                'data': item['data'],
                'object_name': item['object_name'],
                'content_type': item['content_type']
            } for item in upload_data],
            max_concurrent=self.concurrency_config.highlight_workers
        )
        
        # ========== 阶段3：更新结果中的预览图 URL ==========
        success_count = 0
        for i, (success, url, error) in enumerate(upload_results):
            if success and url:
                task_info = upload_data[i]['task_info']
                result_idx = task_info['result_idx']
                value_idx = task_info['value_idx']
                source_idx = task_info['source_idx']
                
                field_results[result_idx].values[value_idx].sources[source_idx].preview_image_url = url
                success_count += 1
            else:
                logger.error(f"上传高亮图失败: {error}")
        
        upload_elapsed = time.time() - upload_start_time
        
        # 清理 PDF 缓存
        from src.utils.paddle_pdf_highlighter import clear_pdf_cache
        clear_pdf_cache()
        
        total_elapsed = gen_elapsed + upload_elapsed
        logger.info(f"批量高亮完成: {success_count}/{len(highlight_tasks)} 成功 | 生成耗时: {gen_elapsed:.2f}s | 上传耗时: {upload_elapsed:.2f}s | 总耗时: {total_elapsed:.2f}s")
    
    async def _extract_single_field(
        self,
        rule: ExtractionRule,
        parsed_files: Dict[str, Dict[str, Any]],
        request: ExtractionRequest,
        skip_highlight: bool = False,
        anchor_markdown_cache: Optional[Dict[str, Tuple[str, Dict[str, Any]]]] = None,
        target_material: Optional[str] = None,
        on_field_completed: Optional[Callable] = None
    ) -> FieldExtractionResult:
        """
        提取单个字段（核心方法）- 统一提取与溯源
        
        使用 Anchor Markdown 方案，一次 LLM 调用完成提取和溯源：
        1. 【查找文件】遍历 reference_materials，找到对应的已解析文件数据
        2. 【转换格式】将解析结果转换为带锚点的 Markdown
        3. 【统一提取】调用 UnifiedExtractionAgent，一次性完成提取和溯源
        4. 【坐标查表】根据返回的锚点 ID 查找精确坐标
        5. 【生成高亮】调用高亮生成器（可选）
        
        Args:
            rule: 提取规则（包含字段名、提取逻辑、参考材料等）
            parsed_files: 解析后的文件数据字典
            request: 原始请求
            skip_highlight: 是否跳过高亮生成
            anchor_markdown_cache: Anchor Markdown 缓存
            target_material: 指定只从该参考材料提取（流水线模式使用，避免无效警告）
            
        Returns:
            FieldExtractionResult: 字段提取结果
        """
        # 确定要处理的参考材料列表
        if target_material:
            materials_to_process = [target_material]
            logger.info(f"提取字段: {rule.field_name}，从指定材料 {target_material} 提取（单材料模式）")
        else:
            materials_to_process = rule.reference_materials
            logger.info(f"提取字段: {rule.field_name}，从 {len(rule.reference_materials)} 个参考材料中提取（统一模式）")
        
        try:
            # 构建 extraction_logic（包含字段类型信息）
            extraction_logic_base = self._build_extraction_logic(rule)
            
            # 收集所有来源的提取值
            extracted_values = []
            
            # 遍历参考材料进行提取
            for ref_material in materials_to_process:
                # 找到对应的解析文件
                file_data = self._find_file_by_material(ref_material, parsed_files)
                if not file_data:
                    logger.warning(f"未找到参考材料对应的文件: {ref_material}")
                    continue
                
                # 检查是否为纯文本提取模式
                is_text_only = self._is_text_only_mode(file_data)
                
                file_type = file_data.get("file_type", "")
                
                tagged_markdown, segment_map, is_excel = resolve_anchor_context(
                    file_data, anchor_markdown_cache
                )
                if tagged_markdown:
                    logger.debug(
                        f"Anchor 上下文 | 文件类型: {file_type} | Excel: {is_excel} | "
                        f"长度: {len(tagged_markdown)} | 锚点: {len(segment_map)}"
                    )
                else:
                    logger.warning(f"转换 Anchor Markdown 失败，降级使用原始 md_content")
                    tagged_markdown = file_data.get("md_content", "")
                    segment_map = {}
                
                # === RAG 处理（统一提取阶段）===
                if self.rag_handler.should_use_rag(len(tagged_markdown)):
                    logger.info(f"Anchor Markdown 内容过长 ({len(tagged_markdown)} 字符)，启用 RAG 检索")
                    parse_results = file_data.get("parse_results", [])
                    if parse_results:
                        query = f"{rule.field_name} {extraction_logic_base}"
                        filtered_markdown, _ = await self.rag_handler.get_relevant_content(
                            parse_results, query
                        )
                        logger.info(f"RAG 检索返回的 Markdown | 长度: {len(filtered_markdown)} 字符")
                        rag_page_indices = self._extract_page_indices_from_rag_result(filtered_markdown)
                        logger.info(f"RAG 检索命中的页面数: {len(rag_page_indices)}, 页码: {sorted(rag_page_indices)}")

                        if is_excel and rag_page_indices:
                            excel_ctx = ExcelAnchorContext.from_file_data(file_data)
                            filtered_ctx = excel_ctx.filter_by_sheet_indices(set(rag_page_indices))
                            tagged_markdown = filtered_ctx.tagged_markdown or tagged_markdown
                            segment_map = filtered_ctx.segment_map or segment_map
                            logger.info(
                                f"Excel RAG 过滤后 | 长度: {len(tagged_markdown)} | "
                                f"锚点: {len(segment_map)}"
                            )
                        elif rag_page_indices:
                            # 过滤 parse_results 只保留 RAG 命中的页面
                            # 注意：parse_results 中的元素可能是 PaddleParseResult 对象或字典
                            filtered_parse_results = self._filter_parse_results_by_pages(
                                parse_results, rag_page_indices
                            )
                            # 统计实际过滤后有多少页
                            total_filtered_pages = 0
                            for result in filtered_parse_results:
                                if hasattr(result, 'pages'):
                                    total_filtered_pages += len(result.pages)
                            logger.info(f"过滤后的 parse_results 包含 {total_filtered_pages} 个页面")
                            if filtered_parse_results:
                                # 重新转换为 Anchor Markdown
                                filtered_file_data = {**file_data, "parse_results": filtered_parse_results}
                                tagged_markdown, segment_map = AnchorMarkdownConverter.convert(filtered_file_data)
                                logger.info(f"RAG 检索后重新生成 Anchor Markdown | 长度: {len(tagged_markdown)} 字符 | 片段数: {len(segment_map)}")
                                
                                # 兜底机制：如果 RAG 后仍然超过阈值，逐步减少页面数量
                                from config.rag_config import RAG_MAX_LENGTH
                                if len(tagged_markdown) > RAG_MAX_LENGTH:
                                    logger.warning(f"RAG 后内容仍然过长 ({len(tagged_markdown)} > {RAG_MAX_LENGTH})，启用兜底机制逐步减少页面")
                                    # 按页面顺序取前 N 页，直到降到阈值以下
                                    sorted_page_indices = sorted(rag_page_indices)
                                    for i in range(len(sorted_page_indices) - 1, 0, -1):  # 从后往前减少页面
                                        reduced_indices = set(sorted_page_indices[:i])
                                        logger.debug(f"尝试减少到 {i} 个页面: {sorted(reduced_indices)}")
                                        
                                        reduced_parse_results = self._filter_parse_results_by_pages(
                                            parse_results, reduced_indices
                                        )
                                        if reduced_parse_results:
                                            reduced_file_data = {**file_data, "parse_results": reduced_parse_results}
                                            tagged_markdown, segment_map = AnchorMarkdownConverter.convert(reduced_file_data)
                                            
                                            if len(tagged_markdown) <= RAG_MAX_LENGTH:
                                                logger.info(f"兜底成功：减少到 {i} 个页面后，长度: {len(tagged_markdown)} 字符 | 片段数: {len(segment_map)}")
                                                break
                                    else:
                                        # 所有尝试都失败，直接使用 RAG 返回的 Markdown（不带坐标）
                                        logger.warning(f"无法通过减少页面降低长度，使用 RAG 原始 Markdown（不带坐标）")
                                        tagged_markdown = filtered_markdown
                                        segment_map = {}
                            else:
                                logger.warning("RAG 检索后过滤结果为空，保持原 Anchor Markdown")
                                logger.info(f"保持原 Anchor Markdown | 长度: {len(tagged_markdown)} 字符")
                        else:
                            # 如果无法提取页面索引，直接使用过滤后的 Markdown（不带锚点）
                            logger.warning("RAG 结果无法提取页面索引，使用过滤后的普通 Markdown")
                            tagged_markdown = filtered_markdown
                            segment_map = {}
                            logger.info(f"RAG 检索后使用普通 Markdown | 长度: {len(tagged_markdown)} 字符")
                    else:
                        logger.warning("无法使用 RAG：缺少 parse_results")
                # ==============================
                
                # === 调用统一提取 Agent（带重试逻辑）===
                max_retries = 2  # 最大重试次数
                retry_hint = ""  # 重试提示
                unified_result = None
                
                for attempt in range(max_retries):
                    # 构建当前的 extraction_logic（可能包含重试提示）
                    current_extraction_logic = extraction_logic_base + retry_hint
                    
                    unified_result = await self._call_unified_extraction_agent(
                        file_content=tagged_markdown,
                        field_name=rule.field_name,
                        extraction_logic=current_extraction_logic,
                        reference_materials=ref_material
                    )
                    
                    # 检查是否需要重试
                    # 只有在真正失败（没有成功标志 且 没有任何锚点）时才考虑重试
                    is_parse_failed = not unified_result.success or (
                        unified_result.extracted_value is None 
                        and not unified_result.anchor_ids
                    )
                    
                    if is_parse_failed and attempt < max_retries - 1:
                        # 解析失败且还有重试机会，拼接错误提示并重试
                        # 获取具体的错误原因
                        error_reason = unified_result.error or "JSON解析失败"
                        # 如果有原始响应用于调试
                        raw_preview = ""
                        if unified_result.raw_response:
                            raw_preview = unified_result.raw_response.replace('\n', ' ')
                        
                        retry_hint = f"\nTips：您上次输出解析失败，错误原因：{error_reason}。请严格按照要求的JSON格式输出，确保JSON语法正确。"
                        logger.warning(
                            f"单字段提取 {rule.field_name} 从 {ref_material} 解析失败 "
                            f"(尝试 {attempt + 1}/{max_retries})，将重试 | "
                            f"错误: {error_reason} | 响应预览: {raw_preview}"
                        )
                        continue
                    
                    # 成功或最后一次尝试，退出重试循环
                    break
                
                # 最终检查提取结果
                if not unified_result or not unified_result.success or (
                    unified_result.extracted_value is None 
                    and not unified_result.anchor_ids
                ):
                    logger.warning(f"字段 {rule.field_name} 从 {ref_material} 提取失败")
                    continue
                
                # === 根据锚点 ID 查表获取坐标 ===
                anchor_ids = unified_result.anchor_ids
                bbox_infos = AnchorMarkdownConverter.lookup_bboxes_by_anchors(anchor_ids, segment_map)
                
                regions = self._build_regions_from_bbox_infos(bbox_infos, is_excel=is_excel)
                
                # 如果没有找到坐标但有锚点，记录详细警告
                if anchor_ids and not regions:
                    # 区分"锚点不存在"和"锚点存在但bbox无效"
                    missing_ids = []
                    invalid_bbox_ids = []
                    for aid in anchor_ids:
                        if aid in segment_map:
                            invalid_bbox_ids.append(aid)
                        else:
                            missing_ids.append(aid)
                    
                    if missing_ids:
                        logger.warning(f"锚点 {missing_ids} 在映射表中不存在")
                    if invalid_bbox_ids:
                        logger.warning(f"锚点 {invalid_bbox_ids} 存在但 bbox 无效，无法生成高亮")
                
                # === 高亮图在批量阶段生成（_batch_generate_highlights）===
                # 这里只保存坐标信息，供后续批量生成高亮时使用
                preview_image = None  # 预留，批量阶段会填充
                cross_page_info = None  # 跨页信息在批量阶段计算
                
                # === 构建溯源信息 ===
                sources = []
                if regions and not is_text_only:
                    sources.append(self._build_source_info_from_regions(
                        file_data=file_data,
                        rule=rule,
                        unified_result=unified_result,
                        regions=regions,
                        segment_map=segment_map,
                        preview_image=preview_image or "",
                        is_excel=is_excel,
                    ))
                
                # 添加到提取值列表
                extracted_values.append(ExtractedFieldValue(
                    source_file_type=file_data["file_type"],
                    source_file_name=", ".join(file_data["file_names"]),
                    source_field_name=rule.field_name,
                    extracted_value=unified_result.extracted_value,
                    extract_status=ExtractStatus.SUCCESS,
                    confidence=unified_result.confidence or 0.8,
                    sources=sources
                ))
                
                logger.info(f"成功从 {ref_material} 提取字段 {rule.field_name}（锚点: {anchor_ids}）")
            
            # 构建提取规则信息
            extraction_rule_info = {
                "rule_id": rule.id,
                "field_name": rule.field_name,
                "field_type": rule.field_type.value,
                "extraction_logic": rule.extraction_logic,
                "reference_materials": rule.reference_materials,
                "enabled": rule.enabled
            }
            
            # 计算字段状态
            field_status, inconsistent_values = self._calculate_field_status(
                extracted_values,
                error_message=None
            )
            
            # 按优先级排序 values：有值的排前面，空值的排后面
            sorted_values = self._sort_values_by_priority(extracted_values, rule.reference_materials)
            
            # 返回提取结果
            return FieldExtractionResult(
                field_id=rule.id,
                field_name=rule.field_name,
                field_type=rule.field_type.value,
                field_status=field_status,
                values=sorted_values,
                error_message=None if len(sorted_values) > 0 else "无法从任何参考材料中提取字段",
                inconsistent_values=inconsistent_values,
                extraction_rule=extraction_rule_info
            )
            
        except Exception as e:
            logger.error(f"提取字段 {rule.field_name} 异常: {e}", exc_info=True)
            
            extraction_rule_info = {
                "rule_id": rule.id,
                "field_name": rule.field_name,
                "field_type": rule.field_type.value,
                "extraction_logic": rule.extraction_logic,
                "reference_materials": rule.reference_materials,
                "enabled": rule.enabled
            }
            
            # 计算字段状态（异常情况）
            field_status, _ = self._calculate_field_status(
                [],
                error_message=str(e)
            )
            
            return FieldExtractionResult(
                field_id=rule.id,
                field_name=rule.field_name,
                field_type=rule.field_type.value,
                field_status=field_status,
                values=[],
                error_message=str(e),
                inconsistent_values=None,
                extraction_rule=extraction_rule_info
            )
    
    def _normalize_value_for_comparison(self, value: str) -> str:
        """
        规范化值用于比较
        
        使用 normalize_for_comparison 进行全面规范化：
        1. 中英文符号转换（如 中文括号 "（）" -> 英文括号 "()"）
        2. 空白字符规范化
        3. 转小写
        4. 数值格式规范化（如 "98.60" -> "98.6"）
        
        这样可以避免以下情况被错误地判断为不一致：
        - "沃克森（北京）有限公司" 和 "沃克森(北京)有限公司"
        - "98.6" 和 "98.60"
        - "Hello World" 和 "hello world"
        
        Args:
            value: 原始值字符串
            
        Returns:
            str: 规范化后的值
        """
        # 使用 text_normalizer 中的综合规范化函数
        return normalize_for_comparison(value)
    
    def _calculate_field_status(
        self,
        extracted_values: List[ExtractedFieldValue],
        error_message: Optional[str] = None
    ) -> tuple[FieldExtractionStatus, Optional[List[str]]]:
        """
        计算字段的综合提取状态
        
        新逻辑（2025-12-03 更新）：
        1. **FAILED**: 所有来源都失败（缺少材料/解析失败等）
           - 有 error_message（全局错误）
           - 或 values 为空
           - 或所有 values 的 extract_status 都是 FAILED
        
        2. **PENDING**: 有空值 OR 多来源值不一致
           - 所有成功提取的值都是空字符串（未找到）
           - 或多来源值不一致（包括空值与非空值不一致）
        
        3. **SUCCESS**: 有提取值 AND 多来源完全一致
           - 所有成功提取的值完全一致（包括空字符串）
        
        重要：空字符串 "" 是有效的提取值，表示"找到位置但内容为空"
        
        场景示例：
        - ["北京公司", "北京公司"] -> SUCCESS（多来源一致）
        - ["北京公司", FAILED, "北京公司"] -> SUCCESS（忽略失败来源）
        - ["北京公司", "", "北京公司"] -> PENDING（空值与非空值不一致）
        - ["北京公司", "上海公司"] -> PENDING（值不一致）
        - ["", ""] -> PENDING（全部空值）
        - [FAILED, FAILED] -> FAILED（全部失败）
        
        Args:
            extracted_values: 提取的值列表
            error_message: 错误信息
            
        Returns:
            tuple: (字段状态, 不一致的值列表)
        """
        # 1. 有错误信息 -> 失败（全局错误）
        if error_message:
            return FieldExtractionStatus.FAILED, None
        
        # 2. 无提取结果 -> 失败（所有来源都失败）
        if not extracted_values or len(extracted_values) == 0:
            return FieldExtractionStatus.FAILED, None
        
        # 3. 检查是否所有来源都失败
        all_failed = all(
            val.extract_status == ExtractStatus.FAILED 
            for val in extracted_values
        )
        if all_failed:
            return FieldExtractionStatus.FAILED, None
        
        # 4. 收集成功提取的值（忽略失败的来源）
        # 重要：空字符串也是合法的提取结果，必须参与一致性比较
        # 保存原始值和规范化值的映射，用于后续显示
        successful_values_raw = []  # 原始值（用于显示）
        successful_values_normalized = []  # 规范化值（用于比较）
        
        for val in extracted_values:
            # 只考虑成功提取的来源
            if val.extract_status == ExtractStatus.SUCCESS and val.extracted_value is not None:
                # 原始值：去除首尾空格
                raw_value = str(val.extracted_value).strip()
                successful_values_raw.append(raw_value)
                
                # 规范化值：用于一致性比较（数值会去掉尾部0）
                normalized_value = self._normalize_value_for_comparison(raw_value)
                successful_values_normalized.append(normalized_value)
        
        # 5. 如果没有任何成功的值 -> 失败
        if not successful_values_normalized:
            return FieldExtractionStatus.FAILED, None
        
        # 6. 检查值的完全一致性（使用规范化后的值进行比较）
        unique_normalized_values = list(set(successful_values_normalized))
        
        # 情况1：所有规范化后的值完全一致 -> SUCCESS
        if len(unique_normalized_values) == 1:
            value = unique_normalized_values[0]
            if value == "":
                # 所有来源都返回空字符串 -> PENDING（未找到有效内容）
                logger.debug("所有成功提取的值都是空字符串，标记为 PENDING")
                return FieldExtractionStatus.PENDING, None
            else:
                # 所有来源都返回相同的非空值 -> SUCCESS
                # 注意：原始值可能不同（如 "98.6" 和 "98.60"），但规范化后一致
                logger.debug(f"成功提取到一致的值: {value} (规范化后)")
                return FieldExtractionStatus.SUCCESS, None
        
        # 情况2：规范化后的值仍不一致 -> PENDING（需人工确认）
        # 包括：空值与非空值不一致、多个不同的非空值
        # 返回原始的不同值（便于用户查看）
        unique_raw_values = list(set(successful_values_raw))
        logger.debug(f"多来源值不一致: {unique_raw_values}（规范化后: {unique_normalized_values}），标记为 PENDING")
        return FieldExtractionStatus.PENDING, unique_raw_values
    
    def _build_extraction_logic(self, rule: ExtractionRule) -> str:
        """
        构建提取逻辑
        
        将字段类型、选项等信息融入extraction_logic
        
        Args:
            rule: 提取规则
            
        Returns:
            str: 完整的提取逻辑描述
        """
        if rule.disclosure_fields:
            return disclosure_prompt(rule)

        logic_parts = [rule.extraction_logic]
        
        # 添加字段类型信息
        if rule.field_type == FieldType.SINGLE_CHOICE and rule.choices:
            # 单选字段：强调必须从枚举值中选择
            logic_parts.append(
                f"\n\n**重要约束**：这是一个单选字段，必须严格从以下可选项中选择一个并输出枚举值本身，不要输出其他内容：\n"
                f"可选项：{', '.join(rule.choices)}\n"
                f"提取规则：理解原文语义后，映射到最匹配的枚举值。例如原文是'东城区'应映射为'市辖区'，原文是'已完成'应映射为'是'。"
            )
        elif rule.field_type == FieldType.MULTIPLE_CHOICE and rule.choices:
            # 多选字段：强调必须从枚举值中选择（可多个）
            logic_parts.append(
                f"\n\n**重要约束**：这是一个多选字段，必须严格从以下可选项中选择（可选多个）并输出枚举值本身，不要输出其他内容：\n"
                f"可选项：{', '.join(rule.choices)}\n"
                f"提取规则：理解原文语义后，映射到所有匹配的枚举值。"
            )
        elif rule.field_type == FieldType.TEXT:
            # 检查 extraction_logic 中是否已包含枚举约束（避免重复提示）
            has_enum_constraint = any(
                keyword in rule.extraction_logic 
                for keyword in ['可选值', '枚举值', '可选项', '可选城市', '【', '】']
            )
            if not has_enum_constraint:
                logic_parts.append("这是一个文本字段，请提取完整的文本内容")
            else:
                # 如果原始逻辑已包含枚举约束，额外强调映射规则
                logic_parts.append(
                    "\n\n**提取规则**：原文包含枚举值约束时，必须理解原文语义后映射到枚举值，不要直接输出原文。"
                    "例如：可选项为'市辖区, 县'时，原文'东城区'应输出'市辖区'。"
                )
        
        return "".join(logic_parts)
    
    def _filter_parse_results_by_pages(
        self, 
        parse_results: List[Any], 
        page_indices: Set[int]
    ) -> List[Any]:
        """
        根据页面索引过滤 parse_results
        
        支持两种格式：
        1. PaddleParseResult 对象（有 pages 属性）
        2. 字典格式（旧格式）
        
        Args:
            parse_results: 解析结果列表
            page_indices: 需要保留的页面索引集合（0-based）
            
        Returns:
            过滤后的解析结果列表
        """
        filtered_results = []
        
        for result in parse_results:
            # 检查是否是对象（如 PaddleParseResult）
            if hasattr(result, 'pages'):
                # 过滤页面
                filtered_pages = []
                for page in result.pages:
                    # PaddlePage.page_num 是 0-based
                    page_idx = getattr(page, 'page_num', 0)
                    if page_idx in page_indices:
                        filtered_pages.append(page)
                
                if filtered_pages:
                    # 创建新的结果对象（浅拷贝，替换 pages）
                    from copy import copy
                    new_result = copy(result)
                    new_result.pages = filtered_pages
                    filtered_results.append(new_result)
            
            elif isinstance(result, dict):
                # 字典格式：检查 page_idx 或 page_info.page_no
                page_idx = result.get("page_idx")
                if page_idx is None:
                    page_info = result.get("page_info", {})
                    # page_no 通常是 1-based，转为 0-based
                    page_idx = page_info.get("page_no", 0) - 1
                
                if page_idx in page_indices:
                    filtered_results.append(result)
        
        logger.debug(f"页面过滤: {len(parse_results)} -> {len(filtered_results)} 个结果")
        return filtered_results
    
    def _extract_page_indices_from_rag_result(self, rag_markdown: str) -> Set[int]:
        """
        从 RAG 返回的 Markdown 中提取页面索引
        
        RAG 返回的 Markdown 格式通常包含页码标记，如：
        - "--- 第 1 页 ---"
        - "[Page 1]"
        - "【第1页】"
        
        Args:
            rag_markdown: RAG 返回的过滤后 Markdown
            
        Returns:
            Set[int]: 页面索引集合（0-based）
        """
        import re
        
        page_indices = set()
        
        # 匹配多种页码格式
        patterns = [
            r'---\s*第\s*(\d+)\s*页\s*---',  # --- 第 1 页 ---
            r'\[Page\s*(\d+)\]',              # [Page 1]
            r'【第(\d+)页】',                  # 【第1页】
            r'第\s*(\d+)\s*页',                # 第 1 页
            r'Page\s*(\d+)',                   # Page 1
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, rag_markdown, re.IGNORECASE)
            for match in matches:
                try:
                    # 页码转为 0-based 索引
                    page_idx = int(match) - 1
                    if page_idx >= 0:
                        page_indices.add(page_idx)
                except ValueError:
                    continue
        
        logger.debug(f"从 RAG 结果中提取到 {len(page_indices)} 个页面索引: {sorted(page_indices)}")
        return page_indices
    
    def _find_file_by_material(
        self,
        material: str,
        parsed_files: Dict[str, Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        根据参考材料名称查找对应的已解析文件数据
        
        核心逻辑：
        1. reference_materials 中的值（如"《信息披露申请书》"）是文件类型的中文名称
        2. 通过 LABEL_TO_FILE_TYPE 反向映射找到对应的 file_type 枚举值
        3. 根据 file_type 在 parsed_files 中查找解析结果
        
        示例：
        - material: "《信息披露申请书》"
        - 映射为: "info_disclosure_application"
        - 查找: parsed_files["info_disclosure_application"]
        
        Args:
            material: 参考材料名称（如"《信息披露申请书》"）
            parsed_files: 解析后的文件字典，格式：
                {
                    "info_disclosure_application": {
                        "file_type": "info_disclosure_application",
                        "file_names": ["申请书1.pdf", "申请书2.pdf"],
                        "content_list_json": "合并后的内容",
                        "middle_json": "合并后的middle数据"
                    }
                }
            
        Returns:
            Optional[Dict]: 文件数据字典；未找到返回None
        """
        from src.schemas.file import LABEL_TO_FILE_TYPE
        
        logger.debug(f"查找参考材料: {material}")
        
        # 通过反向映射找到 file_type
        file_type = LABEL_TO_FILE_TYPE.get(material)
        
        if file_type is None:
            logger.warning(f"无法识别的参考材料: {material}")
            return None
        
        # 在 parsed_files 中查找对应的 file_type
        file_type_value = file_type.value
        file_data = parsed_files.get(file_type_value)
        
        if file_data:
            file_names = file_data.get("file_names", [])
            logger.info(f"找到参考材料 {material} → {file_type_value} → {len(file_names)} 个文件")
            return file_data
        else:
            logger.warning(f"未找到参考材料对应的文件: {material} (file_type: {file_type_value})")
            return None
    
    async def _call_unified_extraction_agent(
        self,
        file_content: str,
        field_name: str,
        extraction_logic: str,
        reference_materials: str
    ):
        """
        调用统一提取溯源 Agent（Anchor Markdown 方案）
        
        一次 LLM 调用完成提取和溯源：
        1. 接收带锚点的 Markdown 文档
        2. LLM 提取字段值并返回对应的锚点 ID
        3. 后端根据锚点 ID 查表获取精确坐标
        
        Args:
            file_content: 带锚点的 Markdown 文档内容
            field_name: 要提取的字段名称
            extraction_logic: 提取逻辑描述
            reference_materials: 参考材料名称
            
        Returns:
            UnifiedExtractionResult: 包含提取值和锚点 ID 的结果
        """
        unified_config = self.llm_config.get_unified_extraction_agent_config()
        
        logger.debug(f"调用 UnifiedExtractionAgent 提取字段: {field_name}")
        logger.debug(f"Anchor Markdown 长度: {len(file_content)} 字符")
        
        # 使用 LLM semaphore 控制并发，确保只在实际 LLM 调用时占用并发名额
        async with self._llm_semaphore:
            async with LLMClient(unified_config) as client:
                agent = UnifiedExtractionAgent(client)
                return await agent.extract_and_trace(
                    file_content=file_content,
                    field_name=field_name,
                    extraction_logic=extraction_logic,
                    reference_materials=reference_materials
                )
    
    def _should_include_highlight_task(self, source: SourceInfo) -> bool:
        """判断是否需要生成高亮预览图"""
        if source.trace_supported is False:
            return False

        is_excel = source.document_type == "excel" or source.sheet_index is not None
        if is_excel:
            return bool(source.regions)

        if not source.page_number or not source.coordinates:
            return False
        return True

    def _get_result_file_bytes(
        self,
        result: Dict[str, Any],
        downloaded_files_cache: Optional[Dict[str, bytes]] = None,
    ) -> Optional[bytes]:
        """从解析结果或下载缓存中获取 Excel 原始字节"""
        file_bytes = result.get("file_bytes")
        if file_bytes:
            return file_bytes

        parse_result = result.get("parse_result")
        if parse_result:
            file_bytes = getattr(parse_result, "file_bytes", None)
            if file_bytes:
                return file_bytes

        if not downloaded_files_cache:
            return None

        path = result.get("file_path", "")
        if path in downloaded_files_cache:
            return downloaded_files_cache[path]

        from src.utils.file_handler import normalize_file_url
        normalized = normalize_file_url(path)
        if normalized in downloaded_files_cache:
            return downloaded_files_cache[normalized]
        return None

    async def _ensure_excel_file_bytes_list(
        self,
        file_data: Dict[str, Any],
        downloaded_files_cache: Optional[Dict[str, bytes]] = None,
    ) -> List[Optional[bytes]]:
        """确保 Excel 高亮所需的 file_bytes_list 可用，必要时重新下载"""
        file_paths = file_data.get("file_paths") or []
        file_names = file_data.get("file_names") or []
        file_bytes_list: List[Optional[bytes]] = list(file_data.get("file_bytes_list") or [])

        while len(file_bytes_list) < len(file_paths):
            file_bytes_list.append(None)

        for idx, path in enumerate(file_paths):
            if file_bytes_list[idx]:
                continue

            cached = None
            if downloaded_files_cache:
                cached = downloaded_files_cache.get(path)
                if cached is None:
                    from src.utils.file_handler import normalize_file_url
                    cached = downloaded_files_cache.get(normalize_file_url(path))

            if cached:
                file_bytes_list[idx] = cached
                continue

            parse_results = file_data.get("parse_results") or []
            if idx < len(parse_results):
                pr_bytes = getattr(parse_results[idx], "file_bytes", None)
                if pr_bytes:
                    file_bytes_list[idx] = pr_bytes
                    continue

            if not path:
                continue

            try:
                file_name = file_names[idx] if idx < len(file_names) else Path(path).name
                content, _ = await FileHandler.read_file_bytes(file_url=path, file_name=file_name)
                file_bytes_list[idx] = content
            except Exception as e:
                logger.warning(f"Excel 高亮重新下载文件失败 [{path}]: {e}")

        return file_bytes_list

    def _is_text_only_mode(self, file_data: Dict[str, Any]) -> bool:
        """
        检查文件是否为纯文本提取模式（不支持溯源）
        
        Args:
            file_data: 文件数据字典
            
        Returns:
            bool: 是否为纯文本模式
        """
        if file_data.get("is_excel") and file_data.get("excel_trace_supported", True):
            return False

        parse_results = file_data.get("parse_results", [])
        if not parse_results:
            return False
        
        # 检查是否所有解析结果都标记为纯文本模式
        return all(
            getattr(result, "is_text_only", False) 
            for result in parse_results
            )

    def _build_regions_from_bbox_infos(
        self,
        bbox_infos: List[Dict[str, Any]],
        is_excel: bool = False,
    ) -> List[Any]:
        from src.services.llm.models import Region

        regions = []
        for info in bbox_infos:
            page_idx = info["page_idx"]
            regions.append(Region(
                page_idx=page_idx,
                page_number=page_idx + 1,
                bbox=info["bbox"],
                text_segment=info.get("text"),
                file_index=info.get("file_index"),
                sheet_name=info.get("sheet_name"),
                cell_ref=info.get("cell_ref"),
            ))
        return regions

    def _build_source_info_from_regions(
        self,
        file_data: Dict[str, Any],
        rule: ExtractionRule,
        unified_result: Any,
        regions: List[Any],
        segment_map: Dict[str, SegmentInfo],
        preview_image: str = "",
        is_excel: bool = False,
    ) -> SourceInfo:
        from src.schemas.extraction import RegionInfo

        source_file_name = ", ".join(file_data["file_names"])
        first_region = regions[0]

        all_bboxes = [r.bbox for r in regions if r.bbox]
        merged_bbox = AnchorMarkdownConverter.merge_bboxes(all_bboxes) if all_bboxes else None

        coordinates = {"x": 0, "y": 0, "width": 0, "height": 0}
        if merged_bbox and len(merged_bbox) == 4:
            x0, y0, x1, y1 = merged_bbox
            coordinates = {
                "x": int(x0),
                "y": int(y0),
                "width": int(x1 - x0),
                "height": int(y1 - y0),
            }

        region_infos = [
            RegionInfo(
                page_idx=r.page_idx,
                bbox=r.bbox,
                file_index=getattr(r, "file_index", None),
                sheet_name=getattr(r, "sheet_name", None),
                cell_ref=getattr(r, "cell_ref", None),
            )
            for r in regions if r.bbox
        ]

        excel_fields = build_excel_source_fields(regions, segment_map) if is_excel else {}
        trace_supported = True
        document_type = None
        page_number = first_region.page_number

        if is_excel:
            document_type = "excel"
            trace_supported = bool(file_data.get("excel_trace_supported", True)) and bool(excel_fields.get("cell_refs"))
            page_number = None
        elif self._is_text_only_mode(file_data):
            trace_supported = False
            document_type = "text"

        return SourceInfo(
            source_file_type=file_data["file_type"],
            source_file_name=source_file_name,
            source_field=rule.field_name,
            source_content=unified_result.extracted_value or "",
            preview_image_url=preview_image or "",
            page_number=page_number,
            coordinates=coordinates,
            confidence=unified_result.confidence or 0.9,
            cross_page_info=None,
            regions=region_infos if region_infos else None,
            trace_supported=trace_supported,
            document_type=document_type,
            sheet_name=excel_fields.get("sheet_name"),
            sheet_index=excel_fields.get("sheet_index"),
            cell_ref=excel_fields.get("cell_ref"),
            cell_refs=excel_fields.get("cell_refs"),
        )
    
    async def _generate_highlight(
        self,
        file_path: Union[str, bytes],
        page_idx: int,
        bbox: List[float],
        backend: str = "mineru",  # 解析后端
        rotation_angle: int = 0  # 文档旋转角度（仅 Paddle 使用）
    ) -> Optional[str]:
        """
        生成PDF高亮（支持多backend）
        
        Args:
            file_path: PDF文件路径、URL 或 bytes 内容
            page_idx: 页码索引
            bbox: 边界框坐标
            backend: 解析后端（'paddle' 或 'mineru'），默认 'mineru'
            rotation_angle: 文档旋转角度（逆时针，度），仅 Paddle 后端使用
            
        Returns:
            Optional[str]: MinIO URL 或 None（失败时）
        """
        try:
            # 判断输入类型
            pdf_input = file_path
            
            # 如果是字符串且为URL，下载文件内容
            if isinstance(file_path, str) and file_path.startswith(('http://', 'https://')):
                # 从URL下载文件内容
                pdf_content, _ = await FileHandler._download_from_url(file_path)
                pdf_input = pdf_content
            # 如果是 bytes，直接使用
            elif isinstance(file_path, bytes):
                pdf_input = file_path
            # 如果是本地路径字符串，直接使用
            
            # ✅ 根据 backend 选择高亮器
            if backend.startswith("paddle"):
                # 使用 Paddle 专用高亮器（144 DPI，像素坐标）
                rotation_info = f" | 旋转: {rotation_angle}°" if rotation_angle != 0 else ""
                logger.info(f"使用 Paddle 专用高亮器 | 页面: {page_idx}{rotation_info}")
                image_url = PaddlePDFHighlighter.highlight_single_region(
                    pdf_path=pdf_input,
                    page_num=page_idx,
                    bbox=bbox,
                    rotation_angle=rotation_angle
                )
            else:
                # 使用通用高亮器（MinerU 等，200 DPI，点坐标）
                logger.info(f"使用通用高亮器 | 页面: {page_idx}")
                image_url = PDFHighlighter.highlight_single_region(
                    pdf_path=pdf_input,
                    page_num=page_idx,
                    bbox=bbox
                )
            
            return image_url
            
        except Exception as e:
            logger.error(f"生成PDF高亮失败: {e}", exc_info=True)
            return None
    
    def _save_single_image_to_bytes(self, img: Any) -> bytes:
        """
        同步方法：将单张图片保存为JPEG字节数据
        在线程池中执行以避免阻塞事件循环
        
        Args:
            img: PIL Image对象
            
        Returns:
            bytes: JPEG图片字节数据
        """
        from io import BytesIO
        buffer = BytesIO()
        img.save(buffer, format='JPEG', quality=85)
        return buffer.getvalue()
    
    def _merge_and_save_images(self, images: List[Any]) -> bytes:
        """
        同步方法：垂直拼接多张图片并保存为JPEG字节数据
        在线程池中执行以避免阻塞事件循环
        
        Args:
            images: PIL Image对象列表
            
        Returns:
            bytes: JPEG图片字节数据
        """
        from PIL import Image, ImageDraw
        from io import BytesIO
        
        max_width = max(img.width for img in images)
        page_gap = 20
        total_height = sum(img.height for img in images) + page_gap * (len(images) - 1)
        
        merged_image = Image.new('RGB', (max_width, total_height), 'white')
        
        current_y = 0
        for i, img in enumerate(images):
            x_offset = (max_width - img.width) // 2
            merged_image.paste(img, (x_offset, current_y))
            current_y += img.height
            
            if i < len(images) - 1:
                draw = ImageDraw.Draw(merged_image)
                line_y = current_y + page_gap // 2
                draw.line([(10, line_y), (max_width - 10, line_y)], fill='gray', width=2)
                current_y += page_gap
        
        buffer = BytesIO()
        merged_image.save(buffer, format='JPEG', quality=85)
        return buffer.getvalue()
    
    async def _generate_highlight_image_bytes(
        self,
        file_path: Union[str, bytes],
        page_bboxes: List[Tuple[int, Optional[List[float]]]],
        backend: str = "mineru",
        page_rotation_angles: Optional[Dict[int, int]] = None
    ) -> Optional[bytes]:
        """
        生成高亮图片字节数据（不上传）
        
        用于批量生成后统一上传，减少网络往返
        
        Args:
            file_path: PDF 文件路径、URL 或 bytes
            page_bboxes: 页码和 bbox 列表 [(page_idx, bbox), ...]
            backend: 解析后端
            page_rotation_angles: 页面旋转角度映射 {page_idx: rotation_angle}，仅 Paddle 使用
            
        Returns:
            Optional[bytes]: PNG 图片字节数据
        """
        try:
            from PIL import Image
            from io import BytesIO
            from collections import defaultdict
            
            if page_rotation_angles is None:
                page_rotation_angles = {}
            
            # 准备 PDF 输入
            pdf_input = file_path
            if isinstance(file_path, str) and file_path.startswith(('http://', 'https://')):
                pdf_content, _ = await FileHandler._download_from_url(file_path)
                pdf_input = pdf_content
            elif isinstance(file_path, bytes):
                pdf_input = file_path
            
            # 按页码分组 bbox
            page_groups = defaultdict(list)
            for page_idx, bbox in page_bboxes:
                if bbox is None:
                    continue
                page_groups[page_idx].append(bbox)
            
            if not page_groups:
                return None
            
            # 选择高亮器
            if backend.startswith("paddle"):
                highlighter = PaddlePDFHighlighter
            else:
                highlighter = PDFHighlighter
            
            # 为每个页面生成高亮图片
            page_images = []
            logger.debug(f"[高亮调试] _generate_highlight_image_bytes | backend: {backend} | page_rotation_angles: {page_rotation_angles}")
            for page_idx in sorted(page_groups.keys()):
                bboxes = page_groups[page_idx]
                rotation_angle = page_rotation_angles.get(page_idx, 0)
                logger.debug(f"[高亮调试] 页面 {page_idx} | rotation_angle: {rotation_angle} | bboxes数量: {len(bboxes)}")
                
                if hasattr(highlighter, 'generate_highlight_image'):
                    # 使用线程池执行CPU密集型的PDF渲染和PIL解码操作
                    # 使用 functools.partial 或默认参数捕获当前循环变量的值（避免闭包问题）
                    def render_and_decode(
                        _pdf_input=pdf_input,
                        _page_idx=page_idx,
                        _bboxes=bboxes,
                        _rotation_angle=rotation_angle,
                        _backend=backend,
                        _highlighter=highlighter
                    ):
                        """在线程池中执行：PDF渲染 + PIL解码"""
                        if _backend.startswith("paddle"):
                            img_bytes = _highlighter.generate_highlight_image(
                                pdf_path=_pdf_input,
                                page_num=_page_idx,
                                bboxes=_bboxes,
                                rotation_angle=_rotation_angle
                            )
                        else:
                            img_bytes = _highlighter.generate_highlight_image(
                                pdf_path=_pdf_input,
                                page_num=_page_idx,
                                bboxes=_bboxes
                            )
                        if img_bytes:
                            from PIL import Image
                            from io import BytesIO
                            return Image.open(BytesIO(img_bytes))
                        return None
                    
                    img = await asyncio.to_thread(render_and_decode)
                    
                    if img:
                        page_images.append((page_idx, img))
                else:
                    # 降级：使用旧方法（会上传，然后下载）
                    # 这种情况下效率较低，但保证兼容性
                    logger.warning(f"高亮器不支持 generate_highlight_image，使用降级方案")
                    return None
            
            if not page_images:
                return None
            
            # 如果只有一页，直接返回（使用 JPEG 格式，更快）
            if len(page_images) == 1:
                _, single_img = page_images[0]
                # 使用线程池执行CPU密集型的图片保存操作
                return await asyncio.to_thread(self._save_single_image_to_bytes, single_img)
            
            # 多页：垂直拼接（使用线程池执行CPU密集型的图片处理操作）
            images_only = [img for _, img in page_images]
            return await asyncio.to_thread(self._merge_and_save_images, images_only)
            
        except Exception as e:
            logger.error(f"生成高亮图片字节失败: {e}", exc_info=True)
            return None
    
    async def _generate_multi_file_highlight_bytes(
        self,
        file_data: Dict[str, Any],
        file_regions_map: Dict[int, List[Tuple[int, List[float]]]],
        parse_results: List[Any],
        file_paths: List[str],
        pdf_contents: Optional[List[Optional[bytes]]] = None
    ) -> Optional[bytes]:
        """
        生成多文件高亮图片字节数据（不上传）
        
        Args:
            file_data: 文件数据字典
            file_regions_map: 按文件索引分组的区域信息
            parse_results: 解析结果列表
            file_paths: 文件路径列表
            pdf_contents: 转换后的 PDF 内容列表（Word/图片文件），优先使用
            
        Returns:
            Optional[bytes]: PNG 图片字节数据
        """
        try:
            from PIL import Image
            from io import BytesIO
            from collections import defaultdict
            
            all_page_images: List[Tuple[int, Image.Image]] = []
            
            # 计算每个文件的全局页码偏移
            file_page_offsets = [0]
            for i, pr in enumerate(parse_results[:-1]):
                file_page_offsets.append(file_page_offsets[-1] + len(pr.pages))
            
            for file_index in sorted(file_regions_map.keys()):
                page_bboxes = file_regions_map[file_index]
                
                if file_index >= len(file_paths):
                    continue
                    
                file_path = file_paths[file_index]
                
                # 优先使用转换后的 PDF 内容（Word/图片文件）
                converted_pdf = None
                if pdf_contents and file_index < len(pdf_contents):
                    converted_pdf = pdf_contents[file_index]
                
                pdf_input = converted_pdf if converted_pdf is not None else file_path
                
                backend = "mineru"
                if file_index < len(parse_results):
                    backend = getattr(parse_results[file_index], "backend", "mineru")
                
                actual_pdf_input = pdf_input
                # 只有当使用原始文件路径时才需要下载
                if converted_pdf is None and isinstance(pdf_input, str) and pdf_input.startswith(('http://', 'https://')):
                    downloaded_content, _ = await FileHandler._download_from_url(pdf_input)
                    actual_pdf_input = downloaded_content
                
                global_offset = file_page_offsets[file_index] if file_index < len(file_page_offsets) else 0
                
                if backend.startswith("paddle"):
                    highlighter = PaddlePDFHighlighter
                    # 获取该文件所有页面的旋转角度
                    _skip_local = converted_pdf is not None
                    page_rotation_angles = self._get_page_rotation_angles(
                        parse_results[file_index],
                        skip_local_rotation=_skip_local,
                    ) if file_index < len(parse_results) else {}
                else:
                    highlighter = PDFHighlighter
                    page_rotation_angles = {}
                
                page_groups = defaultdict(list)
                for actual_page_idx, bbox in page_bboxes:
                    page_groups[actual_page_idx].append(bbox)
                
                for actual_page_idx in sorted(page_groups.keys()):
                    bboxes = page_groups[actual_page_idx]
                    global_page_idx = global_offset + actual_page_idx
                    rotation_angle = page_rotation_angles.get(actual_page_idx, 0)
                    
                    if hasattr(highlighter, 'generate_highlight_image'):
                        # 使用线程池执行CPU密集型的PDF渲染和PIL解码操作
                        # 使用默认参数捕获当前循环变量的值（避免闭包问题）
                        def render_and_decode(
                            _pdf_input=actual_pdf_input,
                            _page_idx=actual_page_idx,
                            _bboxes=bboxes,
                            _rotation_angle=rotation_angle,
                            _global_page_idx=global_page_idx,
                            _backend=backend,
                            _highlighter=highlighter
                        ):
                            """在线程池中执行：PDF渲染 + PIL解码"""
                            if _backend.startswith("paddle"):
                                img_bytes = _highlighter.generate_highlight_image(
                                    pdf_path=_pdf_input,
                                    page_num=_page_idx,
                                    bboxes=_bboxes,
                                    rotation_angle=_rotation_angle
                                )
                            else:
                                img_bytes = _highlighter.generate_highlight_image(
                                    pdf_path=_pdf_input,
                                    page_num=_page_idx,
                                    bboxes=_bboxes
                                )
                            if img_bytes:
                                from PIL import Image
                                from io import BytesIO
                                return (_global_page_idx, Image.open(BytesIO(img_bytes)))
                            return None
                        
                        result = await asyncio.to_thread(render_and_decode)
                        if result:
                            all_page_images.append(result)
            
            if not all_page_images:
                return None
            
            all_page_images.sort(key=lambda x: x[0])
            
            if len(all_page_images) == 1:
                _, single_img = all_page_images[0]
                # 使用线程池执行CPU密集型的图片保存操作
                return await asyncio.to_thread(self._save_single_image_to_bytes, single_img)
            
            # 多页：垂直拼接（使用线程池执行CPU密集型的图片处理操作）
            images_only = [img for _, img in all_page_images]
            return await asyncio.to_thread(self._merge_and_save_images, images_only)
            
        except Exception as e:
            logger.error(f"生成多文件高亮图片字节失败: {e}", exc_info=True)
            return None
    
    async def _generate_multi_file_highlight(
        self,
        file_data: Dict[str, Any],
        file_regions_map: Dict[int, List[Tuple[int, List[float]]]],
        parse_results: List[Any],
        file_paths: List[str],
        pdf_contents: Optional[List[Optional[bytes]]] = None
    ) -> Optional[str]:
        """
        生成多文件的合并高亮图
        
        当 LLM 返回的锚点来自不同文件时，需要分别为每个文件生成高亮，
        然后将所有高亮图按全局页码顺序合并成一张图片。
        
        Args:
            file_data: 文件数据字典
            file_regions_map: 按文件索引分组的区域信息 {file_index: [(actual_page_idx, bbox), ...]}
            parse_results: 解析结果列表
            file_paths: 文件路径列表
            pdf_contents: 转换后的 PDF 内容列表（Word/图片文件），优先使用
            
        Returns:
            Optional[str]: 合并后的 MinIO URL 或 None（失败时）
        """
        try:
            from PIL import Image
            from io import BytesIO
            from src.utils.minio.client import get_minio_client
            
            # 收集所有文件的高亮图，带全局页码信息
            all_page_images: List[Tuple[int, Image.Image]] = []  # [(global_page_idx, image), ...]
            
            # 计算每个文件的全局页码偏移
            file_page_offsets = [0]
            for i, pr in enumerate(parse_results[:-1]):
                file_page_offsets.append(file_page_offsets[-1] + len(pr.pages))
            
            # 按文件索引排序处理
            for file_index in sorted(file_regions_map.keys()):
                page_bboxes = file_regions_map[file_index]
                
                # 获取文件路径
                if file_index >= len(file_paths):
                    logger.warning(f"文件索引 {file_index} 超出范围，跳过")
                    continue
                    
                file_path = file_paths[file_index]
                
                # 优先使用转换后的 PDF 内容（Word/图片文件）
                converted_pdf = None
                if pdf_contents and file_index < len(pdf_contents):
                    converted_pdf = pdf_contents[file_index]
                
                pdf_input = converted_pdf if converted_pdf is not None else file_path
                
                # 获取解析后端
                backend = "mineru"
                if file_index < len(parse_results):
                    backend = getattr(parse_results[file_index], "backend", "mineru")
                
                # 准备 PDF 输入
                actual_pdf_input = pdf_input
                # 只有当使用原始文件路径时才需要下载
                if converted_pdf is None and isinstance(pdf_input, str) and pdf_input.startswith(('http://', 'https://')):
                    downloaded_content, _ = await FileHandler._download_from_url(pdf_input)
                    actual_pdf_input = downloaded_content
                
                # 获取该文件的全局页码偏移
                global_offset = file_page_offsets[file_index] if file_index < len(file_page_offsets) else 0
                
                # 为每个页面生成高亮图
                from collections import defaultdict
                page_groups = defaultdict(list)
                for actual_page_idx, bbox in page_bboxes:
                    page_groups[actual_page_idx].append(bbox)
                
                # 选择高亮器
                if backend.startswith("paddle"):
                    highlighter = PaddlePDFHighlighter
                    # 获取该文件所有页面的旋转角度
                    _skip_local = converted_pdf is not None
                    page_rotation_angles = self._get_page_rotation_angles(
                        parse_results[file_index],
                        skip_local_rotation=_skip_local,
                    ) if file_index < len(parse_results) else {}
                else:
                    highlighter = PDFHighlighter
                    page_rotation_angles = {}
                
                for actual_page_idx in sorted(page_groups.keys()):
                    bboxes = page_groups[actual_page_idx]
                    global_page_idx = global_offset + actual_page_idx
                    rotation_angle = page_rotation_angles.get(actual_page_idx, 0)
                    
                    logger.debug(f"文件 {file_index} 页面 {actual_page_idx}（全局 {global_page_idx}）有 {len(bboxes)} 个高亮框")
                    
                    try:
                        # 使用不上传的方法生成高亮图
                        if hasattr(highlighter, 'generate_highlight_image'):
                            # 使用线程池执行CPU密集型的PDF渲染和PIL解码操作
                            # 使用默认参数捕获当前循环变量的值（避免闭包问题）
                            def render_and_decode(
                                _pdf_input=actual_pdf_input,
                                _page_idx=actual_page_idx,
                                _bboxes=bboxes,
                                _rotation_angle=rotation_angle,
                                _global_page_idx=global_page_idx,
                                _backend=backend,
                                _highlighter=highlighter
                            ):
                                """在线程池中执行：PDF渲染 + PIL解码"""
                                if _backend.startswith("paddle"):
                                    img_bytes = _highlighter.generate_highlight_image(
                                        pdf_path=_pdf_input,
                                        page_num=_page_idx,
                                        bboxes=_bboxes,
                                        rotation_angle=_rotation_angle
                                    )
                                else:
                                    img_bytes = _highlighter.generate_highlight_image(
                                        pdf_path=_pdf_input,
                                        page_num=_page_idx,
                                        bboxes=_bboxes
                                    )
                                if img_bytes:
                                    from PIL import Image
                                    from io import BytesIO
                                    return (_global_page_idx, Image.open(BytesIO(img_bytes)))
                                return None
                            
                            result = await asyncio.to_thread(render_and_decode)
                            if result:
                                all_page_images.append(result)
                        else:
                            # 降级：使用旧方法
                            image_url = await self._generate_multi_bbox_highlight(
                                pdf_input=actual_pdf_input,
                                page_idx=actual_page_idx,
                                bboxes=bboxes,
                                backend=backend,
                                rotation_angle=rotation_angle
                            )
                            if image_url:
                                image_content, _ = await FileHandler._download_from_url(image_url)
                                img = Image.open(BytesIO(image_content))
                                all_page_images.append((global_page_idx, img))
                    except Exception as e:
                        logger.error(f"生成高亮图失败: {e}")
                        continue
            
            if not all_page_images:
                logger.error("没有成功生成任何高亮图")
                return None
            
            # 按全局页码排序
            all_page_images.sort(key=lambda x: x[0])
            
            # 如果只有一张图，直接返回（使用 JPEG 格式）
            if len(all_page_images) == 1:
                # 需要重新上传（因为之前的 URL 可能已经过期或不可用）
                _, single_img = all_page_images[0]
                # 使用线程池执行CPU密集型的图片保存操作
                image_bytes = await asyncio.to_thread(self._save_single_image_to_bytes, single_img)
                
                minio_client = get_minio_client()
                import time
                import uuid
                object_name = f"highlights/merged_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.jpg"
                url = minio_client.upload_bytes(
                    data=image_bytes,
                    object_name=object_name,
                    content_type="image/jpeg"
                )
                logger.info(f"单文件高亮上传成功: {url}")
                return url
            
            # 多张图：垂直拼接（使用线程池执行CPU密集型的图片处理操作）
            images_only = [img for _, img in all_page_images]
            
            logger.info(f"合并 {len(images_only)} 张跨文件高亮图")
            
            # 使用线程池执行图片拼接和保存
            image_bytes = await asyncio.to_thread(self._merge_and_save_images, images_only)
            
            # 上传合并后的图片
            buffer = BytesIO(image_bytes)
            
            minio_client = get_minio_client()
            import time
            import uuid
            object_name = f"highlights/merged_multifile_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.jpg"
            url = minio_client.upload_bytes(
                data=buffer.getvalue(),
                object_name=object_name,
                content_type="image/jpeg"
            )
            
            logger.info(f"多文件高亮合并成功，已上传到: {url}")
            return url
            
        except Exception as e:
            logger.error(f"生成多文件高亮失败: {e}", exc_info=True)
            return None
    
    async def _generate_merged_highlight(
        self,
        file_path: Union[str, bytes],
        page_bboxes: List[Tuple[int, Optional[List[float]]]],
        backend: str = "mineru",
        page_rotation_angles: Optional[Dict[int, int]] = None
    ) -> Optional[str]:
        """
        生成合并的高亮图（V2 - 支持同页多框 + 跨页）
        
        将多个页面（或同一页面的多个区域）的高亮图合并成一张图片
        
        处理逻辑：
        1. 按页码分组 bbox
        2. 对每个页面，在同一张底图上绘制该页所有的 bbox
        3. 如果涉及多页，垂直拼接所有页面
        
        Args:
            file_path: PDF文件路径、URL 或 bytes 内容
            page_bboxes: 页码和bbox的列表 [(page_idx, bbox), ...]
            backend: 解析后端（'paddle' 或 'mineru'），默认 'mineru'
            page_rotation_angles: 页面旋转角度映射 {page_idx: rotation_angle}，仅 Paddle 使用
            
        Returns:
            Optional[str]: 合并后的MinIO URL 或 None（失败时）
        """
        try:
            from PIL import Image
            from io import BytesIO
            import tempfile
            from collections import defaultdict
            from src.utils.minio.client import get_minio_client
            
            # 准备 PDF 输入
            pdf_input = file_path
            if isinstance(file_path, str) and file_path.startswith(('http://', 'https://')):
                pdf_content, _ = await FileHandler._download_from_url(file_path)
                pdf_input = pdf_content
            elif isinstance(file_path, bytes):
                pdf_input = file_path
            
            # 1. 按页码分组 bbox
            page_groups = defaultdict(list)  # {page_idx: [bbox1, bbox2, ...]}
            for page_idx, bbox in page_bboxes:
                if bbox is None:
                    continue
                page_groups[page_idx].append(bbox)
            
            if not page_groups:
                logger.error("没有有效的 bbox 数据")
                return None
            
            # 2. 为每个页面生成高亮图（不上传，最后统一上传）
            page_images = []
            sorted_pages = sorted(page_groups.keys())
            
            # 选择高亮器
            if backend.startswith("paddle"):
                highlighter = PaddlePDFHighlighter
            else:
                highlighter = PDFHighlighter
            
            # 确保旋转角度字典存在
            if page_rotation_angles is None:
                page_rotation_angles = {}
            
            # 批量生成高亮图片（不上传）
            for page_idx in sorted_pages:
                bboxes = page_groups[page_idx]
                rotation_angle = page_rotation_angles.get(page_idx, 0)
                logger.debug(f"页面 {page_idx} 有 {len(bboxes)} 个高亮框")
                
                try:
                    # 使用新的不上传方法
                    if hasattr(highlighter, 'generate_highlight_image'):
                        # 使用线程池执行CPU密集型的PDF渲染和PIL解码操作
                        # 使用默认参数捕获当前循环变量的值（避免闭包问题）
                        def render_and_decode(
                            _pdf_input=pdf_input,
                            _page_idx=page_idx,
                            _bboxes=bboxes,
                            _rotation_angle=rotation_angle,
                            _backend=backend,
                            _highlighter=highlighter
                        ):
                            """在线程池中执行：PDF渲染 + PIL解码"""
                            if _backend.startswith("paddle"):
                                img_bytes = _highlighter.generate_highlight_image(
                                    pdf_path=_pdf_input,
                                    page_num=_page_idx,
                                    bboxes=_bboxes,
                                    rotation_angle=_rotation_angle
                                )
                            else:
                                img_bytes = _highlighter.generate_highlight_image(
                                    pdf_path=_pdf_input,
                                    page_num=_page_idx,
                                    bboxes=_bboxes
                                )
                            if img_bytes:
                                from PIL import Image
                                from io import BytesIO
                                return (_page_idx, Image.open(BytesIO(img_bytes)))
                            return None
                        
                        result = await asyncio.to_thread(render_and_decode)
                        if result:
                            page_images.append(result)
                    else:
                        # 降级：使用旧方法（会上传）
                        image_url = await self._generate_multi_bbox_highlight(
                            pdf_input=pdf_input,
                            page_idx=page_idx,
                            bboxes=bboxes,
                            backend=backend,
                            rotation_angle=rotation_angle
                        )
                        if image_url:
                            image_content, _ = await FileHandler._download_from_url(image_url)
                            img = Image.open(BytesIO(image_content))
                            page_images.append((page_idx, img))
                except Exception as e:
                    logger.error(f"生成页面 {page_idx} 高亮图失败: {e}")
                    continue
            
            if not page_images:
                logger.error("没有成功生成任何页面的高亮图")
                return None
            
            logger.info(f"成功生成 {len(page_images)} 张高亮图，准备上传")
            
            # 3. 如果只有一页，直接上传（使用 JPEG 格式）
            if len(page_images) == 1:
                _, single_img = page_images[0]
                # 使用线程池执行CPU密集型的图片保存操作
                image_bytes = await asyncio.to_thread(self._save_single_image_to_bytes, single_img)
                
                minio_client = get_minio_client()
                import hashlib
                file_hash = hashlib.md5(image_bytes).hexdigest()[:8]
                timestamp = int(time.time() * 1000)
                object_name = f"highlights/single_{timestamp}_{file_hash}.jpg"
                
                url = minio_client.upload_bytes(
                    data=image_bytes,
                    object_name=object_name,
                    content_type='image/jpeg'
                )
                logger.info(f"单页高亮上传成功: {url[:60]}...")
                return url
            
            # 4. 多页：垂直拼接（使用线程池执行CPU密集型的图片处理操作）
            images_only = [img for _, img in page_images]
            
            logger.info(f"合并 {len(images_only)} 张图片")
            
            # 使用线程池执行图片拼接和保存
            image_bytes = await asyncio.to_thread(self._merge_and_save_images, images_only)
            
            minio_client = get_minio_client()
            
            import hashlib
            file_hash = hashlib.md5(image_bytes).hexdigest()[:8]
            timestamp = int(time.time() * 1000)
            object_name = f"highlights/merged_{timestamp}_{file_hash}.jpg"
            
            url = minio_client.upload_bytes(
                data=image_bytes,
                object_name=object_name,
                content_type='image/jpeg'
            )
            
            logger.info(f"多页高亮图合并成功，已上传到: {url}")
            return url
            
        except Exception as e:
            logger.error(
                f"生成合并高亮图失败 | "
                f"错误类型: {type(e).__name__} | "
                f"错误信息: {str(e) or '无详细信息'} | "
                f"文件路径: {str(file_path)[:100] if isinstance(file_path, str) else 'bytes'} | "
                f"区域数: {len(page_bboxes)}",
                exc_info=True
            )
            return None
    
    async def _generate_multi_bbox_highlight(
        self,
        pdf_input: Union[str, bytes],
        page_idx: int,
        bboxes: List[List[float]],
        backend: str = "mineru",
        rotation_angle: int = 0
    ) -> Optional[str]:
        """
        在同一页面上绘制多个 bbox 高亮框
        
        Args:
            pdf_input: PDF 文件路径、URL 或 bytes
            page_idx: 页码索引
            bboxes: bbox 列表 [[x0,y0,x1,y1], ...]
            backend: 解析后端
            rotation_angle: 文档旋转角度（逆时针，度），仅 Paddle 后端使用
            
        Returns:
            Optional[str]: MinIO URL
        """
        try:
            # 选择高亮器
            if backend.startswith("paddle"):
                highlighter = PaddlePDFHighlighter
            else:
                highlighter = PDFHighlighter
            
            # 检查高亮器是否支持多 bbox
            if hasattr(highlighter, 'highlight_multiple_regions_single_page'):
                # 如果有专用方法，使用它
                return highlighter.highlight_multiple_regions_single_page(
                    pdf_path=pdf_input,
                    page_num=page_idx,
                    bboxes=bboxes
                )
            else:
                # 降级：逐个绘制并合并（或者只画第一个框）
                # 这里简化处理：合并所有 bbox 为一个大框
                if len(bboxes) == 1:
                    if backend.startswith("paddle"):
                        return highlighter.highlight_single_region(
                            pdf_path=pdf_input,
                            page_num=page_idx,
                            bbox=bboxes[0],
                            rotation_angle=rotation_angle
                        )
                    else:
                        return highlighter.highlight_single_region(
                            pdf_path=pdf_input,
                            page_num=page_idx,
                            bbox=bboxes[0]
                        )
                else:
                    # 计算包围所有 bbox 的最小矩形
                    x0 = min(b[0] for b in bboxes)
                    y0 = min(b[1] for b in bboxes)
                    x1 = max(b[2] for b in bboxes)
                    y1 = max(b[3] for b in bboxes)
                    merged_bbox = [x0, y0, x1, y1]
                    
                    logger.info(f"合并 {len(bboxes)} 个框为一个大框: {merged_bbox}")
                    if backend.startswith("paddle"):
                        return highlighter.highlight_single_region(
                            pdf_path=pdf_input,
                            page_num=page_idx,
                            bbox=merged_bbox,
                            rotation_angle=rotation_angle
                        )
                    else:
                        return highlighter.highlight_single_region(
                            pdf_path=pdf_input,
                            page_num=page_idx,
                            bbox=merged_bbox
                        )
        except Exception as e:
            logger.error(
                f"生成多框高亮失败 | "
                f"错误类型: {type(e).__name__} | "
                f"错误信息: {str(e) or '无详细信息'} | "
                f"页面: {page_idx} | "
                f"bbox数量: {len(bboxes)} | "
                f"后端: {backend}",
                exc_info=True
            )
            return None
    
    def _locate_file_by_page(
        self,
        file_data: Dict[str, Any],
        global_page_idx: int
    ) -> tuple[Optional[str], int]:
        """
        根据全局页码找到对应的文件路径
        
        当一个 file_type 包含多个文件时，页码是连续累加的。
        这个方法根据全局页码，找到是哪个文件。
        
        Args:
            file_data: 文件数据字典
            global_page_idx: 全局页码（合并后的页码）
            
        Returns:
            tuple: (文件路径, 文件索引)
        """
        parse_results = file_data.get("parse_results", [])
        file_paths = file_data.get("file_paths", [])
        
        if not parse_results or not file_paths:
            return None, -1
        
        # 累加页数，找到对应的文件
        page_offset = 0
        for i, parse_result in enumerate(parse_results):
            page_count = len(parse_result.pages)
            if global_page_idx < page_offset + page_count:
                return file_paths[i], i
            page_offset += page_count
        
        # 如果没找到，返回第一个文件（兜底）
        logger.warning(f"页码 {global_page_idx} 超出范围，使用第一个文件")
        return file_paths[0], 0
    
    def _calculate_actual_page_idx(
        self,
        file_data: Dict[str, Any],
        file_index: int,
        global_page_idx: int
    ) -> int:
        """
        计算在单个文件中的实际页码
        
        Args:
            file_data: 文件数据字典
            file_index: 文件索引
            global_page_idx: 全局页码
            
        Returns:
            int: 在单个文件中的实际页码
        """
        parse_results = file_data.get("parse_results", [])
        
        # 计算该文件之前所有文件的总页数
        page_offset = 0
        for i in range(file_index):
            if i < len(parse_results):
                page_offset += len(parse_results[i].pages)
        
        # 全局页码减去偏移量
        return global_page_idx - page_offset
    
    def _get_page_rotation_angles(
        self,
        parse_result: Any,
        page_indices: Optional[List[int]] = None,
        skip_local_rotation: bool = False,
    ) -> Dict[int, int]:
        """
        从解析结果中获取页面旋转角度映射

        合并两个来源的旋转角度：
        1. Paddle 内部检测（doc_preprocessor_res.angle），存入 PaddlePage.rotation_angle
        2. 本地 RotationDetector 检测，存入 PaddlePage.local_rotation_angle

        skip_local_rotation=True 时，忽略 local_rotation_angle，仅使用 Paddle 的 rotation_angle。
        场景：高亮器使用了 corrected_file_content（/Rotate 已修正的 PDF），
        PDF 渲染器自动应用 /Rotate 使图像方向正确，不需要再对 bbox 做逆变换。

        Args:
            parse_result: 解析结果对象（PaddleParseResult 或其他）
            page_indices: 需要获取的页码列表，None 表示所有页面
            skip_local_rotation: 是否跳过本地旋转角度（使用修正 PDF 时为 True）

        Returns:
            Dict[int, int]: 页面旋转角度映射 {page_idx: rotation_angle}
        """
        rotation_angles: Dict[int, int] = {}

        # 调试日志：检查 parse_result 类型和属性
        logger.debug(
            f"[旋转角度] 入口 | parse_result 类型: {type(parse_result).__name__} | "
            f"page_indices: {page_indices} | skip_local: {skip_local_rotation}"
        )

        if not hasattr(parse_result, 'pages'):
            logger.debug(f"[旋转角度] parse_result 没有 pages 属性，返回空字典")
            return rotation_angles

        logger.debug(f"[旋转角度] pages 数量: {len(parse_result.pages)}")

        for page in parse_result.pages:
            page_idx = getattr(page, 'page_num', -1)
            logger.debug(f"[旋转角度] 遍历页面 | page_num: {page_idx} | has rotation_angle: {hasattr(page, 'rotation_angle')}")
            if page_idx < 0:
                continue

            # 如果指定了页码列表，只获取指定页面的旋转角度
            if page_indices is not None and page_idx not in page_indices:
                logger.debug(f"[旋转角度] 页面 {page_idx} 不在 page_indices 中，跳过")
                continue

            # Paddle 内部检测的旋转角度（doc_preprocessor_res.angle）
            rotation_angle = getattr(page, 'rotation_angle', 0) or 0

            # 本地 RotationDetector 检测的旋转角度
            # skip_local_rotation=True 时忽略：高亮器使用 /Rotate 已修正的 PDF，
            # PDF 渲染器自动应用 /Rotate 使图像方向正确，bbox 无需逆变换
            local_rotation_angle = 0 if skip_local_rotation else (getattr(page, 'local_rotation_angle', 0) or 0)

            # 取两者中非零值（互斥关系：Paddle 开启时 local=0，Paddle 关闭时 rotation=0）
            effective_angle = rotation_angle or local_rotation_angle

            logger.debug(
                f"[旋转角度] 页面 {page_idx} | "
                f"Paddle: {rotation_angle}° | 本地: {local_rotation_angle}° | 有效: {effective_angle}°"
            )

            if effective_angle != 0:
                rotation_angles[page_idx] = effective_angle
                logger.info(f"[旋转角度] 页面 {page_idx} 检测到旋转角度: {effective_angle}°")

        if rotation_angles:
            logger.info(f"[旋转角度] 获取页面旋转角度映射: {rotation_angles}")
        else:
            logger.debug(f"[旋转角度] 所有页面无旋转")

        return rotation_angles
    
    def _detect_cross_page_table(
        self,
        parse_results: List[Any],
        file_index: int,
        page_idx: int
    ) -> Optional[List[int]]:
        """
        检测跨页表格并返回所有相关页面
        
        当表格跨页时，MinerU 会将内容合并到第一页，后续页面标记为 lines_deleted。
        此方法检测这种情况并返回所有相关页码。
        
        Args:
            parse_results: 解析结果列表
            file_index: 文件索引
            page_idx: 当前页码
            
        Returns:
            Optional[List[int]]: 相关页码列表；如果不是跨页表格返回 None
        """
        try:
            if file_index < 0 or file_index >= len(parse_results):
                return None
            
            parse_result = parse_results[file_index]
            if page_idx < 0 or page_idx >= len(parse_result.pages):
                return None
            
            current_page = parse_result.pages[page_idx]
            
            # 检查当前页是否有跨页表格标记
            has_continuation = False
            for block in current_page.layout_blocks:
                if getattr(block, 'is_continuation', False):
                    has_continuation = True
                    break
            
            if not has_continuation:
                # 不是跨页表格的延续页
                # 但可能是跨页表格的起始页，需要向后查找
                related_pages = [page_idx]
                
                # 向后查找连续的延续页
                for next_idx in range(page_idx + 1, len(parse_result.pages)):
                    next_page = parse_result.pages[next_idx]
                    has_next_continuation = False
                    
                    for block in next_page.layout_blocks:
                        if getattr(block, 'is_continuation', False):
                            has_next_continuation = True
                            break
                    
                    if has_next_continuation:
                        related_pages.append(next_idx)
                    else:
                        break  # 不再是连续的延续页
                
                # 如果找到了延续页，返回所有相关页
                if len(related_pages) > 1:
                    logger.info(f"检测到跨页表格起始页 {page_idx}，延续到页面 {related_pages[-1]}")
                    return related_pages
                
                return None
            else:
                # 当前页是延续页，需要向前找到起始页
                logger.info(f"页面 {page_idx} 是跨页表格的延续页，向前查找起始页")
                
                # 向前查找起始页（没有 is_continuation 标记的表格页）
                start_page_idx = page_idx
                for prev_idx in range(page_idx - 1, -1, -1):
                    prev_page = parse_result.pages[prev_idx]
                    
                    # 检查前一页是否有表格
                    has_table = False
                    has_prev_continuation = False
                    
                    for block in prev_page.layout_blocks:
                        if block.category_type == 'table':
                            has_table = True
                            if getattr(block, 'is_continuation', False):
                                has_prev_continuation = True
                    
                    if has_table and not has_prev_continuation:
                        # 找到起始页
                        start_page_idx = prev_idx
                        break
                    elif has_table and has_prev_continuation:
                        # 还是延续页，继续向前找
                        start_page_idx = prev_idx
                    else:
                        # 不是表格页，停止查找
                        break
                
                # 从起始页向后收集所有相关页
                related_pages = [start_page_idx]
                for next_idx in range(start_page_idx + 1, len(parse_result.pages)):
                    next_page = parse_result.pages[next_idx]
                    has_next_continuation = False
                    
                    for block in next_page.layout_blocks:
                        if getattr(block, 'is_continuation', False):
                            has_next_continuation = True
                            break
                    
                    if has_next_continuation or next_idx == page_idx:
                        related_pages.append(next_idx)
                    else:
                        break
                
                logger.info(f"跨页表格完整页码范围: {related_pages}")
                return related_pages if len(related_pages) > 1 else None
                
        except Exception as e:
            logger.error(f"检测跨页表格失败: {e}", exc_info=True)
            return None
    
    def _get_page_bbox(
        self,
        parse_results: List[Any],
        file_index: int,
        page_idx: int
    ) -> Optional[List[float]]:
        """
        获取指定页面的表格 bbox
        
        Args:
            parse_results: 解析结果列表
            file_index: 文件索引
            page_idx: 页码
            
        Returns:
            Optional[List[float]]: bbox 坐标 [x0, y0, x1, y1]；未找到返回 None
        """
        try:
            if file_index < 0 or file_index >= len(parse_results):
                return None
            
            parse_result = parse_results[file_index]
            if page_idx < 0 or page_idx >= len(parse_result.pages):
                return None
            
            page = parse_result.pages[page_idx]
            
            # 查找表格块的 bbox
            for block in page.layout_blocks:
                if block.category_type == 'table':
                    # 兼容处理：支持 bbox 为对象或列表
                    if hasattr(block.bbox, 'x0'):
                        return [block.bbox.x0, block.bbox.y0, block.bbox.x1, block.bbox.y1]
                    elif isinstance(block.bbox, (list, tuple)) and len(block.bbox) == 4:
                        return list(block.bbox)
            
            # 如果没找到表格块，尝试从 contents 中找
            for content in page.contents:
                if content.type == 'table' and hasattr(content, 'bbox') and content.bbox:
                    if hasattr(content.bbox, 'x0'):
                        return [content.bbox.x0, content.bbox.y0, content.bbox.x1, content.bbox.y1]
                    elif isinstance(content.bbox, (list, tuple)) and len(content.bbox) == 4:
                        return list(content.bbox)
            
            logger.warning(f"页面 {page_idx} 未找到表格 bbox")
            return None
            
        except Exception as e:
            logger.error(f"获取页面 bbox 失败: {e}", exc_info=True)
            return None


# ============ 单例获取函数 ============


def get_extraction_service() -> ExtractionService:
    """
    获取ExtractionService单例
    
    Returns:
        ExtractionService: 服务实例
    """
    global _extraction_service_instance
    if _extraction_service_instance is None:
        _extraction_service_instance = ExtractionService()
        logger.debug("创建ExtractionService单例")
    return _extraction_service_instance

