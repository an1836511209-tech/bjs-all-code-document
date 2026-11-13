"""
文件质量检测API路由

提供文件质量检测相关的REST API接口

性能优化：
- 使用 ProcessPoolExecutor 并行处理 CPU 密集型的图像质量检测
- PDF 多页并行处理，充分利用多核 CPU
"""

import uuid
import asyncio
from datetime import datetime
from typing import List, Dict
from functools import partial

from fastapi import APIRouter, HTTPException, status, BackgroundTasks
from loguru import logger
from PIL import Image
import fitz  # PyMuPDF

from src.schemas.file import (
    FileQualityCheckRequest,
    FileQualityCheckResponse,
    FileQualityCheckItem,
    FileQualityResult,
    QualityStatus,
    QualityResultStatus,
    BaseResponse
)
from src.schemas.base import success_response
from src.services.quality.quality_checker import (
    QualityChecker,
    check_image_quality_from_bytes,
    process_pdf_page
)
from src.utils.file_handler import FileHandler
from src.utils.converters.pdf_converter import PDFConverter
from src.utils.process_pool import ProcessPoolManager
from src.utils.exceptions import FileProcessingError, QualityCheckError, PDFConversionError, ExcelProcessingError, CSVProcessingError, WordProcessingError


router = APIRouter(prefix="/file", tags=["文件质量检测"])


@router.post(
    "/quality-check",
    response_model=FileQualityCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="文件质量检测",
    description="""
    同步检测上传附件的质量，包括清晰度、分辨率、遮挡检测等。
    支持PDF和图片格式文件。
    
    **检测项目：**
    - **清晰度**：使用拉普拉斯方差评估图像清晰度，分数越高表示越清晰
    - **分辨率**：检查图像尺寸是否满足最低要求
    - **遮挡**：检测图像中的噪点、黑斑或其他遮挡物
    
    **支持格式：**
    - 图片：JPG, PNG, BMP, TIFF, WebP
    - 文档：PDF（将转换为图片进行检测）
    - Excel：XLSX, XLSM（检查文件是否可以正常读取，加密文件将返回失败）
    - CSV：CSV（检查文件是否可以正常读取，无法解析的文件将返回失败）
    - Word：DOC, DOCX（检查文件是否可以正常读取，可读取的文件直接通过）
    
    **输入方式：**
    - URL：提供文件的HTTP/HTTPS链接
    - 文件流：Base64编码或Data URI格式的文件内容
    """
)
async def check_file_quality(
    request: FileQualityCheckRequest,
    background_tasks: BackgroundTasks
) -> FileQualityCheckResponse:
    """
    文件质量检测接口（并行处理）
    
    Args:
        request: 质量检测请求
        background_tasks: 后台任务（用于清理临时资源）
        
    Returns:
        FileQualityCheckResponse: 检测结果
    """
    trace_id = f"trace_{uuid.uuid4().hex[:16]}"
    logger.info(f"[{trace_id}] 开始并行文件质量检测，文件数量: {len(request.files)}")
    
    try:
        # 创建并行任务列表
        tasks = []
        for idx, file_input in enumerate(request.files):
            file_id = f"file_{datetime.now().strftime('%Y%m%d%H%M%S')}_{idx:03d}"
            task = _process_single_file(file_input, file_id, trace_id)
            tasks.append(task)
        
        # 并行执行所有文件检测任务
        results = await asyncio.gather(*tasks, return_exceptions=False)
        
        logger.info(f"[{trace_id}] 文件质量检测完成，成功处理 {len(results)} 个文件")
        
        # 使用统一的响应包装函数
        return success_response(
            data=results,
            message="success",
            trace_id=trace_id
        )
        
    except Exception as e:
        logger.error(f"[{trace_id}] 文件质量检测服务异常: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "INTERNAL_ERROR",
                "error_message": "服务器内部错误，请稍后重试",
                "trace_id": trace_id
            }
        )


