"""
智能数据切分器模块

保持所有字段完整，只对超长字段进行智能截断切分
"""

import copy
from typing import Any, Dict, List, Tuple
from src.knowledge_base.token_calculator import TokenCalculator
from src.core.logger import get_logger

logger = get_logger(__name__)


class DataSplitter:
    """智能数据切分器 - 保持字段完整性的切分策略"""
    
    def __init__(self, max_tokens: int = 2000):
        """
        初始化数据切分器
        
        Args:
            max_tokens: 每行数据的最大token数限制
        """
        self.max_tokens = max_tokens
        self.token_calculator = TokenCalculator()
        
        # 预留token缓冲区，防止计算误差
        self.token_buffer = 50
        
    def _calculate_field_tokens(self, row_data: Dict[str, Any]) -> Dict[str, int]:
        """
        计算每个字段的token数
        
        Args:
            row_data: 数据行字典
            
        Returns:
            {字段名: token数}
        """
        field_tokens = {}
        for field_name, field_value in row_data.items():
            if field_value is not None:
                tokens = self.token_calculator.count_tokens(str(field_value))
                field_tokens[field_name] = tokens
            else:
                field_tokens[field_name] = 0
        return field_tokens
    
    def _find_splittable_fields(self, field_tokens: Dict[str, int], target_reduction: int) -> List[Tuple[str, int]]:
        """
        找出需要切分的字段
        
        Args:
            field_tokens: 字段token统计
            target_reduction: 需要减少的token数
            
        Returns:
            [(字段名, 原始token数)] 按token数降序排列
        """
        # 排除不可切分的字段（太短或非字符串）
        splittable = []
        for field_name, tokens in field_tokens.items():
            if tokens > 100:  # 只有超过100个token的字段才考虑切分
                splittable.append((field_name, tokens))
        
        # 按token数降序排列，优先切分最长的字段
        splittable.sort(key=lambda x: x[1], reverse=True)
        return splittable
    
    def _calculate_split_strategy(self, row_data: Dict[str, Any], field_tokens: Dict[str, int]) -> Dict[str, int]:
        """
        计算切分策略，确定每个字段应该分配多少token
        
        Args:
            row_data: 原始数据行
            field_tokens: 字段token统计
            
        Returns:
            {字段名: 分配的最大token数}
        """
        total_tokens = sum(field_tokens.values())
        target_tokens = self.max_tokens - self.token_buffer
        
        if total_tokens <= target_tokens:
            return field_tokens  # 不需要切分
        
        reduction_needed = total_tokens - target_tokens
        logger.debug(f"需要减少 {reduction_needed} tokens")
        
        # 找出可切分的字段
        splittable_fields = self._find_splittable_fields(field_tokens, reduction_needed)
        
        if not splittable_fields:
            logger.warning("没有找到可切分的字段")
            return field_tokens
        
        # 分配策略：保持短字段不变，对长字段按比例分配剩余token
        allocation = field_tokens.copy()
        
        # 计算需要保持不变的短字段总token数
        short_fields_tokens = sum(tokens for field_name, tokens in field_tokens.items() 
                                if field_name not in [f[0] for f in splittable_fields])
        
        # 剩余可分配给长字段的token数
        available_for_long_fields = target_tokens - short_fields_tokens
        
        if available_for_long_fields <= 0:
            logger.warning("短字段已占用所有可用token")
            # 给每个长字段分配最少的token
            for field_name, _ in splittable_fields:
                allocation[field_name] = 200  # 最少200 tokens
        else:
            # 计算长字段的总token数
            long_fields_total = sum(tokens for _, tokens in splittable_fields)
            
            # 按比例分配给长字段
            for field_name, original_tokens in splittable_fields:
                ratio = original_tokens / long_fields_total
                allocated_tokens = int(available_for_long_fields * ratio)
                # 确保最少分配200个token
                allocation[field_name] = max(allocated_tokens, 200)
        
        logger.debug(f"切分策略: {allocation}")
        return allocation
    
    def _split_text_to_chunks(self, text: str, max_tokens: int) -> List[str]:
        """
        将文本切分为多个块，每块不超过指定token数
        
        Args:
            text: 要切分的文本
            max_tokens: 每块最大token数
            
        Returns:
            文本块列表
        """
        if not isinstance(text, str) or not text.strip():
            return [text]
        
        current_tokens = self.token_calculator.count_tokens(text)
        if current_tokens <= max_tokens:
            return [text]
        
        # 使用TokenCalculator的切分功能
        return self.token_calculator.split_text_by_tokens(text, max_tokens)
    
    def split_row(self, row_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        智能切分单行数据，保持所有字段完整性
        
        Args:
            row_data: 数据行字典
            
        Returns:
            切分后的数据行列表
        """
        try:
            # 计算原始行的token数
            total_tokens = self.token_calculator.count_row_tokens(row_data)
            
            if total_tokens <= self.max_tokens:
                # 不需要切分
                return [row_data]
            
            logger.debug(f"数据行超过token限制 {total_tokens}/{self.max_tokens}，开始智能切分")
            
            # 计算每个字段的token数
            field_tokens = self._calculate_field_tokens(row_data)
            
            # 计算切分策略
            allocation = self._calculate_split_strategy(row_data, field_tokens)
            
            # 找出需要切分的字段
            fields_to_split = {}
            for field_name, allocated_tokens in allocation.items():
                original_tokens = field_tokens[field_name]
                if original_tokens > allocated_tokens:
                    # 需要切分这个字段
                    field_value = str(row_data[field_name]) if row_data[field_name] is not None else ""
                    chunks = self._split_text_to_chunks(field_value, allocated_tokens)
                    fields_to_split[field_name] = chunks
                    logger.debug(f"字段 {field_name} 从 {original_tokens} tokens 切分为 {len(chunks)} 块")
            
            if not fields_to_split:
                logger.warning("没有字段需要切分，返回原始行")
                return [row_data]
            
            # 生成切分后的行
            result_rows = []
            
            # 计算最大切分数（最长字段的分片数）
            max_splits = max(len(chunks) for chunks in fields_to_split.values())
            
            for split_index in range(max_splits):
                new_row = {}
                
                # 复制所有字段
                for field_name, field_value in row_data.items():
                    if field_name in fields_to_split:
                        # 使用对应的切分块，如果当前分片超出该字段的块数，使用最后一块
                        chunks = fields_to_split[field_name]
                        chunk_index = min(split_index, len(chunks) - 1)
                        new_row[field_name] = chunks[chunk_index]
                    else:
                        # 保持原值
                        new_row[field_name] = field_value
                
                # 添加切分元信息（可选）
                if max_splits > 1:
                    new_row['_split_index'] = split_index + 1
                    new_row['_split_total'] = max_splits
                    new_row['_split_fields'] = list(fields_to_split.keys())
                
                result_rows.append(new_row)
            
            logger.info(f"智能切分完成：原1行 -> {len(result_rows)}行，切分字段: {list(fields_to_split.keys())}")
            
            # 验证结果
            valid_rows = []
            for i, row in enumerate(result_rows):
                row_tokens = self.token_calculator.count_row_tokens(row)
                if row_tokens <= self.max_tokens:
                    valid_rows.append(row)
                else:
                    logger.warning(f"第{i+1}行仍超过限制: {row_tokens} tokens")
                    # 进一步切分这一行
                    further_split = self._further_split_row(row)
                    valid_rows.extend(further_split)
            
            if not valid_rows:
                logger.error("所有切分行都超过限制，返回原始行")
                return [row_data]
            
            return valid_rows
            
        except Exception as e:
            logger.error(f"数据行切分失败: {e}")
            return [row_data]
    
    def _further_split_row(self, row_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        进一步切分仍然超长的行
        
        Args:
            row_data: 数据行字典
            
        Returns:
            进一步切分后的数据行列表
        """
        # 简单的进一步切分：找到最长的字段，强制切分为更小的块
        field_tokens = self._calculate_field_tokens(row_data)
        
        # 找出最长的字段
        longest_field = max(field_tokens.items(), key=lambda x: x[1])
        field_name, tokens = longest_field
        
        if tokens <= 200:  # 如果最长字段已经很短，就不再切分
            return [row_data]
        
        # 强制切分最长字段
        field_value = str(row_data[field_name]) if row_data[field_name] is not None else ""
        chunks = self._split_text_to_chunks(field_value, 200)  # 强制切分为200 token的小块
        
        result_rows = []
        for i, chunk in enumerate(chunks):
            new_row = row_data.copy()
            new_row[field_name] = chunk
            new_row['_further_split'] = True
            new_row['_further_split_index'] = i + 1
            new_row['_further_split_total'] = len(chunks)
            result_rows.append(new_row)
        
        logger.info(f"进一步切分字段 {field_name}：{len(chunks)} 块")
        return result_rows
    
    def split_rows(self, rows_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        批量切分数据行
        
        Args:
            rows_data: 数据行列表
            
        Returns:
            切分后的数据行列表
        """
        result_rows = []
        split_count = 0
        original_count = len(rows_data)
        
        for i, row in enumerate(rows_data):
            if i % 100 == 0:
                logger.info(f"处理数据行进度: {i}/{original_count}")
            
            split_rows = self.split_row(row)
            result_rows.extend(split_rows)
            
            if len(split_rows) > 1:
                split_count += 1
        
        logger.info(f"批量切分完成: 原{original_count}行 -> {len(result_rows)}行，{split_count}行被切分")
        return result_rows