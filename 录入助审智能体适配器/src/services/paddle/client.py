"""
Paddle 客户端

提供 PaddleOCR-VL 和印章识别服务的完整封装
支持与 MinerU 相同的接口，确保上下游兼容
"""

import asyncio
import base64
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Union, List, Tuple
from io import BytesIO

import fitz
import httpx
from loguru import logger

from config.paddle_config import (
    get_paddle_config,
    get_api_endpoint,
    get_structure_token,
    CURRENT_ENV,
    PADDLE_STRUCTURE_OPTIONS
)
from src.services.paddle.models import (
    PaddleOCRVLResponse,
    PaddleLayoutParsingResult,
    PaddleSealRecognitionResponse,
    PaddleParseResult,
    PaddlePage,
    PaddleContent,
    PaddleLayoutBlock,
    PaddleLine,
    PaddleSpan,
    MarkdownResult,
    SealDetection,
    TableSealInfo,
    PaddleTableCell,
    create_bbox_from_list
)
from PIL import Image


# 全局单例实例
_paddle_client_instance: Optional['PaddleClient'] = None


class PaddleError(Exception):
    """Paddle服务错误"""
    pass


class PaddleClient:
    """
    Paddle API客户端
    
    整合 PaddleOCR-VL 和印章识别两个服务
    提供与 MinerU 兼容的接口
    """
    
    def __init__(self, env: str = None):
        """
        初始化Paddle客户端
        
        Args:
            env: 环境名称（dev/prod），默认使用配置文件中的环境
        """
        self.env = env or CURRENT_ENV
        self.config = get_paddle_config(self.env)
        
        # API配置
        self.ocr_vl_config = self.config['api']['ocr_vl']
        self.structure_config = self.config['api']['structure']
        self.seal_config = self.config['api']['seal_recognition']
        
        # 解析选项
        self.ocr_vl_options = self.config['ocr_vl_options']
        self.structure_options = self.config.get('structure_options', PADDLE_STRUCTURE_OPTIONS)
        self.seal_recognition_options = self.config['seal_recognition_options']
        self.seal_extract_config = self.config['seal_config']
        
        # 错误处理配置
        self.error_config = self.config['error']
        self.debug_config = self.config['debug']
        
        # 性能配置
        self.performance_config = self.config['performance']

        # 最近一次 OCR-VL API 原始 JSON 响应（供调试/复现脚本使用）
        self._last_ocr_vl_raw_json: Optional[Dict[str, Any]] = None
        
        # 并发控制配置（延迟初始化 semaphore，确保在事件循环中创建）
        # OCR-VL 并发配置（VL 模型较重，并发数较低）
        self._max_concurrent_ocr_vl = self.performance_config.get('max_concurrent_requests_ocr_vl', 3)
        self._semaphore_ocr_vl: Optional[asyncio.Semaphore] = None
        # PaddleStructureV3 并发配置（相对轻量，可适当提高）
        self._max_concurrent_structure = self.performance_config.get('max_concurrent_requests_structure', 5)
        self._semaphore_structure: Optional[asyncio.Semaphore] = None
        # 印章识别并发配置（较轻量，可以并发更高）
        self._max_concurrent_seal = self.performance_config.get('max_concurrent_requests_seal', 10)
        self._semaphore_seal: Optional[asyncio.Semaphore] = None
        
        # 创建HTTP客户端
        self.client = httpx.AsyncClient(
            timeout=self.ocr_vl_config['timeout'],
            follow_redirects=True,
            verify=False  # 禁用SSL验证（测试环境）
        )
        
        logger.info(
            f"Paddle客户端初始化完成 | "
            f"环境: {self.env} | "
            f"OCR-VL并发: {self._max_concurrent_ocr_vl} | "
            f"Structure并发: {self._max_concurrent_structure} | "
            f"印章识别并发: {self._max_concurrent_seal} | "
            f"OCR-VL: {self.ocr_vl_config['base_url']} | "
            f"Structure: {self.structure_config['base_url']} | "
            f"印章识别: {self.seal_config['base_url']}"
        )
    
    @property
    def semaphore_ocr_vl(self) -> asyncio.Semaphore:
        """
        懒加载 OCR-VL 并发控制信号量
        
        确保在事件循环运行时才创建 Semaphore，避免在模块导入时
        （没有事件循环）创建导致的并发控制失效问题。
        """
        if self._semaphore_ocr_vl is None:
            self._semaphore_ocr_vl = asyncio.Semaphore(self._max_concurrent_ocr_vl)
            logger.info(f"创建 OCR-VL 并发控制信号量，最大并发数: {self._max_concurrent_ocr_vl}")
        return self._semaphore_ocr_vl
    
    @property
    def semaphore_seal(self) -> asyncio.Semaphore:
        """
        懒加载印章识别并发控制信号量
        
        确保在事件循环运行时才创建 Semaphore，避免在模块导入时
        （没有事件循环）创建导致的并发控制失效问题。
        """
        if self._semaphore_seal is None:
            self._semaphore_seal = asyncio.Semaphore(self._max_concurrent_seal)
            logger.info(f"创建印章识别并发控制信号量，最大并发数: {self._max_concurrent_seal}")
        return self._semaphore_seal
    
    @property
    def semaphore_structure(self) -> asyncio.Semaphore:
        """
        懒加载 PaddleStructureV3 并发控制信号量
        
        确保在事件循环运行时才创建 Semaphore，避免在模块导入时
        （没有事件循环）创建导致的并发控制失效问题。
        """
        if self._semaphore_structure is None:
            self._semaphore_structure = asyncio.Semaphore(self._max_concurrent_structure)
            logger.info(f"创建 PaddleStructure 并发控制信号量，最大并发数: {self._max_concurrent_structure}")
        return self._semaphore_structure
    
    async def close(self):
        """关闭客户端"""
        await self.client.aclose()
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()
    
    async def parse_file(
        self,
        file_path: Optional[Union[str, Path]] = None,
        file_content: Optional[bytes] = None,
        file_name: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> PaddleParseResult:
        """
        解析文档文件（与 MinerU 兼容的接口）
        
        处理流程：
        1. 调用 PaddleOCR-VL 进行版面解析
        2. 提取所有印章（base64）
        3. 调用印章识别服务识别印章文本
        4. 将印章文本合并到主文本中
        5. 返回与 MinerU 兼容的解析结果
        
        Args:
            file_path: 文件路径或URL
            file_content: 文件内容（字节）
            file_name: 文件名称
            options: 解析选项
            
        Returns:
            PaddleParseResult: 解析结果（兼容 MinerU）
            
        Raises:
            PaddleError: 解析失败时抛出
        """
        start_time = time.time()
        
        try:
            # 准备文件内容
            if file_path:
                file_path_str = str(file_path)
                
                # 检查是否为 URL
                if file_path_str.startswith(('http://', 'https://')):
                    # 从 URL 下载文件
                    # 使用统一的文件处理器（带重试和更长超时）
                    logger.info(f"从 URL 下载文件: {file_path_str}")
                    from src.utils.file_handler import FileHandler
                    file_content, _ = await FileHandler._download_from_url(
                        file_path_str,
                        max_retries=3,
                        timeout=120.0
                    )
                    
                    # 从 URL 中提取文件名
                    if not file_name:
                        from urllib.parse import urlparse, unquote
                        parsed_url = urlparse(file_path_str)
                        file_name = unquote(Path(parsed_url.path).name)
                else:
                    # 本地文件路径
                    file_path = Path(file_path)
                    file_name = file_name or file_path.name
                    with open(file_path, 'rb') as f:
                        file_content = f.read()
            elif file_content is None:
                raise ValueError("必须提供 file_path 或 file_content")
            
            if not file_name:
                file_name = 'unknown_file'
            
            # 获取文件类型
            file_type = Path(file_name).suffix.lower()
            pdf_page_sizes: Optional[List[Tuple[float, float]]] = None
            local_rotation_map: Dict[int, int] = {}
            rotation_detection_available = False
            if file_type == '.pdf':
                pdf_page_sizes = self._get_pdf_page_sizes(file_content)

                # 前置旋转检测：单例模型矫正页面方向，避免 Paddle 内部旋转损失 OCR 精度
                try:
                    from src.utils.rotation_detector import get_rotation_detector
                    detector = get_rotation_detector()
                    if detector is None:
                        raise ImportError("RotationDetector 单例加载失败（见此前日志）")
                    file_content, local_rotation_map = detector.preprocess_pdf(file_content)
                    rotation_detection_available = True
                    if any(v != 0 for v in local_rotation_map.values()):
                        logger.info(f"前置旋转检测完成，矫正页面: {local_rotation_map}")
                    else:
                        logger.debug("前置旋转检测完成，所有页面方向正常")
                except (FileNotFoundError, ImportError) as e:
                    logger.warning(
                        f"旋转检测模型不可用: {e}，"
                        f"回退到 Paddle 内置方向分类（useDocOrientationClassify=True）"
                    )
                except Exception as e:
                    logger.warning(f"前置旋转检测异常: {e}，回退到 Paddle 内置方向分类")
            elif file_type in {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}:
                # 图像文件：检测并物理旋转
                try:
                    from src.utils.rotation_detector import get_rotation_detector
                    detector = get_rotation_detector()
                    if detector is None:
                        raise ImportError("RotationDetector 单例加载失败（见此前日志）")
                    file_content, img_rotation = detector.preprocess_image(file_content)
                    rotation_detection_available = True
                    if img_rotation != 0:
                        logger.info(f"图像旋转检测完成，已矫正 {img_rotation}°")
                        local_rotation_map = {0: img_rotation}  # 记录检测值（物理已旋转，但保留溯源）
                    else:
                        logger.debug("图像方向正常")
                except (FileNotFoundError, ImportError) as e:
                    logger.warning(
                        f"旋转检测模型不可用: {e}，回退到 Paddle 内置方向分类"
                    )
                except Exception as e:
                    logger.warning(f"图像旋转检测异常: {e}，回退到 Paddle 内置方向分类")

            # 如果本地旋转检测不可用，回退使用 Paddle 内置方向分类
            if not rotation_detection_available:
                if options is None:
                    options = {}
                options = {**options, 'useDocOrientationClassify': True}
                logger.info("已回退：useDocOrientationClassify=True（使用 Paddle 内置旋转处理）")

            # 1. 调用 PaddleOCR-VL 进行版面解析
            ocr_vl_result = await self._call_ocr_vl(file_content, file_name, options)
            
            # 2. 并行提取印章：普通印章 + 表格内印章
            seal_texts_by_page = {}
            table_seals_by_page = {}
            
            seal_tasks = []
            if self.seal_extract_config['enabled']:
                seal_tasks.append(('seal', self._extract_seal_texts(
                    ocr_vl_result, 
                    file_content, 
                    file_name
                )))
            
            table_seal_config = self.seal_extract_config.get('table_seal_recognition', {})
            if table_seal_config.get('enabled', False):
                seal_tasks.append(('table_seal', self._extract_table_seals(
                    ocr_vl_result,
                    file_content,
                    file_name,
                    file_type
                )))
            
            if seal_tasks:
                # 并行执行所有印章识别任务
                results = await asyncio.gather(
                    *[task for _, task in seal_tasks],
                    return_exceptions=True
                )
                for (task_type, _), result in zip(seal_tasks, results):
                    if isinstance(result, Exception):
                        logger.warning(f"印章识别任务 {task_type} 失败: {result}")
                        continue
                    if task_type == 'seal':
                        seal_texts_by_page = result
                    elif task_type == 'table_seal':
                        table_seals_by_page = result
            
            # 4. 转换为兼容 MinerU 的格式
            parse_result = self._convert_to_parse_result(
                ocr_vl_result,
                seal_texts_by_page,
                file_name,
                file_type,
                pdf_page_sizes=pdf_page_sizes,
                table_seals_by_page=table_seals_by_page,
                local_rotation_map=local_rotation_map,
            )

            # 记录解析时间
            parse_time = time.time() - start_time
            parse_result.parse_time = parse_time

            # 如果 PDF 被本地 RotationDetector 修改过（/Rotate 纠正），
            # 将修改后的文件内容存入 parse_result，供下游高亮器使用
            # 确保高亮器打开的 PDF 与 Paddle OCR 的是同一份
            if local_rotation_map and any(v != 0 for v in local_rotation_map.values()):
                parse_result.corrected_file_content = file_content
                logger.info(
                    f"已将修正后的 PDF 存入 parse_result（{file_name}），"
                    f"高亮器将使用此版本以保证坐标系一致"
                )

            logger.info(f"文档解析完成: {file_name}, 总耗时: {parse_time:.2f}秒")
            
            if not parse_result.success:
                logger.error(f"Paddle解析失败 | {file_name}: {parse_result.error_message}")
            
            # 调试输出解析结果详情
            if self.debug_config.get('enabled') or self.debug_config.get('verbose'):
                self._debug_print_parse_result(parse_result, seal_texts_by_page, table_seals_by_page)
            
            return parse_result
            
        except httpx.HTTPError as e:
            logger.error(f"Paddle API调用失败: {e}")
            raise PaddleError(f"API调用失败: {str(e)}")
        except ValueError as e:
            # ValueError直接抛出（不包装）
            raise
        except Exception as e:
            logger.error(f"文件解析异常: {e}", exc_info=True)
            raise PaddleError(f"解析失败: {str(e)}")
    
    async def parse_file_with_strategy(
        self,
        file_path: Optional[Union[str, Path]] = None,
        file_content: Optional[bytes] = None,
        file_name: Optional[str] = None,
        business_file_type: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> PaddleParseResult:
        """
        根据文件类型选择解析策略
        
        策略规则：
        - 使用 PaddleOCR-VL 的文件类型:
          - 信息披露申请书 (info_disclosure_application): VL 能识别打勾、空格等特殊符号
          - 房屋产权所有证/不动产权证 (property_certificate): 证照类文件更适合 VL 模式
          - 返回整表级别坐标
          - 需要调用独立印章服务
          
        - 其他所有文件类型: 使用 PaddleStructureV3
          - 返回单元格级别坐标
          - Structure 仅检测印章位置时，二次调用 /seal-recognition 识别文字
        
        Args:
            file_path: 文件路径或URL
            file_content: 文件内容（字节）
            file_name: 文件名称
            business_file_type: 业务文件类型（FileType 枚举值的字符串）
            options: 解析选项
            
        Returns:
            PaddleParseResult: 解析结果
        """
        # 需要使用 VL 模式解析的文件类型
        vl_file_types = {
            'info_disclosure_application',  # 信息披露申请书
            'property_certificate',         # 房屋产权所有证/不动产权证
        }
        use_vl_mode = business_file_type in vl_file_types
        
        if use_vl_mode:
            # 使用 VL 模式
            logger.info(f"使用 VL 模式解析: {file_name}, 业务类型: {business_file_type}")
            return await self.parse_file(
                file_path=file_path,
                file_content=file_content,
                file_name=file_name,
                options=options
            )
        else:
            # 使用 Structure 模式
            logger.info(f"使用 Structure 模式解析: {file_name}, 业务类型: {business_file_type}")
            return await self._parse_with_structure(
                file_path=file_path,
                file_content=file_content,
                file_name=file_name,
                options=options
            )
    
    async def _parse_with_structure(
        self,
        file_path: Optional[Union[str, Path]] = None,
        file_content: Optional[bytes] = None,
        file_name: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> PaddleParseResult:
        """
        使用 PaddleStructureV3 解析文件
        
        特点：
        - 支持单元格级别坐标
        - 对 seal 块 / img_in_seal_box 裁剪后调用 /seal-recognition 识别印章文字
        
        Args:
            file_path: 文件路径或URL
            file_content: 文件内容（字节）
            file_name: 文件名称
            options: 解析选项
            
        Returns:
            PaddleParseResult: 解析结果
        """
        start_time = time.time()
        
        try:
            # 准备文件内容
            if file_path:
                file_path_str = str(file_path)
                
                # 检查是否为 URL
                if file_path_str.startswith(('http://', 'https://')):
                    # 从 URL 下载文件
                    logger.info(f"从 URL 下载文件: {file_path_str}")
                    from src.utils.file_handler import FileHandler
                    file_content, _ = await FileHandler._download_from_url(
                        file_path_str,
                        max_retries=3,
                        timeout=120.0
                    )
                    
                    # 从 URL 中提取文件名
                    if not file_name:
                        from urllib.parse import urlparse, unquote
                        parsed_url = urlparse(file_path_str)
                        file_name = unquote(Path(parsed_url.path).name)
                else:
                    # 本地文件路径
                    file_path = Path(file_path)
                    file_name = file_name or file_path.name
                    with open(file_path, 'rb') as f:
                        file_content = f.read()
            elif file_content is None:
                raise ValueError("必须提供 file_path 或 file_content")
            
            if not file_name:
                file_name = 'unknown_file'
            
            # 获取文件类型
            file_type = Path(file_name).suffix.lower()
            pdf_page_sizes: Optional[List[Tuple[float, float]]] = None
            local_rotation_map: Dict[int, int] = {}
            rotation_detection_available = False
            if file_type == '.pdf':
                pdf_page_sizes = self._get_pdf_page_sizes(file_content)

                # 前置旋转检测：单例模型矫正页面方向
                try:
                    from src.utils.rotation_detector import get_rotation_detector
                    detector = get_rotation_detector()
                    if detector is None:
                        raise ImportError("RotationDetector 单例加载失败（见此前日志）")
                    file_content, local_rotation_map = detector.preprocess_pdf(file_content)
                    rotation_detection_available = True
                    if any(v != 0 for v in local_rotation_map.values()):
                        logger.info(f"[Structure] 前置旋转检测完成，矫正页面: {local_rotation_map}")
                    else:
                        logger.debug("[Structure] 前置旋转检测完成，所有页面方向正常")
                except (FileNotFoundError, ImportError) as e:
                    logger.warning(
                        f"[Structure] 旋转检测模型不可用: {e}，"
                        f"回退到 Paddle 内置方向分类（useDocOrientationClassify=True）"
                    )
                except Exception as e:
                    logger.warning(f"[Structure] 前置旋转检测异常: {e}，回退到 Paddle 内置方向分类")
            elif file_type in {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}:
                # 图像文件：检测并物理旋转
                try:
                    from src.utils.rotation_detector import get_rotation_detector
                    detector = get_rotation_detector()
                    if detector is None:
                        raise ImportError("RotationDetector 单例加载失败（见此前日志）")
                    file_content, img_rotation = detector.preprocess_image(file_content)
                    rotation_detection_available = True
                    if img_rotation != 0:
                        logger.info(f"[Structure] 图像旋转检测完成，已矫正 {img_rotation}°")
                        local_rotation_map = {0: img_rotation}
                    else:
                        logger.debug("[Structure] 图像方向正常")
                except (FileNotFoundError, ImportError) as e:
                    logger.warning(f"[Structure] 旋转检测模型不可用: {e}，回退到 Paddle 内置方向分类")
                except Exception as e:
                    logger.warning(f"[Structure] 图像旋转检测异常: {e}，回退到 Paddle 内置方向分类")

            # 如果本地旋转检测不可用，回退使用 Paddle 内置方向分类
            if not rotation_detection_available:
                if options is None:
                    options = {}
                options = {**options, 'useDocOrientationClassify': True}
                logger.info("[Structure] 已回退：useDocOrientationClassify=True（使用 Paddle 内置旋转处理）")

            # 调用 PaddleStructureV3 进行解析
            structure_result = await self._call_structure(file_content, file_name, options)

            # 二次印章识别：Structure 可能只返回 img_in_seal_box 占位图，需调 /seal-recognition
            seal_texts_by_page: Dict[int, List[SealDetection]] = {}
            table_seals_by_page: Dict[int, Dict[int, List[TableSealInfo]]] = {}
            if self.seal_extract_config.get('enabled'):
                vl_like_result = self._structure_result_to_vl_response(structure_result)
                seal_tasks = [
                    ('seal', self._extract_seal_texts(vl_like_result, file_content, file_name))
                ]
                table_seal_config = self.seal_extract_config.get('table_seal_recognition', {})
                if table_seal_config.get('enabled', False):
                    seal_tasks.append(
                        ('table_seal', self._extract_table_seals(
                            vl_like_result, file_content, file_name, file_type
                        ))
                    )
                if seal_tasks:
                    seal_results = await asyncio.gather(
                        *[task for _, task in seal_tasks],
                        return_exceptions=True,
                    )
                    for (task_type, _), task_result in zip(seal_tasks, seal_results):
                        if isinstance(task_result, Exception):
                            logger.warning(f"[Structure] 印章识别任务 {task_type} 失败: {task_result}")
                            continue
                        if task_type == 'seal':
                            seal_texts_by_page = task_result
                        elif task_type == 'table_seal':
                            table_seals_by_page = task_result
            
            # 转换为 PaddleParseResult
            parse_result = self._parse_structure_response(
                structure_result,
                file_name,
                file_type,
                pdf_page_sizes,
                local_rotation_map=local_rotation_map,
                seal_texts_by_page=seal_texts_by_page,
                table_seals_by_page=table_seals_by_page,
            )

            # 记录解析时间
            parse_time = time.time() - start_time
            parse_result.parse_time = parse_time

            # 如果 PDF 被本地 RotationDetector 修改过（/Rotate 纠正），
            # 将修改后的文件内容存入 parse_result，供下游高亮器使用
            if local_rotation_map and any(v != 0 for v in local_rotation_map.values()):
                parse_result.corrected_file_content = file_content
                logger.info(
                    f"[Structure] 已将修正后的 PDF 存入 parse_result（{file_name}），"
                    f"高亮器将使用此版本以保证坐标系一致"
                )

            logger.info(f"Structure 解析完成: {file_name}, 总耗时: {parse_time:.2f}秒")
            
            if not parse_result.success:
                logger.error(f"Structure 解析失败 | {file_name}: {parse_result.error_message}")
            
            return parse_result
            
        except httpx.HTTPError as e:
            logger.error(f"Structure API调用失败: {e}")
            raise PaddleError(f"API调用失败: {str(e)}")
        except ValueError as e:
            raise
        except Exception as e:
            logger.error(f"Structure 解析异常: {e}", exc_info=True)
            raise PaddleError(f"Structure 解析失败: {str(e)}")
    
    async def _call_ocr_vl(
        self,
        file_content: bytes,
        file_name: str,
        options: Optional[Dict[str, Any]] = None
    ) -> PaddleOCRVLResponse:
        """
        调用 PaddleOCR-VL API
        
        Args:
            file_content: 文件内容
            file_name: 文件名
            options: 解析选项
            
        Returns:
            PaddleOCRVLResponse: API响应结果
        """
        # 使用信号量控制并发
        logger.debug(f"[并发控制] 等待获取 OCR-VL 信号量: {file_name}")
        async with self.semaphore_ocr_vl:
            logger.info(f"[并发控制] 获取信号量成功，开始 OCR-VL 解析: {file_name}")
            url = get_api_endpoint('ocr_vl', self.env)
            
            # 将文件内容转换为 base64
            file_base64 = base64.b64encode(file_content).decode('utf-8')
            
            # 合并解析选项
            parse_opts = {**self.ocr_vl_options, **(options or {})}
            
            # 根据文件扩展名自动设置 fileType（如果未指定）
            if 'fileType' not in parse_opts or parse_opts['fileType'] is None:
                file_ext = Path(file_name).suffix.lower()
                if file_ext == '.pdf':
                    parse_opts['fileType'] = 0  # PDF 文件
                elif file_ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp']:
                    parse_opts['fileType'] = 1  # 图像文件
                else:
                    # 默认按 PDF 处理
                    parse_opts['fileType'] = 0
            
            # 准备请求体
            request_body = {
                'file': file_base64,
                **{k: v for k, v in parse_opts.items() if v is not None}
            }
            
            # 调试日志：输出实际发送的参数（不包含file内容）
            debug_params = {k: v for k, v in request_body.items() if k != 'file'}
            logger.debug(f"PaddleOCR-VL 请求参数: {debug_params}")
            
            # 重试逻辑
            max_retries = self.ocr_vl_config['max_retries']
            retry_delay = self.ocr_vl_config['retry_delay']
            
            last_error = None
            for attempt in range(max_retries):
                try:
                    response = await self.client.post(
                        url,
                        json=request_body
                    )
                    
                    # 检查响应状态
                    if response.status_code == 200:
                        try:
                            result = response.json()
                        except json.JSONDecodeError as e:
                            error_msg = f"JSON解析失败: {e}, 响应内容: {response.text[:200]}"
                            logger.error(error_msg)
                            raise PaddleError(error_msg)
                        
                        self._last_ocr_vl_raw_json = result
                        self._save_debug_payload('paddle_ocr_vl', result)
                        if self.debug_config.get('verbose'):
                            logger.debug(f"OCR-VL 原始响应: {json.dumps(result, ensure_ascii=False)[:2000]}")

                        # 解析响应
                        logger.debug(f"[并发控制] OCR-VL 请求完成，即将释放信号量: {file_name}")
                        return self._parse_ocr_vl_response(result)
                    else:
                        # 尝试解析错误响应
                        try:
                            error_result = response.json()
                            error_msg = f"API返回错误: {error_result.get('errorMsg', 'Unknown error')} (状态码: {response.status_code})"
                        except:
                            error_msg = f"API返回错误状态码: {response.status_code}, 响应: {response.text[:200]}"
                        
                        self._save_debug_payload('paddle_ocr_vl_error', response.text, suffix='txt')
                        
                        # 检查是否可重试
                        if response.status_code in self.error_config['retryable_status_codes']:
                            last_error = PaddleError(error_msg)
                            if attempt < max_retries - 1:
                                logger.debug(f"OCR-VL重试 ({attempt + 2}/{max_retries})")
                                await asyncio.sleep(retry_delay)
                                continue
                        
                        logger.warning(error_msg)
                        raise PaddleError(error_msg)
                        
                except httpx.TimeoutException as e:
                    last_error = PaddleError(f"请求超时: {str(e)}")
                    if attempt < max_retries - 1:
                        logger.debug(f"OCR-VL超时重试 ({attempt + 2}/{max_retries})")
                        await asyncio.sleep(retry_delay)
                        continue
                    logger.warning(f"OCR-VL请求超时: {e}")
                        
                except httpx.RequestError as e:
                    last_error = PaddleError(f"请求错误: {str(e)}")
                    if attempt < max_retries - 1:
                        logger.debug(f"OCR-VL请求错误重试 ({attempt + 2}/{max_retries})")
                        await asyncio.sleep(retry_delay)
                        continue
                    logger.warning(f"OCR-VL请求错误: {e}")
            
            # 所有重试都失败了
            raise last_error or PaddleError("API调用失败")
    
    def _parse_ocr_vl_response(self, result: Dict[str, Any]) -> PaddleOCRVLResponse:
        """
        解析 PaddleOCR-VL 响应
        
        Args:
            result: API响应JSON
            
        Returns:
            PaddleOCRVLResponse: 解析后的响应对象
        """
        try:
            log_id = result.get('logId', '')
            error_code = result.get('errorCode', -1)
            error_msg = result.get('errorMsg', 'Unknown error')
            
            if error_code != 0:
                raise PaddleError(f"OCR-VL 解析失败: {error_msg}")
            
            result_data = result.get('result', {})
            layout_parsing_results = result_data.get('layoutParsingResults', [])
            data_info = result_data.get('dataInfo', {})
            
            # 解析每页的结果
            parsed_results = []
            for page_result in layout_parsing_results:
                pruned_result = page_result.get('prunedResult', {})
                markdown_data = page_result.get('markdown', {})
                output_images = page_result.get('outputImages')
                input_image = page_result.get('inputImage')
                
                # 解析 Markdown 结果
                markdown_text_raw = markdown_data.get('text', '')
                logger.debug(f"Paddle API 返回页面 markdown.text 长度: {len(markdown_text_raw)} 字符")
                
                markdown = MarkdownResult(
                    text=markdown_text_raw,
                    images=markdown_data.get('images', {}),
                    is_start=markdown_data.get('isStart', True),
                    is_end=markdown_data.get('isEnd', True)
                )
                
                # 解析文档预处理结果中的旋转角度
                doc_preprocessor_res = pruned_result.get('doc_preprocessor_res') or {}
                rotation_angle = int(doc_preprocessor_res.get('angle', 0) or 0)
                if rotation_angle != 0:
                    logger.info(f"检测到文档旋转角度: {rotation_angle}°（逆时针）")
                else:
                    logger.debug(f"页面无旋转（doc_preprocessor_res: {bool(doc_preprocessor_res)}）")
                
                from src.services.paddle.models import PaddleLayoutParsingResult
                parsed_results.append(PaddleLayoutParsingResult(
                    pruned_result=pruned_result,
                    markdown=markdown,
                    output_images=output_images,
                    input_image=input_image,
                    rotation_angle=rotation_angle
                ))
            
            return PaddleOCRVLResponse(
                log_id=log_id,
                error_code=error_code,
                error_msg=error_msg,
                layout_parsing_results=parsed_results,
                data_info=data_info
            )
            
        except Exception as e:
            logger.error(f"解析 OCR-VL 响应失败: {e}", exc_info=True)
            raise PaddleError(f"响应解析失败: {str(e)}")
    
    async def _call_structure(
        self,
        file_content: bytes,
        file_name: str,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        调用 PaddleStructureV3 API
        
        用于非信息披露申请书的文件，支持单元格级别坐标
        
        Args:
            file_content: 文件内容
            file_name: 文件名
            options: 解析选项
            
        Returns:
            Dict[str, Any]: API 响应的 result 部分
        """
        # 使用信号量控制并发
        logger.debug(f"[并发控制] 等待获取 Structure 信号量: {file_name}")
        async with self.semaphore_structure:
            logger.info(f"[并发控制] 获取信号量成功，开始 Structure 解析: {file_name}")
            url = get_api_endpoint('structure', self.env)
            token = get_structure_token(self.env)
            
            # 将文件内容转换为 base64
            file_base64 = base64.b64encode(file_content).decode('utf-8')
            
            # 合并解析选项
            parse_opts = {**self.structure_options, **(options or {})}
            
            # 根据文件扩展名自动设置 fileType（如果未指定）
            if 'fileType' not in parse_opts or parse_opts['fileType'] is None:
                file_ext = Path(file_name).suffix.lower()
                if file_ext == '.pdf':
                    parse_opts['fileType'] = 0  # PDF 文件
                elif file_ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp']:
                    parse_opts['fileType'] = 1  # 图像文件
                else:
                    # 默认按 PDF 处理
                    parse_opts['fileType'] = 0
            
            # 准备请求体
            request_body = {
                'file': file_base64,
                **{k: v for k, v in parse_opts.items() if v is not None}
            }
            
            # 准备请求头（Structure 需要 token 认证）
            headers = {
                "Authorization": f"token {token}",
                "Content-Type": "application/json"
            }
            
            # 调试日志：输出实际发送的参数（不包含file内容）
            debug_params = {k: v for k, v in request_body.items() if k != 'file'}
            logger.debug(f"PaddleStructure 请求参数: {debug_params}")
            
            # 重试逻辑
            max_retries = self.structure_config['max_retries']
            retry_delay = self.structure_config['retry_delay']
            
            last_error = None
            for attempt in range(max_retries):
                try:
                    response = await self.client.post(
                        url,
                        json=request_body,
                        headers=headers,
                        timeout=self.structure_config['timeout']
                    )
                    
                    # 检查响应状态
                    if response.status_code == 200:
                        try:
                            result = response.json()
                        except json.JSONDecodeError as e:
                            error_msg = f"JSON解析失败: {e}, 响应内容: {response.text[:200]}"
                            logger.error(error_msg)
                            raise PaddleError(error_msg)
                        
                        self._save_debug_payload('paddle_structure', result)
                        if self.debug_config.get('verbose'):
                            logger.debug(f"Structure 原始响应: {json.dumps(result, ensure_ascii=False)[:2000]}")
                        
                        # 检查 API 级别错误
                        error_code = result.get('errorCode', 0)
                        if error_code != 0:
                            error_msg = result.get('errorMsg', 'Unknown error')
                            raise PaddleError(f"Structure API 错误: {error_msg}")
                        
                        logger.debug(f"[并发控制] Structure 请求完成，即将释放信号量: {file_name}")
                        return result.get('result', {})
                    else:
                        # 尝试解析错误响应
                        try:
                            error_result = response.json()
                            error_msg = f"API返回错误: {error_result.get('errorMsg', 'Unknown error')} (状态码: {response.status_code})"
                        except:
                            error_msg = f"API返回错误状态码: {response.status_code}, 响应: {response.text[:200]}"
                        
                        self._save_debug_payload('paddle_structure_error', response.text, suffix='txt')
                        
                        # 检查是否可重试
                        if response.status_code in self.error_config['retryable_status_codes']:
                            last_error = PaddleError(error_msg)
                            if attempt < max_retries - 1:
                                logger.debug(f"Structure重试 ({attempt + 2}/{max_retries})")
                                await asyncio.sleep(retry_delay)
                                continue
                        
                        logger.warning(error_msg)
                        raise PaddleError(error_msg)
                        
                except httpx.TimeoutException as e:
                    last_error = PaddleError(f"请求超时: {str(e)}")
                    if attempt < max_retries - 1:
                        logger.debug(f"Structure超时重试 ({attempt + 2}/{max_retries})")
                        await asyncio.sleep(retry_delay)
                        continue
                    logger.warning(f"Structure请求超时: {e}")
                        
                except httpx.RequestError as e:
                    last_error = PaddleError(f"请求错误: {str(e)}")
                    if attempt < max_retries - 1:
                        logger.debug(f"Structure请求错误重试 ({attempt + 2}/{max_retries})")
                        await asyncio.sleep(retry_delay)
                        continue
                    logger.warning(f"Structure请求错误: {e}")
            
            # 所有重试都失败了
            raise last_error or PaddleError("Structure API调用失败")
    
    def _parse_structure_response(
        self,
        result: Dict[str, Any],
        file_name: str,
        file_type: str,
        pdf_page_sizes: Optional[List[Tuple[float, float]]] = None,
        local_rotation_map: Optional[Dict[int, int]] = None,
        seal_texts_by_page: Optional[Dict[int, List[SealDetection]]] = None,
        table_seals_by_page: Optional[Dict[int, Dict[int, List[TableSealInfo]]]] = None,
    ) -> PaddleParseResult:
        """
        解析 PaddleStructureV3 响应，转换为兼容 MinerU 的格式
        
        坐标系统：与 VL 保持一致，使用 144 DPI 像素坐标
        - Structure 返回的 block_bbox、cell_box_list 都是 144 DPI 像素坐标
        - 页面尺寸从 dataInfo 获取（Paddle 渲染后的像素尺寸）
        - 不使用 pdf_page_sizes（PDF 点坐标），确保与 VL 坐标系一致
        
        Args:
            result: _call_structure 返回的 result 字典
            file_name: 文件名
            file_type: 文件类型（.pdf 等）
            pdf_page_sizes: PDF 页面尺寸列表（未使用，保留参数兼容性）
            seal_texts_by_page: /seal-recognition 识别的印章文字（按页）
            table_seals_by_page: 表格内印章识别结果
            
        Returns:
            PaddleParseResult: 解析结果
        """
        if seal_texts_by_page is None:
            seal_texts_by_page = {}
        if table_seals_by_page is None:
            table_seals_by_page = {}
        try:
            layout_parsing_results = result.get('layoutParsingResults', [])
            
            # 从 dataInfo 获取页面尺寸（Paddle 渲染后的像素尺寸 @144 DPI）
            data_info = result.get('dataInfo', {})
            default_pixel_width = data_info.get('width', 1186)   # A4 @144 DPI 默认值
            default_pixel_height = data_info.get('height', 1672)
            
            logger.debug(
                f"Structure 页面尺寸: {default_pixel_width}x{default_pixel_height} px @ 144 DPI | "
                f"坐标系统: 原生像素坐标（与 VL 一致）"
            )
            
            pages = []
            all_markdown_parts = []
            
            for page_idx, page_result in enumerate(layout_parsing_results):
                pruned_result = page_result.get('prunedResult', {})
                markdown_data = page_result.get('markdown', {})
                markdown_images = markdown_data.get('images', {}) or {}
                parsing_res_list = pruned_result.get('parsing_res_list', [])
                page_table_seals = table_seals_by_page.get(page_idx, {})
                
                # 从 Markdown 获取文本（后续可能替换 img_in_seal_box）
                markdown_text = markdown_data.get('text', '')
                
                # 页面尺寸：使用 Paddle 返回的像素尺寸（144 DPI）
                page_info = pruned_result.get('page_info', {}) or {}
                page_width = page_info.get('width', default_pixel_width)
                page_height = page_info.get('height', default_pixel_height)
                
                # 解析文档预处理结果中的旋转角度
                doc_preprocessor_res = pruned_result.get('doc_preprocessor_res') or {}
                rotation_angle = int(doc_preprocessor_res.get('angle', 0) or 0)
                if rotation_angle != 0:
                    logger.info(f"Structure 检测到页面 {page_idx} 旋转角度: {rotation_angle}°（逆时针）")
                else:
                    logger.debug(f"Structure 页面 {page_idx} 无旋转（doc_preprocessor_res: {bool(doc_preprocessor_res)}）")
                
                contents = []
                layout_blocks = []
                
                top_level_table_res_list = pruned_result.get('table_res_list', [])
                table_index = 0
                
                for block_idx, block in enumerate(parsing_res_list):
                    block_label = block.get('block_label', 'text')
                    block_content = block.get('block_content', '')
                    block_bbox = block.get('block_bbox', [0, 0, 0, 0])
                    
                    if self._is_seal_like_block(block_label, block_content):
                        content_type = 'seal'
                    else:
                        content_type = self._normalize_block_type(block_label)
                    
                    cells = None
                    table_body = None
                    text = block_content if content_type not in ('table', 'seal') else None
                    img_path = block.get('image_path')
                    image_base64 = block.get('image_base64') or block.get('image')

                    if content_type == 'table' and top_level_table_res_list:
                        if table_index < len(top_level_table_res_list):
                            single_table_res = [top_level_table_res_list[table_index]]
                            cells = self._extract_cells_from_table_res(
                                single_table_res,
                                block_bbox
                            )
                            table_index += 1
                        else:
                            logger.warning(
                                f"表格索引 {table_index} 超出 table_res_list 范围 "
                                f"({len(top_level_table_res_list)})"
                            )
                        table_body = block_content
                        block_seals = page_table_seals.get(block_idx, [])
                        if block_seals and self.seal_extract_config.get(
                            'table_seal_recognition', {}
                        ).get('merge_to_html', True):
                            table_body = self._merge_seals_to_table_html(table_body, block_seals)
                        if cells and table_body:
                            from src.utils.anchor_markdown_converter import AnchorMarkdownConverter
                            cells = AnchorMarkdownConverter.apply_table_seals_to_cells(cells, table_body)
                    elif content_type == 'seal':
                        if not img_path:
                            img_path = self._extract_image_key_from_block_content(block_content)
                        if not image_base64 and img_path and markdown_images:
                            image_base64 = markdown_images.get(img_path)
                    
                    content = PaddleContent(
                        type=content_type,
                        text=text,
                        bbox=block_bbox,
                        page_idx=page_idx,
                        img_path=img_path,
                        image_base64=image_base64,
                        table_body=table_body,
                        cells=cells,
                    )
                    contents.append(content)
                    
                    span_text = text or self._strip_block_text(block_content or '')
                    if content_type == 'table' and table_body:
                        span_text = re.sub(r'<[^>]+>', ' ', table_body).strip()

                    layout_block = PaddleLayoutBlock(
                        bbox=block_bbox,
                        lines=[PaddleLine(
                            bbox=block_bbox,
                            spans=[PaddleSpan(bbox=block_bbox, text=span_text)],
                        )] if span_text else [],
                        category_type=content_type,
                        text=text if content_type != 'table' else None,
                        table_body=table_body,
                        cells=cells,
                    )
                    layout_blocks.append(layout_block)

                self._apply_seal_detections_to_page(
                    contents, layout_blocks, page_idx, seal_texts_by_page
                )

                page_seals = seal_texts_by_page.get(page_idx, [])
                markdown_text = self._replace_seal_img_tags_in_markdown(markdown_text, page_seals)
                if self.seal_extract_config.get('merge_seal_text') and page_seals:
                    seal_lines = [
                        self.seal_extract_config['seal_text_format'].format(text=seal.text)
                        for seal in page_seals
                        if seal.text and self.seal_extract_config['seal_text_format'].format(text=seal.text) not in markdown_text
                    ]
                    if seal_lines:
                        markdown_text = markdown_text.rstrip() + '\n\n' + '\n\n'.join(seal_lines)

                all_markdown_parts.append(markdown_text)
                
                page = PaddlePage(
                    page_num=page_idx,
                    width=page_width,
                    height=page_height,
                    contents=contents,
                    layout_blocks=layout_blocks,
                    rotation_angle=rotation_angle,
                    local_rotation_angle=(local_rotation_map or {}).get(page_idx, 0),
                )
                pages.append(page)
            
            # 合并所有页面的 Markdown
            full_markdown = '\n\n'.join(all_markdown_parts)
            total_seals = sum(len(seals) for seals in seal_texts_by_page.values())
            total_seals += sum(
                len(seals)
                for blocks in table_seals_by_page.values()
                for seals in blocks.values()
            )
            
            return PaddleParseResult(
                success=True,
                file_name=file_name,
                file_type=file_type,
                total_pages=len(pages),
                backend="paddle_structure",
                pages=pages,
                md_content=full_markdown,
                metadata={
                    'source': 'PaddleStructureV3',
                    'has_cell_coordinates': True,
                    'seal_count': total_seals,
                }
            )
            
        except Exception as e:
            logger.error(f"解析 Structure 响应失败: {e}", exc_info=True)
            return PaddleParseResult(
                success=False,
                file_name=file_name,
                file_type=file_type,
                total_pages=0,
                backend="paddle_structure",
                error_message=f"Structure 响应解析失败: {str(e)}"
            )
    
    def _parse_table_html_cells(self, html: str) -> List[Dict[str, Any]]:
        """
        解析表格 HTML，提取每个单元格的文本和行列信息
        
        PaddleStructure 的 cell_box_list 与 pred_html 是**一一对应**的：
        - cell_box_list 按行优先顺序排列
        - HTML 按 tr -> td 的顺序遍历也是行优先
        - 两者数量相同，可以直接 zip 对齐
        
        Args:
            html: 表格 HTML 字符串
            
        Returns:
            List[Dict[str, Any]]: 单元格信息列表，包含 text, row, col, rowspan, colspan
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.error("未安装 beautifulsoup4，无法解析表格 HTML。请运行: poetry add beautifulsoup4")
            return []
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            cells = []
            
            # 使用二维数组模拟表格，用于计算实际的 row/col（处理 rowspan/colspan）
            grid = {}  # (row, col) -> occupied
            
            current_row = 0
            for tr in soup.find_all('tr'):
                current_col = 0
                for cell in tr.find_all(['td', 'th']):
                    # 跳过被上方单元格 rowspan 占据的位置
                    while (current_row, current_col) in grid:
                        current_col += 1
                    
                    # 获取 rowspan/colspan
                    rowspan = int(cell.get('rowspan', 1))
                    colspan = int(cell.get('colspan', 1))
                    text = cell.get_text(strip=True)
                    
                    # 记录当前单元格信息
                    cells.append({
                        "text": text,
                        "row": current_row,
                        "col": current_col,
                        "rowspan": rowspan,
                        "colspan": colspan
                    })
                    
                    # 标记网格占用（用于处理 rowspan）
                    for r in range(rowspan):
                        for c in range(colspan):
                            grid[(current_row + r, current_col + c)] = True
                    
                    # 移动到下一列
                    current_col += colspan
                
                current_row += 1
            
            return cells
        except Exception as e:
            logger.warning(f"解析表格 HTML 失败: {e}")
            return []
    
    def _extract_cells_from_table_res(
        self,
        table_res_list: List[Dict[str, Any]],
        table_bbox: List[float]
    ) -> List[PaddleTableCell]:
        """
        从 table_res_list 提取单元格信息
        
        **重要发现**: PaddleStructure 的 table_ocr_pred 中的 rec_texts 和 rec_boxes 
        是**完美一一对应**的！这是最可靠的文本-坐标对应关系。
        
        新策略：
        1. 直接使用 table_ocr_pred.rec_texts 和 rec_boxes（天然对应）
        2. 从 pred_html 解析表格结构（row, col, rowspan, colspan）
        3. 通过文本内容匹配关联两者
        
        这比尝试对齐 cell_box_list 和 HTML 更鲁棒，因为：
        - cell_box_list 包含空单元格，而 HTML 的 colspan 会导致单元格数不匹配
        - rec_texts/rec_boxes 是 OCR 直接检测的结果，天然保证文本与坐标一致
        
        Args:
            table_res_list: Structure 返回的 table_res_list
            table_bbox: 表格的边界框
            
        Returns:
            List[PaddleTableCell]: 单元格列表
        """
        cells = []
        
        for table_res in table_res_list:
            pred_html = table_res.get('pred_html', '')
            table_ocr_pred = table_res.get('table_ocr_pred', {})
            
            # 1. 从 table_ocr_pred 获取精确的文本-坐标对应
            rec_texts = table_ocr_pred.get('rec_texts', [])
            rec_boxes = table_ocr_pred.get('rec_boxes', [])
            
            if not rec_texts or not rec_boxes:
                logger.warning("table_ocr_pred 中缺少 rec_texts 或 rec_boxes，回退到 cell_box_list")
                # 回退到旧逻辑
                cells.extend(self._extract_cells_fallback(table_res, table_bbox))
                continue
            
            if len(rec_texts) != len(rec_boxes):
                logger.warning(f"rec_texts({len(rec_texts)}) 和 rec_boxes({len(rec_boxes)}) 长度不匹配")
            
            # 2. 解析 HTML 获取表格结构信息
            html_cells = self._parse_table_html_cells(pred_html)
            
            # 3. 构建文本->坐标映射（处理重复文本）
            # 同一文本可能出现多次，按出现顺序存储
            text_to_boxes: Dict[str, List[List[float]]] = {}
            for text, box in zip(rec_texts, rec_boxes):
                text_stripped = str(text).strip()
                if text_stripped and len(box) >= 4:
                    if text_stripped not in text_to_boxes:
                        text_to_boxes[text_stripped] = []
                    text_to_boxes[text_stripped].append(box[:4])
            
            # 4. 匹配 HTML 单元格和 OCR 坐标
            matched_count = 0
            for html_cell in html_cells:
                cell_text = str(html_cell.get('text', '')).strip()
                if not cell_text:
                    continue  # 跳过空单元格（通常不需要高亮）
                
                # 查找匹配的坐标
                bbox = None
                if cell_text in text_to_boxes and text_to_boxes[cell_text]:
                    bbox = text_to_boxes[cell_text].pop(0)  # 使用并移除第一个匹配
                else:
                    # 尝试模糊匹配：检查是否包含关系
                    for ocr_text, boxes in text_to_boxes.items():
                        if boxes and (ocr_text in cell_text or cell_text in ocr_text):
                            bbox = boxes.pop(0)
                            logger.debug(f"模糊匹配: HTML '{cell_text}' -> OCR '{ocr_text}'")
                            break
                
                if bbox:
                    cells.append(PaddleTableCell(
                        bbox=bbox,
                        text=cell_text,
                        row=html_cell['row'],
                        col=html_cell['col'],
                        rowspan=html_cell.get('rowspan', 1),
                        colspan=html_cell.get('colspan', 1)
                    ))
                    matched_count += 1
                else:
                    logger.debug(f"未找到 HTML 单元格 '{cell_text[:20]}...' 的 OCR 坐标")
            
            logger.info(f"表格单元格匹配完成: {matched_count}/{len([c for c in html_cells if c.get('text', '').strip()])} 个有文本的单元格")
        
        return cells
    
    def _extract_cells_fallback(
        self,
        table_res: Dict[str, Any],
        table_bbox: List[float]
    ) -> List[PaddleTableCell]:
        """
        回退方案：当 table_ocr_pred 不可用时，使用 cell_box_list 和 pred_html 对齐
        
        这是一个不太可靠的方案，因为 cell_box_list 和 HTML td 的对应关系可能不一致
        """
        cells = []
        cell_box_list = table_res.get('cell_box_list', [])
        pred_html = table_res.get('pred_html', '')
        
        if not cell_box_list or not pred_html:
            return cells
        
        html_cells = self._parse_table_html_cells(pred_html)
        
        # 简单的顺序匹配（可能不准确）
        limit = min(len(html_cells), len(cell_box_list))
        
        for i in range(limit):
            html_cell = html_cells[i]
            box = cell_box_list[i]
            
            if len(box) >= 4:
                bbox = box[:4]
                cells.append(PaddleTableCell(
                    bbox=bbox,
                    text=html_cell.get('text', ''),
                    row=html_cell['row'],
                    col=html_cell['col'],
                    rowspan=html_cell.get('rowspan', 1),
                    colspan=html_cell.get('colspan', 1)
                ))
        
        if len(html_cells) != len(cell_box_list):
            logger.warning(
                f"[回退方案] cell_box_list({len(cell_box_list)}) 和 HTML cells({len(html_cells)}) 数量不匹配"
            )
        
        return cells
    
    @staticmethod
    def _normalize_block_type(raw_type: Optional[str]) -> str:
        """
        规范化 Paddle 返回的 block 类型，映射到统一的内容类型
        """
        if not raw_type:
            return 'text'

        raw_type = raw_type.lower()
        type_mapping = {
            'paragraph_title': 'text',
            'doc_title': 'text',
            'title': 'text',
            'caption': 'text',
            'header': 'text',
            'footer': 'text',
            'paragraph': 'text',
            'plain': 'text',
            'textline': 'text',
            'seal': 'seal',
            'table': 'table',
            'table_caption': 'text',
            'chart': 'image',
            'figure': 'image',
            'image': 'image',
            'header_image': 'image',
            'equation': 'formula',
            'formula': 'formula',
            'code': 'code',
            'list': 'list',
            'bulleted_list': 'list',
            'numbered_list': 'list',
        }
        return type_mapping.get(raw_type, raw_type)

    @staticmethod
    def _has_seal_placeholder_img(block_content: Optional[str]) -> bool:
        """block_content 是否含 Structure 印章占位 <img ... img_in_seal_box ...>"""
        if not block_content:
            return False
        return bool(re.search(r'<img[^>]*img_in_seal_box', block_content, re.IGNORECASE))

    @staticmethod
    def _is_seal_like_block(raw_type: Optional[str], block_content: Optional[str]) -> bool:
        """判断版面块是否为印章（含 Structure 的 img_in_seal_box 占位图）"""
        if PaddleClient._normalize_block_type(raw_type) == 'seal':
            return True
        return PaddleClient._has_seal_placeholder_img(block_content)

    @staticmethod
    def _image_key_tail(image_key: Optional[str]) -> Optional[str]:
        """从 image_key 提取文件名部分，兼容 / 与 \\ 分隔"""
        if not image_key:
            return None
        key = image_key.strip()
        if not key:
            return None
        return key.rsplit('/', 1)[-1].rsplit('\\', 1)[-1] or None

    @staticmethod
    def _image_keys_match(key_a: Optional[str], key_b: Optional[str]) -> bool:
        if not key_a or not key_b:
            return False
        if key_a == key_b:
            return True
        tail_a = PaddleClient._image_key_tail(key_a)
        tail_b = PaddleClient._image_key_tail(key_b)
        return bool(tail_a and tail_b and tail_a == tail_b)

    @staticmethod
    def _is_valid_seal_bbox(bbox: Optional[List[float]]) -> bool:
        if not bbox or len(bbox) != 4:
            return False
        try:
            x0, y0, x1, y1 = (float(v) for v in bbox)
        except (TypeError, ValueError):
            return False
        return x1 > x0 and y1 > y0

    def _content_has_recognized_seal_text(self, content: PaddleContent) -> bool:
        text = (content.text or '').strip()
        if not text:
            return False
        if text.startswith('【印章：') and text.endswith('】'):
            return True
        seal_prefix = self.seal_extract_config.get('seal_text_format', '【印章：{text}】').split('{')[0]
        return bool(seal_prefix and text.startswith(seal_prefix))

    def _seal_detection_matches_content(self, seal: SealDetection, content: PaddleContent) -> bool:
        if content.type != 'seal':
            return False
        if content.img_path and seal.image_key and self._image_keys_match(content.img_path, seal.image_key):
            return True
        if content.image_base64 and seal.image_base64 and content.image_base64 == seal.image_base64:
            return True
        if content.bbox and seal.bbox and self._is_same_bbox(seal.bbox, content.bbox):
            return True
        return False

    def _find_unfilled_seal_content(
        self,
        contents: List[PaddleContent],
        seal_det: SealDetection,
    ) -> Optional[PaddleContent]:
        """查找 Structure 已占位、尚未写入识别文字的 seal 块"""
        for content in contents:
            if content.type != 'seal' or self._content_has_recognized_seal_text(content):
                continue
            if self._seal_detection_matches_content(seal_det, content):
                return content
        return None

    def _seal_already_represented(
        self,
        contents: List[PaddleContent],
        seal_det: SealDetection,
        formatted_text: str,
    ) -> bool:
        for content in contents:
            if content.text == formatted_text:
                return True
            if (
                seal_det.bbox
                and content.bbox
                and self._is_same_bbox(content.bbox, seal_det.bbox)
                and self._content_has_recognized_seal_text(content)
            ):
                return True
        return False

    def _write_seal_to_content_and_layout(
        self,
        content: PaddleContent,
        layout_blocks: List[PaddleLayoutBlock],
        formatted_text: str,
        seal_det: SealDetection,
    ) -> None:
        content.text = formatted_text
        content.score = seal_det.score
        if seal_det.image_base64 and not content.image_base64:
            content.image_base64 = seal_det.image_base64
        if seal_det.bbox and not content.bbox:
            content.bbox = seal_det.bbox

        target_bbox = content.bbox or seal_det.bbox or []
        for layout_block in layout_blocks:
            if layout_block.category_type != 'seal':
                continue
            if content.bbox and self._is_same_bbox(layout_block.bbox, content.bbox):
                layout_block.text = formatted_text
                layout_block.score = seal_det.score
                layout_block.lines = [PaddleLine(
                    bbox=layout_block.bbox,
                    spans=[PaddleSpan(bbox=layout_block.bbox, text=formatted_text)],
                )]
                return
        if self._is_valid_seal_bbox(target_bbox):
            layout_blocks.append(PaddleLayoutBlock(
                bbox=target_bbox,
                lines=[PaddleLine(
                    bbox=target_bbox,
                    spans=[PaddleSpan(bbox=target_bbox, text=formatted_text)],
                )],
                category_type='seal',
                text=formatted_text,
                score=seal_det.score,
            ))

    def _structure_result_to_vl_response(self, result: Dict[str, Any]) -> PaddleOCRVLResponse:
        """将 Structure API 响应转换为 VL 格式，以便复用印章提取逻辑"""
        layout_parsing_results = result.get('layoutParsingResults', [])
        parsed_results: List[PaddleLayoutParsingResult] = []
        for page_result in layout_parsing_results:
            pruned_result = page_result.get('prunedResult', {})
            markdown_data = page_result.get('markdown', {})
            doc_preprocessor_res = pruned_result.get('doc_preprocessor_res') or {}
            rotation_angle = int(doc_preprocessor_res.get('angle', 0) or 0)
            markdown = MarkdownResult(
                text=markdown_data.get('text', ''),
                images=markdown_data.get('images', {}),
                is_start=markdown_data.get('isStart', True),
                is_end=markdown_data.get('isEnd', True),
            )
            parsed_results.append(PaddleLayoutParsingResult(
                pruned_result=pruned_result,
                markdown=markdown,
                output_images=page_result.get('outputImages'),
                input_image=page_result.get('inputImage'),
                rotation_angle=rotation_angle,
            ))
        return PaddleOCRVLResponse(
            log_id='structure',
            error_code=0,
            error_msg='',
            layout_parsing_results=parsed_results,
            data_info=result.get('dataInfo', {}),
        )

    def _apply_seal_detections_to_page(
        self,
        contents: List[PaddleContent],
        layout_blocks: List[PaddleLayoutBlock],
        page_idx: int,
        seal_texts_by_page: Dict[int, List[SealDetection]],
    ) -> None:
        """将 /seal-recognition 结果写入页面 contents 与 layout_blocks"""
        recognized_seals = list(seal_texts_by_page.get(page_idx, []))
        remaining_seals = list(recognized_seals)

        for content in contents:
            if content.type != 'seal':
                continue

            matched_seal = next(
                (seal for seal in remaining_seals if self._seal_detection_matches_content(seal, content)),
                None,
            )
            if not matched_seal:
                continue

            formatted_text = self.seal_extract_config['seal_text_format'].format(text=matched_seal.text)
            self._write_seal_to_content_and_layout(content, layout_blocks, formatted_text, matched_seal)
            remaining_seals.remove(matched_seal)

        for seal_det in remaining_seals:
            if not seal_det.text:
                continue
            formatted_text = self.seal_extract_config['seal_text_format'].format(text=seal_det.text)

            unfilled = self._find_unfilled_seal_content(contents, seal_det)
            if unfilled:
                self._write_seal_to_content_and_layout(unfilled, layout_blocks, formatted_text, seal_det)
                continue

            if self._seal_already_represented(contents, seal_det, formatted_text):
                logger.debug(
                    f"跳过重复印章 | page={page_idx} | text={seal_det.text[:20] if seal_det.text else ''}"
                )
                continue

            seal_bbox = seal_det.bbox if self._is_valid_seal_bbox(seal_det.bbox) else None
            contents.append(PaddleContent(
                type='seal',
                text=formatted_text,
                bbox=seal_bbox,
                page_idx=page_idx,
                img_path=seal_det.image_key,
                image_base64=seal_det.image_base64,
                score=seal_det.score,
            ))
            if seal_bbox:
                layout_blocks.append(PaddleLayoutBlock(
                    bbox=seal_bbox,
                    lines=[PaddleLine(
                        bbox=seal_bbox,
                        spans=[PaddleSpan(bbox=seal_bbox, text=formatted_text)],
                    )],
                    category_type='seal',
                    text=formatted_text,
                    score=seal_det.score,
                ))
            else:
                logger.debug(
                    f"印章无有效 bbox，仅写入 contents | page={page_idx} | text={seal_det.text[:20]}"
                )

    def _replace_seal_img_tags_in_markdown(
        self,
        markdown_text: str,
        seals: List[SealDetection],
    ) -> str:
        """将 Markdown 中的 img_in_seal_box 占位图替换为印章文字"""
        if not markdown_text or not seals:
            return markdown_text

        result = markdown_text
        for seal in seals:
            if not seal.text:
                continue
            formatted = self.seal_extract_config['seal_text_format'].format(text=seal.text)

            if seal.image_key:
                img_name = self._image_key_tail(seal.image_key)
                if img_name and len(img_name) >= 3:
                    pattern = rf'<img[^>]*src=["\'][^"\']*{re.escape(img_name)}[^"\']*["\'][^>]*/?>'
                    result, count = re.subn(pattern, formatted, result, count=1)
                    if count:
                        continue

            if seal.bbox and len(seal.bbox) == 4:
                coords = "_".join(str(int(c)) for c in seal.bbox)
                pattern = rf'<img[^>]*img_in_seal_box_{re.escape(coords)}[^>]*/?>'
                result, count = re.subn(pattern, formatted, result, count=1)
                if count:
                    continue

            pattern = r'<img[^>]*img_in_seal_box[^>]*/?>'
            result, _ = re.subn(pattern, formatted, result, count=1)

        return result

    @staticmethod
    def _extract_image_key_from_block_content(block_content: Optional[str]) -> Optional[str]:
        """
        从 block_content 中提取图片的相对路径（src 属性）
        """
        if not block_content:
            return None

        match = re.search(r'src=["\']([^"\']+)["\']', block_content)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _strip_block_text(block_content: Optional[str]) -> str:
        """
        去除 block_content 中的 HTML 标签，提取纯文本
        """
        if not block_content:
            return ''

        # 去除 img 标签
        content = re.sub(r'<img[^>]*>', '', block_content)
        # 去除其他 HTML 标签
        content = re.sub(r'<[^>]+>', '', content)
        # 合并空白
        content = re.sub(r'\s+', ' ', content)
        return content.strip()

    @staticmethod
    def _is_same_bbox(bbox_a: Optional[List[float]], bbox_b: Optional[List[float]], tolerance: float = 5.0) -> bool:
        """
        判断两个 bbox 是否可以视为相同
        """
        if not bbox_a or not bbox_b:
            return False
        if len(bbox_a) != 4 or len(bbox_b) != 4:
            return False
        return all(abs(a - b) <= tolerance for a, b in zip(bbox_a, bbox_b))
    
    def _match_score_from_layout_det(
        self,
        block_bbox: List[float],
        layout_det_boxes: List[Dict[str, Any]],
        block_type: str
    ) -> Optional[float]:
        """
        从 layout_det_res.boxes 中匹配 score
        
        通过 bbox 匹配找到对应的检测框，提取其 score
        
        Args:
            block_bbox: block 的 bbox（像素坐标，未转换）
            layout_det_boxes: layout_det_res.boxes 列表
            block_type: block 类型
            
        Returns:
            Optional[float]: 匹配到的 score，未匹配返回 None
        """
        if not block_bbox or not layout_det_boxes:
            return None
        
        # 遍历 layout_det_res.boxes，找到最匹配的
        best_match_score = None
        best_match_iou = 0.0
        
        for det_box in layout_det_boxes:
            # 获取检测框的坐标
            det_coordinate = det_box.get('coordinate')
            if not det_coordinate or len(det_coordinate) < 4:
                continue
            
            # 标准化坐标格式（可能是4点或8点）
            try:
                det_bbox = create_bbox_from_list(det_coordinate)
            except:
                continue
            
            # 计算 IoU（交并比）
            iou = self._calculate_bbox_iou(block_bbox, det_bbox)
            
            # 如果 IoU > 0.5，认为是匹配的
            if iou > 0.5 and iou > best_match_iou:
                best_match_iou = iou
                best_match_score = det_box.get('score')
                
                # 如果 IoU > 0.9，直接返回（完全匹配）
                if iou > 0.9:
                    return best_match_score
        
            return best_match_score
    
    @staticmethod
    def _calculate_bbox_iou(bbox_a: List[float], bbox_b: List[float]) -> float:
        """
        计算两个 bbox 的 IoU（交并比）
        
        Args:
            bbox_a: bbox [x0, y0, x1, y1]
            bbox_b: bbox [x0, y0, x1, y1]
            
        Returns:
            float: IoU 值（0-1）
        """
        # 计算交集
        x0_inter = max(bbox_a[0], bbox_b[0])
        y0_inter = max(bbox_a[1], bbox_b[1])
        x1_inter = min(bbox_a[2], bbox_b[2])
        y1_inter = min(bbox_a[3], bbox_b[3])
        
        # 如果没有交集
        if x0_inter >= x1_inter or y0_inter >= y1_inter:
            return 0.0
        
        # 交集面积
        inter_area = (x1_inter - x0_inter) * (y1_inter - y0_inter)
        
        # 两个 bbox 的面积
        area_a = (bbox_a[2] - bbox_a[0]) * (bbox_a[3] - bbox_a[1])
        area_b = (bbox_b[2] - bbox_b[0]) * (bbox_b[3] - bbox_b[1])
        
        # 并集面积
        union_area = area_a + area_b - inter_area
        
        # IoU
        if union_area == 0:
            return 0.0
        
        return inter_area / union_area

    def _save_debug_payload(self, service: str, payload: Any, suffix: str = 'json'):
        """
        按配置保存调试信息（如原始响应）
        """
        if not self.debug_config.get('enabled') or not self.debug_config.get('save_raw_response'):
            return

        output_dir = Path(self.debug_config.get('debug_output_dir', 'logs/paddle_debug'))
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return

        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
        file_path = output_dir / f"{service}_{timestamp}.{suffix}"

        try:
            if suffix == 'json':
                with file_path.open('w', encoding='utf-8') as fp:
                    json.dump(payload, fp, ensure_ascii=False, indent=2)
            else:
                with file_path.open('w', encoding='utf-8') as fp:
                    fp.write(str(payload))
        except Exception:
            pass

    def _debug_print_parse_result(
        self,
        parse_result: PaddleParseResult,
        seal_texts_by_page: Dict[int, List[SealDetection]],
        table_seals_by_page: Dict[int, Dict[int, List[TableSealInfo]]]
    ):
        """
        调试输出解析结果的完整详情
        
        输出内容：
        1. 文档基本信息
        2. OCR-VL 识别的印章
        3. 表格内识别的印章（含位置和单元格信息）
        4. 各页内容详情（包括表格中的印章信息）
        5. 最终的 Markdown 内容（传入 LLM 的内容）
        """
        separator = "=" * 100
        subseparator = "-" * 100
        
        logger.debug(f"\n{separator}")
        logger.debug("【文档解析结果完整详情】")
        logger.debug(separator)
        
        # ========== 1. 基本信息 ==========
        logger.debug(f"\n【1. 文档基本信息】")
        logger.debug(f"  文件名: {parse_result.file_name}")
        logger.debug(f"  文件类型: {parse_result.file_type}")
        logger.debug(f"  总页数: {parse_result.total_pages}")
        logger.debug(f"  解析状态: {'✓ 成功' if parse_result.success else '✗ 失败'}")
        if not parse_result.success:
            logger.debug(f"  错误信息: {parse_result.error_message}")
        logger.debug(f"  解析耗时: {parse_result.parse_time:.2f} 秒")
        logger.debug(f"  后端: {parse_result.backend}")
        
        # ========== 2. OCR-VL 识别的印章 ==========
        if seal_texts_by_page:
            logger.debug(f"\n【2. OCR-VL 识别的印章】（版面分析直接识别出的 seal 块）")
            total_seals = sum(len(seals) for seals in seal_texts_by_page.values())
            logger.debug(f"  总计: {total_seals} 个印章")
            
            for page_idx in sorted(seal_texts_by_page.keys()):
                seals = seal_texts_by_page[page_idx]
                logger.debug(f"\n  第 {page_idx} 页: {len(seals)} 个印章")
                for idx, seal in enumerate(seals, 1):
                    bbox_str = f"[{seal.bbox[0]:.0f}, {seal.bbox[1]:.0f}, {seal.bbox[2]:.0f}, {seal.bbox[3]:.0f}]" if seal.bbox else "无坐标"
                    logger.debug(f"    {idx}. 【{seal.text}】")
                    logger.debug(f"       - 置信度: {seal.score:.3f}")
                    logger.debug(f"       - 坐标: {bbox_str}")
        else:
            logger.debug(f"\n【2. OCR-VL 识别的印章】")
            logger.debug(f"  无")
        
        # ========== 3. 表格内识别的印章 ==========
        if table_seals_by_page:
            logger.debug(f"\n【3. 表格内识别的印章】（从表格区域提取并识别）")
            total_table_seals = sum(
                len(seals) 
                for blocks in table_seals_by_page.values() 
                for seals in blocks.values()
            )
            logger.debug(f"  总计: {total_table_seals} 个印章")
            
            for page_idx in sorted(table_seals_by_page.keys()):
                blocks = table_seals_by_page[page_idx]
                logger.debug(f"\n  第 {page_idx} 页: {sum(len(s) for s in blocks.values())} 个印章")
                
                for block_idx in sorted(blocks.keys()):
                    seals = blocks[block_idx]
                    logger.debug(f"\n    表格 #{block_idx}: {len(seals)} 个印章")
                    
                    for idx, seal in enumerate(seals, 1):
                        logger.debug(f"      {idx}. 【{seal.text}】")
                        logger.debug(f"         - 置信度: {seal.score:.3f}")
                        logger.debug(f"         - 位置: {seal.position} (x={seal.position_ratio['x']:.3f}, y={seal.position_ratio['y']:.3f})")
                        
                        bbox_table_str = f"[{seal.bbox_in_table[0]:.0f}, {seal.bbox_in_table[1]:.0f}, {seal.bbox_in_table[2]:.0f}, {seal.bbox_in_table[3]:.0f}]"
                        bbox_page_str = f"[{seal.bbox_in_page[0]:.0f}, {seal.bbox_in_page[1]:.0f}, {seal.bbox_in_page[2]:.0f}, {seal.bbox_in_page[3]:.0f}]"
                        logger.debug(f"         - 表格内坐标: {bbox_table_str}")
                        logger.debug(f"         - 页面坐标: {bbox_page_str}")
                        
                        if seal.matched_cell_text:
                            logger.debug(f"         - 匹配单元格: \"{seal.matched_cell_text}\" (行={seal.matched_cell_row}, 列={seal.matched_cell_col})")
                        else:
                            logger.debug(f"         - 匹配单元格: 未匹配")
        else:
            logger.debug(f"\n【3. 表格内识别的印章】")
            logger.debug(f"  无")
        
        # ========== 4. 各页内容详情 ==========
        logger.debug(f"\n【4. 各页内容详情】")
        
        for page in parse_result.pages:
            logger.debug(f"\n{subseparator}")
            logger.debug(f"第 {page.page_num} 页 (尺寸: {page.width:.0f} x {page.height:.0f})")
            logger.debug(subseparator)
            
            # 统计各类型内容数量
            type_counts = {}
            for content in page.contents:
                type_counts[content.type] = type_counts.get(content.type, 0) + 1
            
            logger.debug(f"  内容类型统计: {dict(sorted(type_counts.items()))}")
            logger.debug(f"  总计: {len(page.contents)} 个内容块\n")
            
            # 输出每个内容块的详情
            for idx, content in enumerate(page.contents):
                bbox_str = f"[{content.bbox[0]:.0f}, {content.bbox[1]:.0f}, {content.bbox[2]:.0f}, {content.bbox[3]:.0f}]" if content.bbox else "无坐标"
                score_str = f", 置信度={content.score:.3f}" if content.score else ""
                
                logger.debug(f"  [{idx:3d}] {content.type.upper():10s} | {bbox_str}{score_str}")
                
                if content.type == 'table':
                    # 表格：检查是否包含印章信息
                    table_html = content.table_body or ''
                    has_seals = "TABLE_SEALS_START" in table_html
                    
                    if has_seals:
                        # 提取印章数量
                        import re
                        seal_count_match = re.search(r'data-seal-count="(\d+)"', table_html)
                        seal_count = seal_count_match.group(1) if seal_count_match else "?"
                        logger.debug(f"        ✓ 包含 {seal_count} 个印章信息")
                        
                        # 提取印章文本
                        seal_texts = re.findall(r'data-text="([^"]+)"', table_html)
                        for seal_text in seal_texts:
                            logger.debug(f"          - 【{seal_text}】")
                    
                    # 显示表格内容预览（去除HTML标签）
                    text_preview = self._strip_block_text(table_html)
                    if text_preview:
                        logger.debug(f"        预览: {text_preview}")
                    
                elif content.type == 'seal':
                    logger.debug(f"        文本: 【{content.text}】")
                    
                elif content.type == 'image':
                    logger.debug(f"        路径: {content.img_path or '无'}")
                    
                elif content.type == 'text':
                    text_preview = (content.text or '')[:150]
                    if len(content.text or '') > 150:
                        text_preview += "..."
                    if text_preview:
                        logger.debug(f"        内容: {text_preview}")
                
                else:
                    # 其他类型
                    text_preview = (content.text or '')

                    if text_preview:
                        logger.debug(f"        内容: {text_preview}")
        
        # ========== 5. Markdown 内容（传入 LLM） ==========
        logger.debug(f"\n{separator}")
        logger.debug(f"【5. Markdown 内容】")
        logger.debug(separator)
        
        if parse_result.md_content:
            md_length = len(parse_result.md_content)
            logger.debug(f"\n【5.1 原始 Markdown】（Paddle 直接输出）")
            logger.debug(f"总长度: {md_length} 字符\n")
            
            # 输出完整的原始 Markdown 内容
            logger.debug("--- 原始 Markdown 开始 ---")
            logger.debug(parse_result.md_content)
            logger.debug("--- 原始 Markdown 结束 ---")
            
            # 统计信息
            line_count = parse_result.md_content.count('\n') + 1
            table_count = parse_result.md_content.count('<table')
            seal_count = parse_result.md_content.count('【印章：')
            
            logger.debug(f"\n统计信息:")
            logger.debug(f"  - 行数: {line_count}")
            logger.debug(f"  - 表格数: {table_count}")
            logger.debug(f"  - 印章标记数: {seal_count}")
            
            # ========== 5.2 转换为带锚点的 Markdown（实际传给 LLM 的格式） ==========
            logger.debug(f"\n{subseparator}")
            logger.debug(f"【5.2 带锚点的 Markdown】（实际传给 LLM 的格式）")
            logger.debug(subseparator)
            
            try:
                # 使用 AnchorMarkdownConverter 转换
                from src.utils.anchor_markdown_converter import AnchorMarkdownConverter
                
                # 构造 file_data 格式
                file_data = {
                    "parse_results": [parse_result]
                }
                
                tagged_markdown, segment_map = AnchorMarkdownConverter.convert(file_data)
                
                if tagged_markdown:
                    tagged_length = len(tagged_markdown)
                    logger.debug(f"\n转换后长度: {tagged_length} 字符")
                    logger.debug(f"锚点片段数: {len(segment_map)}")
                    
                    # 输出带锚点的 Markdown
                    logger.debug("\n--- 带锚点 Markdown 开始 ---")
                    logger.debug(tagged_markdown)
                    logger.debug("--- 带锚点 Markdown 结束 ---")
                    
                    # 显示部分锚点映射示例
                    logger.debug(f"\n锚点映射示例（前 10 个）:")
                    for idx, (anchor_id, seg_info) in enumerate(list(segment_map.items())[:10]):
                        bbox_str = f"[{seg_info.bbox[0]:.0f}, {seg_info.bbox[1]:.0f}, {seg_info.bbox[2]:.0f}, {seg_info.bbox[3]:.0f}]" if seg_info.bbox else "无坐标"
                        text_preview = seg_info.text[:50] + "..." if len(seg_info.text) > 50 else seg_info.text
                        logger.debug(f"  {anchor_id}: {seg_info.segment_type} | 页{seg_info.page_idx} | {bbox_str}")
                        logger.debug(f"          内容: {text_preview}")
                    
                    if len(segment_map) > 10:
                        logger.debug(f"  ... 还有 {len(segment_map) - 10} 个片段")
                    
                    # 锚点格式说明
                    logger.debug(f"\n锚点格式说明:")
                    logger.debug(f"  - 格式: (¶P-ID)")
                    logger.debug(f"    - P: 页码")
                    logger.debug(f"    - ID: 该页内的片段索引")
                    logger.debug(f"  - 示例: '甲方：北京某某公司 (¶0-2)' 表示第0页的第2个片段")
                    logger.debug(f"  - LLM 提取时会引用锚点，用于后续溯源定位")
                    
                else:
                    logger.debug("  转换失败，tagged_markdown 为空")
                    
            except Exception as e:
                logger.debug(f"  转换带锚点 Markdown 失败: {e}")
                import traceback
                logger.debug(traceback.format_exc())
        else:
            logger.debug("  Markdown 内容为空")
        
        logger.debug(f"\n{separator}")
        logger.debug("【调试输出结束】")
        logger.debug(f"{separator}\n")

    def _crop_image_from_file(
        self,
        file_content: bytes,
        file_type: str,
        page_idx: int,
        bbox: List[float]
    ) -> Optional[str]:
        """
        从原始文件中裁剪指定区域图像
        
        Args:
            file_content: 原始文件内容
            file_type: 文件类型 (.pdf/.jpg 等)
            page_idx: 页码索引（仅 PDF 有效）
            bbox: 边界框 [x0, y0, x1, y1]（144 DPI 像素坐标）
            
        Returns:
            Optional[str]: 裁剪后的图像 base64（PNG格式），失败返回 None
        """
        try:
            if file_type.lower() == '.pdf':
                # PDF 裁剪
                return self._crop_pdf_region(file_content, page_idx, bbox)
            else:
                # 图像裁剪
                return self._crop_image_region(file_content, bbox)
        except Exception as e:
            logger.warning(f"裁剪图像失败: {e}")
            return None

    def _crop_pdf_region(
        self,
        file_content: bytes,
        page_idx: int,
        bbox: List[float]
    ) -> Optional[str]:
        """
        从 PDF 中裁剪指定区域
        
        Paddle 使用 144 DPI 渲染，需要转换坐标
        """
        try:
            doc = fitz.open(stream=file_content, filetype="pdf")
            if page_idx >= len(doc):
                logger.warning(f"页码超出范围: {page_idx} >= {len(doc)}")
                doc.close()
                return None
            
            page = doc[page_idx]
            
            # Paddle 使用 144 DPI，fitz 默认 72 DPI
            # 需要将 144 DPI 像素坐标转换为 72 DPI 点坐标
            scale = 72 / 144
            rect = fitz.Rect(
                bbox[0] * scale,
                bbox[1] * scale,
                bbox[2] * scale,
                bbox[3] * scale
            )
            
            # 以 144 DPI 渲染裁剪区域
            pix = page.get_pixmap(clip=rect, dpi=144)
            img_bytes = pix.tobytes("png")
            doc.close()
            
            return base64.b64encode(img_bytes).decode('utf-8')
            
        except Exception as e:
            logger.warning(f"裁剪 PDF 区域失败: {e}")
            return None

    def _crop_image_region(
        self,
        file_content: bytes,
        bbox: List[float]
    ) -> Optional[str]:
        """
        从图像中裁剪指定区域
        """
        try:
            image = Image.open(BytesIO(file_content))
            
            # 确保坐标在图像范围内
            x0 = max(0, int(bbox[0]))
            y0 = max(0, int(bbox[1]))
            x1 = min(image.width, int(bbox[2]))
            y1 = min(image.height, int(bbox[3]))
            
            if x1 <= x0 or y1 <= y0:
                logger.warning(f"无效的裁剪区域: [{x0}, {y0}, {x1}, {y1}]")
                return None
            
            # 裁剪
            cropped = image.crop((x0, y0, x1, y1))
            
            # 转换为 PNG base64
            buffer = BytesIO()
            cropped.save(buffer, format="PNG")
            
            return base64.b64encode(buffer.getvalue()).decode('utf-8')
            
        except Exception as e:
            logger.warning(f"裁剪图像区域失败: {e}")
            return None

    async def _extract_seal_texts(
        self,
        ocr_vl_result: PaddleOCRVLResponse,
        file_content: bytes,
        file_name: str
    ) -> Dict[int, List[SealDetection]]:
        """
        提取并识别印章文本（跨页并行优化）
        
        从 OCR-VL 结果中提取印章图像（base64），
        调用印章识别服务识别文本
        
        Args:
            ocr_vl_result: OCR-VL 解析结果
            file_content: 原始文件内容
            file_name: 文件名
            
        Returns:
            Dict[int, List[SealDetection]]: 每页的印章识别结果
        """
        seal_texts_by_page = {}
        
        try:
            # 第一步：收集所有页面的印章任务（不执行）
            all_seal_tasks = []  # [(page_idx, seal_image, task), ...]
            
            for page_idx, page_result in enumerate(ocr_vl_result.layout_parsing_results):
                pruned_result = page_result.pruned_result
                markdown_images = page_result.markdown.images or {}

                raw_blocks = pruned_result.get('parsing_res_list')
                block_source = 'parsing_res_list'
                if not raw_blocks:
                    raw_blocks = pruned_result.get('layout_dets', [])
                    block_source = 'layout_dets'

                # 提取印章区域
                for det in raw_blocks or []:
                    raw_type = det.get('block_label') if block_source == 'parsing_res_list' else det.get('category_type')
                    block_content = det.get('block_content') if block_source == 'parsing_res_list' else det.get('text')
                    if not self._is_seal_like_block(raw_type, block_content):
                        continue

                    block_type = 'seal'

                    bbox_list = det.get('block_bbox') if block_source == 'parsing_res_list' else det.get('bbox')
                    bbox: List[float] = []
                    if bbox_list:
                        try:
                            bbox = create_bbox_from_list(bbox_list)
                        except Exception:
                            pass

                    block_content = det.get('block_content') if block_source == 'parsing_res_list' else det.get('text')
                    image_base64 = det.get('image_base64') or det.get('image')
                    image_key = det.get('image_path')

                    if not image_base64:
                        if not image_key and block_source == 'parsing_res_list':
                            image_key = self._extract_image_key_from_block_content(block_content)
                        if image_key and markdown_images:
                            image_base64 = markdown_images.get(image_key)

                    if not image_base64 and page_result.output_images:
                        if image_key and page_result.output_images:
                            image_base64 = page_result.output_images.get(image_key)

                    # 如果 OCR-VL 没有返回裁剪图，使用 bbox 从原始文件裁剪
                    # 这比使用整页图片效果好得多
                    if not image_base64 and bbox and file_content:
                        file_type = Path(file_name).suffix.lower()
                        cropped_image = self._crop_image_from_file(
                            file_content, file_type, page_idx, bbox
                        )
                        if cropped_image:
                            image_base64 = cropped_image
                            logger.debug(f"使用 bbox 裁剪印章区域: page={page_idx}, bbox={bbox}")

                    # 仅作为最后的回退方案使用整页图片（通常效果不好）
                    if not image_base64 and page_result.input_image and block_type == 'seal':
                        logger.warning(f"无法裁剪印章区域，回退使用整页图片（效果可能较差）")
                        image_base64 = page_result.input_image

                    if image_base64:
                        seal_image = {
                            'bbox': bbox,
                            'image_base64': image_base64,
                            'image_key': image_key
                        }
                        # 创建任务但不执行
                        task = self._recognize_seal(image_base64, file_name)
                        all_seal_tasks.append((page_idx, seal_image, task))
            
            if not all_seal_tasks:
                return {}
            
            # 第二步：跨页并行执行所有印章识别任务
            logger.info(f"跨页并行识别 {len(all_seal_tasks)} 个印章")
            
            results = await asyncio.gather(
                *[task for _, _, task in all_seal_tasks],
                return_exceptions=True
            )
            
            # 第三步：按页聚合结果
            for (page_idx, seal_image, _), result in zip(all_seal_tasks, results):
                try:
                    if isinstance(result, Exception):
                        logger.debug(f"印章识别失败: {result}")
                        continue
                    
                    if result:
                        text = result.get('text', '')
                        score = result.get('score', 0.0)
                        seal_detection = SealDetection(
                            bbox=seal_image['bbox'],
                            text=text,
                            score=score,
                            image_key=seal_image.get('image_key'),
                            image_base64=seal_image['image_base64']
                        )
                        
                        if page_idx not in seal_texts_by_page:
                            seal_texts_by_page[page_idx] = []
                        seal_texts_by_page[page_idx].append(seal_detection)
                        logger.debug(f"第 {page_idx} 页印章识别: {text} (score={score:.2f})")
                except Exception as e:
                    logger.debug(f"处理印章识别结果失败: {e}")
                    continue
            
            # 输出统计
            total_success = sum(len(seals) for seals in seal_texts_by_page.values())
            logger.info(f"印章识别完成: {total_success}/{len(all_seal_tasks)} 个成功，分布在 {len(seal_texts_by_page)} 页")
            
            return seal_texts_by_page
            
        except Exception as e:
            logger.error(f"提取印章文本失败: {e}", exc_info=True)
            return {}
    
    def _get_pdf_page_sizes(
        self,
        file_content: bytes
    ) -> Optional[List[Tuple[float, float]]]:
        """
        获取 PDF 每页的实际尺寸（单位：pt）
        """
        try:
            doc = fitz.open(stream=file_content, filetype="pdf")
            page_sizes: List[Tuple[float, float]] = []
            for page in doc:
                rect = page.rect
                page_sizes.append((rect.width, rect.height))
            doc.close()
            return page_sizes
        except Exception as e:
            logger.debug(f"无法获取 PDF 页面尺寸: {e}")
            return None
    
    async def _recognize_seal(
        self,
        seal_image_base64: str,
        file_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        调用印章识别服务识别单个印章（带并发控制）
        
        Args:
            seal_image_base64: 印章图像的 base64 编码
            file_name: 文件名（用于日志）
            
        Returns:
            Optional[Dict[str, Any]]: 识别结果，包含 text 与 score
        """
        # 使用信号量控制并发（印章识别并发）
        async with self.semaphore_seal:
            url = get_api_endpoint('seal_recognition', self.env)
            
            # 准备请求体
            request_body = {
                'file': seal_image_base64,
                'fileType': 1,  # 图像
                **{k: v for k, v in self.seal_recognition_options.items() if v is not None}
            }
            
            # 调试日志：输出实际发送的参数（不包含file内容）
            debug_params = {k: v for k, v in request_body.items() if k != 'file'}
            logger.debug(f"印章识别请求参数: {debug_params}")
            
            try:
                response = await self.client.post(
                    url,
                    json=request_body
                )
                
                if response.status_code == 200:
                    result = response.json()
                    self._save_debug_payload('paddle_seal_recognition', result)
                    
                    # 解析响应
                    if result.get('errorCode') == 0:
                        seal_results = result.get('result', {}).get('sealRecResults', [])
                        
                        if seal_results and len(seal_results) > 0:
                            # 提取印章文本
                            first_result = seal_results[0]
                            pruned_result = first_result.get('prunedResult', {})
                            
                            # 实际的印章识别结果在 seal_res_list 中
                            seal_res_list = pruned_result.get('seal_res_list', [])
                            
                            if seal_res_list:
                                # 取第一个印章识别结果
                                first_seal = seal_res_list[0]
                                
                                # rec_texts 包含识别出的文本列表
                                rec_texts = first_seal.get('rec_texts', [])
                                rec_scores = first_seal.get('rec_scores', [])
                                
                                if rec_texts:
                                    # 合并所有识别出的文本
                                    text = ''.join(rec_texts)
                                    # 使用平均分数
                                    score = sum(rec_scores) / len(rec_scores) if rec_scores else 0.0
                                    
                                    return {
                                        'text': text,
                                        'score': score
                                    }
                                
                                # 检查是否检测到了文本区域但未能识别
                                dt_polys = first_seal.get('dt_polys', [])
                                if dt_polys:
                                    logger.debug(f"印章检测到文本区域但识别失败")
                                else:
                                    logger.debug("印章识别：未检测到文本区域")
                            
                            # 兼容其他可能的格式
                            seal_det_res = pruned_result.get('seal_det_res', {})
                            boxes = seal_det_res.get('boxes', [])
                            if boxes:
                                for box in boxes:
                                    text = box.get('text', '')
                                    if text:
                                        return {
                                            'text': text,
                                            'score': box.get('score', 0.0)
                                        }
                            
                            # 检查是否印章检测失败
                            logger.debug(f"印章识别失败: 图像质量不佳或参数需调整")
                    
                    logger.debug(f"印章识别未返回文本")
                    return None
                else:
                    logger.debug(f"印章识别API返回错误: {response.status_code}")
                    self._save_debug_payload('paddle_seal_recognition_error', response.text, suffix='txt')
                    return None
                    
            except Exception as e:
                logger.error(f"调用印章识别服务失败: {e}")
                return None

    async def _call_seal_recognition_api(
        self,
        image_base64: str,
        file_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        调用印章识别 API（返回完整响应）
        
        与 _recognize_seal 不同，此方法返回完整的 API 响应，
        包含 layout_det_res（印章检测框坐标）和 seal_res_list（印章识别结果）
        
        Args:
            image_base64: 图像的 base64 编码
            file_name: 文件名（用于日志）
            
        Returns:
            Optional[Dict[str, Any]]: 完整的 prunedResult，包含坐标和识别信息
        """
        # 使用印章识别并发控制
        async with self.semaphore_seal:
            url = get_api_endpoint('seal_recognition', self.env)
            
            request_body = {
                'file': image_base64,
                'fileType': 1,  # 图像
                **{k: v for k, v in self.seal_recognition_options.items() if v is not None}
            }
            
            debug_params = {k: v for k, v in request_body.items() if k != 'file'}
            logger.debug(f"表格印章识别请求参数: {debug_params}")
            
            try:
                response = await self.client.post(url, json=request_body)
                
                if response.status_code == 200:
                    result = response.json()
                    self._save_debug_payload('paddle_table_seal_recognition', result)
                    
                    if result.get('errorCode') == 0:
                        seal_results = result.get('result', {}).get('sealRecResults', [])
                        
                        if seal_results and len(seal_results) > 0:
                            # 返回完整的 prunedResult，包含坐标信息
                            return seal_results[0].get('prunedResult', {})
                    
                    logger.debug(f"表格印章识别未返回结果")
                    return None
                else:
                    logger.debug(f"表格印章识别API返回错误: {response.status_code}")
                    return None
                    
            except Exception as e:
                logger.error(f"调用表格印章识别服务失败: {e}")
                return None

    @staticmethod
    def _calculate_seal_position(
        seal_bbox: List[float],
        table_bbox: List[float]
    ) -> Tuple[str, Dict[str, float]]:
        """
        计算印章在表格中的位置（9宫格）
        
        Args:
            seal_bbox: 印章坐标 [x0, y0, x1, y1]
            table_bbox: 表格坐标 [x0, y0, x1, y1]
            
        Returns:
            Tuple[str, Dict[str, float]]: 
                - 位置描述 "左下", "中下", "右下" 等
                - 精确比例 {"x": 0.25, "y": 0.85}
        """
        # 计算印章中心点
        seal_cx = (seal_bbox[0] + seal_bbox[2]) / 2
        seal_cy = (seal_bbox[1] + seal_bbox[3]) / 2
        
        # 计算相对位置比例
        table_w = table_bbox[2] - table_bbox[0]
        table_h = table_bbox[3] - table_bbox[1]
        
        if table_w == 0 or table_h == 0:
            return "中", {"x": 0.5, "y": 0.5}
        
        x_ratio = (seal_cx - table_bbox[0]) / table_w
        y_ratio = (seal_cy - table_bbox[1]) / table_h
        
        # 限制在 0-1 范围内
        x_ratio = max(0, min(1, x_ratio))
        y_ratio = max(0, min(1, y_ratio))
        
        # 9宫格划分
        if x_ratio < 0.33:
            x_pos = "左"
        elif x_ratio < 0.67:
            x_pos = "中"
        else:
            x_pos = "右"
        
        if y_ratio < 0.33:
            y_pos = "上"
        elif y_ratio < 0.67:
            y_pos = "中"
        else:
            y_pos = "下"
        
        # 组合位置描述
        if x_pos == "中" and y_pos == "中":
            position = "中"
        elif x_pos == "中":
            position = y_pos
        elif y_pos == "中":
            position = x_pos
        else:
            position = x_pos + y_pos
        
        return position, {"x": round(x_ratio, 3), "y": round(y_ratio, 3)}

    @staticmethod
    def _convert_seal_bbox_to_page(
        seal_bbox: List[float],
        table_bbox: List[float]
    ) -> List[float]:
        """
        将印章坐标从表格坐标系转换为页面坐标系
        
        Args:
            seal_bbox: 印章在表格图像中的坐标 [x0, y0, x1, y1]
            table_bbox: 表格在页面中的坐标 [x0, y0, x1, y1]
            
        Returns:
            印章在页面中的坐标 [x0, y0, x1, y1]
        """
        return [
            table_bbox[0] + seal_bbox[0],
            table_bbox[1] + seal_bbox[1],
            table_bbox[0] + seal_bbox[2],
            table_bbox[1] + seal_bbox[3]
        ]

    def _parse_table_cells(self, table_html: str) -> List[Dict[str, Any]]:
        """
        解析表格 HTML，提取单元格信息
        
        Args:
            table_html: 表格 HTML 字符串
            
        Returns:
            List[Dict]: 单元格列表，每个元素包含:
                - text: 单元格文本
                - row: 行号
                - col: 列号
                - colspan: 列跨度
                - rowspan: 行跨度
        """
        from html.parser import HTMLParser
        
        class TableCellParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.cells = []
                self.current_row = -1
                self.current_col = 0
                self.in_td = False
                self.current_text = []
                self.current_colspan = 1
                self.current_rowspan = 1
                self.col_occupied = {}  # {row: set of occupied cols}
            
            def handle_starttag(self, tag, attrs):
                if tag == 'tr':
                    self.current_row += 1
                    self.current_col = 0
                    # 跳过被 rowspan 占用的列
                    while self.current_col in self.col_occupied.get(self.current_row, set()):
                        self.current_col += 1
                elif tag == 'td' or tag == 'th':
                    self.in_td = True
                    self.current_text = []
                    attrs_dict = dict(attrs)
                    self.current_colspan = int(attrs_dict.get('colspan', 1))
                    self.current_rowspan = int(attrs_dict.get('rowspan', 1))
                    # 跳过被 rowspan 占用的列
                    while self.current_col in self.col_occupied.get(self.current_row, set()):
                        self.current_col += 1
            
            def handle_endtag(self, tag):
                if tag == 'td' or tag == 'th':
                    if self.in_td:
                        text = ''.join(self.current_text).strip()
                        # 清理多余空白
                        text = re.sub(r'\s+', ' ', text)
                        
                        self.cells.append({
                            'text': text,
                            'row': self.current_row,
                            'col': self.current_col,
                            'colspan': self.current_colspan,
                            'rowspan': self.current_rowspan
                        })
                        
                        # 标记 rowspan 占用的单元格
                        if self.current_rowspan > 1:
                            for r in range(self.current_row + 1, self.current_row + self.current_rowspan):
                                if r not in self.col_occupied:
                                    self.col_occupied[r] = set()
                                for c in range(self.current_col, self.current_col + self.current_colspan):
                                    self.col_occupied[r].add(c)
                        
                        self.current_col += self.current_colspan
                        self.in_td = False
            
            def handle_data(self, data):
                if self.in_td:
                    self.current_text.append(data)
        
        try:
            parser = TableCellParser()
            parser.feed(table_html)
            return parser.cells
        except Exception as e:
            logger.warning(f"解析表格 HTML 失败: {e}")
            return []

    def _match_seal_to_cell(
        self,
        seal_bbox: List[float],
        table_bbox: List[float],
        table_html: str
    ) -> Tuple[Optional[str], Optional[int], Optional[int]]:
        """
        尝试将印章匹配到表格单元格
        
        根据印章位置和表格结构推算印章可能属于哪个单元格
        
        Args:
            seal_bbox: 印章在表格内的坐标
            table_bbox: 表格的 bbox
            table_html: 表格 HTML
            
        Returns:
            Tuple: (单元格文本, 行号, 列号) 或 (None, None, None)
        """
        cells = self._parse_table_cells(table_html)
        if not cells:
            return None, None, None
        
        # 获取表格的行数和列数
        max_row = max(c['row'] for c in cells) + 1
        max_col = max(c['col'] + c['colspan'] for c in cells)
        
        if max_row == 0 or max_col == 0:
            return None, None, None
        
        # 计算表格尺寸
        table_width = table_bbox[2] - table_bbox[0]
        table_height = table_bbox[3] - table_bbox[1]
        
        # 计算印章中心点
        seal_cx = (seal_bbox[0] + seal_bbox[2]) / 2
        seal_cy = (seal_bbox[1] + seal_bbox[3]) / 2
        
        # 估算印章所在的行和列
        # 假设单元格均匀分布（近似）
        col_width = table_width / max_col
        row_height = table_height / max_row
        
        estimated_col = int(seal_cx / col_width) if col_width > 0 else 0
        estimated_row = int(seal_cy / row_height) if row_height > 0 else 0
        
        # 限制范围
        estimated_col = max(0, min(estimated_col, max_col - 1))
        estimated_row = max(0, min(estimated_row, max_row - 1))
        
        # 查找匹配的单元格
        best_match = None
        for cell in cells:
            cell_row = cell['row']
            cell_col = cell['col']
            cell_colspan = cell['colspan']
            cell_rowspan = cell['rowspan']
            
            # 检查印章是否在单元格范围内
            if (cell_row <= estimated_row < cell_row + cell_rowspan and
                cell_col <= estimated_col < cell_col + cell_colspan):
                best_match = cell
                break
        
        # 如果没有精确匹配，返回最接近的单元格
        if not best_match:
            min_distance = float('inf')
            for cell in cells:
                cell_row = cell['row']
                cell_col = cell['col']
                # 计算单元格中心与印章位置的距离
                distance = abs(cell_row - estimated_row) + abs(cell_col - estimated_col)
                if distance < min_distance:
                    min_distance = distance
                    best_match = cell
        
        if best_match:
            return best_match['text'], best_match['row'], best_match['col']
        
        return None, None, None

    async def _extract_table_seals(
        self,
        ocr_vl_result: PaddleOCRVLResponse,
        file_content: bytes,
        file_name: str,
        file_type: str
    ) -> Dict[int, Dict[int, List[TableSealInfo]]]:
        """
        提取表格内的印章（跨页并行优化）
        
        对所有识别出的表格区域调用印章识别 API
        
        Args:
            ocr_vl_result: OCR-VL 解析结果
            file_content: 原始文件内容
            file_name: 文件名
            file_type: 文件类型
            
        Returns:
            Dict[int, Dict[int, List[TableSealInfo]]]: 
            {页码: {block_idx: [印章列表]}}
        """
        table_seals_by_page: Dict[int, Dict[int, List[TableSealInfo]]] = {}
        
        try:
            # 第一步：收集所有页面的表格任务（不执行）
            all_table_tasks = []
            
            for page_idx, page_result in enumerate(ocr_vl_result.layout_parsing_results):
                pruned_result = page_result.pruned_result or {}
                
                # 获取 blocks
                if pruned_result.get('parsing_res_list'):
                    block_source = 'parsing_res_list'
                    raw_blocks = pruned_result.get('parsing_res_list', [])
                else:
                    block_source = 'layout_dets'
                    raw_blocks = pruned_result.get('layout_dets', [])
                
                for block_idx, raw_block in enumerate(raw_blocks or []):
                    raw_type = raw_block.get('block_label') if block_source == 'parsing_res_list' else raw_block.get('category_type')
                    block_type = self._normalize_block_type(raw_type)
                    
                    if block_type != 'table':
                        continue
                    
                    # 获取表格 bbox
                    bbox_list = raw_block.get('block_bbox') if block_source == 'parsing_res_list' else raw_block.get('bbox')
                    if not bbox_list:
                        continue
                    
                    try:
                        table_bbox = create_bbox_from_list(bbox_list)
                    except Exception:
                        continue
                    
                    # 获取表格 HTML
                    table_html = raw_block.get('block_content') if block_source == 'parsing_res_list' else raw_block.get('html', '')
                    if not table_html:
                        table_html = raw_block.get('text', '')
                    
                    # 裁剪表格图像
                    table_image = self._crop_image_from_file(
                        file_content, file_type, page_idx, table_bbox
                    )
                    
                    if table_image:
                        all_table_tasks.append({
                            'page_idx': page_idx,
                            'block_idx': block_idx,
                            'table_bbox': table_bbox,
                            'table_html': table_html,
                            'table_image': table_image
                        })
            
            if not all_table_tasks:
                return {}
            
            # 第二步：跨页并行执行所有表格印章识别任务
            logger.info(f"跨页并行识别 {len(all_table_tasks)} 个表格内印章")
            
            api_results = await asyncio.gather(
                *[self._call_seal_recognition_api(t['table_image'], file_name) for t in all_table_tasks],
                return_exceptions=True
            )
            
            # 第三步：按页和 block 聚合结果
            for task, api_result in zip(all_table_tasks, api_results):
                if isinstance(api_result, Exception):
                    logger.debug(f"表格印章识别失败: {api_result}")
                    continue
                
                if not api_result:
                    continue
                
                page_idx = task['page_idx']
                block_idx = task['block_idx']
                table_bbox = task['table_bbox']
                table_html = task['table_html']
                
                # 解析印章结果
                seals = self._parse_table_seal_result(
                    api_result, table_bbox, table_html
                )
                
                if seals:
                    if page_idx not in table_seals_by_page:
                        table_seals_by_page[page_idx] = {}
                    table_seals_by_page[page_idx][block_idx] = seals
                    logger.debug(f"第 {page_idx} 页表格 {block_idx}: 识别出 {len(seals)} 个印章")
            
            # 输出统计
            total_seals = sum(
                sum(len(seals) for seals in blocks.values()) 
                for blocks in table_seals_by_page.values()
            )
            logger.info(f"表格印章识别完成: {total_seals} 个印章，分布在 {len(table_seals_by_page)} 页")
            
            return table_seals_by_page
            
        except Exception as e:
            logger.error(f"提取表格印章失败: {e}", exc_info=True)
            return {}

    def _parse_table_seal_result(
        self,
        api_result: Dict[str, Any],
        table_bbox: List[float],
        table_html: str
    ) -> List[TableSealInfo]:
        """
        解析表格印章识别结果
        
        Args:
            api_result: 印章识别 API 返回的 prunedResult
            table_bbox: 表格在页面中的坐标
            table_html: 表格 HTML
            
        Returns:
            List[TableSealInfo]: 印章信息列表
        """
        seals = []
        
        # 获取检测到的印章框
        layout_det_res = api_result.get('layout_det_res', {})
        boxes = layout_det_res.get('boxes', [])
        
        # 获取印章识别结果
        seal_res_list = api_result.get('seal_res_list', [])
        
        # 遍历检测到的印章框
        for box_idx, box in enumerate(boxes):
            if box.get('label') != 'seal':
                continue
            
            # 获取印章坐标（相对于表格图像）
            coordinate = box.get('coordinate', [])
            if len(coordinate) < 4:
                continue
            
            try:
                seal_bbox_in_table = create_bbox_from_list(coordinate)
            except Exception:
                continue
            
            # 获取印章文本（从 seal_res_list 中查找对应的结果）
            text = ''
            score = box.get('score', 0.0)
            
            if box_idx < len(seal_res_list):
                seal_res = seal_res_list[box_idx]
                rec_texts = seal_res.get('rec_texts', [])
                rec_scores = seal_res.get('rec_scores', [])
                
                if rec_texts:
                    text = ''.join(rec_texts)
                    score = sum(rec_scores) / len(rec_scores) if rec_scores else score
            
            if not text:
                # 尝试从其他来源获取文本
                continue
            
            # 坐标转换：表格 → 页面
            seal_bbox_in_page = self._convert_seal_bbox_to_page(
                seal_bbox_in_table, table_bbox
            )
            
            # 计算位置
            position, position_ratio = self._calculate_seal_position(
                seal_bbox_in_table, [0, 0, table_bbox[2] - table_bbox[0], table_bbox[3] - table_bbox[1]]
            )
            
            # 匹配单元格
            matched_cell_text, matched_cell_row, matched_cell_col = self._match_seal_to_cell(
                seal_bbox_in_table, 
                [0, 0, table_bbox[2] - table_bbox[0], table_bbox[3] - table_bbox[1]],
                table_html
            )
            
            seals.append(TableSealInfo(
                text=text,
                score=score,
                bbox_in_table=seal_bbox_in_table,
                bbox_in_page=seal_bbox_in_page,
                position=position,
                position_ratio=position_ratio,
                matched_cell_text=matched_cell_text,
                matched_cell_row=matched_cell_row,
                matched_cell_col=matched_cell_col
            ))
        
        return seals

    def _merge_seals_to_table_html(
        self,
        table_html: str,
        seals: List[TableSealInfo]
    ) -> str:
        """
        将印章信息以结构化方式合并到表格 HTML
        
        Args:
            table_html: 原始表格 HTML
            seals: 印章信息列表
            
        Returns:
            str: 合并后的表格 HTML
        """
        if not seals:
            return table_html
        
        config = self.seal_extract_config.get('table_seal_recognition', {})
        item_template = config.get('seal_item_template', 
            '<div class="seal-item" data-text="{text}">【印章：{text}】</div>')
        block_template = config.get('seal_block_template',
            '\n<!-- TABLE_SEALS_START -->\n<div class="table-seal-info" data-seal-count="{count}">\n{items}\n</div>\n<!-- TABLE_SEALS_END -->')
        
        seal_items = []
        for seal in seals:
            item = item_template.format(
                text=seal.text,
                score=round(seal.score, 3),
                bbox_table=json.dumps(seal.bbox_in_table),
                bbox_page=json.dumps(seal.bbox_in_page),
                position=seal.position,
                position_ratio=json.dumps(seal.position_ratio),
                cell=seal.matched_cell_text or "未知",
                matched_row=(
                    seal.matched_cell_row if seal.matched_cell_row is not None else ""
                ),
                matched_col=(
                    seal.matched_cell_col if seal.matched_cell_col is not None else ""
                ),
            )
            seal_items.append(item)
        
        seal_block = block_template.format(
            count=len(seals),
            items='\n'.join(seal_items)
        )
        
        return table_html + seal_block
    
    def _convert_to_parse_result(
        self,
        ocr_vl_result: PaddleOCRVLResponse,
        seal_texts_by_page: Dict[int, List[SealDetection]],
        file_name: str,
        file_type: str,
        pdf_page_sizes: Optional[List[Tuple[float, float]]] = None,
        table_seals_by_page: Optional[Dict[int, Dict[int, List[TableSealInfo]]]] = None,
        local_rotation_map: Optional[Dict[int, int]] = None,
    ) -> PaddleParseResult:
        """
        将 Paddle 响应转换为兼容 MinerU 的 ParseResult
        
        Args:
            ocr_vl_result: OCR-VL 解析结果
            seal_texts_by_page: 每页的印章识别结果（OCR-VL 识别的 seal 块）
            file_name: 文件名
            file_type: 文件类型
            pdf_page_sizes: PDF 页面尺寸
            table_seals_by_page: 表格内印章识别结果 {页码: {block_idx: [印章列表]}}
            
        Returns:
            PaddleParseResult: 兼容 MinerU 的解析结果
        """
        if table_seals_by_page is None:
            table_seals_by_page = {}
        try:
            pages: List[PaddlePage] = []
            all_markdown_texts: List[str] = []

            page_info_list = None
            if isinstance(ocr_vl_result.data_info, dict):
                page_info_list = ocr_vl_result.data_info.get('pages')

            for page_idx, page_result in enumerate(ocr_vl_result.layout_parsing_results):
                pruned_result = page_result.pruned_result or {}
                markdown_result = page_result.markdown
                markdown_images = markdown_result.images or {}

                # ===  简化的坐标处理策略 ===
                # Paddle 返回的是 144 DPI 渲染下的像素坐标
                # 我们直接保留原生像素坐标，不做转换
                # 配合专用的 PaddlePDFHighlighter (144 DPI) 使用，确保坐标完全对齐
                
                # 获取页面像素尺寸（用于页面尺寸记录）
                default_pixel_width = 1186  # A4 @144 DPI
                default_pixel_height = 1672
                
                if isinstance(page_info_list, list) and page_idx < len(page_info_list):
                    page_info = page_info_list[page_idx] or {}
                    page_pixel_width = page_info.get('width', default_pixel_width)
                    page_pixel_height = page_info.get('height', default_pixel_height)
                else:
                    page_info = pruned_result.get('page_info', {}) or {}
                    page_pixel_width = page_info.get('width', default_pixel_width)
                    page_pixel_height = page_info.get('height', default_pixel_height)
                
                # 页面尺寸直接使用像素尺寸（144 DPI）
                # 不再转换为点坐标，保持与 Paddle 原始数据一致
                page_width = page_pixel_width
                page_height = page_pixel_height
                
                logger.debug(
                    f"页面 {page_idx} | "
                    f"像素尺寸: {page_pixel_width}x{page_pixel_height} px @ 144 DPI | "
                    f"坐标系统: 原生像素坐标（无转换）"
                )

                if pruned_result.get('parsing_res_list'):
                    block_source = 'parsing_res_list'
                    raw_blocks = pruned_result.get('parsing_res_list', [])
                else:
                    block_source = 'layout_dets'
                    raw_blocks = pruned_result.get('layout_dets', [])

                # 提取 layout_det_res 中的 score 信息（用于匹配到 block）
                layout_det_boxes = []
                if pruned_result.get('layout_det_res'):
                    layout_det_boxes = pruned_result.get('layout_det_res', {}).get('boxes', [])
                
                contents: List[PaddleContent] = []
                layout_blocks: List[PaddleLayoutBlock] = []
                
                # 获取当前页的表格印章信息
                page_table_seals = table_seals_by_page.get(page_idx, {})

                for block_idx, raw_block in enumerate(raw_blocks or []):
                    raw_type = raw_block.get('block_label') if block_source == 'parsing_res_list' else raw_block.get('category_type')
                    block_type = self._normalize_block_type(raw_type)

                    bbox_list = raw_block.get('block_bbox') if block_source == 'parsing_res_list' else raw_block.get('bbox')
                    bbox_value: Optional[List[float]] = None
                    if bbox_list:
                        try:
                            # 标准化bbox格式，保留原生像素坐标（无转换）
                            bbox_value = create_bbox_from_list(bbox_list)
                        except Exception:
                            pass

                    block_content = raw_block.get('block_content') if block_source == 'parsing_res_list' else raw_block.get('text')
                    text = ''
                    table_body = None
                    text_format = None
                    image_base64 = raw_block.get('image_base64') or raw_block.get('image')
                    img_path = raw_block.get('image_path')

                    if block_type == 'table':
                        table_body = raw_block.get('html') if block_source == 'layout_dets' else (block_content or '')
                        text = self._strip_block_text(block_content or '')
                        
                        # 合并表格内印章（如果有）
                        block_seals = page_table_seals.get(block_idx, [])
                        if block_seals and self.seal_extract_config.get('table_seal_recognition', {}).get('merge_to_html', True):
                            table_body = self._merge_seals_to_table_html(table_body, block_seals)
                    elif block_type == 'image':
                        if block_source == 'parsing_res_list' and not img_path:
                            img_path = self._extract_image_key_from_block_content(block_content)
                    elif block_type == 'seal':
                        if block_source == 'parsing_res_list' and not img_path:
                            img_path = self._extract_image_key_from_block_content(block_content)
                    elif block_type == 'formula':
                        text = raw_block.get('text') or raw_block.get('block_text') or self._strip_block_text(block_content or '')
                        text_format = 'latex'
                    elif block_type == 'code':
                        text = raw_block.get('block_text') or (block_content or '')
                    elif block_type == 'list':
                        text = raw_block.get('block_text') or self._strip_block_text(block_content or '')
                    else:
                        if block_source == 'parsing_res_list':
                            text = raw_block.get('block_text') or self._strip_block_text(block_content or '')
                        else:
                            text = raw_block.get('text') or ''

                    if not image_base64 and img_path and markdown_images:
                        image_base64 = markdown_images.get(img_path)

                    if not image_base64 and block_type in ('image', 'seal'):
                        fallback_key = self._extract_image_key_from_block_content(block_content)
                        if fallback_key:
                            if not img_path:
                                img_path = fallback_key
                            image_base64 = markdown_images.get(fallback_key)

                    # 尝试从 layout_det_res.boxes 中匹配 score
                    block_score = None
                    if bbox_value and layout_det_boxes:
                        block_score = self._match_score_from_layout_det(
                            bbox_value, 
                            layout_det_boxes,
                            block_type
                        )
                    
                    content = PaddleContent(
                        type=block_type,
                        text=text,
                        bbox=bbox_value,
                        page_idx=page_idx,
                        img_path=img_path,
                        image_base64=image_base64,
                        table_body=table_body,
                        text_format=text_format,
                        score=block_score  # 添加 score
                    )
                    contents.append(content)

                    # 构建 layout_block 用于溯源
                    # 确保即使 text 为空，也创建包含基本信息的 block
                    span_text = text or self._strip_block_text(block_content or '') or ''
                    
                    # 为表格类型，尝试从 table_body 提取文本
                    if block_type == 'table' and not span_text and table_body:
                        # 简单去除 HTML 标签获取纯文本（用于溯源）
                        import re
                        span_text = re.sub(r'<[^>]+>', ' ', table_body).strip()
                    
                    # 创建 spans 和 lines
                    spans = []
                    if span_text:
                        # 将文本按换行符分割为多个 span（提高溯源精度）
                        text_parts = span_text.split('\n')
                        for part in text_parts:
                            part = part.strip()
                            if part:  # 只添加非空文本
                                spans.append(PaddleSpan(
                                    bbox=bbox_value or [],
                                    text=part
                                ))
                    
                    # 即使没有文本，也创建一个空的 layout_block（保持结构完整性）
                    # 同时保留原始的 text 和 table_body，以便后续处理使用
                    layout_blocks.append(PaddleLayoutBlock(
                        bbox=bbox_value or [],
                        lines=[PaddleLine(bbox=bbox_value or [], spans=spans)] if spans else [],
                        category_type=block_type,
                        text=span_text or None,  # 保留纯文本
                        table_body=table_body if block_type == 'table' else None,  # 保留表格HTML
                        score=block_score
                    ))

                # 印章坐标保留原生像素坐标（无转换）
                self._apply_seal_detections_to_page(
                    contents, layout_blocks, page_idx, seal_texts_by_page
                )

                # 获取页面旋转角度（从 PaddleLayoutParsingResult 中获取）
                rotation_angle = page_result.rotation_angle

                # 获取本地旋转检测模型测得的旋转角度
                local_rotation_angle = (local_rotation_map or {}).get(page_idx, 0)

                page = PaddlePage(
                    page_num=page_idx,
                    width=page_width,
                    height=page_height,
                    contents=contents,
                    layout_blocks=layout_blocks,
                    rotation_angle=rotation_angle,
                    local_rotation_angle=local_rotation_angle,
                )
                pages.append(page)
                
                if rotation_angle != 0:
                    logger.debug(f"页面 {page_idx} 旋转角度: {rotation_angle}°")

                markdown_text = markdown_result.text or ''
                
                if not markdown_text:
                    logger.warning(f"页面 {page_idx} markdown_text 为空！")
                
                if self.seal_extract_config['merge_seal_text'] and seal_texts_by_page.get(page_idx):
                    seal_lines = [
                        self.seal_extract_config['seal_text_format'].format(text=seal.text)
                        for seal in seal_texts_by_page[page_idx]
                        if seal.text
                    ]
                    if seal_lines:
                        markdown_text = markdown_text.rstrip() + '\n\n' + '\n\n'.join(seal_lines)

                all_markdown_texts.append(markdown_text)

            md_content = '\n\n---\n\n'.join(all_markdown_texts)
            logger.info(f"Paddle 解析完成，md_content 总长度: {len(md_content)} 字符，来自 {len(all_markdown_texts)} 页")

            parse_result = PaddleParseResult(
                success=True,
                file_name=file_name,
                file_type=file_type,
                total_pages=len(pages),
                backend='paddle',
                pages=pages,
                md_content=md_content,
                metadata={
                    'ocr_vl_log_id': ocr_vl_result.log_id,
                    'seal_count': sum(len(seals) for seals in seal_texts_by_page.values())
                }
            )

            return parse_result
            
        except Exception as e:
            logger.error(f"转换解析结果失败: {e}", exc_info=True)
            return PaddleParseResult(
                success=False,
                file_name=file_name,
                file_type=file_type,
                total_pages=0,
                error_message=f"结果转换失败: {str(e)}"
            )


# 便捷函数

async def parse_file(
    file_path: Optional[Union[str, Path]] = None,
    file_content: Optional[bytes] = None,
    file_name: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    env: str = None
) -> PaddleParseResult:
    """
    便捷函数：解析文档文件
    
    Args:
        file_path: 文件路径
        file_content: 文件内容（字节）
        file_name: 文件名称
        options: 解析选项
        env: 环境名称
        
    Returns:
        PaddleParseResult: 解析结果
    """
    async with PaddleClient(env) as client:
        return await client.parse_file(file_path, file_content, file_name, options)


# ============ 单例获取函数 ============


def get_paddle_client(env: str = None) -> PaddleClient:
    """
    获取Paddle客户端单例
    
    Args:
        env: 环境名称（dev/prod）
        
    Returns:
        PaddleClient: 客户端实例
    """
    global _paddle_client_instance
    if _paddle_client_instance is None:
        _paddle_client_instance = PaddleClient(env)
        logger.debug(f"创建Paddle客户端单例: env={env or CURRENT_ENV}")
    return _paddle_client_instance


async def close_paddle_client():
    """关闭Paddle客户端"""
    global _paddle_client_instance
    if _paddle_client_instance is not None:
        try:
            await _paddle_client_instance.close()
            logger.debug("关闭Paddle客户端")
        except Exception as e:
            logger.warning(f"关闭Paddle客户端失败: {e}")
        finally:
            _paddle_client_instance = None