async def _process_single_file(
    file_input,
    file_id: str,
    trace_id: str
) -> FileQualityCheckItem:
    """
    处理单个文件的质量检测
    
    Args:
        file_input: 文件输入信息
        file_id: 文件ID
        trace_id: 追踪ID
        
    Returns:
        FileQualityCheckItem: 文件检测结果
    """
    try:
        # 处理文件输入
        file_content, file_extension = await FileHandler.process_file_input(
            file_url=file_input.file_url,
            file_stream=file_input.file_stream,
            file_name=file_input.file_name
        )
        
        logger.info(
            f"[{trace_id}] 处理文件 {file_input.file_name}，"
            f"大小: {len(file_content)} bytes, 格式: {file_extension}"
        )
        
        # 根据文件类型进行处理
        if FileHandler.is_pdf_format(file_extension):
            # PDF文件：转换为图像后检测
            quality_result = await _check_pdf_quality(file_content, trace_id)
        elif FileHandler.is_image_format(file_extension):
            # 图像文件：直接检测
            quality_result = await _check_image_quality(file_content, trace_id)
        elif FileHandler.is_excel_format(file_extension):
            # Excel文件：检查是否可以正常读取
            quality_result = await _check_excel_quality(file_content, trace_id)
        elif FileHandler.is_csv_format(file_extension):
            # CSV文件：检查是否可以正常读取
            quality_result = await _check_csv_quality(file_content, trace_id)
        elif FileHandler.is_word_format(file_extension):
            # Word文档：检查是否可以正常读取
            quality_result = await _check_word_quality(file_content, trace_id)
        else:
            raise FileProcessingError(f"不支持的文件格式: {file_extension}")
        
        # 构建检测结果
        result_item = FileQualityCheckItem(
            file_id=file_id,
            file_name=file_input.file_name,
            file_type=file_input.file_type,
            file_url=file_input.file_url,
            quality_status=quality_result['overall_status'],
            quality_result=FileQualityResult(
                clarity=quality_result['clarity']['status'],
                clarity_score=quality_result['clarity'].get('score', 0),
                resolution=quality_result['resolution']['status'],
                resolution_value=quality_result['resolution']['resolution'],
                occlusion=quality_result['occlusion']['status'],
                occlusion_score=quality_result['occlusion']['occlusion_score']
            ),
            message=quality_result['message']
        )
        
        logger.info(
            f"[{trace_id}] 文件 {file_input.file_name} 检测完成，"
            f"状态: {quality_result['overall_status']}"
        )
        
        return result_item
        
    except (FileProcessingError, QualityCheckError, PDFConversionError, ExcelProcessingError, CSVProcessingError, WordProcessingError) as e:
        logger.error(f"[{trace_id}] 文件 {file_input.file_name} 检测失败: {str(e)}")
        
        # 创建失败结果
        return FileQualityCheckItem(
            file_id=file_id,
            file_name=file_input.file_name,
            file_type=file_input.file_type,
            file_url=file_input.file_url,
            quality_status=QualityStatus.FAILED,
            quality_result=FileQualityResult(
                clarity=QualityResultStatus.FAILED,
                clarity_score=100.0,
                resolution=QualityResultStatus.FAILED,
                resolution_value="0x0",
                occlusion=QualityResultStatus.FAILED,
                occlusion_score=1.0
            ),
            message=f"文件处理失败: {str(e)}"
        )
        
    except Exception as e:
        logger.error(f"[{trace_id}] 文件 {file_input.file_name} 发生未知错误: {str(e)}")
        
        # 创建未知错误结果
        return FileQualityCheckItem(
            file_id=file_id,
            file_name=file_input.file_name,
            file_type=file_input.file_type,
            file_url=file_input.file_url,
            quality_status=QualityStatus.FAILED,
            quality_result=FileQualityResult(
                clarity=QualityResultStatus.FAILED,
                clarity_score=100.0,
                resolution=QualityResultStatus.FAILED,
                resolution_value="0x0",
                occlusion=QualityResultStatus.FAILED,
                occlusion_score=1.0
            ),
            message="服务器内部错误，请稍后重试"
        )


async def _check_image_quality(image_content: bytes, trace_id: str) -> dict:
    """
    检测图像质量（使用进程池并行处理）
    
    Args:
        image_content: 图像内容
        trace_id: 追踪ID
        
    Returns:
        dict: 质量检测结果
    """
    try:
        # 验证图像文件
        if not FileHandler.validate_image_file(image_content):
            raise QualityCheckError("无效的图像文件")
        
        # 使用进程池执行 CPU 密集型的质量检测
        loop = asyncio.get_event_loop()
        executor = ProcessPoolManager.get_executor()
        
        # 在进程池中执行质量检测
        result = await loop.run_in_executor(
            executor,
            check_image_quality_from_bytes,
            image_content,
            trace_id
        )
        
        return result
        
    except Exception as e:
        logger.error(f"[{trace_id}] 图像质量检测失败: {str(e)}")
        raise QualityCheckError(f"图像质量检测失败: {str(e)}")


