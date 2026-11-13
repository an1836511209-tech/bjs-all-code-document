"""
Paddle 文档解析服务模块

提供 PaddleOCR-VL 和印章识别的完整封装
兼容 MinerU 接口，支持无缝切换
"""

# 导入客户端
from src.services.paddle.client import (
    PaddleClient,
    PaddleError,
    parse_file
)

# 导入数据模型
from src.services.paddle.models import (
    # 解析结果模型
    PaddleParseResult,
    PaddlePage,
    PaddleContent,
    PaddleLayoutBlock,
    PaddleLine,
    PaddleSpan,
    
    # API 响应模型
    PaddleOCRVLResponse,
    PaddleSealRecognitionResponse,
    
    # 辅助模型
    LayoutBlockType,
    MarkdownResult,
    SealDetection,
    
    # 辅助函数
    create_bbox_from_list,
)


__all__ = [
    # 客户端
    'PaddleClient',
    'PaddleError',
    'parse_file',
    
    # 解析结果模型
    'PaddleParseResult',
    'PaddlePage',
    'PaddleContent',
    'PaddleLayoutBlock',
    'PaddleLine',
    'PaddleSpan',
    
    # API 响应模型
    'PaddleOCRVLResponse',
    'PaddleSealRecognitionResponse',
    
    # 辅助模型
    'LayoutBlockType',
    'MarkdownResult',
    'SealDetection',
    
    # 辅助函数
    'create_bbox_from_list',
]









