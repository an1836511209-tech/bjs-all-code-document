"""
文本匹配工具

提供精确匹配和模糊匹配功能，用于在middle.json中查找提取结果的位置
"""

import json
from typing import Dict, Any, List, Optional, Tuple
from difflib import SequenceMatcher
from collections import Counter
from loguru import logger

from src.services.llm.models import TracingResult, Region


class TextMatcher:
    """文本匹配器"""
    
    def __init__(self, fuzzy_threshold: float = 0.8):
        """
        初始化文本匹配器
        
        Args:
            fuzzy_threshold: 模糊匹配阈值（0-1），默认0.8
        """
        self.fuzzy_threshold = fuzzy_threshold
    
    # 极短文本阈值：低于此长度的文本跳过字符串匹配，直接交给 LLM 溯源
    MIN_TEXT_LENGTH_FOR_MATCHING = 3
    
    def find_in_middle_json(
        self,
        middle_json_content: str,
        search_text: str,
        field_name: str
    ) -> Optional[TracingResult]:
        """
        在middle.json中查找文本位置（V2 - 支持跨页/跨块）
        
        匹配策略：
        0. Level 0: 极短文本跳过 - 长度 < MIN_TEXT_LENGTH_FOR_MATCHING 的直接返回 None，交给 LLM 溯源
        1. Level 1: 全文拼接匹配（anchor_stitch）- 解决跨块/跨页问题
        2. Level 2: 精确匹配（exact）- 单块内完全匹配
        3. Level 3: 模糊匹配（fuzzy）- 单块内相似度匹配
        
        Args:
            middle_json_content: middle.json的内容（字符串）
            search_text: 要查找的文本
            field_name: 字段名称（用于日志）
            
        Returns:
            Optional[TracingResult]: 找到返回溯源结果，否则返回None
        """
        try:
            # Level 0: 极短文本跳过字符串匹配
            # 像 "5"、"是"、"否" 这类极短的值在文档中可能多处出现，
            # 字符串匹配容易匹配到错误位置，应交给 LLM 根据上下文溯源
            search_text_stripped = search_text.strip()
            if len(search_text_stripped) < self.MIN_TEXT_LENGTH_FOR_MATCHING:
                logger.info(
                    f"字段 '{field_name}' 的值 '{search_text_stripped}' 长度过短 "
                    f"(< {self.MIN_TEXT_LENGTH_FOR_MATCHING})，跳过字符串匹配，交给 LLM 溯源"
                )
                return None
            
            # 解析middle.json
            middle_data = json.loads(middle_json_content)
            
            # Level 1: 全文拼接匹配（仅对长文本启用，避免短词误匹配）
            if len(search_text) > 5:
                anchor_result = self._global_anchor_match(middle_data, search_text)
                if anchor_result:
                    logger.info(f"字段 '{field_name}' 全文拼接匹配成功")
                    return anchor_result
            
            # Level 2: 精确匹配
            exact_result = self._exact_match(middle_data, search_text)
            if exact_result:
                logger.info(f"字段 '{field_name}' 精确匹配成功")
                return exact_result
            
            # Level 3: 模糊匹配
            fuzzy_result = self._fuzzy_match(middle_data, search_text)
            if fuzzy_result:
                logger.info(f"字段 '{field_name}' 模糊匹配成功")
                return fuzzy_result
            
            logger.warning(f"字段 '{field_name}' 在middle.json中未找到匹配")
            return None
            
        except json.JSONDecodeError as e:
            logger.error(f"解析middle.json失败: {e}")
            return None
        except Exception as e:
            logger.error(f"文本匹配异常: {e}", exc_info=True)
            return None
    
    def _exact_match(
        self,
        middle_data: List[Dict[str, Any]],
        search_text: str
    ) -> Optional[TracingResult]:
        """
        精确匹配
        
        在middle.json数据中查找完全匹配的文本
        
        优化策略：
        1. 优先查找完全匹配（text == search_text）
        2. 如果没有完全匹配，再查找包含关系，但要求匹配度高
        3. 对文本进行标准化（去除多余空格、换行符）提高匹配成功率
        4. 返回最佳匹配结果
        
        Args:
            middle_data: middle.json解析后的数据
            search_text: 要查找的文本
            
        Returns:
            Optional[TracingResult]: 找到返回溯源结果，否则返回None
        """
        search_text = search_text.strip()
        # 标准化搜索文本：去除所有空格和换行符，用于更宽松的匹配
        search_text_normalized = search_text.replace(" ", "").replace("\n", "").replace("\t", "")
        
        # 如果搜索文本过短（<= 3个字符），提高匹配严格度
        is_short_text = len(search_text) <= 3
        
        best_match = None
        best_match_score = 0.0
        
        for page in middle_data:
            page_idx = page.get("page_idx", 0)
            layout_dets = page.get("layout_dets", [])
            
            for layout in layout_dets:
                # 获取文本内容
                text_content = self._extract_text_from_layout(layout)
                text_content_clean = text_content.strip()
                # 标准化文本内容：去除所有空格和换行符
                text_content_normalized = text_content_clean.replace(" ", "").replace("\n", "").replace("\t", "")
                
                # 1. 完全匹配（最高优先级）- 使用标准化文本
                if text_content_normalized == search_text_normalized:
                    bbox = layout.get("bbox", [])
                    return TracingResult(
                        matched_text=text_content,
                        page_idx=page_idx,
                        page_number=page_idx + 1,  # 页面号从1开始
                        bbox=bbox,
                        match_type="exact",
                        raw_response=None,
                        success=True,
                        error=None
                    )
                
                # 2. 包含匹配（但需要评分）- 使用标准化文本
                if search_text_normalized in text_content_normalized:
                    # 计算匹配分数：搜索文本占比越高，分数越高
                    match_score = len(search_text_normalized) / len(text_content_normalized) if text_content_normalized else 0
                    
                    # 短文本要求更严格的匹配
                    if is_short_text:
                        # 短文本要求：
                        # - 搜索文本长度 >= 文本内容长度的 50%，或
                        # - 文本内容长度不超过搜索文本的 2 倍
                        if match_score < 0.5 or len(text_content_normalized) > len(search_text_normalized) * 2:
                            continue
                    else:
                        # 长文本要求：搜索文本至少占 30%
                        if match_score < 0.3:
                            continue
                    
                    # 记录最佳匹配
                    if match_score > best_match_score:
                        best_match_score = match_score
                        bbox = layout.get("bbox", [])
                        best_match = TracingResult(
                            matched_text=text_content,
                            page_idx=page_idx,
                            page_number=page_idx + 1,  # 页面号从1开始
                            bbox=bbox,
                            match_type="exact",
                            raw_response=None,
                            success=True,
                            error=None
                        )
        
        # 返回最佳匹配（如果有）
        if best_match and best_match_score >= 0.5:  # 至少 50% 匹配度
            return best_match
        
        return None
    
    def _fuzzy_match(
        self,
        middle_data: List[Dict[str, Any]],
        search_text: str
    ) -> Optional[TracingResult]:
        """
        模糊匹配
        
        使用相似度算法在middle.json数据中查找最相似的文本
        
        Args:
            middle_data: middle.json解析后的数据
            search_text: 要查找的文本
            
        Returns:
            Optional[TracingResult]: 找到唯一匹配返回溯源结果，否则返回None
        """
        search_text = search_text.strip()
        matches = []  # 存储所有匹配结果 (similarity, page_idx, bbox, text)
        
        for page in middle_data:
            page_idx = page.get("page_idx", 0)
            layout_dets = page.get("layout_dets", [])
            
            for layout in layout_dets:
                # 获取文本内容
                text_content = self._extract_text_from_layout(layout)
                
                # 计算相似度
                similarity = self._calculate_similarity(search_text, text_content)
                
                # 如果相似度超过阈值，加入候选列表
                if similarity >= self.fuzzy_threshold:
                    bbox = layout.get("bbox", [])
                    matches.append((similarity, page_idx, bbox, text_content))
        
        # 如果没有匹配
        if not matches:
            return None
        
        # 如果有多个匹配，检查是否有唯一的最高相似度
        matches.sort(reverse=True, key=lambda x: x[0])
        
        # 如果最高相似度的匹配只有一个，或者第一个明显高于第二个
        if len(matches) == 1 or (matches[0][0] - matches[1][0]) > 0.1:
            similarity, page_idx, bbox, matched_text = matches[0]
            
            return TracingResult(
                matched_text=matched_text,
                page_idx=page_idx,
                page_number=page_idx + 1,  # 页面号从1开始
                bbox=bbox,
                match_type="fuzzy",
                raw_response=None,
                success=True,
                error=None
            )
        
        # 如果有多个相似度接近的匹配，返回None表示无法确定
        logger.warning(f"模糊匹配找到多个候选结果，无法确定唯一匹配: {len(matches)} 个匹配")
        return None
    
    def _extract_text_from_layout(self, layout: Dict[str, Any]) -> str:
        """
        从layout中提取文本内容
        
        Args:
            layout: layout对象
            
        Returns:
            str: 提取的文本
        """
        texts = []
        
        # 递归提取文本
        def extract_recursive(obj):
            if isinstance(obj, dict):
                # 如果有text字段，直接提取
                if "text" in obj:
                    text = obj["text"]
                    if isinstance(text, str) and text.strip():
                        texts.append(text.strip())
                
                # 递归处理所有值
                for value in obj.values():
                    extract_recursive(value)
                    
            elif isinstance(obj, list):
                for item in obj:
                    extract_recursive(item)
        
        extract_recursive(layout)
        return " ".join(texts)
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        计算两个文本的相似度
        
        使用SequenceMatcher算法
        
        Args:
            text1: 文本1
            text2: 文本2
            
        Returns:
            float: 相似度 (0-1)
        """
        # 去除空格后比较
        text1_clean = text1.replace(" ", "").replace("\n", "")
        text2_clean = text2.replace(" ", "").replace("\n", "")
        
        # 如果text1是text2的子串，或text2是text1的子串
        if text1_clean in text2_clean or text2_clean in text1_clean:
            # 返回较短字符串在较长字符串中的占比
            return min(len(text1_clean), len(text2_clean)) / max(len(text1_clean), len(text2_clean))
        
        # 使用SequenceMatcher计算相似度
        return SequenceMatcher(None, text1_clean, text2_clean).ratio()
    
    def _global_anchor_match(
        self,
        middle_data: List[Dict[str, Any]],
        search_text: str
    ) -> Optional[TracingResult]:
        """
        全文拼接匹配算法（Global Stitching Match）
        
        解决跨块、跨行、跨页的文本匹配问题。
        
        逻辑：
        1. 将所有页面的文本拼接成一个虚拟字符串。
        2. 建立字符索引映射：index -> (page_idx, bbox)。
        3. 在长字符串中查找 search_text。
        4. 反查映射表，计算覆盖的所有 bbox 并按页分组合并。
        
        Args:
            middle_data: middle.json解析后的数据
            search_text: 要查找的文本
            
        Returns:
            Optional[TracingResult]: 找到返回包含多区域的溯源结果，否则返回None
        """
        try:
            # 1. 预处理搜索文本
            clean_search = self._normalize_text(search_text)
            if not clean_search:
                return None

            # 2. 构建全文索引
            full_text_buffer = []
            char_map = []  # 存储每个字符对应的元数据 {'page_idx': int, 'bbox': list}
            
            for page in middle_data:
                page_idx = page.get("page_idx", 0)
                layout_dets = page.get("layout_dets", [])
                
                for layout in layout_dets:
                    # 优先从 lines -> spans 提取文本（保证顺序准确）
                    raw_text = ""
                    if "lines" in layout:
                        for line in layout["lines"]:
                            for span in line.get("spans", []):
                                span_text = span.get("content", "") or span.get("text", "")
                                if span_text:
                                    raw_text += span_text
                    
                    # 如果从 spans 提取失败，使用顶层 text
                    if not raw_text:
                        raw_text = layout.get("text", "")

                    if not raw_text:
                        continue

                    # 归一化该块文本
                    clean_block = self._normalize_text(raw_text)
                    if not clean_block:
                        continue
                        
                    full_text_buffer.append(clean_block)
                    
                    # 记录每个字符的归属（简化：将整个块的 bbox 赋给块内所有字符）
                    bbox = layout.get("bbox", [0, 0, 0, 0])
                    meta = {"page_idx": page_idx, "bbox": bbox}
                    char_map.extend([meta] * len(clean_block))

            full_text = "".join(full_text_buffer)
            
            if not full_text or not char_map:
                return None
            
            # 3. 执行查找
            start_idx = full_text.find(clean_search)
            
            # 容错策略：如果全匹配失败且文本较长，尝试匹配前70%
            if start_idx == -1 and len(clean_search) > 20:
                half_len = int(len(clean_search) * 0.7)
                start_idx = full_text.find(clean_search[:half_len])
                if start_idx != -1:
                    clean_search = clean_search[:half_len]
            
            if start_idx == -1:
                return None
                
            # 4. 坐标回溯与合并
            end_idx = start_idx + len(clean_search)
            
            # 获取覆盖范围内的所有元数据
            if end_idx > len(char_map):
                end_idx = len(char_map)
            
            matched_meta = char_map[start_idx:end_idx]
            if not matched_meta:
                return None
            
            # 按页码分组 bbox
            page_bboxes = {}  # {page_idx: [bbox1, bbox2, ...]}
            for meta in matched_meta:
                page_idx = meta["page_idx"]
                bbox = meta["bbox"]
                if page_idx not in page_bboxes:
                    page_bboxes[page_idx] = []
                # 避免重复添加相同的 bbox
                if bbox not in page_bboxes[page_idx]:
                    page_bboxes[page_idx].append(bbox)
            
            # 5. 构建 Region 列表（合并同页的 bbox）
            regions = []
            for page_idx in sorted(page_bboxes.keys()):
                bboxes = page_bboxes[page_idx]
                if not bboxes:
                    continue
                
                # 合并该页所有 bbox（Union）
                x0 = min(b[0] for b in bboxes)
                y0 = min(b[1] for b in bboxes)
                x1 = max(b[2] for b in bboxes)
                y1 = max(b[3] for b in bboxes)
                
                regions.append(Region(
                    page_idx=page_idx,
                    page_number=page_idx + 1,
                    bbox=[x0, y0, x1, y1],
                    text_segment=None  # 不填充，节省内存
                ))
            
            if not regions:
                return None
            
            # 6. 构建 TracingResult（兼容旧版字段）
            # 如果只有一个区域，同时填充旧字段
            if len(regions) == 1:
                single_region = regions[0]
                return TracingResult(
                    matched_text=search_text,
                    regions=regions,
                    page_idx=single_region.page_idx,
                    page_number=single_region.page_number,
                    bbox=single_region.bbox,
                    match_type="anchor_stitch",
                    success=True,
                    error=None
                )
            else:
                # 多区域情况，旧字段设为第一个区域
                first_region = regions[0]
                return TracingResult(
                    matched_text=search_text,
                    regions=regions,
                    page_idx=first_region.page_idx,
                    page_number=first_region.page_number,
                    bbox=first_region.bbox,
                    match_type="anchor_stitch",
                    success=True,
                    error=None
                )
            
        except Exception as e:
            logger.error(f"全文拼接匹配异常: {e}", exc_info=True)
            return None
    
    def _normalize_text(self, text: str) -> str:
        """
        极简归一化：去空格、去换行、转小写
        
        Args:
            text: 原始文本
            
        Returns:
            str: 归一化后的文本
        """
        if not text:
            return ""
        return text.replace(" ", "").replace("\n", "").replace("\t", "").replace("\r", "").lower()