def _aggregate_pdf_quality_results(results: List[Dict], trace_id: str) -> Dict:
    """
    聚合PDF多页质量检测结果

    Args:
        results: 每页的检测结果列表
        trace_id: 追踪ID

    Returns:
        Dict: 聚合后的最终结果
    """
    if not results:
        raise QualityCheckError("PDF页面为空，无法进行质量检测")

    overall_statuses = [r['overall_status'] for r in results]
    
    # 确定最终状态
    if 'failed' in overall_statuses:
        final_status = 'failed'
    elif 'warning' in overall_statuses:
        final_status = 'warning'
    else:
        final_status = 'passed'
    
    # 找到最差的结果作为代表
    worst_result = min(results, key=lambda r: {'passed': 2, 'warning': 1, 'failed': 0}[r['overall_status']])
    
    # 生成聚合消息
    page_issues = []
    for i, r in enumerate(results):
        if r['overall_status'] != 'passed':
            page_issues.append(f"第 {i+1} 页: {r['message']}")
    
    if final_status == 'passed':
        message = "文件质量校验通过"
    else:
        message = f"PDF文件质量存在问题 ({len(page_issues)}/{len(results)} 页有问题): " + "; ".join(page_issues)

    # 用最差页的结果填充，但覆盖状态和消息
    final_result = worst_result.copy()
    final_result['overall_status'] = final_status
    final_result['message'] = message
    final_result['details'] = {
        'page_count': len(results),
        'problematic_pages': len(page_issues),
        'page_by_page_results': results
    }
    
    logger.info(f"[{trace_id}] PDF聚合结果: 最终状态={final_status}, 问题页数={len(page_issues)}/{len(results)}")
    
    return final_result


