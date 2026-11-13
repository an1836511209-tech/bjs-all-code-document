"""
Anchor Markdown 转换器

将 Paddle/MinerU 解析结果转换为带锚点的 Markdown 格式
用于统一提取与溯源的 LLM 输入

锚点格式: (¶P-ID)
- P: 页码 (Page Index)
- ID: 该页内的片段索引

示例输出:
    甲方：北京某某公司 (¶0-2)
    [印章: 合同专用章] (¶0-10)
"""

import json
import re
from typing import Dict, Any, List, Tuple, Optional
from loguru import logger


class SegmentInfo:
    """片段信息（用于后端查表）"""
    
    def __init__(
        self,
        anchor_id: str,
        page_idx: int,
        bbox: List[float],
        text: str,
        segment_type: str = "text",
        score: Optional[float] = None,
        cells: Optional[List[Dict[str, Any]]] = None,
        file_index: Optional[int] = None,
        sheet_name: Optional[str] = None,
        row: Optional[int] = None,
        col: Optional[int] = None,
        cell_ref: Optional[str] = None,
    ):
        self.anchor_id = anchor_id
        self.page_idx = page_idx
        self.bbox = bbox
        self.text = text
        self.segment_type = segment_type  # text, seal, table, image, excel_cell
        self.score = score
        # 表格单元格信息（仅 table 类型，由 PaddleStructureV3 提供）
        # 每个 cell: {"bbox": [...], "text": "...", "row": 0, "col": 0}
        self.cells = cells
        # Excel 溯源扩展字段
        self.file_index = file_index
        self.sheet_name = sheet_name
        self.row = row
        self.col = col
        self.cell_ref = cell_ref
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "anchor_id": self.anchor_id,
            "page_idx": self.page_idx,
            "bbox": self.bbox,
            "text": self.text,
            "type": self.segment_type,
            "score": self.score
        }
        # 只有当 cells 有值时才加入结果
        if self.cells:
            result["cells"] = self.cells
        if self.file_index is not None:
            result["file_index"] = self.file_index
        if self.sheet_name:
            result["sheet_name"] = self.sheet_name
        if self.row is not None:
            result["row"] = self.row
        if self.col is not None:
            result["col"] = self.col
        if self.cell_ref:
            result["cell_ref"] = self.cell_ref
        return result


