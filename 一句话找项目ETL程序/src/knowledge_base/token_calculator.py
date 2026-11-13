"""
Token计算器模块

使用OpenAI官方的tiktoken进行精确的token计算
"""

import re
import json
from typing import Any, Dict, List, Union
from src.core.logger import get_logger

logger = get_logger(__name__)

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logger.warning("tiktoken未安装，将使用简单估算方法。建议运行: pip install tiktoken")


class TokenCalculator:
    """Token计算器 - 使用OpenAI官方tiktoken进行精确计算"""
    
    def __init__(self, encoding_name: str = "cl100k_base"):
        """
        初始化Token计算器
        
        Args:
            encoding_name: tiktoken编码器名称
                - "cl100k_base": GPT-3.5/GPT-4 (推荐用于embedding)
                - "o200k_base": GPT-4o 
                - "r50k_base": GPT-3
        """
        self.encoding_name = encoding_name
        
        if TIKTOKEN_AVAILABLE:
            try:
                self.encoder = tiktoken.get_encoding(encoding_name)
                logger.info(f"使用tiktoken编码器: {encoding_name}")
            except Exception as e:
                logger.error(f"tiktoken初始化失败: {e}，将使用简单估算")
                self.encoder = None
        else:
            self.encoder = None
            
        # 备用估算规则（当tiktoken不可用时）
        if not self.encoder:
            self.chinese_char_factor = 1.2  # 中文字符token系数
            self.english_word_factor = 1.3  # 英文单词token系数
            self.number_factor = 1.0  # 数字token系数
            self.symbol_factor = 1.0  # 符号token系数
        
    def count_tokens(self, text: str) -> int:
        """
        计算文本的token数量
        
        Args:
            text: 输入文本
            
        Returns:
            精确的token数量（使用tiktoken）或估算值
        """
        if not text or not isinstance(text, str):
            return 0
        
        # 优先使用tiktoken进行精确计算
        if self.encoder:
            try:
                tokens = self.encoder.encode(text)
                return len(tokens)
            except Exception as e:
                logger.error(f"tiktoken计算失败: {e}，使用备用估算方法")
        
        # 备用估算方法
        try:
            # 统计中文字符
            chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
            
            # 统计英文单词
            english_words = len(re.findall(r'\b[a-zA-Z]+\b', text))
            
            # 统计数字
            numbers = len(re.findall(r'\d+', text))
            
            # 统计符号（除了中英文字符和数字）
            symbols = len(re.findall(r'[^\u4e00-\u9fff\w\s]', text))
            
            # 计算总token数
            total_tokens = (
                chinese_chars * self.chinese_char_factor +
                english_words * self.english_word_factor +
                numbers * self.number_factor +
                symbols * self.symbol_factor
            )
            
            return int(total_tokens)
            
        except Exception as e:
            logger.error(f"计算token数量失败: {e}")
            # 最简单的fallback：按字符数估算
            return len(text)
    
    def count_row_tokens(self, row_data: Dict[str, Any]) -> int:
        """
        计算数据行的总token数量
        
        Args:
            row_data: 数据行字典
            
        Returns:
            该行数据的总token数量
        """
        total_tokens = 0
        
        for key, value in row_data.items():
            if value is None:
                continue
            
            # 转换为字符串
            if isinstance(value, (list, dict)):
                text = json.dumps(value, ensure_ascii=False)
            else:
                text = str(value)
            
            # 计算字段token数
            field_tokens = self.count_tokens(text)
            total_tokens += field_tokens
            
            # 添加字段名的token数
            key_tokens = self.count_tokens(key)
            total_tokens += key_tokens
        
        return total_tokens
    
    def analyze_row_tokens(self, row_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析数据行的token分布
        
        Args:
            row_data: 数据行字典
            
        Returns:
            token分析结果
        """
        field_tokens = {}
        total_tokens = 0
        
        for key, value in row_data.items():
            if value is None:
                field_tokens[key] = 0
                continue
            
            # 转换为字符串
            if isinstance(value, (list, dict)):
                text = json.dumps(value, ensure_ascii=False)
            else:
                text = str(value)
            
            # 计算字段token数（包含字段名）
            field_token_count = self.count_tokens(text) + self.count_tokens(key)
            field_tokens[key] = field_token_count
            total_tokens += field_token_count
        
        # 按token数量排序
        sorted_fields = sorted(field_tokens.items(), key=lambda x: x[1], reverse=True)
        
        return {
            'total_tokens': total_tokens,
            'field_tokens': field_tokens,
            'sorted_fields': sorted_fields,
            'max_field': sorted_fields[0] if sorted_fields else None,
            'min_field': sorted_fields[-1] if sorted_fields else None
        }
    
    def estimate_split_count(self, text: str, max_tokens: int) -> int:
        """
        估算文本需要分割的片段数量
        
        Args:
            text: 输入文本
            max_tokens: 每个片段的最大token数
            
        Returns:
            需要分割的片段数量
        """
        total_tokens = self.count_tokens(text)
        if total_tokens <= max_tokens:
            return 1
        
        return (total_tokens + max_tokens - 1) // max_tokens
    
    def split_text_by_tokens(self, text: str, max_tokens: int) -> List[str]:
        """
        按token数量分割文本（使用tiktoken精确计算或备用方法）
        
        Args:
            text: 输入文本
            max_tokens: 每个片段的最大token数
            
        Returns:
            分割后的文本片段列表
        """
        if not text:
            return []
        
        total_tokens = self.count_tokens(text)
        if total_tokens <= max_tokens:
            return [text]
        
        # 如果有tiktoken，使用更精确的token级别切分
        if self.encoder:
            return self._split_with_tiktoken(text, max_tokens)
        else:
            return self._split_with_estimation(text, max_tokens)
    
    def _split_with_tiktoken(self, text: str, max_tokens: int) -> List[str]:
        """
        使用tiktoken进行精确的token级别切分
        """
        try:
            # 编码整个文本
            tokens = self.encoder.encode(text)
            
            if len(tokens) <= max_tokens:
                return [text]
            
            segments = []
            start_idx = 0
            
            while start_idx < len(tokens):
                # 取最多max_tokens个token
                end_idx = min(start_idx + max_tokens, len(tokens))
                segment_tokens = tokens[start_idx:end_idx]
                
                # 解码为文本
                segment_text = self.encoder.decode(segment_tokens)
                
                # 尝试在合适的位置切分（避免切断词语）
                if end_idx < len(tokens):  # 不是最后一段
                    segment_text = self._optimize_split_point(segment_text)
                
                if segment_text.strip():
                    segments.append(segment_text.strip())
                
                start_idx = end_idx
            
            return segments
            
        except Exception as e:
            logger.error(f"tiktoken切分失败: {e}，使用备用方法")
            return self._split_with_estimation(text, max_tokens)
    
    def _split_with_estimation(self, text: str, max_tokens: int) -> List[str]:
        """
        使用估算方法进行文本切分（备用方法）
        """
        segments = []
        remaining_text = text
        
        while remaining_text:
            current_tokens = self.count_tokens(remaining_text)
            
            if current_tokens <= max_tokens:
                # 剩余文本符合要求
                segments.append(remaining_text)
                break
            
            # 需要切分，使用二分查找找到合适的切分点
            left, right = 0, len(remaining_text)
            best_end = len(remaining_text) // 2
            
            while left < right:
                mid = (left + right + 1) // 2
                segment = remaining_text[:mid]
                segment_tokens = self.count_tokens(segment)
                
                if segment_tokens <= max_tokens:
                    best_end = mid
                    left = mid
                else:
                    right = mid - 1
            
            # 优化切分点
            best_end = self._find_optimal_cut_position(remaining_text, best_end)
            
            # 确保至少切分一些内容，避免无限循环
            if best_end == 0:
                best_end = max(1, len(remaining_text) // 4)
            
            segment = remaining_text[:best_end].strip()
            if segment:
                segments.append(segment)
            
            remaining_text = remaining_text[best_end:].strip()
        
        return segments
    
    def _optimize_split_point(self, text: str) -> str:
        """
        优化切分点，尝试在合适的位置结束
        """
        # 从后往前找合适的切分点
        for i in range(len(text) - 1, max(0, len(text) - 50), -1):
            if text[i] in '。！？；，\n\t ':
                return text[:i + 1]
        return text
    
    def _find_optimal_cut_position(self, text: str, initial_pos: int) -> int:
        """
        在给定位置附近找到最优的切分位置
        """
        # 尝试在标点符号处切分
        for offset in range(min(100, len(text) - initial_pos)):
            cut_pos = initial_pos + offset
            if cut_pos >= len(text):
                break
            if text[cut_pos] in '。！？；，\n\t ':
                return cut_pos + 1
        
        return initial_pos


