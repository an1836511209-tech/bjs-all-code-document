"""
字段审核服务

实现字段审核的主流程：
1. 根据audit_type查找规则配置
2. 解析用户附件（检查哈希是否已解析过）
3. 如果未解析，则走字段提取和溯源流程
4. 遍历审核规则，构建LLM请求参数
5. 调用LLM审核agent
6. 封装返回结果
"""

import asyncio
import difflib
import json
import re
import time
import uuid
from typing import List, Dict, Any, Optional, Set, Tuple
from loguru import logger

from config.llm_config import LLMConfig
from config.env_config import get_current_env
from src.services.llm.client import LLMClient, AuditAgent
from src.services.rule_config_service import RuleConfigService
from src.services.extraction.service import ExtractionService
from src.services.classification_service import classification_service
from src.services.task_store import get_task_store
from src.utils.cache_policy import is_cacheable_extraction_result
from src.schemas.task import TaskType, TaskStatus
from src.schemas.audit import (
    AuditRequest,
    AuditData,
    AuditRuleResult,
    AuditSummary,
    AuditResult as AuditResultEnum,
    AuditStatus,
    AuditType as AuditTypeEnum,
    RelatedFieldInfo,
    UploadedFileInfo,
    ConfirmedField,
    AuditFileInput,
    AuditPointDetail
)
from src.schemas.extraction import ExtractionRequest, ExtractionFileInput, FieldExtractionResult
from src.schemas.file import FILE_TYPE_LABELS, LABEL_TO_FILE_TYPE, FileType
from src.schemas.rule_config import AuditRule, AuditType, MappingType
from src.utils.extraction_type_mapper import map_extraction_type_to_business_type
from src.utils.disclosure import DISCLOSURE_TYPES
from src.utils.file_hash import FileHasher
from src.utils.rag_handler import RagHandler
from src.utils.file_processor import download_files_and_compute_hashes
from src.utils.material_resolver import MaterialResolver
from src.utils.field_value_converter import FieldValueConverter
from src.utils.text_normalizer import normalize_for_comparison


# 全局单例实例
_audit_service_instance: Optional['AuditService'] = None


