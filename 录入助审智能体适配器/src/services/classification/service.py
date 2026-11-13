"""
文件分类 API 服务

提供文件分类接口服务，支持：
1. 多种文件格式（PDF、Word、图片、Excel、CSV）
2. 只解析前两页内容用于分类
3. 并发处理多个文件
4. 基于文件名快速分类（优先）
5. 调用 LLM 进行智能分类（兜底）
"""

import asyncio
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

import fitz  # PyMuPDF
from loguru import logger

from config.llm_config import LLMConfig
from src.schemas.classification import (
    ClassificationData,
    ClassificationFileInput,
    ClassificationResultItem,
    ClassificationStatus,
)
from src.schemas.file import FileType, FILE_TYPE_LABELS
from src.schemas.task import TaskStatus
from src.services.llm.client import LLMClient, ClassificationAgent
from src.utils.file_handler import FileHandler
from src.utils.exceptions import FileProcessingError


# 全局单例实例
_classification_api_service_instance: Optional['FileClassificationAPIService'] = None


# 文件类型映射规则（按优先级排序，越靠前优先级越高）
# 注意：更具体的匹配项放在前面，避免被更通用的规则覆盖
FILE_TYPE_MAPPING = [
    # 信息披露申请书（最具体到最通用）
    ("实物资产转让信息披露申请书", FileType.INFO_DISCLOSURE_APPLICATION),
    ("信息披露申请书", FileType.INFO_DISCLOSURE_APPLICATION),
    ("披露申请书", FileType.INFO_DISCLOSURE_APPLICATION),
    ("信息披露申请", FileType.INFO_DISCLOSURE_APPLICATION),
    
    # 资产清单（最具体到最通用）
    ("资产清单", FileType.ASSET_LIST),
    ("处置清单", FileType.ASSET_LIST),
    ("资产明细", FileType.ASSET_LIST),
    ("资产列表", FileType.ASSET_LIST),
    
    # 营业执照
    ("营业执照", FileType.BUSINESS_LICENSE),
    ("工商执照", FileType.BUSINESS_LICENSE),
    ("企业法人营业执照", FileType.BUSINESS_LICENSE),
    ("事业单位法人证书", FileType.BUSINESS_LICENSE),
    ("法人证书", FileType.BUSINESS_LICENSE),
    ("身份证", FileType.BUSINESS_LICENSE),
    
    # 房产证相关（最具体到最通用）
    ("不动产权所有证", FileType.PROPERTY_CERTIFICATE),
    ("不动产权证书", FileType.PROPERTY_CERTIFICATE),
    ("不动产权证", FileType.PROPERTY_CERTIFICATE),
    ("房屋产权所有证", FileType.PROPERTY_CERTIFICATE),
    ("房屋产权证书", FileType.PROPERTY_CERTIFICATE),
    ("房屋所有权证", FileType.PROPERTY_CERTIFICATE),
    ("房屋产权证", FileType.PROPERTY_CERTIFICATE),
    ("房屋产权", FileType.PROPERTY_CERTIFICATE),
    ("不动产证", FileType.PROPERTY_CERTIFICATE),
    ("房产证", FileType.PROPERTY_CERTIFICATE),
    ("产权登记表", FileType.PROPERTY_CERTIFICATE),
    ("产权证", FileType.PROPERTY_CERTIFICATE),
    
    # 评估报告和备案表（需要精确匹配顺序）
    ("资产评估报告书", FileType.EVALUATION_REPORT),
    ("评估报告的核准或备案材料", FileType.EVALUATION_FILING),
    ("资产评估备案表", FileType.EVALUATION_FILING),
    ("评估报告备案表", FileType.EVALUATION_FILING),
    ("评估备案表", FileType.EVALUATION_FILING),
    ("评估备案", FileType.EVALUATION_FILING),
    ("备案表", FileType.EVALUATION_FILING),
    ("核准文件", FileType.EVALUATION_FILING),
    ("房地产评估报告", FileType.EVALUATION_REPORT),
    ("资产评估报告", FileType.EVALUATION_REPORT),
    ("评估报告", FileType.EVALUATION_REPORT),
    ("资产评估", FileType.EVALUATION_REPORT),
    ("定价文件", FileType.EVALUATION_REPORT),
    ("估价报告", FileType.EVALUATION_REPORT),
    
    # 决策文件（最具体到最通用）
    ("内部决议或有权批准机构决策文件", FileType.INTERNAL_DECISION),
    ("有权批准机构决策文件", FileType.INTERNAL_DECISION),
    ("项目方决策文件", FileType.INTERNAL_DECISION),
    ("合伙人内部决议", FileType.INTERNAL_DECISION),
    ("内部决议", FileType.INTERNAL_DECISION),
    ("内部决策", FileType.INTERNAL_DECISION),
    ("股东会决议", FileType.INTERNAL_DECISION),
    ("股东决定", FileType.INTERNAL_DECISION),
    ("董事会决议", FileType.INTERNAL_DECISION),
    ("会议纪要", FileType.INTERNAL_DECISION),
    ("决策文件", FileType.INTERNAL_DECISION),
    ("批准文件", FileType.INTERNAL_DECISION),
    ("集团批复", FileType.INTERNAL_DECISION),
    ("批复", FileType.INTERNAL_DECISION),
    ("请示", FileType.INTERNAL_DECISION),
    
    # 踏勘管理/承诺函（最具体到最通用）
    ("踏勘管理办法", FileType.INSPECTION_COMMITMENT),
    ("踏勘确认书", FileType.INSPECTION_COMMITMENT),
    ("踏勘承诺函", FileType.INSPECTION_COMMITMENT),
    ("踏勘承诺", FileType.INSPECTION_COMMITMENT),
    ("踏勘确认", FileType.INSPECTION_COMMITMENT),
    ("现场踏勘", FileType.INSPECTION_COMMITMENT),
    ("踏勘", FileType.INSPECTION_COMMITMENT),
    
    # 国有土地使用证
    ("国有土地使用证", FileType.LAND_USE_CERTIFICATE),
    ("土地使用证", FileType.LAND_USE_CERTIFICATE),
    ("国有土地", FileType.LAND_USE_CERTIFICATE),
    ("土地证", FileType.LAND_USE_CERTIFICATE),
    
    # 国有建设用地使用权出让合同
    ("国有建设用地使用权出让合同", FileType.LAND_USE_CONTRACT),
    ("土地使用权出让合同", FileType.LAND_USE_CONTRACT),
    ("建设用地使用权出让合同", FileType.LAND_USE_CONTRACT),
    ("土地出让", FileType.LAND_USE_CONTRACT),
    ("建设用地使用权出让", FileType.LAND_USE_CONTRACT),
    
    # 车辆证书（最具体到最通用）
    ("机动车登记证书", FileType.VEHICLE_CERTIFICATE),
    ("机动车登记", FileType.VEHICLE_CERTIFICATE),
    ("车辆登记", FileType.VEHICLE_CERTIFICATE),
    ("行驶证", FileType.VEHICLE_CERTIFICATE),
    
    # 船舶证书（最具体到最通用）
    ("船舶所有权证书", FileType.SHIP_CERTIFICATE),
    ("船舶检验证书", FileType.SHIP_CERTIFICATE),
    ("船舶国籍证明", FileType.SHIP_CERTIFICATE),
    ("船舶所有权", FileType.SHIP_CERTIFICATE),
    ("船舶检验", FileType.SHIP_CERTIFICATE),
    ("船舶国籍", FileType.SHIP_CERTIFICATE),
    ("船舶证书", FileType.SHIP_CERTIFICATE),
    
    # 飞机证书（最具体到最通用）
    ("国籍登记证", FileType.AIRCRAFT_CERTIFICATE),
    ("适航证", FileType.AIRCRAFT_CERTIFICATE),
    ("电台执照", FileType.AIRCRAFT_CERTIFICATE),
    ("航空器", FileType.AIRCRAFT_CERTIFICATE),
    
    # 专利证书
    ("专利证书", FileType.PATENT_CERTIFICATE),
    ("专利权证", FileType.PATENT_CERTIFICATE),
    ("发明专利", FileType.PATENT_CERTIFICATE),
    ("实用新型", FileType.PATENT_CERTIFICATE),
    
    # 中央行政事业单位相关文件（最具体到最通用）
    ("中央行政事业单位国有资产处置委托书", FileType.CENTRAL_ASSET_DISPOSAL_AUTHORIZATION),
    ("中央行政事业单位国有资产处置委托", FileType.CENTRAL_ASSET_DISPOSAL_AUTHORIZATION),
    ("中央行政事业单位国有资产转让申请表", FileType.CENTRAL_ASSET_TRANSFER_APPLICATION),
    ("中央行政事业单位国有资产转让申请", FileType.CENTRAL_ASSET_TRANSFER_APPLICATION),
    ("中央行政事业单位国有资产接收单", FileType.CENTRAL_ASSET_RECEIPT),
    
    # 行政事业单位相关文件（最具体到最通用）
    ("行政事业单位国有资产处置申请表", FileType.ASSET_DISPOSAL_APPLICATION),
    ("行政事业单位国有资产处置申请", FileType.ASSET_DISPOSAL_APPLICATION),
    ("行政事业单位国有资产接收确认书", FileType.ASSET_RECEIPT_CONFIRMATION),
    ("行政事业单位国有资产接收确认", FileType.ASSET_RECEIPT_CONFIRMATION),
    ("行政事业单位国有资产确认单", FileType.ASSET_CONFIRMATION_FORM),
    ("国有资产处置申请表", FileType.ASSET_DISPOSAL_APPLICATION),
    ("国有资产接收确认书", FileType.ASSET_RECEIPT_CONFIRMATION),
    ("国有资产确认单", FileType.ASSET_CONFIRMATION_FORM),
    
    # 项目进度记录表
    ("项目进度记录表", FileType.PROJECT_PROGRESS_RECORD),
    ("项目进度记录", FileType.PROJECT_PROGRESS_RECORD),
    ("进度记录表", FileType.PROJECT_PROGRESS_RECORD),
]


