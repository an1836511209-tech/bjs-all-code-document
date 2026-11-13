"""
MinerU 文档解析配置文件

MinerU是一个高质量的文档解析工具，支持从PDF、Word、图片等格式中提取文字信息及坐标。
文档参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/
"""

from config.env_config import get_current_env

# --- MinerU API配置 ---
MINERU_API_CONFIG = {
    # 开发环境使用外部API
    'dev': {
        'base_url': 'http://35.241.77.81:8001',
        'timeout': 300,  # 超时时间（秒），文档解析可能较慢
        'max_retries': 3,  # 最大重试次数
        'retry_delay': 2,  # 重试延迟（秒）
    },
    
    # 生产环境配置（待部署）
    'prod': {
        'base_url': 'http://35.241.77.81:8001',
        'timeout': 300,
        'max_retries': 3,
        'retry_delay': 2,
    }
}

# 当前环境（从全局环境配置获取）
# 注意：不再使用 MINERU_ENV 环境变量，统一使用 ENV 环境变量
CURRENT_ENV = get_current_env()

# --- MinerU解析参数配置 ---
# 参考 MinerU API 文档的标准参数
MINERU_PARSE_OPTIONS = {
    # 后端选择
    'backend': 'pipeline',  # pipeline| vlm-vllm-async-engine| transformers| vlm-transformers | vlm-vllm-engine | vlm-vllm-async-engine | vlm-http-client
    
    # 解析方法
    'parse_method': 'ocr',  # auto | txt | ocr
    
    # 功能开关
    'formula_enable': True,  # 是否启用公式解析
    'table_enable': True,    # 是否启用表格解析
    
    # 返回格式控制（关键配置）
    'return_md': True,              # 返回 Markdown 内容
    'return_middle_json': True,     # 返回 middle.json（用于溯源和坐标匹配）
    'return_content_list': True,    # 返回 content_list.json（用于 LLM 提取）
    'return_model_output': True,    # 返回原始模型输出 model.json（VLM 必需）
    'return_images': False,         # 返回提取的图片
    
    # 页面范围
    'start_page_id': 0,       # 开始页码（从 0 开始）
    'end_page_id': 99999,     # 结束页码
    
    # 语言设置
    'languages': ['ch', 'en'],  # 中文、英文
}

# --- 文件类型支持配置 ---
MINERU_SUPPORTED_FORMATS = {
    # 文档格式
    'documents': ['.pdf', '.doc', '.docx'],
    
    # 图片格式
    'images': ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'],
    
    # 最大文件大小（字节）
    'max_file_size': {
        'pdf': 100 * 1024 * 1024,      # 50MB
        'image': 100 * 1024 * 1024,    # 20MB
        'document': 100 * 1024 * 1024, # 30MB
    }
}

# --- 输出结构配置 ---
# MinerU输出的JSON结构说明
MINERU_OUTPUT_STRUCTURE = {
    'description': 'MinerU解析结果的标准结构',
    
    # 页面级别的信息
    'pages': {
        'page_num': 'int - 页码（从0开始）',
        'width': 'float - 页面宽度（点）',
        'height': 'float - 页面高度（点）',
        'blocks': 'list - 页面中的内容块列表'
    },
    
    # 内容块结构
    'block': {
        'type': 'str - 内容类型（text/image/table/formula）',
        'bbox': 'dict - 边界框坐标 {x0, y0, x1, y1} 或 {x, y, width, height}',
        'text': 'str - 文本内容（如果是文本块）',
        'content': 'str/dict - 具体内容，根据type不同而不同',
        'confidence': 'float - 置信度（0-1）',
        'metadata': 'dict - 其他元数据'
    },
    
    # 坐标系统说明
    'coordinate_system': {
        'origin': '左上角(0, 0)',
        'x_axis': '向右为正',
        'y_axis': '向下为正',
        'unit': '点（1/72英寸） - Pipeline后端',
        'unit_vlm': '百分比（0-1） - VLM后端的坐标为相对于原始页面尺寸的百分比'
    }
}