class AuditService:
    """字段审核服务"""
    
    def __init__(self):
        """初始化审核服务"""
        self.rule_service = RuleConfigService()
        
        # 使用单例ExtractionService
        from src.services.extraction.service import get_extraction_service
        self.extraction_service = get_extraction_service()
        
        self.task_store = get_task_store()
        
        # LLM配置
        self.llm_config = LLMConfig()
        self.concurrency_config = self.llm_config.get_concurrency_config()
        
        # RAG处理器（用于处理大文件审核）
        self.rag_handler = RagHandler()
    
    async def audit_fields(
        self,
        request: AuditRequest,
        enable_cache: bool = True
    ) -> AuditData:
        """
        执行字段审核
        
        主流程：
        0. 文件分类（将中台类型代码映射到系统FileType）
        1. 根据audit_type查找规则配置
        2. 计算附件哈希，尝试从缓存中获取提取结果
        3. 如果没有缓存，走一次字段提取和溯源流程
        4. 遍历审核规则，构建LLM请求参数
        5. 调用LLM审核agent
        6. 封装返回结果
        
        Args:
            request: 审核请求
            enable_cache: 是否启用缓存查询（默认True）
            
        Returns:
            AuditData: 审核响应数据
        """
        
        # 统一标准化所有文件的 URL（相对路径转完整 URL）
        # 这样后续所有模块（paddle、mineru、高亮等）都能直接使用完整 URL，避免耦合
        from src.utils.file_handler import normalize_file_url
        normalized_files = []
        # 保存原始URL和标准化URL的映射，用于返回结果时恢复相对路径
        url_mapping = {}  # {normalized_url: original_url}
        
        for file_input in request.files:
            original_url = file_input.file_url
            normalized_url = normalize_file_url(original_url)
            if original_url != normalized_url:
                logger.debug(f"文件 URL 标准化: {original_url[:80]}... -> {normalized_url[:80]}...")
                url_mapping[normalized_url] = original_url
            else:
                # 即使没有变化，也记录映射（保持一致性）
                url_mapping[normalized_url] = original_url
            
            # 创建新的对象，使用标准化后的 URL
            normalized_file = AuditFileInput(
                file_url=normalized_url,
                file_name=file_input.file_name,
                file_type=file_input.file_type,
                file_content_hash=file_input.file_content_hash,
                file_size=file_input.file_size
            )
            normalized_files.append(normalized_file)
        
        # 替换 request.files 为标准化后的文件列表
        request.files = normalized_files
        logger.info(f"已标准化 {len(normalized_files)} 个文件的 URL")
        
        # 生成任务ID（在信号量之前就需要知道 task_id）
        task_id = request.task_id or request.request_id
        
        # 如果任务已在 endpoint 层创建，先设置初始状态消息
        if task_id:
            # 先将任务状态更新为 PROCESSING（这样才能被正确统计）
            await self.task_store.update_task(
                task_id, 
                status=TaskStatus.PROCESSING,
                progress=0.0,
                status_message="等待处理"
                # 不需要 clear_result/clear_error_message，已在 endpoint 层的 reset_if_exists 中处理
            )
            
            # 获取当前正在处理的任务数（PROCESSING 状态，包括等待信号量和正在执行的）
            from config.api_config import get_rate_limit_config
            processing_count = await self.task_store.get_processing_count(task_type=TaskType.AUDIT)
            max_concurrent = get_rate_limit_config().get_limit("audit_sync")
            # 排队数 = 正在处理的任务数 - 最大并发数（超出并发限制的部分就是在排队）
            queue_count = max(0, processing_count - max_concurrent)
            
            if queue_count > 0:
                status_msg = f"当前有 {queue_count} 个助审任务排队等待处理，请您稍作等候，系统将按照顺序自动启动任务处理。"
                await self.task_store.update_task(
                    task_id,
                    status_message=status_msg
                )
                
        # 获取限流信号量（确保在实际处理生命周期内持有）
        from src.api.v1.middleware.rate_limiter import rate_limit_context
        
        # 根据是否启用流式来选择不同的信号量
        # 注意：同步接口使用 audit_sync，流式接口在各自的方法中管理
        endpoint_name = "audit_sync"
        
        async with rate_limit_context(endpoint_name):
            from src.services.llm.token_usage import token_usage_scope

            with token_usage_scope("审核", task_id):
                start_time = time.time()
                
                # 0. 文件分类：将中台类型代码映射到系统FileType，同时缓存解析结果
                logger.info("开始文件分类，将中台类型映射到系统FileType")
                # 更新状态消息
                if task_id:
                    await self.task_store.update_task(
                        task_id,
                        status=TaskStatus.PROCESSING,
                        status_message="正在分类文件..."
                    )
                
                parsed_files_cache = await self._classify_files(request)
                
                # task_id 已在方法开头生成
                # task_id = request.task_id or request.request_id
                task_created = False
                
                # 确保文件有 content_hash（用于准确的缓存命中）
                files_with_hash = list(request.files)
                all_have_hash = all(
                    hasattr(f, 'file_content_hash') and f.file_content_hash
                    for f in files_with_hash
                )
                
                # 存储已下载的文件内容缓存（用于传递给提取服务，避免重复下载）
                downloaded_files_cache: Dict[str, bytes] = {}
                
                # 如果有文件没有哈希，需要先下载文件并计算哈希
                if not all_have_hash and enable_cache:
                    logger.info("部分文件没有 content_hash，开始下载文件并计算哈希用于缓存查询")
                    # 使用公共的文件处理方法（AuditFileInput 已在文件顶部导入）
                    files_with_hash, downloaded_files_cache = await download_files_and_compute_hashes(
                        request.files,
                        AuditFileInput
                    )
                    logger.info(f"文件哈希计算完成，已下载 {len(downloaded_files_cache)} 个文件")
                
                # 计算附件哈希（用于缓存查询）
                # 使用带有 content_hash 的文件列表确保缓存一致性
                # 只基于文件内容哈希计算，与 audit_type/rule_config_id 无关
                files_hash = FileHasher.compute_files_hash(files=files_with_hash)
                
                try:
                    # 更新任务状态（任务已在 endpoint 层创建）
                    if task_id:
                        await self.task_store.create_task(
                            task_id=task_id,
                            task_type=TaskType.AUDIT,
                            context={
                                "audit_type": request.audit_type,
                                "rule_config_id": request.rule_config_id
                            }
                            # 审核任务不保存 files_hash，只有提取任务需要用于缓存
                        )
                        task_created = True
                    
                    # 1. 加载规则配置
                    # 注意：endpoint 层已提前加载并设置了 total_rules，这里主要是获取完整配置用于后续处理
                    config = await self._load_rule_config(request)
                    logger.info(f"使用规则配置: {config.id} ({config.name})")
                    
                    # 2. 获取提取结果（缓存或新提取），复用分类阶段的解析结果和已下载的文件
                    logger.info("开始获取附件提取结果")
                    if task_created and task_id:
                        await self.task_store.update_task(
                            task_id,
                            status_message="正在提取字段..."
                        )
                    extraction_results, extraction_results_list, parsed_files = await self._get_extraction_results(
                        request=request,
                        config_id=config.id,
                        enable_cache=enable_cache,
                        files_hash=files_hash,
                        parsed_files_cache=parsed_files_cache,
                        files_with_hash=files_with_hash,  # 传递带哈希的文件列表
                        downloaded_files_cache=downloaded_files_cache  # 传递已下载的文件缓存
                    )
                    logger.info(f"获取到 {len(extraction_results)} 个字段的提取结果")
                    
                    # 构建材料名称到文件类型的映射
                    material_lookup = self._build_material_lookup(request.files)
                    
                    # 解析全文所需的文件
                    parsed_files = parsed_files or {}
                    required_file_types = self._get_required_file_types(
                        audit_rules=config.audit_rules,
                        material_lookup=material_lookup,
                        parsed_files=parsed_files
                    )
                    
                    # ⭐ 预加载所有 parse_results 到内存（避免并发审核时重复从磁盘加载）
                    logger.info("预加载 parse_results 到内存以支持 RAG 检索")
                    for file_type, file_data in parsed_files.items():
                        if file_data and not file_data.get("parse_results") and file_data.get("parse_result_key"):
                            parse_result_key = file_data.get("parse_result_key")
                            
                            # 检查是否为禁用标记（_disabled后缀）
                            if parse_result_key.endswith("_disabled"):
                                logger.debug(f"二级缓存已禁用，{file_type} 的 parse_results 应已在快照中保留，跳过从磁盘加载")
                                continue
                            
                            from src.services.storage.cache_service import get_disk_cache
                            logger.debug(f"从磁盘预加载 {file_type} 的 parse_results: {parse_result_key}")
                            parse_results = await get_disk_cache().get(parse_result_key)
                            if parse_results:
                                file_data["parse_results"] = parse_results
                                logger.debug(f"已将 {file_type} 的 parse_results 加载到内存")
                    
                    missing_file_types = set()
                    for file_type in required_file_types:
                        file_data = parsed_files.get(file_type)
                        
                        # 情况1: 缓存中完全没有该文件类型
                        if not file_data:
                            missing_file_types.add(file_type)
                            continue
                        
                        # 情况2: 缓存中有，但缺少 md_content
                        md_content = file_data.get("md_content", "")
                        if not md_content:
                            missing_file_types.add(file_type)
                            continue
                        
                        # 情况3: 缓存中有内容，但缺少结构化 parse_results (或其key)，且内容较长需要 RAG
                        # 这是针对旧缓存的修复逻辑
                        if self.rag_handler.should_use_rag(len(md_content)) and not file_data.get("parse_results") and not file_data.get("parse_result_key"):
                            logger.info(f"文件类型 {file_type} 内容过长 ({len(md_content)} 字符) 且缺失结构化数据(旧缓存)，触发重新解析")
                            missing_file_types.add(file_type)
                    
                    if missing_file_types:
                        logger.info(f"检测到需要额外解析全文的文件类型: {missing_file_types}")
                        additional_parsed = await self._parse_required_files(
                            request=request,
                            missing_file_types=missing_file_types
                        )
                        
                        if additional_parsed:
                            for file_type, data in additional_parsed.items():
                                if file_type in parsed_files:
                                    existing = parsed_files[file_type]
                                    existing_names = set(existing.get("file_names", []))
                                    new_names = data.get("file_names", [])
                                    existing["file_names"] = list(existing_names.union(new_names))
                                    if not existing.get("md_content"):
                                        existing["md_content"] = data.get("md_content", "")
                                    if not existing.get("file_label"):
                                        existing["file_label"] = data.get("file_label")
                                    
                                    # 补充 parse_results (修复旧缓存缺失问题)
                                    if not existing.get("parse_results"):
                                        if data.get("parse_results"):
                                            existing["parse_results"] = data.get("parse_results")
                                            logger.info(f"已为文件类型 {file_type} 补充结构化解析数据")
                                        elif data.get("parse_result_key"):
                                            # 如果是新版缓存，补充 key
                                            existing["parse_result_key"] = data.get("parse_result_key")
                                            logger.info(f"已为文件类型 {file_type} 补充结构化解析 Key: {data.get('parse_result_key')}")
                                else:
                                    parsed_files[file_type] = data
                        else:
                            logger.warning("未能解析缺失的全文文件，将以空内容继续审核")
                    else:
                        logger.info("无需额外解析文件，复用提取阶段的解析结果")
                    
                    # 3. 构建用户确认字段映射
                    confirmed_fields_map = self._build_confirmed_fields_map(request.confirmed_fields)
                    
                    # 4. 审核所有规则
                    logger.info(f"开始审核 {len(config.audit_rules)} 个规则")
                    if task_created and task_id:
                        await self.task_store.update_task(
                            task_id,
                            status_message="正在审核规则..."
                        )
                    audit_results = await self._audit_all_rules(
                        audit_rules=config.audit_rules,
                        extraction_results=extraction_results,
                        extraction_results_list=extraction_results_list,
                        confirmed_fields_map=confirmed_fields_map,
                        parsed_files=parsed_files,
                        material_lookup=material_lookup,
                        request=request,
                        task_id=task_id,
                        task_created=task_created
                    )
                    
                    # 5. 添加人工审核项（未被自动审核覆盖的字段）
                    logger.info("检查需人工审核的字段")
                    audit_results = self._add_manual_review_items(
                        confirmed_fields=request.confirmed_fields,
                        audit_results=audit_results,
                        extraction_results_list=extraction_results_list,
                        audit_type=request.audit_type
                    )
                    
                    # 6. 根据级联关系过滤不应显示的审核结果
                    # 例如：转让方类型为"法人"时，过滤掉"自然人"相关的字段审核结果
                    fields_to_filter = FieldValueConverter.get_fields_to_filter_by_cascade(
                        request.confirmed_fields, request.audit_type
                    )
                    if fields_to_filter:
                        original_count = len(audit_results)
                        audit_results = [
                            r for r in audit_results 
                            if r.audit_rule_name not in fields_to_filter
                        ]
                        filtered_count = original_count - len(audit_results)
                        logger.info(f"根据级联关系过滤了 {filtered_count} 个审核结果，"
                                   f"过滤的字段: {fields_to_filter}")
                    
                    # 7. 统计结果（只统计字段审核和人工审核，不统计文件审核）
                    field_audit_results = [
                        r for r in audit_results 
                        if r.audit_type in [AuditTypeEnum.FIELD_AUDIT, AuditTypeEnum.MANUAL_REVIEW]
                    ]
                    
                    passed_count = sum(1 for r in field_audit_results if r.audit_result == AuditResultEnum.PASSED)
                    failed_count = sum(1 for r in field_audit_results if r.audit_result == AuditResultEnum.FAILED)
                    pending_count = sum(1 for r in field_audit_results if r.audit_result == AuditResultEnum.PENDING)
                    manual_review_count = sum(1 for r in field_audit_results if r.audit_result == AuditResultEnum.MANUAL_REVIEW)
                    
                    summary = AuditSummary(
                        total=len(field_audit_results),
                        passed=passed_count,
                        failed=failed_count,
                        pending=pending_count,
                        manual_review=manual_review_count
                    )
                    
                    processing_time = int((time.time() - start_time) * 1000)

                    if get_current_env() == 'dev':
                        logger.info(
                            f"审核结果汇总: task_id={task_id}, "
                            f"request_id={request.request_id}, "
                            f"summary={summary.model_dump()}, "
                            f"processing_time_ms={processing_time}"
                        )
                    
                    response = AuditData(
                        request_id=request.request_id or task_id or f"req_{int(time.time() * 1000)}",
                        task_id=task_id if task_created else None,
                        status="completed",
                        audit_type=request.audit_type,
                        confirmed_fields=request.confirmed_fields,
                        audit_results=audit_results,
                        summary=summary,
                        processing_time_ms=processing_time,
                        trigger_type=request.trigger_type
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
                    logger.error(f"字段审核失败: {e}", exc_info=True)
                    
                    # 更新任务状态为失败
                    if task_created and task_id:
                        await self.task_store.update_task(
                            task_id,
                            status=TaskStatus.FAILED,
                            error_message=str(e)
                        )
                    
                    raise
    
    async def _classify_files(self, request: AuditRequest) -> Dict[str, Any]:
        """
        对请求中的文件进行分类，将中台类型代码映射到系统FileType
        
        优化策略：
        1. 先处理可直接映射的文件（快速通道）
        2. 批量解析需要LLM分类的文件
        3. 并行调用LLM进行分类
        
        Args:
            request: 审核请求（会直接修改request.files中的file_type）
            
        Returns:
            Dict[str, Any]: 已解析文件的缓存字典，key为file_url，value为parse_result
                用于后续提取阶段复用，避免重复解析
        """
        from src.services.classification_service import FileClassificationService
        
        # 第一阶段：快速处理可直接映射的文件
        files_need_llm = []  # 需要LLM分类的文件列表
        
        for file_input in request.files:
            original_type = file_input.file_type
            
            # 检查是否已经是有效的系统FileType
            try:
                FileType(original_type)
                logger.info(f"文件 {file_input.file_name} 类型已是系统FileType: {original_type}")
                continue
            except ValueError:
                # 不是系统FileType，需要分类
                logger.info(f"文件 {file_input.file_name} 需要分类，原始类型: {original_type}")
            
            # 检查是否需要LLM分类（一对多关系，如QTWJ）
            require_llm = original_type in FileClassificationService.REQUIRE_LLM_CLASSIFICATION
            
            if require_llm:
                logger.info(f"文件 {file_input.file_name} 的中台类型 {original_type} 需要LLM智能分类")
                files_need_llm.append(file_input)
            else:
                # 先尝试直接映射（快速路径）
                classification_result = await classification_service.classify_file(
                    file_name=file_input.file_name,
                    original_type_code=original_type,
                    file_content=None
                )
                
                # 如果直接映射或文件名关键词分类成功，使用分类结果
                if classification_result["method"] in ["direct_mapping", "filename_keyword"]:
                    classified_type = classification_result["file_type"]
                    file_input.file_type = classified_type
                    method_name = "直接映射" if classification_result["method"] == "direct_mapping" else "文件名关键词"
                    logger.info(
                        f"文件 {file_input.file_name} {method_name}成功: "
                        f"{original_type} -> {classified_type}"
                    )
                else:
                    # 无法直接映射或文件名分类，需要LLM分类
                    files_need_llm.append(file_input)
        
        # 第二阶段：批量解析需要LLM分类的文件
        # 用于缓存已解析的文件，避免后续重复解析
        parsed_files_cache = {}
        
        if not files_need_llm:
            logger.info("没有需要LLM分类的文件")
            return parsed_files_cache
        
        logger.info(f"批量解析 {len(files_need_llm)} 个需要LLM分类的文件")
        
        # 并行解析所有需要分类的文件
        async def parse_file_for_classification(file_input):
            """解析单个文件"""
            try:
                # 使用文件当前的类型（如果已分类）或默认类型
                # 如果 file_input.file_type 已经是有效的 FileType，使用它；否则使用默认类型
                try:
                    current_file_type = FileType(file_input.file_type) if isinstance(file_input.file_type, str) else file_input.file_type
                except (ValueError, AttributeError):
                    # 如果无法转换，使用默认类型
                    current_file_type = FileType.INFO_DISCLOSURE_APPLICATION
                
                extraction_file_input = ExtractionFileInput(
                    file_url=file_input.file_url,
                    file_name=file_input.file_name,
                    file_type=current_file_type
                )
                
                # _parse_single_file 返回元组: (parse_result, pdf_content)
                parse_result_tuple = await self.extraction_service._parse_single_file(extraction_file_input)
                parse_result, pdf_content = parse_result_tuple
                
                # 调试日志：检查解析结果
                logger.debug(f"文件 {file_input.file_name} 解析返回: parse_result={type(parse_result).__name__}, "
                            f"has_md_content={hasattr(parse_result, 'md_content') if parse_result else 'N/A'}")
                
                if parse_result and hasattr(parse_result, 'md_content'):
                    md_content = parse_result.md_content
                    if md_content:
                        logger.info(f"文件 {file_input.file_name} 解析成功，内容长度: {len(md_content)}")
                        return {
                            "file_input": file_input,
                            "file_content": md_content,
                            "parse_result": parse_result,  # 保存完整的解析结果用于缓存
                            "success": True
                        }
                    else:
                        logger.warning(f"文件 {file_input.file_name} 解析成功但 md_content 为空")
                        return {
                            "file_input": file_input,
                            "file_content": None,
                            "parse_result": None,
                            "success": False
                        }
                else:
                    # 详细记录失败原因
                    if parse_result is None:
                        reason = "parse_result 为 None"
                    elif not hasattr(parse_result, 'md_content'):
                        available_attrs = [attr for attr in dir(parse_result) if not attr.startswith('_')]
                        reason = f"parse_result 类型为 {type(parse_result).__name__}，没有 md_content 属性，可用属性: {available_attrs[:5]}"
                    else:
                        reason = "未知原因"
                    logger.warning(f"文件 {file_input.file_name} 解析失败: {reason}")
                    return {
                        "file_input": file_input,
                        "file_content": None,
                        "parse_result": None,
                        "success": False
                    }
            except Exception as e:
                logger.error(f"文件 {file_input.file_name} 解析异常: {e}", exc_info=True)
                return {
                    "file_input": file_input,
                    "file_content": None,
                    "parse_result": None,
                    "success": False,
                    "error": str(e)
                }
        
        # 并行解析所有文件
        parse_tasks = [parse_file_for_classification(f) for f in files_need_llm]
        parse_results = await asyncio.gather(*parse_tasks, return_exceptions=True)
        
        # 保存解析结果到缓存（按 file_url 索引）
        for result in parse_results:
            if not isinstance(result, Exception) and result.get("success") and result.get("parse_result"):
                file_url = result["file_input"].file_url
                parsed_files_cache[file_url] = result["parse_result"]
                logger.debug(f"已缓存文件解析结果: {file_url}")
        
        # 第三阶段：并行调用LLM进行分类
        logger.info(f"并行调用LLM分类 {len(parse_results)} 个文件")
        
        # 创建分类任务
        async def classify_single_file(parse_result):
            """分类单个文件"""
            if isinstance(parse_result, Exception):
                logger.error(f"解析任务异常: {parse_result}")
                return None
            
            file_input = parse_result["file_input"]
            file_content = parse_result["file_content"]
            original_type = file_input.file_type
            
            try:
                classification_result = await classification_service.classify_file(
                    file_name=file_input.file_name,
                    original_type_code=original_type,
                    file_content=file_content
                )
                
                return {
                    "file_input": file_input,
                    "original_type": original_type,
                    "classification_result": classification_result,
                    "success": True
                }
            except Exception as e:
                logger.error(f"文件 {file_input.file_name} LLM分类异常: {e}", exc_info=True)
                return {
                    "file_input": file_input,
                    "original_type": original_type,
                    "success": False,
                    "error": str(e)
                }
        
        # 使用信号量控制并发数
        max_workers = self.concurrency_config.classification_workers
        semaphore = asyncio.Semaphore(max_workers)
        
        async def classify_with_semaphore(parse_result):
            async with semaphore:
                return await classify_single_file(parse_result)
        
        # 并行分类
        classification_tasks = [classify_with_semaphore(r) for r in parse_results]
        classification_results = await asyncio.gather(*classification_tasks, return_exceptions=True)
        
        # 第四阶段：更新文件类型
        for result in classification_results:
            if isinstance(result, Exception):
                logger.error(f"分类任务异常: {result}")
                continue
            
            if not result or not result.get("success"):
                continue
            
            file_input = result["file_input"]
            original_type = result["original_type"]
            classification_result = result["classification_result"]
            
            classified_type = classification_result["file_type"]
            file_input.file_type = classified_type
            
            logger.info(
                f"文件 {file_input.file_name} LLM分类完成: "
                f"{original_type} -> {classified_type} "
                f"(方法: {classification_result['method']}, "
                f"置信度: {classification_result['confidence']}, "
                f"原因: {classification_result.get('reason', '未提供')})"
            )
        
        logger.info(f"文件分类完成，共处理 {len(files_need_llm)} 个文件")
        logger.info(f"已缓存 {len(parsed_files_cache)} 个文件的解析结果，可复用于提取阶段")
        
        return parsed_files_cache
    
    async def _load_rule_config(self, request: AuditRequest):
        """加载规则配置"""
        if request.audit_type in DISCLOSURE_TYPES:
            raise ValueError(f"{request.audit_type}仅支持辅助录入")
        if request.rule_config_id:
            logger.info(f"加载规则配置: {request.rule_config_id}")
            config = self.rule_service.get_config(request.rule_config_id)
            if not config:
                raise ValueError(f"规则配置不存在: {request.rule_config_id}")
            if config.business_type in DISCLOSURE_TYPES:
                raise ValueError(f"规则配置 {config.id} 仅支持辅助录入")
            return config
        else:
            # 根据audit_type查找默认规则配置
            logger.info(f"未提供rule_config_id，尝试根据audit_type查找默认规则: {request.audit_type}")
            business_type = map_extraction_type_to_business_type(request.audit_type)
            
            if business_type is None:
                raise ValueError(
                    f"无法识别的audit_type: {request.audit_type}。"
                    f"支持的类型: 有纸大宗实物, 无纸大宗实物, 有纸小宗实物, 无纸小宗实物"
                )
            
            config = self.rule_service.get_default_config_by_business_type(business_type)
            
            if config is None:
                raise ValueError(
                    f"未找到业务类型 '{business_type.value}' 的启用规则配置。"
                    f"请先在规则配置管理中创建并启用对应的规则配置，或者显式提供rule_config_id参数。"
                )
            
            return config
    
    async def _get_extraction_results(
        self,
        request: AuditRequest,
        config_id: str,
        enable_cache: bool,
        files_hash: Optional[str],
        parsed_files_cache: Optional[Dict[str, Any]] = None,
        files_with_hash: Optional[List[Any]] = None,
        downloaded_files_cache: Optional[Dict[str, bytes]] = None
    ) -> Tuple[Dict[str, Any], List[FieldExtractionResult], Dict[str, Any]]:
        """
        获取提取结果（缓存或新提取）
        
        Args:
            request: 审核请求
            config_id: 规则配置ID
            enable_cache: 是否启用缓存
            files_hash: 文件哈希
            parsed_files_cache: 预解析的文件缓存（来自分类阶段），避免重复解析
            files_with_hash: 带有 content_hash 的文件列表（用于提取服务）
            downloaded_files_cache: 已下载的文件内容缓存（用于传递给提取服务，避免重复下载）
            
        Returns:
            Tuple: (提取字段结果, 完整提取结果列表, 解析文件快照)
                - 提取字段结果: {field_name: {source_file_type: {"value": str, ...}}}（用于LLM审核）
                - 完整提取结果列表: List[FieldExtractionResult]（用于嵌入审核返回）
                - 解析文件快照: {file_type: {"file_names": [...], "file_label": str, "md_content": str}}
        """
        # 尝试从缓存中获取提取结果
        if enable_cache and files_hash:
            cached_task = await self.task_store.find_task_by_files_hash(
                files_hash=files_hash,
                only_completed=True
            )
            
            if cached_task and cached_task.result:
                cached_result = cached_task.result if isinstance(cached_task.result, dict) else {}
                if not is_cacheable_extraction_result(cached_result):
                    logger.info(
                        f"找到历史提取任务 {cached_task.task_id}，"
                        f"但提取质量未达缓存阈值 (success+pending > failed)，跳过缓存复用"
                    )
                else:
                    logger.info(f"找到缓存的提取结果，任务ID: {cached_task.task_id}")
                    parsed_results = self._parse_extraction_result(cached_result)
                    parsed_files = cached_result.get("parsed_files") or {}

                    # 从缓存结果中恢复 FieldExtractionResult 列表
                    results_list = []
                    results_data = cached_result.get("results", [])
                    for result_dict in results_data:
                        try:
                            results_list.append(FieldExtractionResult(**result_dict))
                        except Exception as e:
                            logger.warning(f"解析缓存的提取结果失败: {e}")

                    return parsed_results, results_list, parsed_files
        
        # 没有缓存，执行新的提取
        if parsed_files_cache:
            logger.info(f"没有缓存的提取结果，执行新的提取（复用已解析的 {len(parsed_files_cache)} 个文件）")
        else:
            logger.info("没有缓存的提取结果，执行新的提取")
        
        # 使用带哈希的文件列表（如果有的话）
        files_to_use = files_with_hash if files_with_hash else request.files
        
        # 生成用于内部提取的唯一任务ID
        # 这确保提取结果能被正确缓存，供后续请求复用
        import uuid
        internal_task_id = f"extraction_internal_{uuid.uuid4().hex[:16]}"
        
        extraction_request = ExtractionRequest(
            task_id=internal_task_id,  # 传递任务ID以确保 files_hash 被保存
            extraction_type=request.audit_type,
            files=[
                ExtractionFileInput(
                    file_url=f.file_url,
                    file_name=f.file_name,
                    file_type=f.file_type,
                    file_content_hash=getattr(f, 'file_content_hash', None),
                    file_size=getattr(f, 'file_size', None)
                )
                for f in files_to_use
            ],
            rule_config_id=config_id
        )
        
        extraction_data = await self.extraction_service.extract_fields(
            request=extraction_request,
            enable_cache=enable_cache,
            parsed_files_cache=parsed_files_cache,
            downloaded_files_cache=downloaded_files_cache  # 复用已下载的文件，避免重复下载
        )
        
        raw_data = extraction_data.model_dump()
        parsed_results = self._parse_extraction_result(raw_data)
        parsed_files = raw_data.get("parsed_files") or extraction_data.parsed_files or {}
        
        # 直接使用 extraction_data.results，这已经是 List[FieldExtractionResult]
        results_list = extraction_data.results if extraction_data.results else []
        
        return parsed_results, results_list, parsed_files
    
    def _parse_extraction_result(self, extraction_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析提取结果为便于审核使用的格式
        
        Args:
            extraction_result: 提取结果（ExtractionData的dict形式）
            
        Returns:
            Dict: {
                field_name: {
                    source_file_type: {
                        "value": extracted_value,
                        "source_file_name": file_name
                    }
                }
            }
        """
        parsed = {}
        
        results = extraction_result.get("results", [])
        for field_result in results:
            field_name = field_result.get("field_name")
            values = field_result.get("values", [])
            
            field_data = {}
            for value in values:
                source_file_type = value.get("source_file_type")
                extracted_value = value.get("extracted_value")
                source_file_name = value.get("source_file_name")
                
                field_data[source_file_type] = {
                    "value": extracted_value,
                    "source_file_name": source_file_name
                }
            
            parsed[field_name] = field_data
        
        logger.debug(f"解析提取结果: {list(parsed.keys())}")
        return parsed
    
    def _build_confirmed_fields_map(self, confirmed_fields: List) -> Dict[str, Any]:
        """构建用户确认字段映射（使用工具类）"""
        return FieldValueConverter.build_confirmed_fields_map(confirmed_fields)
    
    def _convert_field_value_to_string(self, value: Any) -> str:
        """将字段值转换为字符串（使用工具类）"""
        return FieldValueConverter.convert_field_value_to_string(value)

    def _normalize_material_name(self, name: Optional[str]) -> str:
        """规范化材料名称（使用工具类）"""
        return MaterialResolver.normalize_material_name(name)

    def _build_material_lookup(self, files: List[AuditFileInput]) -> Dict[str, str]:
        """构建材料名称到文件类型的映射（使用工具类）"""
        return MaterialResolver.build_material_lookup(files)

    def _get_file_label(self, file_type: Optional[str]) -> str:
        """根据文件类型获取展示名称（使用工具类）"""
        return MaterialResolver.get_file_label(file_type)

    def _resolve_file_type(
        self,
        material_name: Optional[str],
        material_lookup: Dict[str, str],
        parsed_files: Dict[str, Any]
    ) -> Optional[str]:
        """根据材料名称解析对应的文件类型（使用工具类）"""
        return MaterialResolver.resolve_file_type(material_name, material_lookup, parsed_files)

    def _get_display_name(
        self,
        material_name: Optional[str],
        file_type: Optional[str],
        file_data: Optional[Dict[str, Any]]
    ) -> str:
        """获取用于展示的材料名称（使用工具类）"""
        return MaterialResolver.get_display_name(material_name, file_type, file_data)

    def _get_required_file_types(
        self,
        audit_rules: List[AuditRule],
        material_lookup: Dict[str, str],
        parsed_files: Dict[str, Any]
    ) -> Set[str]:
        """获取需要解析全文的文件类型集合"""
        required: Set[str] = set()

        for rule in audit_rules:
            if not rule.enabled:
                continue

            if rule.audit_type == AuditType.FILE_AUDIT:
                if rule.audit_data_sources:
                    for ds in rule.audit_data_sources:
                        file_type = self._resolve_file_type(ds.material_name, material_lookup, parsed_files)
                        if file_type:
                            required.add(file_type)

            if rule.audit_type == AuditType.FIELD_AUDIT and rule.mapping_type == MappingType.MANUAL:
                if rule.audit_data_sources:
                    for ds in rule.audit_data_sources:
                        if ds.field_name:
                            continue
                        file_type = self._resolve_file_type(ds.material_name, material_lookup, parsed_files)
                        if file_type:
                            required.add(file_type)

        return required

    async def _parse_required_files(
        self,
        request: AuditRequest,
        missing_file_types: Set[str]
    ) -> Dict[str, Any]:
        """按需解析缺失的文件类型，复用提取服务的解析能力"""
        if not missing_file_types:
            return {}

        files_to_parse: List[ExtractionFileInput] = []
        for file_input in request.files:
            file_type_value = file_input.file_type.value if isinstance(file_input.file_type, FileType) else str(file_input.file_type)
            if file_type_value in missing_file_types:
                files_to_parse.append(
                    ExtractionFileInput(
                        file_url=file_input.file_url,
                        file_name=file_input.file_name,
                        file_type=file_input.file_type
                    )
                )

        if not files_to_parse:
            logger.warning("缺失的文件类型在请求中不存在，无法解析")
            return {}

        logger.info(f"按需解析 {len(files_to_parse)} 个文件用于全文审核: {missing_file_types}")
        parsed_raw = await self.extraction_service._parse_files(files_to_parse)
        
        # 使用异步构建快照
        snapshot = await self.extraction_service.build_parsed_files_snapshot_async(parsed_raw)

        return {file_type: snapshot[file_type] for file_type in snapshot if file_type in missing_file_types}
    
    async def _audit_all_rules(
        self,
        audit_rules: List[AuditRule],
        extraction_results: Dict[str, Any],
        extraction_results_list: List[FieldExtractionResult],
        confirmed_fields_map: Dict[str, Any],
        parsed_files: Dict[str, Any],
        material_lookup: Dict[str, str],
        request: AuditRequest,
        task_id: Optional[str] = None,
        task_created: bool = False
    ) -> List[AuditRuleResult]:
        """
        审核所有规则
        
        使用并发方式审核多个规则，并实时更新任务进度
        """
        # 筛选启用的规则
        enabled_rules = [rule for rule in audit_rules if rule.enabled]
        total_rules = len(enabled_rules)
        
        if total_rules == 0:
            return []
        
        # 创建审核任务列表
        tasks = []
        
        for rule in enabled_rules:
            task = self._audit_single_rule(
                rule=rule,
                extraction_results=extraction_results,
                extraction_results_list=extraction_results_list,
                confirmed_fields_map=confirmed_fields_map,
                parsed_files=parsed_files,
                material_lookup=material_lookup,
                request=request
            )
            tasks.append(task)
        
        # 并发执行，限制并发数，同时追踪完成进度
        semaphore = asyncio.Semaphore(self.concurrency_config.audit_workers)
        
        async def bounded_task(idx: int, task):
            """包装任务，返回索引和结果"""
            async with semaphore:
                result = await task
                return idx, result
        
        # 创建带索引的任务
        bounded_tasks = [
            bounded_task(idx, task) 
            for idx, task in enumerate(tasks)
        ]
        
        # 使用 as_completed 追踪任务完成情况
        results = [None] * total_rules  # 预分配结果列表
        completed_count = 0
        
        # 逐个等待任务完成，实时更新进度
        for coro in asyncio.as_completed(bounded_tasks):
            # 检查任务是否已取消
            if task_created and task_id:
                from src.services.redis.task_cancel_subscriber import get_task_cancel_subscriber
                if get_task_cancel_subscriber().is_cancelled(task_id):
                    logger.warning(f"检测到任务取消信号: {task_id}")
                    raise asyncio.CancelledError("任务已取消")
            
            idx, result = await coro
            results[idx] = result
            completed_count += 1
            
            # 更新任务进度
            if task_created and task_id:
                progress = completed_count / total_rules
                await self.task_store.update_task(
                    task_id, 
                    progress=progress,
                    status_message="正在审核规则..."
                )
                logger.debug(f"审核进度更新: {completed_count}/{total_rules} ({progress:.2%})")
        
        return results
    
    async def _audit_single_rule(
        self,
        rule: AuditRule,
        extraction_results: Dict[str, Any],
        extraction_results_list: List[FieldExtractionResult],
        confirmed_fields_map: Dict[str, Any],
        parsed_files: Dict[str, Any],
        material_lookup: Dict[str, str],
        request: AuditRequest
    ) -> AuditRuleResult:
        """
        审核单个规则
        
        核心逻辑：
        1. 根据audit_type、mapping_type构建audit_data_sources（描述性）和reference_materials（实际内容）
        2. 预检查审核条件，如果不满足则直接返回待确认结果，跳过LLM调用
        3. 如果启用简单对比模式，直接进行字符串对比；否则调用LLM审核
        4. 调用LLM审核（如果满足条件）
        5. 封装结果
        """
        try:
            logger.info(f"审核规则: {rule.field_name} (简单对比模式: {rule.use_simple_comparison})")
            
            # 1. 构建审核数据源（描述性）和参考材料（实际内容）
            audit_data_sources = []  # 改为列表，只描述数据源
            reference_materials = {}  # 实际数据内容
            
            if rule.audit_type == AuditType.FIELD_AUDIT:
                # 字段审核
                if rule.mapping_type == MappingType.AUTO:
                    # 自动映射：从提取结果中根据source_field_name获取
                    source_field_name = rule.source_field_name
                    if source_field_name and source_field_name in extraction_results:
                        field_data = extraction_results[source_field_name]
                        for source_type, data in field_data.items():
                            file_name = data['source_file_name']
                            # audit_data_sources：只描述数据源
                            audit_data_sources.append(f"{file_name} - {source_field_name}")
                            # reference_materials：实际内容
                            key = f"{file_name} - {source_field_name}"
                            reference_materials[key] = data["value"]
                else:
                    # 自定义映射：根据audit_data_sources配置获取
                    if rule.audit_data_sources:
                        for ds in rule.audit_data_sources:
                            material_name = ds.material_name
                            field_name = ds.field_name
                            
                            if field_name:
                                # 字段值：从提取结果获取
                                if field_name in extraction_results:
                                    field_data = extraction_results[field_name]
                                    for source_type, data in field_data.items():
                                        # audit_data_sources：只描述
                                        audit_data_sources.append(f"{material_name} - {field_name}")
                                        # reference_materials：实际内容
                                        key = f"{material_name} - {field_name}"
                                        reference_materials[key] = data["value"]
                                else:
                                    logger.warning(f"未找到字段提取结果: {field_name}")
                            else:
                                # 全文：从parsed_files获取
                                file_type = self._resolve_file_type(material_name, material_lookup, parsed_files)
                                file_data = parsed_files.get(file_type) if file_type else None

                                if file_data and file_data.get("md_content"):
                                    display_name = self._get_display_name(material_name, file_type, file_data)
                                    key = f"{display_name} - 全文"
                                    audit_data_sources.append(key)
                                    
                                    # === RAG 处理（字段审核-全文模式）===
                                    md_content = file_data.get("md_content", "")
                                    if self.rag_handler.should_use_rag(len(md_content)):
                                        logger.info(f"审核全文内容过长 ({len(md_content)} 字符)，启用 RAG 检索")
                                        
                                        # 获取 parse_results（应该已经预加载到内存）
                                        parse_results = file_data.get("parse_results")
                                        if not parse_results:
                                            logger.warning(f"parse_results 未找到（文件类型: {file_type}），RAG 检索可能失败")
                                        
                                        # 使用审核规则的字段名和审核内容作为查询
                                        query = f"{rule.field_name} {rule.audit_content}"
                                        md_content, _ = await self.rag_handler.get_relevant_content(
                                            parse_results, query
                                        )
                                        logger.info(f"RAG 检索后内容长度: {len(md_content)} 字符")
                                    # =====================================
                                    
                                    reference_materials[key] = md_content
                                else:
                                    logger.warning(f"未找到全文解析内容: material={material_name}, file_type={file_type}")
                
                # 是否包含用户输入
                user_input_value = None
                if rule.include_user_input and rule.field_name in confirmed_fields_map:
                    user_input_value = confirmed_fields_map[rule.field_name]
                    # 转换为字符串（支持各种 JSON 类型）
                    user_input_value = self._convert_field_value_to_string(user_input_value)
            
            else:
                # 文件审核：根据audit_data_sources获取全文
                user_input_value = None
                if rule.audit_data_sources:
                    for ds in rule.audit_data_sources:
                        material_name = ds.material_name
                        file_type = self._resolve_file_type(material_name, material_lookup, parsed_files)
                        file_data = parsed_files.get(file_type) if file_type else None

                        if file_data and file_data.get("md_content"):
                            display_name = self._get_display_name(material_name, file_type, file_data)
                            key = f"{display_name} - 全文"
                            audit_data_sources.append(key)
                            
                            # === RAG 处理（文件审核）===
                            md_content = file_data.get("md_content", "")
                            if self.rag_handler.should_use_rag(len(md_content)):
                                logger.info(f"文件审核内容过长 ({len(md_content)} 字符)，启用 RAG 检索")
                                
                                # 获取 parse_results（应该已经预加载到内存）
                                parse_results = file_data.get("parse_results")
                                if not parse_results:
                                    logger.warning(f"parse_results 未找到（文件类型: {file_type}），RAG 检索可能失败")
                                
                                # 使用审核内容作为查询（文件审核通常审核特定要点）
                                query = f"{rule.field_name} {rule.audit_content}"
                                md_content, _ = await self.rag_handler.get_relevant_content(
                                    parse_results, query
                                )
                                logger.info(f"RAG 检索后内容长度: {len(md_content)} 字符")
                            # ==============================
                            
                            reference_materials[key] = md_content
                        else:
                            logger.warning(f"未找到文件审核所需的全文内容: material={material_name}, file_type={file_type}")
            
            # 2. 检查是否为"材料无值且非必填空白"的情况（仅字段审核）
            # 此检查需要在预检查之前，因为这种情况应该自动通过，而不是返回pending
            if rule.audit_type == AuditType.FIELD_AUDIT:
                # 条件：用户输入为空 且 提取数据为空
                user_input_empty = not user_input_value or not user_input_value.strip()
                
                extraction_data = self._find_extraction_data(rule.field_name, extraction_results_list)
                
                # 判断提取数据是否为空（包含三种情况）
                # 1. extraction_data 本身为 None
                # 2. extraction_data.values 为空或长度为 0
                # 3. extraction_data.values 存在但所有 extracted_value 都为空字符串
                extraction_empty = (
                    extraction_data is None or 
                    not extraction_data.values or 
                    len(extraction_data.values) == 0 or
                    all(
                        not v.extracted_value or not str(v.extracted_value).strip()
                        for v in extraction_data.values
                    )
                )
                
                if user_input_empty and extraction_empty:
                    logger.info(f"规则 {rule.field_name} 材料中无值且用户未填写，标记为待确认")
                    
                    # 构建审核规则信息
                    audit_rule_info = self._build_audit_rule_info(rule)
                    
                    return AuditRuleResult(
                        audit_id=f"audit_{uuid.uuid4().hex[:16]}",
                        audit_rule_id=getattr(rule, 'id', None),
                        audit_rule_name=rule.field_name,
                        audit_type=AuditTypeEnum.FIELD_AUDIT,
                        audit_result=AuditResultEnum.PENDING,  # 改为待确认
                        audit_status=AuditStatus.COMPLETED,
                        audit_explanation="材料中无值且用户未填写，需人工确认",
                        confidence=0.0,
                        related_fields=[RelatedFieldInfo(
                            field_name=rule.field_name,
                            field_value="",
                            field_type="text",
                            extraction_data=None
                        )],
                        audit_rule=audit_rule_info
                    )
            
            # 3. 预检查审核条件
            pre_check_result = self._pre_check_audit_conditions(
                rule=rule,
                user_input_value=user_input_value,
                reference_materials=reference_materials,
                extraction_results_list=extraction_results_list
            )
            
            if pre_check_result:
                # 如果预检查返回结果，说明不满足审核条件，直接返回
                logger.info(f"规则 {rule.field_name} 预检查未通过，跳过LLM审核")
                return pre_check_result
            
            # 4. 判断是否使用简单对比模式
            if rule.use_simple_comparison:
                # 简单对比模式：直接进行字符串对比
                comparison_result = self._simple_field_comparison(
                    user_input_value=user_input_value,
                    reference_materials=reference_materials
                )
                
                # 构建字段信息（包含完整的提取数据）
                extraction_data = self._find_extraction_data(rule.field_name, extraction_results_list)
                related_fields = [RelatedFieldInfo(
                    field_name=rule.field_name,
                    field_value=user_input_value or "",
                    field_type="text",
                    extraction_data=extraction_data
                )]
                
                # 构建审核规则信息
                audit_rule_info = self._build_audit_rule_info(rule)
                
                return AuditRuleResult(
                    audit_id=f"audit_{uuid.uuid4().hex[:16]}",
                    audit_rule_id=getattr(rule, 'id', None),
                    audit_rule_name=rule.field_name,
                    audit_type=AuditTypeEnum.FIELD_AUDIT,
                    audit_result=comparison_result["audit_result"],
                    audit_status=AuditStatus.COMPLETED,
                    audit_explanation=comparison_result["explanation"],
                    confidence=comparison_result["confidence"],
                    related_fields=related_fields,
                    audit_rule=audit_rule_info
                )
            
            # 5. 文件审核多要点处理
            if rule.audit_type == AuditType.FILE_AUDIT:
                # 拆分审核要点
                audit_points = self._split_audit_points(rule.audit_content)
                
                # 文件审核始终使用多要点处理（即使只有一个要点）
                logger.info(f"文件审核：拆分出 {len(audit_points)} 个审核要点")
                
                # 并发审核所有要点
                point_results = await self._audit_multiple_points(
                    audit_points=audit_points,
                    reference_materials=reference_materials,
                    audit_data_sources=audit_data_sources,
                    rule=rule
                )
                
                # 使用 rule.field_name 作为 file_type
                file_type = rule.field_name
                
                # 匹配已上传的文件 - 优先使用 primary_file_type 精确匹配
                uploaded_files = self._get_uploaded_files_for_rule(rule, request.files)
                
                # 构建审核规则信息
                audit_rule_info = self._build_audit_rule_info(rule)
                
                # 返回结果（audit_result、audit_explanation、confidence 都为 None）
                return AuditRuleResult(
                    audit_id=f"audit_{uuid.uuid4().hex[:16]}",
                    audit_rule_id=getattr(rule, 'id', None),
                    audit_rule_name=rule.field_name,
                    audit_type=AuditTypeEnum.FILE_AUDIT,
                    audit_result=None,  # 文件审核不使用整体结果
                    audit_status=AuditStatus.COMPLETED,
                    audit_explanation=None,  # 文件审核不使用整体说明
                    confidence=None,  # 文件审核不使用整体置信度
                    related_fields=[],  # 文件审核不关联字段
                    file_type=file_type,
                    audit_points=rule.audit_content,  # 保留原始审核内容
                    uploaded_files=uploaded_files,
                    audit_details=None,  # 废弃字段
                    audit_point_details=point_results,  # 各要点的详细结果
                    audit_rule=audit_rule_info
                )
            
            # 6. 调用LLM审核（字段审核）
            audit_config = self.llm_config.get_audit_agent_config()
            
            async with LLMClient(audit_config) as client:
                agent = AuditAgent(client)
                llm_result = await agent.audit_field(
                    audit_type=rule.audit_type.value,
                    field_name=rule.field_name,
                    audit_content=rule.audit_content,
                    auto_process_rules=rule.auto_process_rules,
                    audit_data_sources=audit_data_sources,
                    user_input_value=user_input_value,
                    reference_materials=reference_materials
                )
            
            # 7. 封装结果（仅字段审核）
            if llm_result.success:
                # 映射审核结果
                audit_result_str = llm_result.audit_result
                if audit_result_str == "通过":
                    audit_result = AuditResultEnum.PASSED
                elif audit_result_str == "不通过":
                    audit_result = AuditResultEnum.FAILED
                else:
                    audit_result = AuditResultEnum.PENDING
                
                # 构建审核规则信息
                audit_rule_info = self._build_audit_rule_info(rule)
                
                # 字段审核：构建 related_fields（包含完整的提取数据）
                extraction_data = self._find_extraction_data(rule.field_name, extraction_results_list)
                related_fields = [RelatedFieldInfo(
                    field_name=rule.field_name,
                    field_value=user_input_value or "",
                    field_type="text",
                    extraction_data=extraction_data
                )]
                
                return AuditRuleResult(
                    audit_id=f"audit_{uuid.uuid4().hex[:16]}",
                    audit_rule_id=getattr(rule, 'id', None),
                    audit_rule_name=rule.field_name,
                    audit_type=AuditTypeEnum.FIELD_AUDIT,
                    audit_result=audit_result,
                    audit_status=AuditStatus.COMPLETED,
                    audit_explanation=llm_result.audit_analysis,
                    confidence=0.9,
                    related_fields=related_fields,
                    audit_rule=audit_rule_info
                )
            else:
                # 审核失败（仅字段审核走到这里）
                extraction_data = self._find_extraction_data(rule.field_name, extraction_results_list)
                related_fields = [RelatedFieldInfo(
                    field_name=rule.field_name,
                    field_value=user_input_value or "",
                    field_type="text",
                    extraction_data=extraction_data
                )]
                
                # 构建审核规则信息
                audit_rule_info = self._build_audit_rule_info(rule)
                
                return AuditRuleResult(
                    audit_id=f"audit_{uuid.uuid4().hex[:16]}",
                    audit_rule_id=getattr(rule, 'id', None),
                    audit_rule_name=rule.field_name,
                    audit_type=AuditTypeEnum.FIELD_AUDIT,
                    audit_result=AuditResultEnum.PENDING,
                    audit_status=AuditStatus.FAILED,
                    audit_explanation=f"审核失败: {llm_result.error}",
                    confidence=0.0,
                    related_fields=related_fields,
                    audit_rule=audit_rule_info
                )
        
        except Exception as e:
            logger.error(f"审核规则 {rule.field_name} 失败: {e}", exc_info=True)
            
            # 构建审核规则信息（即使异常也要返回）
            audit_rule_info = self._build_audit_rule_info(rule)
            
            # 根据审核类型构建不同的返回结构
            if rule.audit_type == AuditType.FILE_AUDIT:
                # 文件审核异常：返回包含单个失败要点的结果
                # 使用 rule.field_name 作为 file_type
                file_type = rule.field_name
                
                # 匹配已上传的文件 - 优先使用 primary_file_type 精确匹配
                uploaded_files = self._get_uploaded_files_for_rule(rule, request.files)
                
                # 创建一个表示异常的审核要点
                error_point = AuditPointDetail(
                    point_index=1,
                    point_content=rule.audit_content or "审核要点",
                    audit_result=AuditResultEnum.PENDING,
                    audit_explanation=f"审核异常: {str(e)}",
                    confidence=0.0
                )
                
                return AuditRuleResult(
                    audit_id=f"audit_{uuid.uuid4().hex[:16]}",
                    audit_rule_id=getattr(rule, 'id', None),
                    audit_rule_name=rule.field_name,
                    audit_type=AuditTypeEnum.FILE_AUDIT,
                    audit_result=None,
                    audit_status=AuditStatus.FAILED,
                    audit_explanation=None,
                    confidence=None,
                    related_fields=[],
                    file_type=file_type,
                    audit_points=rule.audit_content,
                    uploaded_files=uploaded_files,
                    audit_details=None,
                    audit_point_details=[error_point],
                    audit_rule=audit_rule_info
                )
            else:
                # 字段审核异常
                user_input_value = None
                if rule.include_user_input and rule.field_name in confirmed_fields_map:
                    user_input_value = confirmed_fields_map[rule.field_name]
                    # 转换为字符串（支持各种 JSON 类型）
                    user_input_value = self._convert_field_value_to_string(user_input_value)
                
                extraction_data = self._find_extraction_data(rule.field_name, extraction_results_list)
                related_fields = [RelatedFieldInfo(
                    field_name=rule.field_name,
                    field_value=user_input_value or "",
                    field_type="text",
                    extraction_data=extraction_data
                )]
                
                return AuditRuleResult(
                    audit_id=f"audit_{uuid.uuid4().hex[:16]}",
                    audit_rule_id=getattr(rule, 'id', None),
                    audit_rule_name=rule.field_name,
                    audit_type=AuditTypeEnum.FIELD_AUDIT,
                    audit_result=AuditResultEnum.PENDING,
                    audit_status=AuditStatus.FAILED,
                    audit_explanation=f"审核异常: {str(e)}",
                    confidence=0.0,
                    related_fields=related_fields,
                    audit_rule=audit_rule_info
                )

    _YYZZYXQZ_LONG_TERM_SENTINEL = "2999-12-31"

    def _is_field_extraction_empty(
        self,
        field_name: str,
        extraction_results_list: List[FieldExtractionResult]
    ) -> bool:
        extraction_data = self._find_extraction_data(field_name, extraction_results_list)
        return (
            extraction_data is None
            or not extraction_data.values
            or len(extraction_data.values) == 0
            or all(
                not v.extracted_value or not str(v.extracted_value).strip()
                for v in extraction_data.values
            )
        )

    def _try_yyzzyxqz_long_term_pre_check_pass(
        self,
        rule: AuditRule,
        user_input_value: Optional[str],
        reference_materials: Dict[str, str],
        extraction_results_list: List[FieldExtractionResult]
    ) -> Optional[AuditRuleResult]:
        """YYZZYXQZ 填报长期营业期限哨兵值且材料未提取到有效期时，跳过预检查拦截。"""
        if rule.field_name != "YYZZYXQZ" or rule.audit_type != AuditType.FIELD_AUDIT:
            return None

        if not user_input_value or user_input_value.strip() != self._YYZZYXQZ_LONG_TERM_SENTINEL:
            return None

        if not self._is_field_extraction_empty(rule.field_name, extraction_results_list):
            return None

        ref_empty = (
            not reference_materials
            or all(not value or not str(value).strip() for value in reference_materials.values())
        )
        if not ref_empty:
            return None

        logger.info(
            f"规则 {rule.field_name} 填报长期营业期限哨兵值 {self._YYZZYXQZ_LONG_TERM_SENTINEL}，"
            "且参考材料未提取到有效期结束日期，跳过预检查直接通过"
        )

        extraction_data = self._find_extraction_data(rule.field_name, extraction_results_list)
        related_fields = [RelatedFieldInfo(
            field_name=rule.field_name,
            field_value=user_input_value,
            field_type="text",
            extraction_data=extraction_data
        )]
        audit_rule_info = self._build_audit_rule_info(rule)

        return AuditRuleResult(
            audit_id=f"audit_{uuid.uuid4().hex[:16]}",
            audit_rule_id=getattr(rule, 'id', None),
            audit_rule_name=rule.field_name,
            audit_type=AuditTypeEnum.FIELD_AUDIT,
            audit_result=AuditResultEnum.PASSED,
            audit_status=AuditStatus.COMPLETED,
            audit_explanation=(
                "营业执照为长期有效，填报2999-12-31且参考材料未提取到营业期限结束日期，审核通过"
            ),
            confidence=1.0,
            related_fields=related_fields,
            audit_rule=audit_rule_info
        )

    def _pre_check_audit_conditions(
        self,
        rule: AuditRule,
        user_input_value: Optional[str],
        reference_materials: Dict[str, str],
        extraction_results_list: List[FieldExtractionResult]
    ) -> Optional[AuditRuleResult]:
        """
        预检查审核条件，判断是否可以跳过LLM调用
        
        检查以下条件：
        1. 缺少参考材料
        2. 字段审核时要求用户输入但用户未提供（文件审核不检查此条件）
        3. 参考材料中所有值都为空
        
        Args:
            rule: 审核规则
            user_input_value: 用户输入的字段值（文件审核时为None）
            reference_materials: 参考材料字典 {材料名称: 字段值或全文}
            
        Returns:
            - None: 满足审核条件，可以继续调用LLM
            - AuditRuleResult: 不满足条件，返回待确认结果
        """
        long_term_pass = self._try_yyzzyxqz_long_term_pre_check_pass(
            rule=rule,
            user_input_value=user_input_value,
            reference_materials=reference_materials,
            extraction_results_list=extraction_results_list
        )
        if long_term_pass:
            return long_term_pass

        # 条件1: 缺少参考材料
        if not reference_materials or len(reference_materials) == 0:
            # 检查是否配置了材料缺失时自动通过
            if getattr(rule, 'auto_pass_when_missing', False):
                logger.info(f"规则 {rule.field_name} 缺少参考材料，但配置为材料缺失时自动通过")
                
                # 文件审核：返回标准文件审核格式（自动通过）
                if rule.audit_type == AuditType.FILE_AUDIT:
                    return self._create_file_audit_pre_check_result(
                        rule=rule, 
                        auto_pass=True,
                        explanation="信息披露申请书为自动生成电签文件时，该字段对比值默认一致通过"
                    )
                
                # 字段审核：返回字段审核格式（自动通过）
                extraction_data = self._find_extraction_data(rule.field_name, extraction_results_list)
                related_fields = [RelatedFieldInfo(
                    field_name=rule.field_name,
                    field_value=user_input_value or "",
                    field_type="text",
                    extraction_data=extraction_data
                )]
                
                audit_rule_info = self._build_audit_rule_info(rule)
                
                return AuditRuleResult(
                    audit_id=f"audit_{uuid.uuid4().hex[:16]}",
                    audit_rule_id=getattr(rule, 'id', None),
                    audit_rule_name=rule.field_name,
                    audit_type=AuditTypeEnum.FIELD_AUDIT,
                    audit_result=AuditResultEnum.PASSED,
                    audit_status=AuditStatus.COMPLETED,
                    audit_explanation="信息披露申请书为自动生成电签文件时，该字段对比值默认一致通过",
                    confidence=1.0,
                    related_fields=related_fields,
                    audit_rule=audit_rule_info
                )
            
            logger.warning(f"规则 {rule.field_name} 缺少参考材料，跳过LLM审核")
            
            # 文件审核：返回标准文件审核格式
            if rule.audit_type == AuditType.FILE_AUDIT:
                return self._create_file_audit_pre_check_result(rule=rule)
            
            # 字段审核：返回字段审核格式
            extraction_data = self._find_extraction_data(rule.field_name, extraction_results_list)
            related_fields = [RelatedFieldInfo(
                field_name=rule.field_name,
                field_value=user_input_value or "",
                field_type="text",
                extraction_data=extraction_data
            )]
            
            # 构建审核规则信息
            audit_rule_info = self._build_audit_rule_info(rule)
            
            return AuditRuleResult(
                audit_id=f"audit_{uuid.uuid4().hex[:16]}",
                audit_rule_id=getattr(rule, 'id', None),
                audit_rule_name=rule.field_name,
                audit_type=AuditTypeEnum.FIELD_AUDIT,
                audit_result=AuditResultEnum.PENDING,
                audit_status=AuditStatus.COMPLETED,
                audit_explanation="缺少必要的参考材料，无法进行审核。请确保已上传相关文件并成功解析。",
                confidence=0.0,
                related_fields=related_fields,
                audit_rule=audit_rule_info
            )
        
        # 条件2: 字段审核时要求用户输入但用户未提供
        # 注意：文件审核不需要用户输入字段值，user_input_value 为 None 是正常的
        if rule.audit_type == AuditType.FIELD_AUDIT and rule.include_user_input and (not user_input_value or not user_input_value.strip()):
            logger.warning(f"规则 {rule.field_name} 要求用户输入但未提供，跳过LLM审核")
            extraction_data = self._find_extraction_data(rule.field_name, extraction_results_list)
            
            # 构建审核规则信息
            audit_rule_info = self._build_audit_rule_info(rule)
            
            return AuditRuleResult(
                audit_id=f"audit_{uuid.uuid4().hex[:16]}",
                audit_rule_id=getattr(rule, 'id', None),
                audit_rule_name=rule.field_name,
                audit_type=AuditTypeEnum.FIELD_AUDIT,
                audit_result=AuditResultEnum.PENDING,
                audit_status=AuditStatus.COMPLETED,
                audit_explanation="该审核项要求用户输入字段值，但未提供。请先完成字段录入。",
                confidence=0.0,
                related_fields=[RelatedFieldInfo(
                    field_name=rule.field_name,
                    field_value="",
                    field_type="text",
                    extraction_data=extraction_data
                )],
                audit_rule=audit_rule_info
            )
        
        # 条件3: 参考材料中所有值都为空
        all_empty = all(
            not value or not str(value).strip() 
            for value in reference_materials.values()
        )
        if all_empty:
            # 检查是否配置了材料缺失时自动通过
            if getattr(rule, 'auto_pass_when_missing', False):
                logger.info(f"规则 {rule.field_name} 的所有参考材料值为空，但配置为材料缺失时自动通过")
                
                # 文件审核：返回标准文件审核格式（自动通过）
                if rule.audit_type == AuditType.FILE_AUDIT:
                    return self._create_file_audit_pre_check_result(
                        rule=rule,
                        auto_pass=True,
                        explanation="信息披露申请书为自动生成电签文件时，该字段对比值默认一致通过"
                    )
                
                # 字段审核：返回字段审核格式（自动通过）
                extraction_data = self._find_extraction_data(rule.field_name, extraction_results_list)
                related_fields = [RelatedFieldInfo(
                    field_name=rule.field_name,
                    field_value=user_input_value or "",
                    field_type="text",
                    extraction_data=extraction_data
                )]
                
                audit_rule_info = self._build_audit_rule_info(rule)
                
                return AuditRuleResult(
                    audit_id=f"audit_{uuid.uuid4().hex[:16]}",
                    audit_rule_id=getattr(rule, 'id', None),
                    audit_rule_name=rule.field_name,
                    audit_type=AuditTypeEnum.FIELD_AUDIT,
                    audit_result=AuditResultEnum.PASSED,
                    audit_status=AuditStatus.COMPLETED,
                    audit_explanation="信息披露申请书为自动生成电签文件时，该字段对比值默认一致通过",
                    confidence=1.0,
                    related_fields=related_fields,
                    audit_rule=audit_rule_info
                )
            
            logger.warning(f"规则 {rule.field_name} 的所有参考材料值为空，跳过LLM审核")
            
            # 文件审核：返回标准文件审核格式
            if rule.audit_type == AuditType.FILE_AUDIT:
                return self._create_file_audit_pre_check_result(rule=rule)
            
            # 字段审核：返回字段审核格式
            extraction_data = self._find_extraction_data(rule.field_name, extraction_results_list)
            related_fields = [RelatedFieldInfo(
                field_name=rule.field_name,
                field_value=user_input_value or "",
                field_type="text",
                extraction_data=extraction_data
            )]
            
            # 构建审核规则信息
            audit_rule_info = self._build_audit_rule_info(rule)
            
            return AuditRuleResult(
                audit_id=f"audit_{uuid.uuid4().hex[:16]}",
                audit_rule_id=getattr(rule, 'id', None),
                audit_rule_name=rule.field_name,
                audit_type=AuditTypeEnum.FIELD_AUDIT,
                audit_result=AuditResultEnum.PENDING,
                audit_status=AuditStatus.COMPLETED,
                audit_explanation="参考材料中未提取到有效内容，无法进行审核。建议检查文件质量或重新上传。",
                confidence=0.0,
                related_fields=related_fields,
                audit_rule=audit_rule_info
            )
        
        # 所有条件通过，可以继续审核
        return None
    
    def _format_long_text_diff(
        self,
        text1: str,
        text2: str,
        context_len: int = 15,
        max_diffs: int = 3
    ) -> str:
        """
        生成长文本的差异对比摘要
        
        使用 difflib 对比两段文本，仅展示差异部分及其上下文，
        避免长文本全量展示导致审核人员难以定位问题。
        
        注意：会先对文本进行规范化（统一符号、空格、大小写等），
        然后再进行差异对比，确保忽略格式差异。
        
        Args:
            text1: 用户输入文本
            text2: 参考材料文本
            context_len: 差异点前后的上下文字符数
            max_diffs: 最多展示的差异数量
            
        Returns:
            str: 格式化后的差异描述
        """
        if not text1 or not text2:
            return f"内容缺失 (用户输入长度: {len(text1 or '')}, 材料长度: {len(text2 or '')})"

        # 先规范化文本（统一符号、空白、大小写），再进行差异对比
        # 这样可以忽略中英文括号、空格、大小写等格式差异
        normalized_text1 = normalize_for_comparison(text1)
        normalized_text2 = normalize_for_comparison(text2)
        
        # 使用 SequenceMatcher 计算差异（使用规范化后的文本）
        s = difflib.SequenceMatcher(None, normalized_text1, normalized_text2)
        diff_blocks = []
        
        # 获取差异块 (replace, delete, insert)
        for tag, i1, i2, j1, j2 in s.get_opcodes():
            if tag == 'equal':
                continue
            
            # 提取差异内容（使用规范化后的文本）
            segment1 = normalized_text1[i1:i2]
            segment2 = normalized_text2[j1:j2]
            
            # 提取上下文（差异点前后的文本）
            prefix = normalized_text1[max(0, i1 - context_len):i1]
            suffix = normalized_text1[i2:min(len(normalized_text1), i2 + context_len)]
            
            # 格式化差异描述
            if tag == 'replace':
                # 替换：用户输入的内容与材料不同
                diff_msg = f"...{prefix}【用户填: {segment1[:50]}{'...' if len(segment1) > 50 else ''} ≠ 材料: {segment2[:50]}{'...' if len(segment2) > 50 else ''}】{suffix}..."
            elif tag == 'delete':
                # 删除：用户输入中多出的内容（材料中没有）
                diff_msg = f"...{prefix}【用户多出: {segment1[:50]}{'...' if len(segment1) > 50 else ''}】{suffix}..."
            elif tag == 'insert':
                # 插入：材料中多出的内容（用户输入中没有）
                prefix_j = normalized_text2[max(0, j1 - context_len):j1]
                suffix_j = normalized_text2[j2:min(len(normalized_text2), j2 + context_len)]
                diff_msg = f"...{prefix_j}【用户缺失: {segment2[:50]}{'...' if len(segment2) > 50 else ''}】{suffix_j}..."
            else:
                continue
            
            diff_blocks.append(diff_msg)
            
            # 只展示前 max_diffs 个差异，避免过多
            if len(diff_blocks) >= max_diffs:
                remaining = sum(1 for op in s.get_opcodes() if op[0] != 'equal') - max_diffs
                if remaining > 0:
                    diff_blocks.append(f"...(还有 {remaining} 处差异)")
                break
        
        if not diff_blocks:
            # 理论上不会走到这里，因为调用前已经判断不一致
            return "内容基本一致（可能仅存在格式差异）"
        
        return "；".join(diff_blocks)

    def _simple_field_comparison(
        self,
        user_input_value: Optional[str],
        reference_materials: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        简单字段对比逻辑
        
        适用于简单的字段一致性校验，直接比对用户输入值与参考材料中的字段值。
        
        规则：
        1. 若用户输入为空或参考材料为空，则审核结果为待确认
        2. 若用户输入值与所有参考材料字段值一致，则审核通过
        3. 若用户输入值与任一参考材料字段值不一致，则审核不通过
        
        Args:
            user_input_value: 用户输入的字段值
            reference_materials: 参考材料字典 {材料名称: 字段值}
            
        Returns:
            Dict: {
                "audit_result": AuditResultEnum,
                "explanation": str,
                "confidence": float
            }
        """
        # 1. 检查数据完整性
        if not user_input_value or not user_input_value.strip():
            return {
                "audit_result": AuditResultEnum.PENDING,
                "explanation": "用户未输入字段值，无法进行对比审核",
                "confidence": 0.0
            }
        
        if not reference_materials:
            return {
                "audit_result": AuditResultEnum.PENDING,
                "explanation": "未找到参考材料中的字段值，无法进行对比审核",
                "confidence": 0.0
            }
        
        # 规范化用户输入（统一符号、空白字符、大小写）
        normalized_user_input = normalize_for_comparison(user_input_value)
        
        # 2. 对比所有参考材料
        all_matched = True
        mismatch_details = []  # 存储不一致的 (文件名, 材料值)
        match_details = []     # 存储一致的文件名
        skipped_details = []   # 存储跳过的空值材料文件名
        
        for material_name, material_value in reference_materials.items():
            # 提取文件名（去掉 " - 字段名" 后缀，只保留文件名用于展示）
            display_name = material_name.rsplit(" - ", 1)[0] if " - " in material_name else material_name
            
            if not material_value or not str(material_value).strip():
                # 参考材料值为空，跳过该材料，继续对比其他材料
                skipped_details.append(display_name)
                continue
            
            # 规范化参考材料值（统一符号、空白字符、大小写）
            normalized_material_value = normalize_for_comparison(material_value)
            
            # 进行对比
            if normalized_user_input == normalized_material_value:
                match_details.append(display_name)
            else:
                all_matched = False
                mismatch_details.append((display_name, str(material_value).strip()))
        
        # 3. 生成审核结果
        user_input_display = user_input_value.strip()
        
        # 如果所有材料都是空值，无法进行对比
        if not match_details and not mismatch_details:
            skipped_info = "、".join(skipped_details) if skipped_details else "所有材料"
            return {
                "audit_result": AuditResultEnum.PENDING,
                "explanation": f"参考材料中未找到字段值，无法进行对比审核。\n\n跳过的材料：{skipped_info}",
                "confidence": 0.0
            }
        
        # 构建跳过材料的说明（如果有的话）
        skipped_info = ""
        if skipped_details:
            skipped_info = f"跳过的材料（无值）：{', '.join(skipped_details)}"
        
        if all_matched:
            # 全部一致：只显示结论，不显示明细
            parts = ["字段值对比一致，审核通过"]
            if skipped_info:
                parts.append(skipped_info)
            
            explanation = "；".join(parts) + "。" if skipped_info else parts[0] + "。"
            return {
                "audit_result": AuditResultEnum.PASSED,
                "explanation": explanation,
                "confidence": 1.0
            }
        else:
            # 存在不一致：分别展示一致和不一致的材料
            details_lines = []
            
            # 长文本阈值：超过此长度使用差异对比展示
            LONG_TEXT_THRESHOLD = 80
            
            # 先展示一致的
            for name in match_details:
                details_lines.append(f"✓ {name}")
            
            # 再展示不一致的（对长文本使用差异对比）
            for name, mat_value in mismatch_details:
                is_long_text = len(user_input_display) > LONG_TEXT_THRESHOLD or len(mat_value) > LONG_TEXT_THRESHOLD
                
                if is_long_text:
                    # 长文本：使用差异对比，只展示差异部分
                    diff_desc = self._format_long_text_diff(user_input_display, mat_value)
                    details_lines.append(f"✗ {name}：{diff_desc}")
                else:
                    # 短文本：直接展示完整内容
                    details_lines.append(f"✗ {name}：用户填[{user_input_display}] ≠ 材料[{mat_value}]")
            
            # 构建最终说明
            # 对于长文本不一致，不再重复展示完整的用户输入
            has_long_mismatch = any(
                len(user_input_display) > LONG_TEXT_THRESHOLD or len(mat_value) > LONG_TEXT_THRESHOLD
                for _, mat_value in mismatch_details
            )
            
            if has_long_mismatch:
                # 长文本不一致时，差异已在 details_lines 中体现，不需要再展示完整用户输入
                parts = [
                    "字段值对比不一致，审核不通过",
                    "差异详情：" + "；".join(details_lines)
                ]
            else:
                # 短文本保持原有格式
                parts = [
                    "字段值对比不一致，审核不通过",
                    "材料核对：" + "；".join(details_lines)
                ]
            
            if skipped_info:
                parts.append(skipped_info)
            
            explanation = "；".join(parts) + "。"
            return {
                "audit_result": AuditResultEnum.FAILED,
                "explanation": explanation,
                "confidence": 1.0
            }
    
    def _add_manual_review_items(
        self,
        confirmed_fields: List[ConfirmedField],
        audit_results: List[AuditRuleResult],
        extraction_results_list: List[FieldExtractionResult],
        audit_type: str = ""
    ) -> List[AuditRuleResult]:
        """
        添加需人工审核的字段
        
        逻辑：
        1. 展开嵌套字段的子字段（如 ZRF 的子字段）
        2. 收集已审核的字段
        3. 找出 confirmed_fields 中未被审核的字段（包括展开的子字段）
        4. 为每个未审核的字段创建一个人工审核项，包含提取数据
        
        注意：级联过滤在 audit_fields 方法的步骤 6 中统一处理，
        此处不再重复过滤。
        
        Args:
            confirmed_fields: 用户确认的字段列表
            audit_results: 审核结果列表
            extraction_results_list: 完整提取结果列表
            audit_type: 审核类型（保留参数以保持接口兼容，实际未使用）
            
        Returns:
            List[AuditRuleResult]: 包含人工审核项的审核结果列表
        """
        # 1. 展开嵌套字段的子字段
        expanded_fields = FieldValueConverter.expand_confirmed_fields(confirmed_fields)
        logger.debug(f"展开后的字段数量: {len(expanded_fields)} (原始: {len(confirmed_fields)})")
        
        # 2. 收集已审核的字段
        audited_fields = set()
        for result in audit_results:
            for field_info in result.related_fields:
                audited_fields.add(field_info.field_name)
        
        # 3. 找出未审核的字段（包括展开的子字段）
        for field_dict in expanded_fields:
            field_name = field_dict["field_name"]
            field_value = field_dict["field_value"]
            field_type = field_dict["field_type"]
            
            if field_name not in audited_fields:
                logger.info(f"字段 '{field_name}' 未被自动审核覆盖，标记为需人工审核")
                
                # 4. 获取该字段的完整提取数据
                extraction_data = self._find_extraction_data(field_name, extraction_results_list)
                
                # 5. 创建人工审核项
                audit_results.append(AuditRuleResult(
                    audit_id=f"audit_{uuid.uuid4().hex[:16]}",
                    audit_rule_id=None,
                    audit_rule_name=field_name,
                    audit_type=AuditTypeEnum.MANUAL_REVIEW,
                    audit_result=AuditResultEnum.MANUAL_REVIEW,
                    audit_status=AuditStatus.COMPLETED,
                    audit_explanation="该字段未配置自动审核规则，需要人工审核",
                    confidence=None,
                    related_fields=[RelatedFieldInfo(
                        field_name=field_name,
                        field_value=field_value,
                        field_type=field_type,
                        extraction_data=extraction_data
                    )]
                ))
        
        return audit_results
    
    def _find_extraction_data(
        self,
        field_name: str,
        extraction_results_list: List[FieldExtractionResult]
    ) -> Optional[FieldExtractionResult]:
        """
        根据字段名查找对应的提取数据
        
        Args:
            field_name: 字段名称
            extraction_results_list: 提取结果列表
            
        Returns:
            Optional[FieldExtractionResult]: 找到的提取数据，未找到返回 None
        """
        for result in extraction_results_list:
            if result.field_name == field_name:
                return result
        return None
    
    def _match_uploaded_files(
        self,
        material_name: Optional[str],
        files: List[AuditFileInput]
    ) -> List[UploadedFileInfo]:
        """
        根据 material_name 匹配已上传的文件
        
        Args:
            material_name: 材料名称（如"信息披露申请书"或"《信息披露申请书》"）
            files: 请求中的文件列表
            
        Returns:
            List[UploadedFileInfo]: 匹配的文件列表
        """
        if not material_name:
            return []
        
        # 使用 LABEL_TO_FILE_TYPE 映射
        # 先尝试直接匹配
        file_type_enum = LABEL_TO_FILE_TYPE.get(material_name)
        
        # 如果直接匹配失败，尝试添加书名号《》
        if not file_type_enum and not material_name.startswith("《"):
            material_name_with_brackets = f"《{material_name}》"
            file_type_enum = LABEL_TO_FILE_TYPE.get(material_name_with_brackets)
            if file_type_enum:
                logger.debug(f"材料名称 '{material_name}' 添加书名号后成功匹配: '{material_name_with_brackets}'")
        
        if not file_type_enum:
            logger.warning(f"无法将 material_name '{material_name}' 映射到文件类型")
            return []
        
        # 在请求文件中查找匹配的文件
        matched_files = []
        for f in files:
            file_type_value = f.file_type.value if isinstance(f.file_type, FileType) else str(f.file_type)
            if file_type_value == file_type_enum.value:
                matched_files.append(UploadedFileInfo(
                    file_name=f.file_name,
                    file_url=f.file_url,
                    file_type=file_type_value
                ))
        
        return matched_files
    
    def _match_uploaded_files_by_sources(
        self,
        audit_data_sources: Optional[List[Any]],
        files: List[AuditFileInput]
    ) -> List[UploadedFileInfo]:
        """
        根据 audit_data_sources 中的材料名称匹配已上传的文件
        
        这是 _match_uploaded_files 的增强版本，支持从审核规则的数据源中
        获取正确的材料名称来匹配文件。
        
        Args:
            audit_data_sources: 审核数据源列表，每个元素包含 material_name 属性
            files: 请求中的文件列表
            
        Returns:
            List[UploadedFileInfo]: 匹配的文件列表（已去重）
        """
        if not audit_data_sources:
            return []
        
        uploaded_files = []
        seen_urls = set()  # 用于去重
        
        for source in audit_data_sources:
            # 获取材料名称
            material_name = None
            if hasattr(source, 'material_name'):
                material_name = source.material_name
            elif isinstance(source, dict):
                material_name = source.get('material_name')
            
            if not material_name:
                continue
            
            # 使用现有方法匹配文件
            matched = self._match_uploaded_files(material_name, files)
            
            # 去重添加
            for f in matched:
                if f.file_url not in seen_urls:
                    seen_urls.add(f.file_url)
                    uploaded_files.append(f)
        
        return uploaded_files
    
    def _match_uploaded_files_by_file_type(
        self,
        file_type: str,
        files: List[AuditFileInput]
    ) -> List[UploadedFileInfo]:
        """
        根据 file_type 精确匹配文件
        
        当审核规则配置了 primary_file_type 时使用此方法，
        只返回 file_type 与指定值匹配的文件。
        
        Args:
            file_type: 要匹配的文件类型枚举值（如 'asset_list'）
            files: 请求中的文件列表
            
        Returns:
            List[UploadedFileInfo]: 匹配的文件列表
        """
        matched_files = []
        
        for f in files:
            if f.file_type == file_type:
                matched_files.append(UploadedFileInfo(
                    file_name=f.file_name,
                    file_url=f.file_url,
                    file_type=f.file_type
                ))
        
        return matched_files
    
    def _get_uploaded_files_for_rule(
        self,
        rule: AuditRule,
        files: List[AuditFileInput]
    ) -> List[UploadedFileInfo]:
        """
        获取与审核规则相关的已上传文件
        
        优先使用 primary_file_type 精确匹配，如果未配置则使用 audit_data_sources 匹配。
        注意：返回的文件 URL 会自动转回相对路径（用于返回给前端）。
        
        Args:
            rule: 审核规则
            files: 请求中的文件列表
            
        Returns:
            List[UploadedFileInfo]: 匹配的文件列表（URL 为相对路径）
        """
        from src.utils.file_handler import denormalize_file_url
        
        # 如果配置了 primary_file_type，使用精确匹配
        if hasattr(rule, 'primary_file_type') and rule.primary_file_type:
            matched_files = self._match_uploaded_files_by_file_type(rule.primary_file_type, files)
        else:
            # 否则使用原有逻辑（匹配 audit_data_sources 中的所有材料）
            matched_files = self._match_uploaded_files_by_sources(rule.audit_data_sources, files)
        
        # 将所有文件的 URL 转回相对路径（用于返回结果）
        for file_info in matched_files:
            file_info.file_url = denormalize_file_url(file_info.file_url)
        
        return matched_files
    
    def _split_audit_points(self, audit_content: str) -> List[str]:
        """
        拆分审核要点
        
        按换行符拆分，过滤空行
        
        Args:
            audit_content: 审核内容字符串
            
        Returns:
            List[str]: 审核要点列表
        """
        if not audit_content:
            return []
        
        # 按 \r\n 或 \n 拆分
        lines = audit_content.replace('\r\n', '\n').split('\n')
        
        # 过滤空行，保留有内容的行
        points = [line.strip() for line in lines if line.strip()]
        
        return points
    
    def _create_file_audit_pre_check_result(
        self,
        rule: AuditRule,
        auto_pass: bool = False,
        explanation: Optional[str] = None
    ) -> AuditRuleResult:
        """
        创建文件审核预检查失败的结果
        
        当文件审核无法通过预检查时（如文件未上传、参考材料为空等），
        返回符合文件审核标准格式的结果，包含完整的审核要点详情。
        
        Args:
            rule: 审核规则
            auto_pass: 是否自动通过（适用于无纸项目等场景）
            explanation: 自定义说明信息
            
        Returns:
            AuditRuleResult: 文件审核结果
        """
        # 1. 获取 file_type
        # 使用 rule.field_name 作为 file_type
        file_type = rule.field_name
        
        # 2. 拆分审核要点
        audit_points = self._split_audit_points(rule.audit_content)
        
        # 3. 创建审核要点详情
        point_details = []
        for i, point in enumerate(audit_points):
            if auto_pass:
                # 自动通过时，每个审核要点都设为通过
                point_details.append(AuditPointDetail(
                    point_index=i + 1,
                    point_content=point,
                    audit_result=AuditResultEnum.PASSED,
                    audit_explanation=explanation or "该规则配置为材料缺失时自动通过",
                    confidence=1.0
                ))
            else:
                # 文件未上传时返回空值
                point_details.append(AuditPointDetail(
                    point_index=i + 1,
                    point_content=point,
                    audit_result=None,
                    audit_explanation="",  # 预检查失败时使用空字符串
                    confidence=0.0
                ))
        
        # 4. 创建空上传文件列表（显示需要上传的文件类型）
        uploaded_files = []
        if file_type:
            # 从 rule.audit_data_sources 获取真正的材料名称（带书名号）
            material_name = None
            if rule.audit_data_sources and len(rule.audit_data_sources) > 0:
                material_name = rule.audit_data_sources[0].material_name
            
            # 将 material_name 映射到 file_type 枚举
            file_type_enum = None
            if material_name:
                file_type_enum = LABEL_TO_FILE_TYPE.get(material_name)
            
            # 如果还是没找到，尝试给 file_type 添加书名号
            if not file_type_enum and not file_type.startswith("《"):
                file_type_with_brackets = f"《{file_type}》"
                file_type_enum = LABEL_TO_FILE_TYPE.get(file_type_with_brackets)
            
            if file_type_enum:
                uploaded_files.append(UploadedFileInfo(
                    file_name="",
                    file_url="",
                    file_type=file_type_enum.value
                ))
            else:
                logger.warning(f"无法为文件类型 '{file_type}' (material_name: '{material_name}') 创建占位符")
        
        # 5. 构建审核规则信息
        audit_rule_info = self._build_audit_rule_info(rule)
        
        # 6. 返回结果
        if auto_pass:
            # 自动通过时返回通过结果
            return AuditRuleResult(
                audit_id=f"audit_{uuid.uuid4().hex[:16]}",
                audit_rule_id=getattr(rule, 'id', None),
                audit_rule_name=rule.field_name,
                audit_type=AuditTypeEnum.FILE_AUDIT,
                audit_result=AuditResultEnum.PASSED,
                audit_status=AuditStatus.COMPLETED,
                audit_explanation=explanation or "信息披露申请书为自动生成电签文件时，该字段对比值默认一致通过",
                confidence=1.0,
                related_fields=[],
                file_type=file_type,
                audit_points=rule.audit_content,
                uploaded_files=uploaded_files,
                audit_details=None,
                audit_point_details=point_details,
                audit_rule=audit_rule_info
            )
        else:
            return AuditRuleResult(
                audit_id=f"audit_{uuid.uuid4().hex[:16]}",
                audit_rule_id=getattr(rule, 'id', None),
                audit_rule_name=rule.field_name,
                audit_type=AuditTypeEnum.FILE_AUDIT,
                audit_result=None,
                audit_status=AuditStatus.COMPLETED,
                audit_explanation=None,
                confidence=None,
                related_fields=[],
                file_type=file_type,
                audit_points=rule.audit_content,
                uploaded_files=uploaded_files,
                audit_details=None,
                audit_point_details=point_details,
                audit_rule=audit_rule_info
            )
    
    async def _audit_multiple_points(
        self,
        audit_points: List[str],
        reference_materials: Dict[str, str],
        audit_data_sources: List[str],
        rule: AuditRule
    ) -> List[AuditPointDetail]:
        """
        并发审核多个审核要点
        
        Args:
            audit_points: 审核要点列表
            reference_materials: 参考材料
            audit_data_sources: 数据源描述
            rule: 审核规则
            
        Returns:
            List[AuditPointDetail]: 各要点的审核结果
        """
        async def audit_single_point(index: int, point: str) -> AuditPointDetail:
            """审核单个要点"""
            try:
                audit_config = self.llm_config.get_audit_agent_config()
                
                async with LLMClient(audit_config) as client:
                    agent = AuditAgent(client)
                    llm_result = await agent.audit_field(
                        audit_type=rule.audit_type.value,
                        field_name=rule.field_name,
                        audit_content=point,  # 使用单个审核要点
                        auto_process_rules=rule.auto_process_rules,
                        audit_data_sources=audit_data_sources,
                        user_input_value=None,  # 文件审核不需要用户输入
                        reference_materials=reference_materials
                    )
                
                if llm_result.success:
                    # 映射审核结果
                    if llm_result.audit_result == "通过":
                        audit_result = AuditResultEnum.PASSED
                    elif llm_result.audit_result == "不通过":
                        audit_result = AuditResultEnum.FAILED
                    else:
                        audit_result = AuditResultEnum.PENDING
                    
                    return AuditPointDetail(
                        point_index=index,
                        point_content=point,
                        audit_result=audit_result,
                        audit_explanation=llm_result.audit_analysis,
                        confidence=0.9
                    )
                else:
                    return AuditPointDetail(
                        point_index=index,
                        point_content=point,
                        audit_result=AuditResultEnum.PENDING,
                        audit_explanation=f"审核失败: {llm_result.error}",
                        confidence=0.0
                    )
            except Exception as e:
                logger.error(f"审核要点 {index} 失败: {e}", exc_info=True)
                return AuditPointDetail(
                    point_index=index,
                    point_content=point,
                    audit_result=AuditResultEnum.PENDING,
                    audit_explanation=f"审核异常: {str(e)}",
                    confidence=0.0
                )
        
        # 使用信号量控制并发
        semaphore = asyncio.Semaphore(self.concurrency_config.audit_workers)
        
        async def bounded_audit(idx: int, point: str):
            async with semaphore:
                return await audit_single_point(idx + 1, point)  # 索引从1开始
        
        # 并发审核所有要点
        tasks = [bounded_audit(i, point) for i, point in enumerate(audit_points)]
        results = await asyncio.gather(*tasks)
        
        return results
    
    def _build_audit_rule_info(self, rule: AuditRule) -> Dict[str, Any]:
        """
        构建审核规则信息（用于前端展示）
        
        Args:
            rule: 审核规则对象
            
        Returns:
            Dict: 审核规则信息字典
        """
        audit_data_sources_list = []
        if rule.audit_data_sources:
            for ds in rule.audit_data_sources:
                audit_data_sources_list.append({
                    "material_name": ds.material_name,
                    "field_name": ds.field_name
                })
        
        return {
            "rule_id": getattr(rule, 'id', None),
            "field_name": rule.field_name,
            "audit_type": rule.audit_type.value,
            "audit_content": rule.audit_content,
            "mapping_type": rule.mapping_type.value if rule.mapping_type else None,
            "source_field_name": rule.source_field_name,
            "include_user_input": rule.include_user_input,
            "use_simple_comparison": rule.use_simple_comparison,
            "auto_process_rules": rule.auto_process_rules,
            "audit_data_sources": audit_data_sources_list,
            "enabled": rule.enabled
        }


# ============ 单例获取函数 ============


def get_audit_service() -> AuditService:
    """
    获取AuditService单例
    
    Returns:
        AuditService: 服务实例
    """
    global _audit_service_instance
    if _audit_service_instance is None:
        _audit_service_instance = AuditService()
        logger.debug("创建AuditService单例")
    return _audit_service_instance