async def _check_excel_quality(excel_content: bytes, trace_id: str) -> dict:
    """
    检测Excel文件质量（检查是否可以正常读取）
    
    Args:
        excel_content: Excel文件内容
        trace_id: 追踪ID
        
    Returns:
        dict: 质量检测结果
    """
    try:
        # 验证Excel文件是否可以正常读取（检查是否加密）
        if not FileHandler.validate_excel_file(excel_content):
            raise ExcelProcessingError("Excel文件无法读取，可能已加密或文件损坏")
        
        logger.info(f"[{trace_id}] Excel文件验证通过，可以正常读取")
        
        # Excel文件只要能正常读取就通过
        return {
            'overall_status': QualityStatus.PASSED,
            'clarity': {
                'status': QualityResultStatus.PASSED,
                'score': 100.0  # Excel文件不检测清晰度，设为默认值
            },
            'resolution': {
                'status': QualityResultStatus.PASSED,
                'resolution': 'N/A'  # Excel文件不检测分辨率
            },
            'occlusion': {
                'status': QualityResultStatus.PASSED,
                'occlusion_score': 0.0  # Excel文件不检测遮挡
            },
            'message': 'Excel文件可以正常读取'
        }
        
    except ExcelProcessingError as e:
        logger.error(f"[{trace_id}] Excel文件读取失败: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"[{trace_id}] Excel质量检测失败: {str(e)}")
        raise ExcelProcessingError(f"Excel质量检测失败: {str(e)}")


async def _check_csv_quality(csv_content: bytes, trace_id: str) -> dict:
    """
    检测CSV文件质量（检查是否可以正常读取）
    
    Args:
        csv_content: CSV文件内容
        trace_id: 追踪ID
        
    Returns:
        dict: 质量检测结果
    """
    try:
        # 验证CSV文件是否可以正常读取
        if not FileHandler.validate_csv_file(csv_content):
            raise CSVProcessingError("CSV文件无法读取，文件可能损坏或格式错误")
        
        logger.info(f"[{trace_id}] CSV文件验证通过，可以正常读取")
        
        # CSV文件只要能正常读取就通过
        return {
            'overall_status': QualityStatus.PASSED,
            'clarity': {
                'status': QualityResultStatus.PASSED,
                'score': 100.0  # CSV文件不检测清晰度，设为默认值
            },
            'resolution': {
                'status': QualityResultStatus.PASSED,
                'resolution': 'N/A'  # CSV文件不检测分辨率
            },
            'occlusion': {
                'status': QualityResultStatus.PASSED,
                'occlusion_score': 0.0  # CSV文件不检测遮挡
            },
            'message': 'CSV文件可以正常读取'
        }
        
    except CSVProcessingError as e:
        logger.error(f"[{trace_id}] CSV文件读取失败: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"[{trace_id}] CSV质量检测失败: {str(e)}")
        raise CSVProcessingError(f"CSV质量检测失败: {str(e)}")


async def _check_word_quality(word_content: bytes, trace_id: str) -> dict:
    """
    检测Word文档质量（检查是否可以正常读取）
    
    Args:
        word_content: Word文档内容
        trace_id: 追踪ID
        
    Returns:
        dict: 质量检测结果
    """
    try:
        # 验证Word文档是否可以正常读取
        if not FileHandler.validate_word_file(word_content):
            raise WordProcessingError("Word文档无法读取，文件可能损坏或格式错误")
        
        logger.info(f"[{trace_id}] Word文档验证通过，可以正常读取")
        
        # Word文档只要能正常读取就通过
        return {
            'overall_status': QualityStatus.PASSED,
            'clarity': {
                'status': QualityResultStatus.PASSED,
                'score': 100.0  # Word文档不检测清晰度，设为默认值
            },
            'resolution': {
                'status': QualityResultStatus.PASSED,
                'resolution': 'N/A'  # Word文档不检测分辨率
            },
            'occlusion': {
                'status': QualityResultStatus.PASSED,
                'occlusion_score': 0.0  # Word文档不检测遮挡
            },
            'message': 'Word文档可以正常读取'
        }
        
    except WordProcessingError as e:
        logger.error(f"[{trace_id}] Word文档读取失败: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"[{trace_id}] Word质量检测失败: {str(e)}")
        raise WordProcessingError(f"Word质量检测失败: {str(e)}")


async def _check_pdf_quality(pdf_content: bytes, trace_id: str) -> dict:
    """
    检测PDF文件质量（使用进程池并行处理所有页面）
    
    Args:
        pdf_content: PDF内容
        trace_id: 追踪ID
        
    Returns:
        dict: 质量检测结果
    """
    try:
        # 获取 PDF 页数
        doc = fitz.open(stream=pdf_content, filetype="pdf")
        page_count = min(len(doc), 10)  # 限制最大页数防止内存溢出
        doc.close()
        
        if page_count == 0:
            raise PDFConversionError("PDF 文件为空")
        
        logger.info(f"[{trace_id}] PDF 共 {page_count} 页，使用进程池并行检测")
        
        # 使用进程池并行处理所有页面
        loop = asyncio.get_event_loop()
        executor = ProcessPoolManager.get_executor()
        
        # 创建所有页面的处理任务
        tasks = [
            loop.run_in_executor(
                executor,
                process_pdf_page,
                pdf_content,
                page_num,
                200  # DPI
            )
            for page_num in range(page_count)
        ]
        
        # 并行执行所有页面的检测
        page_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常结果
        valid_results = []
        for i, result in enumerate(page_results):
            if isinstance(result, Exception):
                logger.warning(f"[{trace_id}] PDF 第 {i+1} 页处理失败: {str(result)}")
                # 创建失败结果
                valid_results.append({
                    'overall_status': 'failed',
                    'clarity': {'status': 'failed', 'score': 0},
                    'resolution': {'status': 'failed', 'resolution': '0x0'},
                    'occlusion': {'status': 'failed', 'occlusion_score': 1.0},
                    'message': f'页面处理失败: {str(result)}'
                })
            else:
                valid_results.append(result)
        
        if not valid_results:
            raise PDFConversionError("PDF 所有页面处理失败")

        # 聚合所有页面的结果
        return _aggregate_pdf_quality_results(valid_results, trace_id)
        
    except PDFConversionError as e:
        logger.error(f"[{trace_id}] PDF转换失败: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"[{trace_id}] PDF质量检测失败: {str(e)}")
        raise QualityCheckError(f"PDF质量检测失败: {str(e)}")


@router.get(
    "/health",
    summary="健康检查",
    description="检查文件质量检测服务是否正常运行"
)
async def health_check():
    """健康检查接口"""
    return success_response(
        data={"status": "healthy", "service": "file_quality_check"},
        message="File quality service is healthy"
    )
