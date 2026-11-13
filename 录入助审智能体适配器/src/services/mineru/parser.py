"""
MinerU响应解析器

根据MinerU官方文档解析API响应
参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/
"""

import json
from typing import Dict, Any, List, Optional, Union
from loguru import logger

from src.services.mineru.models import (
    ParseResult,
    ParsedPage,
    BBox,
    TextContent,
    ImageContent,
    TableContent,
    FormulaContent,
    CodeContent,
    ListContent,
    DiscardedContent,
    ContentListType,
    ContentSubType,
    BlockType,
    CategoryType,
    LayoutBlock,
    Block,
    Line,
    Span,
    parse_bbox_from_any
)


class MinerUParser:
    """
    MinerU响应解析器
    
    支持解析pipeline和VLM后端的响应
    """
    
    @staticmethod
    def parse_response(
        response: Dict[str, Any],
        file_name: str,
        file_type: str
    ) -> ParseResult:
        """
        解析MinerU API响应
        
        Args:
            response: API响应数据
            file_name: 文件名
            file_type: 文件类型
            
        Returns:
            ParseResult: 解析结果
        """
        try:
            # 检查响应格式
            if not isinstance(response, dict):
                raise ValueError(f"响应格式错误: 期望dict，得到 {type(response)}")
            
            # 打印响应结构用于调试
            logger.info(f"MinerU API 响应结构分析:")
            logger.info(f"  - 顶层键: {list(response.keys())}")
            logger.info(f"  - 响应大小: {len(str(response))} 字符")
            
            # 详细打印前500个字符
            response_preview = str(response)[:500]
            logger.info(f"  - 响应预览: {response_preview}...")
            
            # 判断后端类型（从 _backend 或 backend 字段获取）
            backend = response.get('_backend', response.get('backend', 'vlm-vllm-async-engine'))
            logger.info(f"  - 后端类型: {backend}")
            
            # 检查是否包含错误信息
            if 'error' in response or 'error_message' in response:
                error_msg = response.get('error', response.get('error_message', '解析失败'))
                logger.error(f"MinerU解析失败: {error_msg}")
                return ParseResult(
                    success=False,
                    file_name=file_name,
                    file_type=file_type,
                    total_pages=0,
                    backend=backend,
                    error_message=error_msg
                )
            
            # MinerU 官方格式：包含 pdf_info 字段
            # 参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/
            if 'pdf_info' not in response:
                # 如果没有 pdf_info，检查是否有旧格式的 success 字段
                if 'success' in response and not response['success']:
                    error_msg = response.get('message', '解析失败')
                    logger.error(f"MinerU解析失败: {error_msg}")
                    return ParseResult(
                        success=False,
                        file_name=file_name,
                        file_type=file_type,
                        total_pages=0,
                        backend=backend,
                        error_message=error_msg
                    )
            
            # 解析页面数据
            pages = []
            md_content = None  # 存储 Markdown 内容
            
            # 方式1: results 格式（实际 API 返回格式）
            if 'results' in response:
                logger.info("检测到 results 格式")
                results = response['results']
                logger.info(f"  - results 类型: {type(results)}")
                
                if isinstance(results, dict):
                    logger.info(f"  - results 键: {list(results.keys())}")
                    
                    # 遍历 results 中的每个文件（通常只有一个）
                    for file_key, file_data in results.items():
                        if not isinstance(file_data, dict):
                            continue
                            
                        logger.info(f"  - 文件 '{file_key}' 的数据键: {list(file_data.keys())}")
                        
                        # 提取 md_content
                        if 'md_content' in file_data:
                            md_content = file_data['md_content']
                            logger.info(f"  - 提取到 md_content，长度: {len(md_content) if md_content else 0} 字符")
                        
                        # 优先使用 middle_json（包含完整的结构和坐标）
                        if 'middle_json' in file_data:
                            logger.info("  - 发现 middle_json，使用它解析")
                            middle_data = file_data['middle_json']
                            
                            # 如果是字符串，先解析为 JSON 对象
                            if isinstance(middle_data, str):
                                try:
                                    middle_data = json.loads(middle_data)
                                    logger.info("  - middle_json 字符串已解析为字典")
                                except Exception as e:
                                    logger.error(f"  - 解析 middle_json 字符串失败: {e}")
                                    middle_data = None
                            
                            # middle_json 应该包含 pdf_info 数组
                            if isinstance(middle_data, dict) and 'pdf_info' in middle_data:
                                logger.info(f"  - middle_json 包含 pdf_info，共 {len(middle_data['pdf_info'])} 页")
                                pdf_info = middle_data['pdf_info']
                                if isinstance(pdf_info, list):
                                    for idx, page_data in enumerate(pdf_info):
                                        try:
                                            page = MinerUParser._parse_pdf_info_page(page_data, backend)
                                            if page:
                                                pages.append(page)
                                                logger.debug(f"  - 第 {idx} 页解析成功，内容数量: {len(page.contents)}")
                                        except Exception as e:
                                            logger.warning(f"  - 解析第 {idx} 页失败: {e}")
                                            continue
                            else:
                                logger.warning(f"  - middle_json 格式不符合预期: type={type(middle_data)}, 包含 pdf_info: {isinstance(middle_data, dict) and 'pdf_info' in middle_data}")
                        
                        # 如果没有 middle_json 但有 content_list_json 或 content_list
                        elif 'content_list_json' in file_data or 'content_list' in file_data:
                            logger.info("  - 发现 content_list，使用它解析")
                            content_data = file_data.get('content_list_json') or file_data.get('content_list')
                            
                            # 如果是字符串，先解析为 JSON 对象
                            if isinstance(content_data, str):
                                try:
                                    content_data = json.loads(content_data)
                                    logger.info("  - content_list 字符串已解析为列表")
                                except Exception as e:
                                    logger.error(f"  - 解析 content_list 字符串失败: {e}")
                                    content_data = None
                            
                            if isinstance(content_data, list):
                                pages = MinerUParser._parse_content_list(content_data, backend)
                            else:
                                logger.warning(f"  - content_list 格式不符合预期: type={type(content_data)}")
                        
                        # 如果都没有，尝试 VLM 的 model_json 格式
                        elif 'model_json' in file_data:
                            logger.info("  - 发现 model_json (VLM 格式)，使用它解析")
                            model_data = file_data['model_json']
                            
                            # 如果是字符串，先解析为 JSON 对象
                            if isinstance(model_data, str):
                                try:
                                    model_data = json.loads(model_data)
                                    logger.info("  - model_json 字符串已解析")
                                except Exception as e:
                                    logger.error(f"  - 解析 model_json 字符串失败: {e}")
                                    model_data = None
                            
                            # VLM 的 model.json 是两层嵌套的 list：[[page1_blocks], [page2_blocks], ...]
                            if isinstance(model_data, list):
                                pages = MinerUParser._parse_vlm_model_format(model_data)
                                logger.info(f"  - VLM model.json 解析完成，共 {len(pages)} 页")
                        
                        # 如果都没有，只有 md_content
                        elif 'md_content' in file_data:
                            logger.warning("  - 只有 md_content，无结构化数据")
                            logger.warning("  - 这不应该发生，检查 API 请求参数")
                
                logger.info(f"results 格式解析完成，共 {len(pages)} 页")
            
            # 方式2: MinerU 官方文档格式 - pdf_info 数组
            elif 'pdf_info' in response:
                logger.info("检测到 pdf_info 格式，使用官方解析方式")
                pdf_info = response['pdf_info']
                logger.info(f"  - pdf_info 类型: {type(pdf_info)}, 长度: {len(pdf_info) if isinstance(pdf_info, list) else 'N/A'}")
                
                if isinstance(pdf_info, list):
                    for idx, page_data in enumerate(pdf_info):
                        try:
                            logger.debug(f"  - 解析第 {idx} 页, 键: {list(page_data.keys()) if isinstance(page_data, dict) else 'N/A'}")
                            page = MinerUParser._parse_pdf_info_page(page_data, backend)
                            if page:
                                pages.append(page)
                                logger.debug(f"  - 第 {idx} 页解析成功，内容数量: {len(page.contents)}")
                        except Exception as e:
                            logger.warning(f"解析第 {idx} 页失败: {e}", exc_info=True)
                            continue
                    logger.info(f"pdf_info 格式解析完成，共 {len(pages)} 页")
            
            # 方式2: 直接包含content_list数据
            elif 'content_list' in response:
                logger.info("检测到 content_list 格式")
                pages = MinerUParser._parse_content_list(response['content_list'], backend)
                logger.info(f"content_list 格式解析完成，共 {len(pages)} 页")
            
            # 方式3: 包含pages数组
            elif 'pages' in response:
                logger.info("检测到 pages 数组格式")
                pages_data = response['pages']
                for page_data in pages_data:
                    try:
                        page = MinerUParser._parse_page_data(page_data, backend)
                        if page:
                            pages.append(page)
                    except Exception as e:
                        logger.warning(f"解析页面失败: {e}")
                        continue
                logger.info(f"pages 数组格式解析完成，共 {len(pages)} 页")
            
            # 方式4: 包含middle.json格式的数据
            elif 'middle' in response or 'preproc_blocks' in response:
                logger.info("检测到 middle.json 格式")
                middle_data = response.get('middle', response)
                pages = MinerUParser._parse_middle_format(middle_data)
                logger.info(f"middle.json 格式解析完成，共 {len(pages)} 页")
            
            else:
                logger.warning("未识别的响应格式，尝试基本解析")
                logger.warning(f"可用的键: {list(response.keys())}")
                # 尝试基本解析
                if 'page_info' in response:
                    logger.info("尝试使用 page_info 基本解析")
                    page = MinerUParser._parse_basic_page(response)
                    if page:
                        pages = [page]
            
            # 创建解析结果
            result = ParseResult(
                success=True,
                file_name=file_name,
                file_type=file_type,
                total_pages=len(pages),
                backend=backend,
                pages=pages,
                md_content=md_content,
                metadata=response.get('metadata', {})
            )
            
            return result
            
        except Exception as e:
            logger.error(f"解析响应失败: {e}", exc_info=True)
            return ParseResult(
                success=False,
                file_name=file_name,
                file_type=file_type,
                total_pages=0,
                error_message=f"解析响应失败: {str(e)}"
            )
    
    @staticmethod
    def _parse_content_list(
        content_list: List[Dict[str, Any]],
        backend: str = "pipeline"
    ) -> List[ParsedPage]:
        """
        解析content_list.json格式的数据
        
        参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/#content_listjson
        """
        # 按页面分组
        pages_dict: Dict[int, List[Any]] = {}
        page_dimensions: Dict[int, tuple[float, float]] = {}
        
        for item in content_list:
            try:
                page_idx = item.get('page_idx', item.get('page_num', item.get('page_no', 0)))
                
                # 解析内容对象
                content = MinerUParser._parse_content_item(item)
                if content:
                    if page_idx not in pages_dict:
                        pages_dict[page_idx] = []
                    pages_dict[page_idx].append(content)
                    
                    # 尝试获取页面尺寸（从第一个有bbox的内容推断）
                    if page_idx not in page_dimensions and hasattr(content, 'bbox') and content.bbox:
                        # 暂时使用默认A4尺寸，后续可以从page_info获取
                        page_dimensions[page_idx] = (595, 842)
                        
            except Exception as e:
                logger.warning(f"解析内容项失败: {e}")
                continue
        
        # 创建页面对象
        pages = []
        for page_idx in sorted(pages_dict.keys()):
            width, height = page_dimensions.get(page_idx, (595, 842))
            page = ParsedPage(
                page_num=page_idx,
                width=width,
                height=height,
                contents=pages_dict[page_idx]
            )
            pages.append(page)
        
        return pages
    
    @staticmethod
    def _parse_content_item(item: Dict[str, Any]) -> Optional[Union[
        TextContent, ImageContent, TableContent, FormulaContent, 
        CodeContent, ListContent, DiscardedContent
    ]]:
        """解析单个内容项"""
        content_type = item.get('type', '')
        page_idx = item.get('page_idx', item.get('page_num', 0))
        
        # 解析bbox
        bbox = None
        if 'bbox' in item and item['bbox']:
            try:
                bbox = parse_bbox_from_any(item['bbox'])
            except Exception as e:
                logger.warning(f"解析bbox失败: {e}")
        
        # 根据类型解析
        if content_type == 'text':
            return TextContent(
                type=ContentListType.TEXT,
                text=item.get('text', ''),
                bbox=bbox,
                page_idx=page_idx
            )
        
        elif content_type == 'image':
            return ImageContent(
                type=ContentListType.IMAGE,
                img_path=item.get('img_path', ''),
                img_caption=item.get('img_caption'),
                bbox=bbox,
                page_idx=page_idx
            )
        
        elif content_type == 'table':
            return TableContent(
                type=ContentListType.TABLE,
                img_path=item.get('img_path', ''),
                table_caption=item.get('table_caption'),
                bbox=bbox,
                page_idx=page_idx
            )
        
        elif content_type in ['interline_equation', 'equation']:
            return FormulaContent(
                type='equation',
                text=item.get('text', item.get('latex', '')),
                img_path=item.get('img_path', ''),
                text_format='latex',
                bbox=bbox,
                page_idx=page_idx
            )
        
        elif content_type == 'code':
            sub_type_str = item.get('sub_type', 'code')
            try:
                sub_type = ContentSubType(sub_type_str)
            except ValueError:
                sub_type = ContentSubType.CODE
            
            return CodeContent(
                type=ContentListType.CODE,
                sub_type=sub_type,
                code_body=item.get('code_body', ''),
                code_caption=item.get('code_caption'),
                bbox=bbox,
                page_idx=page_idx
            )
        
        elif content_type == 'list':
            sub_type_str = item.get('sub_type', 'text')
            try:
                sub_type = ContentSubType(sub_type_str)
            except ValueError:
                sub_type = ContentSubType.TEXT
            
            return ListContent(
                type=ContentListType.LIST,
                sub_type=sub_type,
                list_items=item.get('list_items', []),
                bbox=bbox,
                page_idx=page_idx
            )
        
        # 废弃内容类型
        elif content_type in ['header', 'footer', 'page_number', 'aside_text', 'page_footnote', 'phonetic']:
            return DiscardedContent(
                type=ContentListType(content_type),
                text=item.get('text', ''),
                bbox=bbox,
                page_idx=page_idx
            )
        
        else:
            logger.warning(f"未知的内容类型: {content_type}")
            return None
    
    @staticmethod
    def _parse_page_data(
        page_data: Dict[str, Any],
        backend: str
    ) -> Optional[ParsedPage]:
        """解析单个页面数据"""
        try:
            page_num = page_data.get('page_num', page_data.get('page_no', 0))
            width = page_data.get('width', 595)
            height = page_data.get('height', 842)
            
            # 解析内容
            contents = []
            
            # 如果包含blocks
            if 'blocks' in page_data:
                for block_data in page_data['blocks']:
                    content = MinerUParser._parse_content_item(block_data)
                    if content:
                        contents.append(content)
            
            # 如果包含contents
            elif 'contents' in page_data:
                for content_data in page_data['contents']:
                    content = MinerUParser._parse_content_item(content_data)
                    if content:
                        contents.append(content)
            
            return ParsedPage(
                page_num=page_num,
                width=width,
                height=height,
                contents=contents,
                metadata=page_data.get('metadata', {})
            )
            
        except Exception as e:
            logger.error(f"解析页面数据失败: {e}")
            return None
    
    @staticmethod
    def _parse_middle_format(middle_data: Dict[str, Any]) -> List[ParsedPage]:
        """
        解析middle.json格式的数据
        
        参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/#middlejson_2
        """
        pages = []
        
        try:
            # 获取页面信息
            page_info = middle_data.get('page_info', {})
            page_num = page_info.get('page_no', 0)
            width = page_info.get('width', 595)
            height = page_info.get('height', 842)
            
            # 解析预处理块
            preproc_blocks = middle_data.get('preproc_blocks', [])
            contents = []
            
            for block_data in preproc_blocks:
                # 从块中提取文本内容
                text = MinerUParser._extract_text_from_block(block_data)
                if text:
                    bbox = parse_bbox_from_any(block_data['bbox'])
                    content = TextContent(
                        type=ContentListType.TEXT,
                        text=text,
                        bbox=bbox,
                        page_idx=page_num
                    )
                    contents.append(content)
            
            page = ParsedPage(
                page_num=page_num,
                width=width,
                height=height,
                contents=contents
            )
            pages.append(page)
            
        except Exception as e:
            logger.error(f"解析middle格式失败: {e}")
        
        return pages
    
    @staticmethod
    def _parse_pdf_info_page(page_data: Dict[str, Any], backend: str = "pipeline") -> Optional[ParsedPage]:
        """
        解析 pdf_info 中的单页数据
        
        根据 MinerU 官方文档格式解析
        参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/
        
        Args:
            page_data: 页面数据，包含 preproc_blocks, para_blocks, page_idx, page_size 等
            backend: 后端类型
            
        Returns:
            Optional[ParsedPage]: 解析后的页面对象
        """
        try:
            page_idx = page_data.get('page_idx', 0)
            page_size = page_data.get('page_size', [595, 842])  # 默认 A4 尺寸
            width, height = page_size[0], page_size[1]
            
            logger.debug(f"    解析页面 {page_idx}, 尺寸: {width}x{height}")
            
            # 存储所有内容块
            layout_blocks = []
            contents = []
            
            # 解析 para_blocks（主要内容块）
            para_blocks = page_data.get('para_blocks', [])
            logger.debug(f"    para_blocks 数量: {len(para_blocks)}")
            
            # 如果没有 para_blocks，尝试 preproc_blocks
            if not para_blocks and 'preproc_blocks' in page_data:
                para_blocks = page_data.get('preproc_blocks', [])
                logger.debug(f"    使用 preproc_blocks，数量: {len(para_blocks)}")
            
            for block_idx, block_data in enumerate(para_blocks):
                try:
                    # 解析布局块
                    layout_block = MinerUParser._parse_layout_block(block_data)
                    if layout_block:
                        layout_blocks.append(layout_block)
                        
                        # 根据块类型创建对应的 Content 对象
                        block_type = block_data.get('type', 'text')
                        bbox = parse_bbox_from_any(block_data.get('bbox', [0, 0, width, height]))
                        
                        if block_type == 'table':
                            # 表格内容：提取 HTML
                            html_content = MinerUParser._extract_html_from_table_block(block_data)
                            if html_content:
                                content = TableContent(
                                    type='table',
                                    bbox=bbox,
                                    page_idx=page_idx,
                                    img_path="",  # 暂时留空
                                    table_body=html_content
                                )
                                contents.append(content)
                        
                        elif block_type == 'title':
                            # 标题内容
                            text = MinerUParser._extract_text_from_block(block_data)
                            if text:
                                content = TextContent(
                                    type='text',
                                    text=text,
                                    bbox=bbox,
                                    page_idx=page_idx,
                                    block_type=block_type,
                                    text_level=1  # 标题级别
                                )
                                contents.append(content)
                        
                        else:
                            # 普通文本内容
                            text = MinerUParser._extract_text_from_block(block_data)
                            if text:
                                content = TextContent(
                                    type='text',
                                    text=text,
                                    bbox=bbox,
                                    page_idx=page_idx,
                                    block_type=block_type
                                )
                                contents.append(content)
                
                except Exception as e:
                    logger.debug(f"解析块 {block_idx} 失败: {e}")
                    continue
            
            # 创建页面对象
            page = ParsedPage(
                page_num=page_idx,
                width=width,
                height=height,
                layout_blocks=layout_blocks,
                contents=contents
            )
            
            return page
            
        except Exception as e:
            logger.error(f"解析 pdf_info 页面失败: {e}")
            return None
    
    @staticmethod
    def _parse_layout_block(block_data: Dict[str, Any]) -> Optional[LayoutBlock]:
        """解析布局块"""
        try:
            block_type = block_data.get('type', 'text')
            bbox_data = block_data.get('bbox', [0, 0, 0, 0])
            bbox = parse_bbox_from_any(bbox_data)
            
            # 检查是否为跨页表格的延续页（lines_deleted 标记）
            is_continuation = False
            if block_type == 'table' and 'blocks' in block_data:
                for nested_block in block_data['blocks']:
                    if isinstance(nested_block, dict) and nested_block.get('lines_deleted'):
                        is_continuation = True
                        break
            
            # 解析 lines
            lines_data = block_data.get('lines', [])
            
            # 对于表格块，lines 可能在嵌套的 blocks 中
            if not lines_data and 'blocks' in block_data:
                nested_blocks = block_data.get('blocks', [])
                for nested_block in nested_blocks:
                    if isinstance(nested_block, dict):
                        nested_lines = nested_block.get('lines', [])
                        if nested_lines:
                            lines_data.extend(nested_lines)
            
            # 解析 lines
            lines = []
            for line_data in lines_data:
                if isinstance(line_data, dict):
                    line = MinerUParser._parse_line(line_data)
                    if line:
                        lines.append(line)
            
            # 创建布局块（即使 lines 为空也创建，保留块的结构信息）
            layout_block = LayoutBlock(
                category_type=block_type,
                bbox=bbox,
                lines=lines
            )
            
            # 添加跨页标记（作为动态属性）
            if is_continuation:
                layout_block.is_continuation = True
            
            return layout_block
            
        except Exception as e:
            logger.debug(f"解析布局块失败: {e}")
            return None
    
    @staticmethod
    def _parse_line(line_data: Dict[str, Any]) -> Optional[Line]:
        """解析行数据"""
        try:
            bbox_data = line_data.get('bbox', [0, 0, 0, 0])
            bbox = parse_bbox_from_any(bbox_data)
            
            # 解析 spans
            spans = []
            if 'spans' in line_data:
                for span_data in line_data['spans']:
                    span = MinerUParser._parse_span(span_data)
                    if span:
                        spans.append(span)
            
            line = Line(
                bbox=bbox,
                spans=spans
            )
            
            return line
            
        except Exception as e:
            logger.debug(f"解析行失败: {e}")
            return None
    
    @staticmethod
    def _parse_span(span_data: Dict[str, Any]) -> Optional[Span]:
        """解析 span 数据"""
        try:
            bbox_data = span_data.get('bbox', [0, 0, 0, 0])
            bbox = parse_bbox_from_any(bbox_data)
            
            # 提取文本内容：优先 content，其次 text，最后 html（表格）
            content = span_data.get('content')
            if content is None:
                content = span_data.get('text')
            if content is None:
                content = span_data.get('html', '')
            
            span_type = span_data.get('type', 'text')
            score = span_data.get('score', 1.0)
            
            span = Span(
                bbox=bbox,
                text=content if isinstance(content, str) else '',
                type=span_type,
                score=score
            )
            
            return span
            
        except Exception as e:
            logger.debug(f"解析 span 失败: {e}")
            return None
    
    @staticmethod
    def _extract_text_from_block(block_data: Dict[str, Any]) -> str:
        """从块数据中提取文本"""
        texts = []
        
        # 递归提取blocks中的文本
        if 'blocks' in block_data:
            for sub_block in block_data['blocks']:
                text = MinerUParser._extract_text_from_block(sub_block)
                if text:
                    texts.append(text)
        
        # 从lines中提取文本
        if 'lines' in block_data:
            for line in block_data['lines']:
                if 'spans' in line:
                    for span in line['spans']:
                        if 'content' in span:
                            texts.append(span['content'])
        
        return '\n'.join(texts)
    
    @staticmethod
    def _extract_html_from_table_block(block_data: Dict[str, Any]) -> str:
        """
        从表格块中提取 HTML 内容
        
        表格块的结构：
        {
            "type": "table",
            "blocks": [
                {
                    "type": "table_body",
                    "lines": [
                        {
                            "spans": [
                                {
                                    "html": "<table>...</table>",
                                    "type": "table"
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        
        Args:
            block_data: 表格块数据
            
        Returns:
            str: HTML 内容
        """
        # 检查嵌套的 blocks
        if 'blocks' in block_data:
            for sub_block in block_data['blocks']:
                if 'lines' in sub_block:
                    for line in sub_block['lines']:
                        if 'spans' in line:
                            for span in line['spans']:
                                # 表格的 span 包含 html 字段
                                if 'html' in span:
                                    return span['html']
        
        # 直接检查 lines
        if 'lines' in block_data:
            for line in block_data['lines']:
                if 'spans' in line:
                    for span in line['spans']:
                        if 'html' in span:
                            return span['html']
        
        return ""
    
    @staticmethod
    def _parse_basic_page(data: Dict[str, Any]) -> Optional[ParsedPage]:
        """基本页面解析（降级方案）"""
        try:
            page_info = data.get('page_info', {})
            page_num = page_info.get('page_no', 0)
            width = page_info.get('width', 595)
            height = page_info.get('height', 842)
            
            return ParsedPage(
                page_num=page_num,
                width=width,
                height=height,
                contents=[],
                metadata=data.get('metadata', {})
            )
        except Exception as e:
            logger.error(f"基本页面解析失败: {e}")
            return None
    
    @staticmethod
    def _parse_vlm_model_format(model_data: List[List[Dict[str, Any]]]) -> List[ParsedPage]:
        """
        解析 VLM 的 model.json 格式
        
        VLM 的 model.json 是两层嵌套的 list：
        [
            [  # 第一页
                {"type": "text", "bbox": [x0, y0, x1, y1], "content": "...", ...},
                ...
            ],
            [  # 第二页
                ...
            ]
        ]
        
        注意：VLM 的 bbox 坐标是相对于页面尺寸的百分比（0-1）
        
        Args:
            model_data: VLM model.json 数据（两层嵌套 list）
            
        Returns:
            List[ParsedPage]: 解析后的页面列表
        """
        pages = []
        
        try:
            # 遍历每一页
            for page_idx, page_blocks in enumerate(model_data):
                if not isinstance(page_blocks, list):
                    logger.warning(f"页面 {page_idx} 数据格式错误，跳过")
                    continue
                
                # 使用默认的 A4 页面尺寸（595x842 点）
                # 注意：VLM 的坐标是百分比，我们需要页面实际尺寸来转换
                # 这里使用标准 A4 尺寸，实际应该从 API 响应中获取
                page_width = 595
                page_height = 842
                
                # 解析内容块
                contents = []
                for block in page_blocks:
                    if not isinstance(block, dict):
                        continue
                    
                    try:
                        content = MinerUParser._parse_vlm_block(block, page_idx, page_width, page_height)
                        if content:
                            contents.append(content)
                    except Exception as e:
                        logger.debug(f"解析 VLM 块失败: {e}")
                        continue
                
                # 创建页面对象
                page = ParsedPage(
                    page_num=page_idx,
                    width=page_width,
                    height=page_height,
                    contents=contents
                )
                pages.append(page)
                
                logger.debug(f"VLM 页面 {page_idx} 解析完成，内容块数量: {len(contents)}")
        
        except Exception as e:
            logger.error(f"解析 VLM model.json 失败: {e}")
        
        return pages
    
    @staticmethod
    def _parse_vlm_block(
        block: Dict[str, Any], 
        page_idx: int,
        page_width: float,
        page_height: float
    ) -> Optional[Union[TextContent, ImageContent, TableContent, FormulaContent, CodeContent, ListContent, DiscardedContent]]:
        """
        解析 VLM 的单个内容块
        
        VLM 块结构：
        {
            "type": "text",
            "bbox": [x0, y0, x1, y1],  # 百分比坐标 (0-1)
            "angle": 0,
            "content": "文本内容",
            ...
        }
        
        Args:
            block: VLM 块数据
            page_idx: 页码
            page_width: 页面宽度（用于坐标转换）
            page_height: 页面高度（用于坐标转换）
            
        Returns:
            内容对象
        """
        block_type = block.get('type', '')
        content_text = block.get('content', '')
        
        # 解析 bbox（VLM 的 bbox 是百分比坐标）
        bbox = None
        if 'bbox' in block and block['bbox']:
            try:
                bbox = BBox.from_list(block['bbox'], page_width, page_height)
            except Exception as e:
                logger.debug(f"解析 VLM bbox 失败: {e}")
        
        # 根据类型创建对应的内容对象
        # 文本类型
        if block_type in ['text', 'title']:
            return TextContent(
                type='text',
                text=content_text,
                bbox=bbox,
                page_idx=page_idx,
                block_type=block_type,
                text_level=1 if block_type == 'title' else None
            )
        
        # 公式类型
        elif block_type == 'equation':
            return FormulaContent(
                type='equation',
                bbox=bbox,
                page_idx=page_idx,
                img_path="",
                text=content_text,
                text_format='latex'
            )
        
        # 图片类型
        elif block_type == 'image':
            return ImageContent(
                type='image',
                img_path="",
                bbox=bbox,
                page_idx=page_idx
            )
        
        # 图片描述/脚注
        elif block_type in ['image_caption', 'image_footnote']:
            return TextContent(
                type='text',
                text=content_text,
                bbox=bbox,
                page_idx=page_idx,
                block_type=block_type
            )
        
        # 表格类型
        elif block_type == 'table':
            return TableContent(
                type='table',
                bbox=bbox,
                page_idx=page_idx,
                img_path="",
                table_body=content_text if content_text else ""
            )
        
        # 表格描述/脚注
        elif block_type in ['table_caption', 'table_footnote']:
            return TextContent(
                type='text',
                text=content_text,
                bbox=bbox,
                page_idx=page_idx,
                block_type=block_type
            )
        
        # 代码类型
        elif block_type in ['code', 'algorithm']:
            return CodeContent(
                type=ContentListType.CODE,
                sub_type=ContentSubType.CODE if block_type == 'code' else ContentSubType.ALGORITHM,
                code_body=content_text,
                bbox=bbox,
                page_idx=page_idx
            )
        
        # 代码描述
        elif block_type == 'code_caption':
            return TextContent(
                type='text',
                text=content_text,
                bbox=bbox,
                page_idx=page_idx,
                block_type=block_type
            )
        
        # 列表类型
        elif block_type == 'list':
            # VLM 的 list 在 model.json 中只有 content，没有 list_items
            # 需要从 content 中提取或使用 middle.json/content_list.json
            list_items = content_text.split('\n') if content_text else []
            return ListContent(
                type=ContentListType.LIST,
                sub_type=ContentSubType.TEXT,
                list_items=list_items,
                bbox=bbox,
                page_idx=page_idx
            )
        
        # 参考文献
        elif block_type == 'ref_text':
            return ListContent(
                type=ContentListType.LIST,
                sub_type=ContentSubType.REF_TEXT,
                list_items=[content_text] if content_text else [],
                bbox=bbox,
                page_idx=page_idx
            )
        
        # 废弃内容类型
        elif block_type in ['header', 'footer', 'page_number', 'aside_text', 'page_footnote', 'phonetic']:
            try:
                content_list_type = ContentListType(block_type)
            except ValueError:
                # 如果类型不在 ContentListType 中，使用 aside_text 作为默认值
                content_list_type = ContentListType.ASIDE_TEXT
            
            return DiscardedContent(
                type=content_list_type,
                text=content_text,
                bbox=bbox,
                page_idx=page_idx
            )
        
        # 未知类型
        else:
            logger.debug(f"未知的 VLM 块类型: {block_type}")
            # 尝试作为文本处理
            if content_text:
                return TextContent(
                    type='text',
                    text=content_text,
                    bbox=bbox,
                    page_idx=page_idx,
                    block_type=block_type
                )
        
        return None