class AnchorMarkdownConverter:
    """
    Anchor Markdown 转换器
    
    将 Paddle/MinerU 解析结果转换为：
    1. 带锚点的 Markdown 文本（给 LLM 看）
    2. 片段映射表（给后端查表用）
    """
    
    # 锚点符号（使用 ¶ 符号，不易与正文混淆）
    ANCHOR_SYMBOL = "¶"
    # 单元格已有内容与印章标记的分隔符（避免与正文粘连）
    SEAL_CELL_TEXT_SEPARATOR = "\n"
    
    @classmethod
    def convert(
        cls,
        file_data: Dict[str, Any],
        include_tables: bool = True,
        include_seals: bool = True
    ) -> Tuple[str, Dict[str, SegmentInfo]]:
        """
        将解析结果转换为带锚点的 Markdown
        
        Args:
            file_data: 解析后的文件数据，包含 parse_results
            include_tables: 是否包含表格内容
            include_seals: 是否包含印章内容
            
        Returns:
            Tuple[str, Dict[str, SegmentInfo]]:
                - 带锚点的 Markdown 文本
                - 片段映射表 {anchor_id: SegmentInfo}
        """
        parse_results = file_data.get("parse_results", [])
        
        if not parse_results:
            logger.warning("parse_results 为空，无法转换")
            return "", {}
        
        # Debug: 输出 file_data 的顶层结构
        logger.debug(
            f"Anchor Markdown 转换开始 | "
            f"file_data keys: {list(file_data.keys())} | "
            f"parse_results 数量: {len(parse_results)} | "
            f"parse_results 类型: {type(parse_results[0]).__name__ if parse_results else 'N/A'}"
        )
        
        # 统计变量，用于最终诊断
        total_pages = 0
        total_layout_blocks = 0
        total_skipped_empty_blocks = 0
        
        all_lines: List[str] = []
        segment_map: Dict[str, SegmentInfo] = {}
        
        # 全局页码偏移（用于多文件合并场景）
        global_page_offset = 0
        
        for result_idx, parse_result in enumerate(parse_results):
            # 获取文件名（如果有多个文件）
            file_name = getattr(parse_result, 'file_name', None)
            if file_name and len(parse_results) > 1:
                all_lines.append(f"\n# === {file_name} ===\n")
            
            pages = getattr(parse_result, 'pages', [])
            
            # Debug: 输出每个 parse_result 的结构
            parse_result_attrs = [attr for attr in dir(parse_result) if not attr.startswith('_')]
            logger.debug(
                f"parse_result[{result_idx}] | "
                f"类型: {type(parse_result).__name__} | "
                f"属性: {parse_result_attrs[:10]}... | "
                f"pages 数量: {len(pages) if pages else 0}"
            )
            
            for page in pages:
                page_idx = getattr(page, 'page_num', 0) + global_page_offset
                total_pages += 1
                
                # 获取该页的所有 layout_blocks
                layout_blocks = getattr(page, 'layout_blocks', [])
                total_layout_blocks += len(layout_blocks) if layout_blocks else 0
                
                # Debug: 输出每页的 layout_blocks 信息
                if not layout_blocks:
                    page_attrs = [attr for attr in dir(page) if not attr.startswith('_')]
                    logger.debug(
                        f"页面 {page_idx} 没有 layout_blocks | "
                        f"page 类型: {type(page).__name__} | "
                        f"page 属性: {page_attrs[:15]}..."
                    )
                else:
                    logger.debug(
                        f"页面 {page_idx} | layout_blocks 数量: {len(layout_blocks)}"
                    )
                
                # 按 y 坐标排序（从上到下）
                sorted_blocks = cls._sort_blocks_by_position(layout_blocks)
                
                segment_idx = 0
                skipped_empty_blocks = 0
                
                for block in sorted_blocks:
                    category_type = getattr(block, 'category_type', 'text')
                    bbox = cls._extract_bbox(block)
                    
                    # 获取文本内容
                    text = cls._extract_block_text(block)
                    
                    # 对于表格，即使 text 为空也不应该跳过（内容在 table_body 中）
                    table_body = getattr(block, 'table_body', None)
                    has_content = bool(text and text.strip()) or bool(table_body and table_body.strip())
                    
                    if not has_content:
                        skipped_empty_blocks += 1
                        total_skipped_empty_blocks += 1
                        continue
                    
                    # 生成锚点 ID
                    anchor_id = f"{page_idx}-{segment_idx}"
                    anchor_tag = f"({cls.ANCHOR_SYMBOL}{anchor_id})"
                    
                    # 根据类型格式化
                    if category_type == 'seal' and include_seals:
                        # 印章：特殊格式
                        # 检查是否已经被格式化（避免重复包装）
                        seal_text = text.strip()
                        if seal_text.startswith('【印章：') and seal_text.endswith('】'):
                            # 已经格式化过，直接使用
                            formatted_line = f"{seal_text} {anchor_tag}"
                        else:
                            formatted_line = f"[印章: {seal_text}] {anchor_tag}"
                        score = getattr(block, 'score', None)
                        segment_info = SegmentInfo(
                            anchor_id=anchor_id,
                            page_idx=page_idx,
                            bbox=bbox,
                            text=text.strip(),
                            segment_type="seal",
                            score=score
                        )
                    elif category_type == 'table' and include_tables:
                        # 表格：为每个单元格生成锚点（如果有单元格信息）
                        table_result = cls._format_table_with_anchors(
                            block, page_idx, segment_idx, segment_map
                        )
                        if table_result:
                            formatted_text, anchor_count = table_result
                            all_lines.append(formatted_text)
                            segment_idx += anchor_count  # 增加使用的锚点数量
                            continue  # 表格已经处理完毕
                        else:
                            # 表格处理失败，降级为普通文本
                            formatted_line = f"{text.strip()} {anchor_tag}"
                            segment_info = SegmentInfo(
                                anchor_id=anchor_id,
                                page_idx=page_idx,
                                bbox=bbox,
                                text=text.strip(),
                                segment_type="table"
                            )
                    else:
                        # 普通文本
                        formatted_line = f"{text.strip()} {anchor_tag}"
                        segment_info = SegmentInfo(
                            anchor_id=anchor_id,
                            page_idx=page_idx,
                            bbox=bbox,
                            text=text.strip(),
                            segment_type=category_type
                        )
                    
                    # 保存映射
                    segment_map[anchor_id] = segment_info
                    all_lines.append(formatted_line)
                    segment_idx += 1
                
                # Debug: 页面处理完成后输出统计
                if skipped_empty_blocks > 0 or segment_idx == 0:
                    logger.debug(
                        f"页面 {page_idx} 处理完成 | "
                        f"有效片段: {segment_idx} | "
                        f"跳过空 blocks: {skipped_empty_blocks}"
                    )

                # PDF 文本层补全：按行注入锚点（默认整页 bbox 溯源，144 DPI 与 Paddle 对齐）
                segment_idx = cls._append_text_layer_supplement_anchors(
                    file_data=file_data,
                    page_idx=page_idx,
                    segment_idx=segment_idx,
                    all_lines=all_lines,
                    segment_map=segment_map,
                )
            
            # 更新全局页码偏移
            global_page_offset += len(pages)
        
        # 合并所有行
        tagged_markdown = "\n\n".join(all_lines)
        
        # 如果结果为空，输出诊断 warning
        if not segment_map:
            logger.warning(
                f"Anchor Markdown 转换结果为空 | "
                f"parse_results 数量: {len(parse_results)} | "
                f"总页数: {total_pages} | "
                f"总 layout_blocks: {total_layout_blocks} | "
                f"跳过的空 blocks: {total_skipped_empty_blocks} | "
                f"parse_result 类型: {type(parse_results[0]).__name__ if parse_results else 'N/A'}"
            )
        else:
            logger.info(
                f"Anchor Markdown 转换完成 | "
                f"总片段数: {len(segment_map)} | "
                f"总字符数: {len(tagged_markdown)}"
            )
        
        # Debug: 输出完整的 AnchorMarkdown 内容
        logger.debug(
            f"=== AnchorMarkdown 完整内容 ===\n"
            f"{tagged_markdown}\n"
            f"=== AnchorMarkdown 结束 ==="
        )
        
        # Debug: 输出 segment_map 详情
        if segment_map:
            segment_map_preview = {
                k: v.to_dict() for k, v in list(segment_map.items())[:10]
            }
            logger.debug(
                f"=== segment_map 前 10 条 ===\n"
                f"{json.dumps(segment_map_preview, ensure_ascii=False, indent=2)}\n"
                f"=== segment_map 结束 (共 {len(segment_map)} 条) ==="
            )
        
        return tagged_markdown, segment_map
    
    @classmethod
    def _sort_blocks_by_position(cls, blocks: List[Any]) -> List[Any]:
        """
        按位置排序 blocks（从上到下，从左到右）
        
        Args:
            blocks: layout_block 列表
            
        Returns:
            排序后的 blocks
        """
        def get_position(block):
            bbox = cls._extract_bbox(block)
            if bbox and len(bbox) >= 4:
                # 主要按 y0 排序，次要按 x0 排序
                return (bbox[1], bbox[0])
            return (float('inf'), float('inf'))
        
        return sorted(blocks, key=get_position)
    
    @classmethod
    def _extract_bbox(cls, block: Any) -> List[float]:
        """
        提取 block 的 bbox
        
        Args:
            block: layout_block 对象
            
        Returns:
            bbox 列表 [x0, y0, x1, y1]
        """
        bbox = getattr(block, 'bbox', None)
        
        if bbox is None:
            return [0, 0, 0, 0]
        
        # 如果 bbox 是对象，提取属性
        if hasattr(bbox, 'x0'):
            return [bbox.x0, bbox.y0, bbox.x1, bbox.y1]
        
        # 如果 bbox 是列表/元组
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            return list(bbox[:4])
        
        return [0, 0, 0, 0]
    
    @classmethod
    def _extract_block_text(cls, block: Any) -> str:
        """
        提取 block 的文本内容
        
        优先从 lines/spans 中提取，否则从 text 属性提取
        
        Args:
            block: layout_block 对象
            
        Returns:
            文本内容
        """
        # 尝试从 lines/spans 提取
        lines = getattr(block, 'lines', [])
        if lines:
            text_parts = []
            for line in lines:
                spans = getattr(line, 'spans', [])
                for span in spans:
                    span_text = getattr(span, 'text', '')
                    if span_text:
                        text_parts.append(span_text)
            if text_parts:
                return ' '.join(text_parts)
        
        # 降级：从 text 属性提取
        text = getattr(block, 'text', '')
        return text or ''
    
    @classmethod
    def _format_table_with_anchors(
        cls,
        block: Any,
        page_idx: int,
        base_segment_idx: int,
        segment_map: Dict[str, SegmentInfo]
    ) -> Optional[Tuple[str, int]]:
        """
        格式化表格并添加锚点
        
        策略：
        - 如果有单元格信息（PaddleStructure），为每个单元格生成独立锚点
        - 如果没有单元格信息（VL 模式），整个表格一个锚点
        
        Args:
            block: 表格 block
            page_idx: 页码
            base_segment_idx: 基础片段索引
            segment_map: 片段映射表（会被修改）
            
        Returns:
            Tuple[格式化后的表格文本, 使用的锚点数量]，失败返回 None
        """
        try:
            # 优先获取 table_body (HTML格式，Paddle原生结果)
            table_body = getattr(block, 'table_body', None)
            
            # 如果没有 table_body，降级使用纯文本
            if not table_body:
                table_body = cls._extract_block_text(block)
            
            if not table_body:
                return None
            
            table_bbox = cls._extract_bbox(block)
            
            # 提取表格单元格信息（如果存在，由 PaddleStructureV3 提供）
            block_cells = getattr(block, 'cells', None)
            
            # 有单元格信息：为每个单元格生成独立锚点
            if block_cells and len(block_cells) > 0:
                return cls._format_table_with_cell_anchors(
                    block_cells, table_body, table_bbox, page_idx, base_segment_idx, segment_map
                )
            
            # 无单元格信息：整表一个锚点（VL 模式）；table_body 可能已含 TABLE_SEALS
            anchor_id = f"{page_idx}-{base_segment_idx}"
            anchor_tag = f"({cls.ANCHOR_SYMBOL}{anchor_id})"
            
            # 获取纯文本用于保存到 segment_map
            text = getattr(block, 'text', None) or cls._extract_block_text(block)
            
            # 保存映射（整表级别）
            segment_map[anchor_id] = SegmentInfo(
                anchor_id=anchor_id,
                page_idx=page_idx,
                bbox=table_bbox,
                text=text.strip() if text else table_body.strip(),
                segment_type="table"
            )
            
            # 返回 HTML 表格格式（table_body 已含 TABLE_SEALS 时无需再追加独立印章行）
            return f"{table_body.strip()}\n\n{anchor_tag}", 1
            
        except Exception as e:
            logger.warning(f"格式化表格失败: {e}")
            return None
    
    @classmethod
    def _format_table_with_cell_anchors(
        cls,
        block_cells: List[Any],
        table_body: str,
        table_bbox: List[float],
        page_idx: int,
        base_segment_idx: int,
        segment_map: Dict[str, SegmentInfo]
    ) -> Tuple[str, int]:
        """
        为表格的每个单元格生成独立锚点
        
        输出格式：纯文本表格，每个单元格后跟锚点
        
        Args:
            block_cells: 单元格列表
            table_body: 原始 HTML 内容
            table_bbox: 表格边界框
            page_idx: 页码
            base_segment_idx: 基础片段索引
            segment_map: 片段映射表
            
        Returns:
            Tuple[格式化后的文本, 使用的锚点数量]
        """
        seal_items = cls._parse_table_seal_items(table_body)
        rows_dict, unmatched_seals = cls._inject_seals_into_cell_rows(rows_dict={}, block_cells=block_cells, seals=seal_items)
        
        # 将单元格按行分组（已在 _inject 中构建 rows_dict，若为空则重建）
        if not rows_dict:
            for cell in block_cells:
                if hasattr(cell, 'to_dict'):
                    cell_data = cell.to_dict()
                elif isinstance(cell, dict):
                    cell_data = dict(cell)
                else:
                    cell_data = {
                        "bbox": getattr(cell, 'bbox', []),
                        "text": getattr(cell, 'text', ''),
                        "row": getattr(cell, 'row', 0),
                        "col": getattr(cell, 'col', 0),
                        "rowspan": getattr(cell, 'rowspan', 1),
                        "colspan": getattr(cell, 'colspan', 1),
                    }
                row_idx = cell_data.get('row', 0)
                if row_idx not in rows_dict:
                    rows_dict[row_idx] = []
                rows_dict[row_idx].append(cell_data)
        
        # 按列排序每行的单元格
        for row_idx in rows_dict:
            rows_dict[row_idx].sort(key=lambda c: c.get('col', 0))
        
        # 生成带锚点的 HTML 表格
        html_parts = ['<div style="text-align: center;"><html><body><table border="1">']
        anchor_count = 0
        
        for row_idx in sorted(rows_dict.keys()):
            row_cells = rows_dict[row_idx]
            html_parts.append("<tr>")
            
            for cell_data in row_cells:
                cell_text = cell_data.get('text', '').strip()
                cell_bbox = cell_data.get('bbox', [])
                rowspan = cell_data.get('rowspan', 1)
                colspan = cell_data.get('colspan', 1)
                
                # 生成单元格锚点 ID：page-tableIdx-cellIdx
                anchor_id = f"{page_idx}-{base_segment_idx}-{anchor_count}"
                anchor_tag = f"({cls.ANCHOR_SYMBOL}{anchor_id})"
                
                # 含印章的单元格溯源使用印章 page 坐标，而非整格 bbox
                trace_bbox = cls._resolve_cell_trace_bbox(
                    cell_data, cell_text, cell_bbox, table_bbox
                )
                segment_map[anchor_id] = SegmentInfo(
                    anchor_id=anchor_id,
                    page_idx=page_idx,
                    bbox=trace_bbox,
                    text=cell_text,
                    segment_type="table_cell"
                )
                
                # 构建 td 标签，包含 rowspan/colspan 属性
                attrs = ""
                if rowspan > 1:
                    attrs += f' rowspan="{rowspan}"'
                if colspan > 1:
                    attrs += f' colspan="{colspan}"'
                
                content = f"{cell_text}{anchor_tag}" if cell_text else f"{anchor_tag}"
                html_parts.append(f'<td{attrs}>{content}</td>')
                
                anchor_count += 1
            
            html_parts.append("</tr>")
        
        html_parts.append("</table></body></html></div>")
        
        formatted_text = "".join(html_parts)
        
        extra_lines, extra_count = cls._format_unmatched_table_seals(
            unmatched_seals,
            page_idx,
            base_segment_idx,
            anchor_count,
            segment_map,
            table_bbox,
        )
        if extra_lines:
            formatted_text = f"{formatted_text}\n\n{extra_lines}"
            anchor_count += extra_count
        
        injected_count = len(seal_items) - len(unmatched_seals)
        logger.debug(
            f"表格单元格锚点生成完成 (HTML) | 页面: {page_idx} | "
            f"基础索引: {base_segment_idx} | 单元格数: {anchor_count - extra_count} | "
            f"表格印章: {injected_count} 注入单元格, {extra_count} 独立输出"
        )
        
        return formatted_text, anchor_count

    @staticmethod
    def _parse_html_attr(attrs: str, name: str) -> str:
        match = re.search(rf'{re.escape(name)}="([^"]*)"', attrs)
        return match.group(1) if match else ''

    @classmethod
    def _parse_table_seal_items(cls, table_body: Optional[str]) -> List[Dict[str, Any]]:
        """从 table_body 的 TABLE_SEALS 块解析表格内印章信息"""
        if not table_body:
            return []

        seals: List[Dict[str, Any]] = []
        if 'TABLE_SEALS_START' not in table_body and 'seal-item' not in table_body:
            return seals

        for match in re.finditer(r'<div class="seal-item"([^>]*)>', table_body):
            attrs = match.group(1)
            text = cls._parse_html_attr(attrs, 'data-text').strip()
            if not text:
                continue
            bbox_page_raw = cls._parse_html_attr(attrs, 'data-bbox-page')
            bbox_page: List[float] = []
            if bbox_page_raw:
                try:
                    parsed = json.loads(bbox_page_raw)
                    if isinstance(parsed, list) and len(parsed) >= 4:
                        bbox_page = [float(v) for v in parsed[:4]]
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
            score_raw = cls._parse_html_attr(attrs, 'data-score')
            score = float(score_raw) if score_raw else None
            matched_cell = cls._parse_html_attr(attrs, 'data-matched-cell').strip()
            row_raw = cls._parse_html_attr(attrs, 'data-matched-row')
            col_raw = cls._parse_html_attr(attrs, 'data-matched-col')
            matched_row = int(row_raw) if row_raw not in ('', None) and str(row_raw).isdigit() else None
            matched_col = int(col_raw) if col_raw not in ('', None) and str(col_raw).isdigit() else None
            seals.append({
                'text': text,
                'score': score,
                'bbox_page': bbox_page,
                'matched_cell_text': matched_cell,
                'matched_row': matched_row,
                'matched_col': matched_col,
            })

        if not seals:
            for text in re.findall(r'【印章：([^】]+)】', table_body):
                text = text.strip()
                if text:
                    seals.append({
                        'text': text,
                        'score': None,
                        'bbox_page': [],
                        'matched_cell_text': '',
                        'matched_row': None,
                        'matched_col': None,
                    })
        return seals

    @classmethod
    def _inject_seals_into_cell_rows(
        cls,
        rows_dict: Dict[int, List[Dict[str, Any]]],
        block_cells: List[Any],
        seals: List[Dict[str, Any]],
    ) -> Tuple[Dict[int, List[Dict[str, Any]]], List[Dict[str, Any]]]:
        """将印章文本写入匹配单元格，返回未匹配的印章列表"""
        if not seals:
            return rows_dict, []

        if not rows_dict:
            for cell in block_cells:
                if hasattr(cell, 'to_dict'):
                    cell_data = cell.to_dict()
                elif isinstance(cell, dict):
                    cell_data = dict(cell)
                else:
                    cell_data = {
                        "bbox": getattr(cell, 'bbox', []),
                        "text": getattr(cell, 'text', ''),
                        "row": getattr(cell, 'row', 0),
                        "col": getattr(cell, 'col', 0),
                        "rowspan": getattr(cell, 'rowspan', 1),
                        "colspan": getattr(cell, 'colspan', 1),
                    }
                row_idx = cell_data.get('row', 0)
                rows_dict.setdefault(row_idx, []).append(cell_data)

        unmatched: List[Dict[str, Any]] = []
        for seal in seals:
            text = seal.get('text', '').strip()
            if not text:
                continue
            seal_marker = f'【印章：{text}】'
            target = cls._find_cell_for_seal(rows_dict, seal)
            if target is not None:
                existing = (target.get('text') or '').strip()
                if seal_marker not in existing and text not in existing:
                    target['text'] = (
                        f"{existing}{cls.SEAL_CELL_TEXT_SEPARATOR}{seal_marker}"
                        if existing else seal_marker
                    )
                seal_bbox = seal.get('bbox_page') or []
                if cls._is_valid_bbox(seal_bbox):
                    target.setdefault('seal_bbox_pages', []).append(seal_bbox)
            else:
                unmatched.append(seal)

        return rows_dict, unmatched

    @classmethod
    def _find_cell_for_seal(
        cls,
        rows_dict: Dict[int, List[Dict[str, Any]]],
        seal: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """按行列或单元格文本匹配印章所属单元格"""
        matched_row = seal.get('matched_row')
        matched_col = seal.get('matched_col')
        if matched_row is not None and matched_col is not None:
            for cell in rows_dict.get(matched_row, []):
                if cell.get('col') == matched_col:
                    return cell
                col_start = cell.get('col', 0)
                colspan = cell.get('colspan', 1)
                if col_start <= matched_col < col_start + colspan:
                    return cell

        if matched_row is not None:
            for cell in rows_dict.get(matched_row, []):
                if not (cell.get('text') or '').strip():
                    return cell

        matched_text = (seal.get('matched_cell_text') or '').strip()
        if matched_text and matched_text != '未知':
            best: Optional[Dict[str, Any]] = None
            best_len = 0
            for row_cells in rows_dict.values():
                for cell in row_cells:
                    cell_text = (cell.get('text') or '').strip()
                    if not cell_text:
                        continue
                    if matched_text in cell_text or cell_text in matched_text:
                        if len(cell_text) > best_len:
                            best = cell
                            best_len = len(cell_text)
            if best is not None:
                return best

        return None

    @classmethod
    def _resolve_cell_trace_bbox(
        cls,
        cell_data: Dict[str, Any],
        cell_text: str,
        cell_bbox: List[float],
        table_bbox: List[float],
    ) -> List[float]:
        """单元格溯源 bbox：含印章时优先使用印章 page 坐标"""
        if '【印章：' in cell_text:
            seal_bboxes = cell_data.get('seal_bbox_pages') or []
            valid = [b for b in seal_bboxes if cls._is_valid_bbox(b)]
            if valid:
                return cls.merge_bboxes(valid)
        if cls._is_valid_bbox(cell_bbox):
            return cell_bbox
        return table_bbox

    @classmethod
    def _format_unmatched_table_seals(
        cls,
        seals: List[Dict[str, Any]],
        page_idx: int,
        base_segment_idx: int,
        start_anchor_count: int,
        segment_map: Dict[str, SegmentInfo],
        table_bbox: List[float],
    ) -> Tuple[str, int]:
        """未匹配到单元格的印章，以独立 seal 片段输出"""
        if not seals:
            return '', 0

        lines: List[str] = []
        for idx, seal in enumerate(seals):
            text = (seal.get('text') or '').strip()
            if not text:
                continue
            anchor_id = f"{page_idx}-{base_segment_idx}-{start_anchor_count + idx}"
            anchor_tag = f"({cls.ANCHOR_SYMBOL}{anchor_id})"
            formatted_seal = f"【印章：{text}】"
            lines.append(f"[印章: {text}] {anchor_tag}")
            bbox = seal.get('bbox_page') or table_bbox
            segment_map[anchor_id] = SegmentInfo(
                anchor_id=anchor_id,
                page_idx=page_idx,
                bbox=bbox if cls._is_valid_bbox(bbox) else table_bbox,
                text=formatted_seal,
                segment_type="seal",
                score=seal.get('score'),
            )
        return '\n\n'.join(lines), len(lines)

    @classmethod
    def apply_table_seals_to_cells(cls, cells: List[Any], table_body: str) -> List[Any]:
        """将 table_body 中的 TABLE_SEALS 信息写回 cells 列表（Structure 解析阶段同步）"""
        seal_items = cls._parse_table_seal_items(table_body)
        if not seal_items or not cells:
            return cells

        cell_dicts: List[Dict[str, Any]] = []
        for cell in cells:
            if hasattr(cell, 'to_dict'):
                cell_dicts.append(cell.to_dict())
            elif isinstance(cell, dict):
                cell_dicts.append(dict(cell))
            else:
                cell_dicts.append({
                    "bbox": getattr(cell, 'bbox', []),
                    "text": getattr(cell, 'text', ''),
                    "row": getattr(cell, 'row', 0),
                    "col": getattr(cell, 'col', 0),
                    "rowspan": getattr(cell, 'rowspan', 1),
                    "colspan": getattr(cell, 'colspan', 1),
                })

        rows_dict, _ = cls._inject_seals_into_cell_rows(
            rows_dict={}, block_cells=cell_dicts, seals=seal_items
        )

        updated_by_key = {
            (d.get('row'), d.get('col')): d.get('text', '')
            for row_cells in rows_dict.values()
            for d in row_cells
        }
        for cell in cells:
            key = (getattr(cell, 'row', None), getattr(cell, 'col', None))
            if key in updated_by_key:
                cell.text = updated_by_key[key]
        return cells

    @classmethod
    def _append_text_layer_supplement_anchors(
        cls,
        file_data: Dict[str, Any],
        page_idx: int,
        segment_idx: int,
        all_lines: List[str],
        segment_map: Dict[str, SegmentInfo],
    ) -> int:
        """
        将文本层补全写入 Anchor Markdown。

        文本层补全片段默认使用整页 bbox（见 text_layer_page_paddle_bboxes），
        模型命中补全锚点溯源时高亮整页 PDF；无整页坐标时回退 segment 内 bbox。
        """
        from src.utils.pdf_text_layer_supplement import (
            TextLayerSupplementSegment,
            deserialize_supplement_segments,
            _parse_supplement_block_to_lines,
        )

        page_paddle_bboxes = file_data.get("text_layer_page_paddle_bboxes") or {}
        page_full_bbox = page_paddle_bboxes.get(page_idx)

        raw_segments = file_data.get("text_layer_supplement_segments")
        segments_by_page = deserialize_supplement_segments(raw_segments)
        page_segments: List[TextLayerSupplementSegment] = segments_by_page.get(page_idx, [])

        if page_segments:
            added = 0
            for seg in page_segments:
                if not seg.text.strip():
                    continue
                bbox = page_full_bbox if cls._is_valid_bbox(page_full_bbox) else seg.bbox
                if not cls._is_valid_bbox(bbox):
                    logger.debug(
                        f"文本层补全片段无有效 bbox，跳过锚点 | 页 {page_idx} | {seg.text[:40]}..."
                    )
                    continue
                anchor_id = f"{page_idx}-{segment_idx}"
                anchor_tag = f"({cls.ANCHOR_SYMBOL}{anchor_id})"
                formatted_line = f"{seg.text.strip()} {anchor_tag}"
                segment_map[anchor_id] = SegmentInfo(
                    anchor_id=anchor_id,
                    page_idx=page_idx,
                    bbox=bbox,
                    text=seg.text.strip(),
                    segment_type="text_layer_supplement",
                )
                all_lines.append(formatted_line)
                segment_idx += 1
                added += 1
            if added:
                logger.debug(
                    f"页面 {page_idx} 已注入 {added} 个文本层补全锚点"
                    f"（{'整页' if cls._is_valid_bbox(page_full_bbox) else '字级'} bbox）"
                )
                return segment_idx

        # 兼容旧数据：仅有整页补全块、或 segments 均未命中坐标
        page_supplements = file_data.get("text_layer_page_supplements") or {}
        supplement_text = page_supplements.get(page_idx)
        if supplement_text and supplement_text.strip():
            lines = _parse_supplement_block_to_lines(supplement_text)
            if not lines:
                lines = [supplement_text.strip()]
            fallback_bbox = page_full_bbox if cls._is_valid_bbox(page_full_bbox) else None
            for line in lines:
                anchor_id = f"{page_idx}-{segment_idx}"
                anchor_tag = f"({cls.ANCHOR_SYMBOL}{anchor_id})"
                formatted_line = f"{line} {anchor_tag}"
                if not cls._is_valid_bbox(fallback_bbox):
                    logger.debug(
                        f"文本层补全降级锚点无整页 bbox，跳过 | 页 {page_idx} | {line[:40]}..."
                    )
                    segment_idx += 1
                    continue
                segment_map[anchor_id] = SegmentInfo(
                    anchor_id=anchor_id,
                    page_idx=page_idx,
                    bbox=fallback_bbox,
                    text=line,
                    segment_type="text_layer_supplement",
                )
                all_lines.append(formatted_line)
                segment_idx += 1
            logger.debug(
                f"页面 {page_idx} 文本层补全（整页溯源降级）| 行数: {len(lines)}"
            )
        return segment_idx
    
    @classmethod
    def _is_valid_bbox(cls, bbox: List[float]) -> bool:
        """
        检查 bbox 是否有效
        
        有效 bbox 需要满足：
        - 不为空
        - 长度为 4
        - x1 > x0 且 y1 > y0（有实际面积）
        - 不是全零 [0, 0, 0, 0]
        
        Args:
            bbox: 边界框 [x0, y0, x1, y1]
            
        Returns:
            是否有效
        """
        if not bbox or len(bbox) != 4:
            return False
        
        x0, y0, x1, y1 = bbox
        
        # 检查是否有实际面积
        if x1 <= x0 or y1 <= y0:
            return False
        
        # 检查不是全零（无效占位值）
        if x0 == 0 and y0 == 0 and x1 == 0 and y1 == 0:
            return False
        
        return True
    
    @classmethod
    def lookup_bbox_by_anchor(
        cls,
        anchor_id: str,
        segment_map: Dict[str, SegmentInfo]
    ) -> Optional[Dict[str, Any]]:
        """
        根据锚点 ID 查找 bbox
        
        Args:
            anchor_id: 锚点 ID（如 "0-5"）
            segment_map: 片段映射表
            
        Returns:
            包含 page_idx 和 bbox 的字典，未找到或 bbox 无效返回 None
        """
        segment = segment_map.get(anchor_id)
        if segment:
            # 检查 bbox 有效性
            if not cls._is_valid_bbox(segment.bbox):
                logger.warning(
                    f"锚点 {anchor_id} 的 bbox 无效: {segment.bbox}，无法用于高亮"
                )
                return None
            
            info = {
                "page_idx": segment.page_idx,
                "bbox": segment.bbox,
                "text": segment.text,
                "type": segment.segment_type
            }
            if getattr(segment, "file_index", None) is not None:
                info["file_index"] = segment.file_index
            if getattr(segment, "sheet_name", None):
                info["sheet_name"] = segment.sheet_name
            if getattr(segment, "row", None) is not None:
                info["row"] = segment.row
            if getattr(segment, "col", None) is not None:
                info["col"] = segment.col
            if getattr(segment, "cell_ref", None):
                info["cell_ref"] = segment.cell_ref
            return info
        return None
    
    @classmethod
    def lookup_bboxes_by_anchors(
        cls,
        anchor_ids: List[str],
        segment_map: Dict[str, SegmentInfo]
    ) -> List[Dict[str, Any]]:
        """
        根据多个锚点 ID 查找 bbox 列表
        
        Args:
            anchor_ids: 锚点 ID 列表
            segment_map: 片段映射表
            
        Returns:
            bbox 信息列表
        """
        results = []
        for anchor_id in anchor_ids:
            info = cls.lookup_bbox_by_anchor(anchor_id, segment_map)
            if info:
                results.append(info)
        return results
    
    @classmethod
    def merge_bboxes(cls, bbox_list: List[List[float]]) -> List[float]:
        """
        合并多个 bbox 为一个外接矩形
        
        Args:
            bbox_list: bbox 列表，每个 bbox 为 [x0, y0, x1, y1]
            
        Returns:
            合并后的 bbox [x0, y0, x1, y1]
        """
        if not bbox_list:
            return [0, 0, 0, 0]
        
        if len(bbox_list) == 1:
            return bbox_list[0]
        
        x0 = min(b[0] for b in bbox_list)
        y0 = min(b[1] for b in bbox_list)
        x1 = max(b[2] for b in bbox_list)
        y1 = max(b[3] for b in bbox_list)
        
        return [x0, y0, x1, y1]
    
    @classmethod
    def validate_segment_map(
        cls,
        segment_map: Dict[str, SegmentInfo]
    ) -> Dict[str, Any]:
        """
        验证 segment_map 中所有锚点的有效性
        
        用于调试和质量检查
        
        Args:
            segment_map: 片段映射表
            
        Returns:
            验证报告，包含：
            - total: 总锚点数
            - valid: 有效锚点数（bbox 可用于高亮）
            - invalid: 无效锚点列表
            - by_type: 按类型统计
        """
        total = len(segment_map)
        valid_count = 0
        invalid_anchors = []
        by_type: Dict[str, int] = {}
        
        for anchor_id, segment in segment_map.items():
            # 统计类型
            seg_type = segment.segment_type
            by_type[seg_type] = by_type.get(seg_type, 0) + 1
            
            # 检查 bbox 有效性
            if cls._is_valid_bbox(segment.bbox):
                valid_count += 1
            else:
                invalid_anchors.append({
                    "anchor_id": anchor_id,
                    "type": seg_type,
                    "bbox": segment.bbox,
                    "text_preview": segment.text[:50] if segment.text else ""
                })
        
        return {
            "total": total,
            "valid": valid_count,
            "invalid_count": len(invalid_anchors),
            "invalid": invalid_anchors,
            "by_type": by_type
        }
    
    @classmethod
    def parse_anchor_ids_from_response(cls, anchor_ids_raw: Any) -> List[str]:
        """
        从 LLM 响应中解析锚点 ID 列表
        
        支持多种格式：
        - 列表: ["0-1", "0-2"]
        - 单个字符串: "0-1"
        - 逗号分隔: "0-1, 0-2"
        
        Args:
            anchor_ids_raw: LLM 返回的原始 anchor_ids
            
        Returns:
            解析后的锚点 ID 列表
        """
        if anchor_ids_raw is None:
            return []
        
        if isinstance(anchor_ids_raw, list):
            return [str(aid).strip() for aid in anchor_ids_raw if aid]
        
        if isinstance(anchor_ids_raw, str):
            # 尝试逗号分隔
            if ',' in anchor_ids_raw:
                return [aid.strip() for aid in anchor_ids_raw.split(',') if aid.strip()]
            # 单个 ID
            return [anchor_ids_raw.strip()] if anchor_ids_raw.strip() else []
        
        return []




