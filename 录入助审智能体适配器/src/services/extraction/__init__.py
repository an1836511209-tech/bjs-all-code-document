"""
字段提取服务模块

提供字段提取功能，包括：
1. 文件解析（使用MinerU）
2. 字段提取（使用LLM Agent）
3. 字段溯源（文本匹配或LLM Agent）
4. PDF高亮生成
"""

from src.services.extraction.service import ExtractionService

__all__ = ["ExtractionService"]