class FileClassificationAPIService:
    """
    文件分类 API 服务
    
    提供独立的文件分类接口服务，与现有的内部分类服务（classification_service.py）分离。
    主要用于对外暴露的 REST API 接口。
    """
    
    # 用于分类的最大页数
    MAX_PAGES_FOR_CLASSIFICATION = 2
    
    # 内容截断长度（避免超出 LLM token 限制）
    MAX_CONTENT_LENGTH = 10000
    
    def __init__(self):
        """初始化分类服务"""
        self.llm_config = LLMConfig()
        self.concurrency_config = self.llm_config.get_concurrency_config()
        
        # 延迟初始化客户端（避免循环导入）
        self._paddle_client = None
        self._tika_client = None
        self._gotenberg_client = None
    
    @property
    def paddle_client(self):
        """获取 Paddle 客户端（延迟加载）"""
        if self._paddle_client is None:
            from src.services.paddle.client import get_paddle_client
            self._paddle_client = get_paddle_client()
        return self._paddle_client
    
    @property
    def tika_client(self):
        """获取 Tika 客户端（延迟加载）"""
        if self._tika_client is None:
            from src.services.tika.client import get_tika_client
            self._tika_client = get_tika_client()
        return self._tika_client
    
    @property
    def gotenberg_client(self):
        """获取 Gotenberg 客户端（延迟加载）"""
        if self._gotenberg_client is None:
            from src.services.gotenberg.client import get_gotenberg_client
            self._gotenberg_client = get_gotenberg_client()
        return self._gotenberg_client
    
    def _classify_by_filename(self, file_name: str) -> Optional[FileType]:
        """
        基于文件名快速分类
        
        按优先级顺序匹配 FILE_TYPE_MAPPING 中的关键词。
        更具体的关键词排在前面，避免被通用规则误匹配。
        
        Args:
            file_name: 文件名（含扩展名）
            
        Returns:
            Optional[FileType]: 匹配到的文件类型，未匹配返回 None
        """
        # 移除文件扩展名，只保留文件名主体
        name_without_ext = file_name.rsplit('.', 1)[0] if '.' in file_name else file_name
        
        # 按优先级顺序匹配
        for keyword, file_type in FILE_TYPE_MAPPING:
            if keyword in name_without_ext:
                logger.info(f"文件名快速匹配成功: '{file_name}' 包含 '{keyword}' -> {file_type.value}")
                return file_type
        
        return None
    
    async def classify_files(
        self,
        files: List[ClassificationFileInput],
        task_id: Optional[str] = None,
        request_id: Optional[str] = None,
        base_task_id: Optional[str] = None,
    ) -> ClassificationData:
        """
        批量分类文件，并在提供 task_id 时按文件完成进度更新任务。

        Args:
            files: 待分类的文件列表
            task_id: 任务存储使用的任务 ID（可选）
            request_id: 请求唯一标识（可选）
            base_task_id: 对外任务 ID（不含前缀，可选）

        Returns:
            ClassificationData: 分类结果与整体状态
        """
        start_time = time.time()
        total_files = len(files)
        task_store = None

        try:
            if task_id:
                from src.services.task_store import get_task_store
                task_store = get_task_store()
            if task_id and task_store:
                await task_store.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    progress=0,
                    status_message="正在分类文件...",
                    context={"total_files": total_files, "completed_count": 0},
                )

            # 使用信号量控制并发
            semaphore = asyncio.Semaphore(self.concurrency_config.classification_workers)

            async def classify_with_semaphore(file_input: ClassificationFileInput):
                async with semaphore:
                    return await self._classify_single_file(file_input)

            completed = 0
            success_count = 0
            failed_count = 0
            results_by_index: Dict[int, ClassificationResultItem] = {}

            async def run_one(idx: int, file_input: ClassificationFileInput):
                from src.services.redis.task_cancel_subscriber import get_task_cancel_subscriber
                if task_id and get_task_cancel_subscriber().is_cancelled(task_id):
                    logger.warning(f"检测到任务取消信号: {task_id}")
                    raise asyncio.CancelledError("任务已取消")
                try:
                    item = await classify_with_semaphore(file_input)
                    return idx, item, True
                except Exception as e:
                    logger.error(f"文件分类失败: {file_input.file_name}, 错误: {e}")
                    item = ClassificationResultItem(
                        file_name=file_input.file_name,
                        file_url=file_input.file_url,
                        file_type=FileType.OTHER_DOCUMENTS.value,
                    )
                    return idx, item, False

            indexed = [
                asyncio.create_task(run_one(i, f))
                for i, f in enumerate(files)
            ]
            for coro in asyncio.as_completed(indexed):
                idx, item, ok = await coro
                results_by_index[idx] = item
                completed += 1
                if ok:
                    success_count += 1
                else:
                    failed_count += 1
                if task_id and task_store and total_files:
                    progress = completed / total_files
                    await task_store.update_task(
                        task_id,
                        progress=progress,
                        status_message=f"正在分类文件... ({completed}/{total_files})",
                        context={"total_files": total_files, "completed_count": completed},
                    )

            classification_results = [results_by_index[i] for i in range(total_files)]

            if failed_count == 0:
                overall_status = ClassificationStatus.SUCCESS
            elif success_count == 0:
                overall_status = ClassificationStatus.FAILED
            else:
                overall_status = ClassificationStatus.PARTIAL

            processing_time_ms = int((time.time() - start_time) * 1000)
            resolved_request_id = (
                request_id or base_task_id or task_id or f"req_{int(time.time() * 1000)}"
            )
            data = ClassificationData(
                request_id=resolved_request_id,
                task_id=base_task_id if base_task_id is not None else task_id,
                status=overall_status,
                results=classification_results,
                total_files=total_files,
                success_count=success_count,
                failed_count=failed_count,
                processing_time_ms=processing_time_ms,
            )

            if task_id and task_store:
                await task_store.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    progress=1.0,
                    result=data.model_dump(),
                    status_message="处理完成",
                )

            return data

        except Exception as e:
            logger.error(f"文件分类失败: {e}", exc_info=True)
            if task_id and task_store:
                await task_store.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    error_message=str(e),
                )
            raise
    
    async def _classify_single_file(
        self,
        file_input: ClassificationFileInput
    ) -> ClassificationResultItem:
        """
        分类单个文件
        
        流程（优化后）：
        1. 优先尝试基于文件名快速分类（零延迟）
        2. 如果文件名无法匹配，下载并解析文件内容
        3. 调用 LLM 分类（兜底）
        
        Args:
            file_input: 文件输入
            
        Returns:
            ClassificationResultItem: 分类结果。文件名命中，或内容为空 / LLM 正常返回
            （含 other_documents）时直接返回，由调用方计入 success_count。

        Raises:
            Exception: 下载、解析或模型调用中的异常向上抛出，由 classify_files
            兜底为 other_documents 并计入 failed_count。
        """
        file_name = file_input.file_name
        file_url = file_input.file_url
        
        logger.info(f"开始分类文件: {file_name}")
        
        try:
            # 1. 优先尝试基于文件名快速分类（零延迟，无需下载文件）
            filename_match = self._classify_by_filename(file_name)
            if filename_match:
                logger.info(f"文件 {file_name} 通过文件名快速分类: {filename_match.value}")
                return ClassificationResultItem(
                    file_name=file_name,
                    file_url=file_url,
                    file_type=filename_match.value
                )
            
            logger.debug(f"文件 {file_name} 文件名未匹配，将下载文件并使用 LLM 分类")
            
            # 2. 文件名未匹配，下载文件并获取扩展名
            file_content, file_extension = await FileHandler.process_file_input(
                file_url=file_url,
                file_name=file_name
            )
            
            logger.debug(f"文件 {file_name} 下载完成, 大小: {len(file_content)} 字节, 扩展名: {file_extension}")
            
            # 3. 根据文件格式解析内容（只解析前两页）
            parsed_content = await self._parse_file_for_classification(
                file_content=file_content,
                file_name=file_name,
                file_extension=file_extension
            )
            
            if not parsed_content:
                logger.warning(f"文件 {file_name} 内容解析为空，使用默认分类")
                return ClassificationResultItem(
                    file_name=file_name,
                    file_url=file_url,
                    file_type=FileType.OTHER_DOCUMENTS.value
                )
            
            # 4. 调用 LLM 分类（兜底）
            classified_type = await self._classify_by_llm(
                file_name=file_name,
                file_content=parsed_content
            )
            
            logger.info(f"文件 {file_name} 通过 LLM 分类完成: {classified_type}")
            
            return ClassificationResultItem(
                file_name=file_name,
                file_url=file_url,
                file_type=classified_type
            )
            
        except Exception as e:
            logger.error(f"文件 {file_name} 分类失败: {e}", exc_info=True)
            raise
    
    async def _parse_file_for_classification(
        self,
        file_content: bytes,
        file_name: str,
        file_extension: str
    ) -> Optional[str]:
        """
        解析文件内容用于分类（只解析前两页）
        
        Args:
            file_content: 文件二进制内容
            file_name: 文件名
            file_extension: 文件扩展名
            
        Returns:
            Optional[str]: 解析后的文本内容
        """
        try:
            # PDF 格式
            if FileHandler.is_pdf_format(file_extension):
                return await self._parse_pdf_first_pages(file_content, file_name)
            
            # Word 格式（需要先转换为 PDF）
            elif FileHandler.is_word_format(file_extension):
                return await self._parse_word_first_pages(file_content, file_name)
            
            # 图片格式
            elif FileHandler.is_image_format(file_extension):
                return await self._parse_image(file_content, file_name)
            
            # Excel/CSV 格式
            elif FileHandler.is_excel_format(file_extension) or FileHandler.is_csv_format(file_extension):
                return await self._parse_spreadsheet(file_content, file_name)
            
            # 其他文本格式
            elif FileHandler.is_text_document_format(file_extension):
                return await self._parse_text_document(file_content, file_name)
            
            else:
                logger.warning(f"不支持的文件格式: {file_extension}")
                return None
                
        except Exception as e:
            logger.error(f"解析文件 {file_name} 失败: {e}", exc_info=True)
            return None
    
    async def _parse_pdf_first_pages(
        self,
        file_content: bytes,
        file_name: str
    ) -> Optional[str]:
        """
        解析 PDF 前两页内容
        
        Args:
            file_content: PDF 文件内容
            file_name: 文件名
            
        Returns:
            Optional[str]: 解析后的 Markdown 内容
        """
        try:
            # 使用 PyMuPDF 截取前两页
            truncated_pdf = self._truncate_pdf_pages(
                file_content, 
                max_pages=self.MAX_PAGES_FOR_CLASSIFICATION
            )
            
            if truncated_pdf is None:
                return None
            
            # 使用 Paddle 解析截取后的 PDF
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                tmp_file.write(truncated_pdf)
                tmp_path = tmp_file.name
            
            try:
                parse_result = await self.paddle_client.parse_file(file_path=tmp_path)
                
                if parse_result and parse_result.success and parse_result.md_content:
                    return parse_result.md_content
                else:
                    logger.warning(f"Paddle 解析 PDF {file_name} 失败")
                    return None
            finally:
                # 清理临时文件
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"清理临时文件失败: {e}")
                    
        except Exception as e:
            logger.error(f"解析 PDF {file_name} 失败: {e}", exc_info=True)
            return None
    
    async def _parse_word_first_pages(
        self,
        file_content: bytes,
        file_name: str
    ) -> Optional[str]:
        """
        解析 Word 文档前两页内容
        
        流程：先用 Gotenberg 转 PDF，再截取前两页解析
        
        Args:
            file_content: Word 文件内容
            file_name: 文件名
            
        Returns:
            Optional[str]: 解析后的 Markdown 内容
        """
        try:
            # 先将 Word 转换为 PDF
            pdf_content = await self.gotenberg_client.convert_office_to_pdf(
                file_content=file_content,
                file_name=file_name
            )
            
            if not pdf_content:
                logger.warning(f"Word 转 PDF 失败: {file_name}")
                # 降级使用 Tika 直接提取文本
                return await self._parse_text_document(file_content, file_name)
            
            # 解析转换后的 PDF 前两页
            return await self._parse_pdf_first_pages(pdf_content, file_name)
            
        except Exception as e:
            logger.warning(f"Word 文档处理失败: {e}, 降级使用 Tika")
            # 降级使用 Tika 直接提取文本
            return await self._parse_text_document(file_content, file_name)
    
    async def _parse_image(
        self,
        file_content: bytes,
        file_name: str
    ) -> Optional[str]:
        """
        解析图片内容
        
        图片不需要分页，直接使用 Paddle 解析
        
        Args:
            file_content: 图片文件内容
            file_name: 文件名
            
        Returns:
            Optional[str]: 解析后的 Markdown 内容
        """
        try:
            parse_result = await self.paddle_client.parse_file(
                file_content=file_content,
                file_name=file_name
            )
            
            if parse_result and parse_result.success and parse_result.md_content:
                return parse_result.md_content
            else:
                logger.warning(f"Paddle 解析图片 {file_name} 失败")
                return None
                
        except Exception as e:
            logger.error(f"解析图片 {file_name} 失败: {e}", exc_info=True)
            return None
    
    async def _parse_spreadsheet(
        self,
        file_content: bytes,
        file_name: str
    ) -> Optional[str]:
        """
        解析 Excel/CSV 文件
        
        使用 Tika 提取文本内容
        
        Args:
            file_content: 文件内容
            file_name: 文件名
            
        Returns:
            Optional[str]: 解析后的文本内容
        """
        return await self._parse_text_document(file_content, file_name)
    
    async def _parse_text_document(
        self,
        file_content: bytes,
        file_name: str
    ) -> Optional[str]:
        """
        解析文本类文档（使用 Tika）
        
        Args:
            file_content: 文件内容
            file_name: 文件名
            
        Returns:
            Optional[str]: 解析后的文本内容
        """
        try:
            tika_result = await self.tika_client.extract_text(
                file_content=file_content,
                file_name=file_name
            )
            
            text = tika_result.get("text", "")
            if text:
                # 只取前部分内容用于分类
                return text[:self.MAX_CONTENT_LENGTH]
            
            return None
            
        except Exception as e:
            logger.error(f"Tika 提取文本失败 {file_name}: {e}", exc_info=True)
            return None
    
    def _truncate_pdf_pages(
        self,
        pdf_content: bytes,
        max_pages: int = 2
    ) -> Optional[bytes]:
        """
        截取 PDF 前 N 页
        
        Args:
            pdf_content: PDF 文件内容
            max_pages: 最大页数
            
        Returns:
            Optional[bytes]: 截取后的 PDF 内容
        """
        try:
            doc = fitz.open(stream=pdf_content, filetype="pdf")
            total_pages = len(doc)
            
            if total_pages == 0:
                doc.close()
                return None
            
            # 如果页数少于等于 max_pages，直接返回原内容
            if total_pages <= max_pages:
                doc.close()
                return pdf_content
            
            # 创建新文档，只包含前 N 页
            new_doc = fitz.open()
            for i in range(min(max_pages, total_pages)):
                new_doc.insert_pdf(doc, from_page=i, to_page=i)
            
            truncated_pdf = new_doc.tobytes()
            
            new_doc.close()
            doc.close()
            
            logger.debug(f"PDF 截取完成: {total_pages} 页 -> {min(max_pages, total_pages)} 页")
            
            return truncated_pdf
            
        except Exception as e:
            logger.error(f"截取 PDF 页面失败: {e}", exc_info=True)
            return None
    
    async def _classify_by_llm(
        self,
        file_name: str,
        file_content: str
    ) -> str:
        """
        使用 LLM 分类文件
        
        Args:
            file_name: 文件名
            file_content: 文件内容
            
        Returns:
            str: 分类后的文件类型枚举值
        """
        try:
            # 构建可选类型列表
            types_list = self._build_types_list()
            
            # 截断内容避免超出 token 限制
            truncated_content = file_content[:self.MAX_CONTENT_LENGTH]
            if len(file_content) > self.MAX_CONTENT_LENGTH:
                truncated_content += "\n\n...(内容已截断)..."
            
            # 调用 LLM 分类 Agent
            classification_config = self.llm_config.get_classification_agent_config()
            
            async with LLMClient(classification_config) as client:
                agent = ClassificationAgent(client)
                result = await agent.classify_file(
                    file_name=file_name,
                    file_content=truncated_content,
                    types_list=types_list
                )
            
            if result.success and result.classified_file_type:
                # 验证分类结果是否在有效范围内
                try:
                    file_type = FileType(result.classified_file_type)
                    return file_type.value
                except ValueError:
                    logger.error(f"LLM 返回的文件类型无效: {result.classified_file_type}")
                    return FileType.OTHER_DOCUMENTS.value
            else:
                logger.warning(f"LLM 分类失败: {result.error}")
                return FileType.OTHER_DOCUMENTS.value
                
        except Exception as e:
            logger.error(f"LLM 分类异常: {e}", exc_info=True)
            return FileType.OTHER_DOCUMENTS.value
    
    def _build_types_list(self) -> str:
        """
        构建可选文件类型列表（格式化为字符串）
        
        Returns:
            str: 格式化的类型列表
        """
        types_items = []
        for file_type, label in FILE_TYPE_LABELS.items():
            types_items.append(f"- {file_type.value}: {label}")
        
        return "\n".join(types_items)


# ============ 单例获取函数 ============


def get_classification_api_service() -> FileClassificationAPIService:
    """
    获取 FileClassificationAPIService 单例
    
    Returns:
        FileClassificationAPIService: 服务实例
    """
    global _classification_api_service_instance
    if _classification_api_service_instance is None:
        _classification_api_service_instance = FileClassificationAPIService()
        logger.debug("创建 FileClassificationAPIService 单例")
    return _classification_api_service_instance