# --- 坐标格式配置 ---
MINERU_BBOX_FORMATS = {
    # MinerU可能返回的坐标格式
    'formats': [
        'x0_y0_x1_y1',  # {x0, y0, x1, y1} - 左上角和右下角
        'x_y_w_h',      # {x, y, width, height} - 左上角和宽高
        'ltrb',         # {left, top, right, bottom} - 四边坐标
    ],
    
    # 默认使用的格式
    'default_format': 'x_y_w_h',
    
    # 坐标容差（用于坐标匹配时的误差容忍，单位：点）
    'tolerance': 2.0
}

# --- 提取字段配置 ---
MINERU_EXTRACTION_CONFIG = {
    # 字段提取时的上下文窗口大小（字符数）
    'context_window': 100,
    
    # 字段匹配的最低置信度
    'min_confidence': 0.6,
    
    # 是否合并相邻的文本块
    'merge_adjacent_blocks': True,
    
    # 相邻文本块的最大间距（点）
    'adjacent_threshold': 10,
    
    # 是否过滤低质量的识别结果
    'filter_low_quality': True,
    
    # 低质量阈值
    'low_quality_threshold': 0.5
}

# --- 缓存配置 ---
MINERU_CACHE_CONFIG = {
    # 是否启用解析结果缓存
    'enabled': True,
    
    # 缓存过期时间（秒）
    'ttl': 3600 * 24,  # 24小时
    
    # 缓存键前缀
    'key_prefix': 'mineru:parse:',
    
    # 最大缓存大小（条目数）
    'max_size': 1000
}

# --- 错误处理配置 ---
MINERU_ERROR_CONFIG = {
    # API错误时是否自动重试
    'auto_retry': True,
    
    # 可重试的错误状态码
    'retryable_status_codes': [408, 429, 500, 502, 503, 504],
    
    # 超时后的行为
    'timeout_behavior': 'raise',  # raise | return_none | return_partial
    
    # 是否记录详细的错误日志
    'verbose_logging': True
}

# --- 性能优化配置 ---
MINERU_PERFORMANCE_CONFIG = {
    # 是否使用异步请求
    'async_enabled': True,
    
    # 批量处理时的并发数
    'max_concurrent_requests': 5,
    
    # 是否启用流式处理（对于大文件）
    'streaming_enabled': False,
    
    # 流式处理的块大小（字节）
    'chunk_size': 1024 * 1024,  # 1MB
}

# --- 调试配置 ---
MINERU_DEBUG_CONFIG = {
    # 是否启用调试模式
    'enabled': False,
    
    # 是否保存原始API响应
    'save_raw_response': False,
    
    # 调试文件保存路径
    'debug_output_dir': 'logs/mineru_debug',
    
    # 是否打印请求和响应详情
    'verbose': False
}


def get_mineru_config(env: str = None) -> dict:
    """
    获取MinerU配置
    
    Args:
        env: 环境名称（dev/prod），默认使用CURRENT_ENV
        
    Returns:
        dict: MinerU配置字典
    """
    if env is None:
        env = CURRENT_ENV
    
    return {
        'api': MINERU_API_CONFIG.get(env, MINERU_API_CONFIG['dev']),
        'parse_options': MINERU_PARSE_OPTIONS,
        'supported_formats': MINERU_SUPPORTED_FORMATS,
        'bbox_formats': MINERU_BBOX_FORMATS,
        'extraction': MINERU_EXTRACTION_CONFIG,
        'cache': MINERU_CACHE_CONFIG,
        'error': MINERU_ERROR_CONFIG,
        'performance': MINERU_PERFORMANCE_CONFIG,
        'debug': MINERU_DEBUG_CONFIG
    }


def get_api_endpoint(endpoint: str, env: str = None) -> str:
    """
    获取完整的API端点URL
    
    Args:
        endpoint: API端点路径（如 '/file_parse'）
        env: 环境名称
        
    Returns:
        str: 完整的URL
    """
    if env is None:
        env = CURRENT_ENV
    
    base_url = MINERU_API_CONFIG.get(env, MINERU_API_CONFIG['dev'])['base_url']
    return f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

