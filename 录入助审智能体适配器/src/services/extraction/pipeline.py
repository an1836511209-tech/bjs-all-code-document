"""
流水线提取相关的数据结构和工具类

用于支持事件驱动的文件解析和字段提取流水线模式：
- FileTypeParseContext: 文件类型解析上下文，包含解析完成事件
- FieldExtractionTask: 字段提取任务，记录依赖关系
- PipelineProgressTracker: 流水线进度追踪器
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Set, Optional, List, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.schemas.rule_config import ExtractionRule


@dataclass
class FileTypeParseContext:
    """
    文件类型解析上下文
    
    每个 file_type 对应一个上下文，用于：
    1. 存储解析完成信号（asyncio.Event）
    2. 存储解析结果或错误信息
    3. 供提取任务等待和获取结果
    """
    file_type: str
    parse_event: asyncio.Event = field(default_factory=asyncio.Event)
    parse_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    def mark_completed(self, result: Dict[str, Any]):
        """
        标记解析完成
        
        Args:
            result: 解析结果数据
        """
        self.parse_result = result
        self.parse_event.set()
    
    def mark_failed(self, error: str):
        """
        标记解析失败
        
        Args:
            error: 错误信息
        """
        self.error = error
        self.parse_event.set()
    
    async def wait(self, timeout: Optional[float] = None) -> bool:
        """
        等待解析完成
        
        Args:
            timeout: 超时时间（秒），None 表示无限等待
            
        Returns:
            bool: 是否成功（False 表示超时或解析失败）
        """
        try:
            await asyncio.wait_for(self.parse_event.wait(), timeout)
            return self.error is None
        except asyncio.TimeoutError:
            return False
    
    @property
    def is_completed(self) -> bool:
        """是否已完成（成功或失败）"""
        return self.parse_event.is_set()
    
    @property
    def is_success(self) -> bool:
        """是否成功完成"""
        return self.is_completed and self.error is None


@dataclass
class FieldExtractionTask:
    """
    字段提取任务
    
    记录一个字段的提取任务信息，包括：
    - 提取规则
    - 依赖的文件类型集合
    - 是否为级联字段
    """
    rule: Any  # ExtractionRule，使用 Any 避免循环导入
    dependencies: Set[str]  # 依赖的 file_type 集合
    is_cascade: bool = False
    cascade_config: Optional[Any] = None  # 级联配置


class PipelineProgressTracker:
    """
    流水线进度追踪器
    
    跟踪流水线模式下的进度：
    - 解析进度：已解析的 file_type 数 / 总 file_type 数
    - 提取进度：已完成的字段数 / 总字段数
    - 高亮进度：已生成的高亮数 / 需要高亮的总数
    
    总进度 = 解析进度 * 0.3 + 提取进度 * 0.5 + 高亮进度 * 0.2
    """
    
    def __init__(self, total_file_types: int, total_fields: int):
        """
        初始化进度追踪器
        
        Args:
            total_file_types: 总文件类型数
            total_fields: 总字段数
        """
        self.total_file_types = total_file_types
        self.total_fields = total_fields
        self.parsed_count = 0
        self.extracted_count = 0
        self.highlight_count = 0
        self.total_highlights = 0
        self._lock = asyncio.Lock()
    
    async def increment_parsed(self):
        """增加已解析的文件类型计数"""
        async with self._lock:
            self.parsed_count += 1
    
    async def increment_extracted(self, count: int = 1):
        """
        增加已提取的字段计数
        
        Args:
            count: 增加的数量
        """
        async with self._lock:
            self.extracted_count += count
    
    async def set_total_highlights(self, total: int):
        """
        设置需要高亮的总数
        
        Args:
            total: 总数
        """
        async with self._lock:
            self.total_highlights = total
    
    async def increment_highlights(self, count: int = 1):
        """
        增加已生成的高亮计数
        
        Args:
            count: 增加的数量
        """
        async with self._lock:
            self.highlight_count += count
    
    def get_progress(self) -> float:
        """
        计算总进度（0.0 ~ 1.0）
        
        进度组成：
        - 解析阶段占 30%
        - 提取阶段占 50%
        - 高亮阶段占 20%
        
        Returns:
            float: 当前进度（0.0 ~ 1.0）
        """
        # 解析进度
        parse_progress = (
            self.parsed_count / self.total_file_types 
            if self.total_file_types > 0 else 1.0
        )
        
        # 提取进度
        extract_progress = (
            self.extracted_count / self.total_fields 
            if self.total_fields > 0 else 0.0
        )
        
        # 高亮进度（如果还没设置总数，假设为完成）
        highlight_progress = (
            self.highlight_count / self.total_highlights 
            if self.total_highlights > 0 else 1.0
        )
        
        # 加权计算总进度
        total_progress = (
            parse_progress * 0.3 + 
            extract_progress * 0.5 + 
            highlight_progress * 0.2
        )
        
        return min(total_progress, 1.0)
    
    def get_stage_info(self) -> Dict[str, Any]:
        """
        获取各阶段详细进度信息
        
        Returns:
            Dict: 包含各阶段进度的字典
        """
        return {
            "parse": {
                "completed": self.parsed_count,
                "total": self.total_file_types,
                "progress": self.parsed_count / self.total_file_types if self.total_file_types > 0 else 1.0
            },
            "extract": {
                "completed": self.extracted_count,
                "total": self.total_fields,
                "progress": self.extracted_count / self.total_fields if self.total_fields > 0 else 0.0
            },
            "highlight": {
                "completed": self.highlight_count,
                "total": self.total_highlights,
                "progress": self.highlight_count / self.total_highlights if self.total_highlights > 0 else 1.0
            },
            "overall": self.get_progress()
        }


