"""
MinerU文档解析服务模块

提供MinerU文档解析的完整封装，严格按照官方文档实现
参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/
"""

# 导入客户端
from src.services.mineru.client import (
    MinerUClient,
    MinerUError,
    parse_file,
    parse_pdf_page
)

# 导入数据模型
from src.services.mineru.models import (
    # 坐标模型
    BBox,
    parse_bbox_from_any,
    
    # 内容模型
    TextContent,
    ImageContent,
    TableContent,
    FormulaContent,
    CodeContent,
    ListContent,
    DiscardedContent,
    
    # 页面和结果模型
    ParsedPage,
    ParseResult,
    
    # 枚举类型
    CategoryType,
    BlockType,
    ContentListType,
    ContentSubType,
)

# 导入解析器
from src.services.mineru.parser import MinerUParser


__all__ = [
    # 客户端
    'MinerUClient',
    'MinerUError',
    'parse_file',
    'parse_pdf_page',
    
    # 坐标模型
    'BBox',
    'parse_bbox_from_any',
    
    # 内容模型
    'TextContent',
    'ImageContent',
    'TableContent',
    'FormulaContent',
    'CodeContent',
    'ListContent',
    'DiscardedContent',
    
    # 页面和结果
    'ParsedPage',
    'ParseResult',
    
    # 枚举
    'CategoryType',
    'BlockType',
    'ContentListType',
    'ContentSubType',
    
    # 解析器
    'MinerUParser',
]
