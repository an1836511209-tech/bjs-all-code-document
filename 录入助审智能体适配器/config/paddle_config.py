"""
PaddleOCR 文档解析配置文件

包含 PaddleOCR-VL 和 Paddle 印章文本识别产线的配置
参考文档: 
- https://www.paddleocr.ai/latest/version3.x/pipeline_usage/PaddleOCR-VL.html
- https://www.paddleocr.ai/latest/version3.x/pipeline_usage/seal_recognition.html
"""

from typing import Dict, Any
from config.env_config import get_current_env


# --- PaddleOCR API配置 ---
PADDLE_API_CONFIG = {
    # PaddleOCR-VL 服务配置（用于信息披露申请书）
    'ocr_vl': {
        # 'dev': {
        #     'base_url': 'http://136.110.87.133:8080',
        #     'endpoint': '/layout-parsing',
        #     'timeout': 3000,  # 超时时间（秒），文档解析可能较慢
        #     'max_retries': 3,  # 最大重试次数
        #     'retry_delay': 2,  # 重试延迟（秒）
        # },
        'dev': {
            'base_url': 'http://10.224.98.182',
            'endpoint': '/layout-parsing-vl',
            'timeout': 3000,
            'max_retries': 3,
            'retry_delay': 2,
        },
        'prod': {
            'base_url': 'http://10.224.98.182',
            'endpoint': '/layout-parsing-vl',
            'timeout': 3000,
            'max_retries': 3,
            'retry_delay': 2,
        }
    },
    
    # PaddleStructureV3 服务配置（用于非信息披露申请书的其他文件）
    # 特点：支持单元格级别坐标、内置印章识别
    'structure': {
        'dev': {
            'base_url': 'http://10.224.98.182',
            'endpoint': '/layout-parsing',
            'token': '17f6cb92fbd4f52efe0b8d8a456d5a6709279f27',
            'timeout': 500,
            'max_retries': 3,
            'retry_delay': 2,
        },
        'prod': {
            'base_url': 'http://10.224.98.182',
            'endpoint': '/layout-parsing',
            'token': '17f6cb92fbd4f52efe0b8d8a456d5a6709279f27',
            'timeout': 500,
            'max_retries': 3,
            'retry_delay': 2,
        }
    },
    
    # Paddle 印章文本识别服务配置（仅用于 VL 模式）
    'seal_recognition': {
        'dev': {
            'base_url': 'http://10.224.98.182',
            'endpoint': '/seal-recognition',
            'timeout': 60,  # 印章识别较快
            'max_retries': 2,
            'retry_delay': 1,
        },
        'prod': {
            'base_url': 'http://10.224.98.182',
            'endpoint': '/seal-recognition',
            'timeout': 60,
            'max_retries': 2,
            'retry_delay': 1,
        }
    }
}

# 当前环境（从全局环境配置获取）
# 注意：不再使用 PADDLE_ENV 环境变量，统一使用 ENV 环境变量
CURRENT_ENV = get_current_env()


# --- PaddleOCR-VL 解析参数配置 ---
# PADDLE_OCR_VL_OPTIONS = {
#     # 文件类型：0=PDF，1=图像，None=客户端按扩展名自动推断
#     'fileType': 0,

#     # 文档方向分类（检测页面是否旋转）；PDF 溯源场景建议关闭，避免误报 angle
#     'useDocOrientationClassify': False,

#     # 文档矫正（曲面/透视矫正）
#     'useDocUnwarping': False,

#     # 版面检测（识别标题、正文、表格等区域）
#     'useLayoutDetection': True,

#     # 图表识别（识别并解析文档中的图表）
#     'useChartRecognition': False,

#     # 印章识别（VL 内置）；本项目走独立 /seal-recognition，此处关闭
#     'useSealRecognition': False,

#     # 对 image 类型版面块是否执行 OCR
#     'useOcrForImageBlock': False,

#     # 合并跨页/相邻表格为完整表格
#     'mergeTables': True,

#     # 重新调整标题层级（如 h1/h2/h3）
#     'relevelTitles': True,

#     # 版面形状模式：auto=自动选择矩形/四边形检测
#     'layoutShapeMode': 'auto',

#     # 版面检测 NMS（非极大值抑制，去除重叠框）
#     'layoutNms': True,

#     # 跨页内容重构（优化分页后的段落/表格连续性）
#     'restructurePages': True,

#     # VL 提示标签：ocr=纯 OCR 模式
#     'promptLabel': 'ocr',

#     # 重复惩罚（>1 抑制重复输出；1=不惩罚）
#     'repetitionPenalty': 1,

#     # 采样温度（0=确定性输出，越高越随机）
#     'temperature': 0,

#     # 核采样 top_p（1=不截断，越小采样范围越窄）
#     'topP': 1,

#     # VL 输入图像最小像素数（宽×高下限）
#     'minPixels': 147384,

#     # VL 输入图像最大像素数（宽×高上限，控制显存与速度）
#     'maxPixels': 2822400,

#     # 格式化各版面块内容为 Markdown
#     'formatBlockContent': True,

#     # 美化输出的 Markdown 排版
#     'prettifyMarkdown': True,

#     # 在 Markdown 中显示公式编号
#     'showFormulaNumber': True,

#     # 是否返回可视化结果图（调试用）
#     'visualize': False,
# }
# --- PaddleOCR-VL 解析参数配置原版 ---
PADDLE_OCR_VL_OPTIONS = {
    # 文件类型：0=PDF，1=图像，null=自动推断
    'fileType': None,

    # 文档方向分类（已由本地 ONNX 模型前置处理，设为 False 避免 Paddle 内部旋转损失 OCR 精度）
    'useDocOrientationClassify': False,

    # 文档矫正
    'useDocUnwarping': False,

    # 版面检测
    'useLayoutDetection': True,

    # 图表识别
    'useChartRecognition': True,

    # 跨页内容重构
    'restructurePages': False,

    # 版面检测阈值
    'layoutThreshold': None,

    # 版面NMS
    'layoutNms': True,

    # 版面扩展比例
    'layoutUnclipRatio': None,

    # 版面合并模式
    'layoutMergeBboxesMode': None,

    # 提示标签 (OCR模式)
    'promptLabel': 'ocr',

    # 忽略的 Markdown 标签
    'markdownIgnoreLabels': [],

    # 格式化块内容
    'formatBlockContent': True,

    # 重复惩罚 (降低惩罚，对表格更友好)
    'repetitionPenalty': 1,

    # 温度参数 (降低温度，提高稳定性)
    'temperature': 0,

    # top_p 参数 (核采样)
    'topP': 1,

    # 最小像素
    'minPixels': 147384,

    # 最大像素
    'maxPixels': 2822400,

    # 美化Markdown
    'prettifyMarkdown': True,

    # 显示公式编号
    'showFormulaNumber': True,

    # 可视化结果
    'visualize': False,
}

# --- Paddle 印章识别参数配置 ---
PADDLE_SEAL_RECOGNITION_OPTIONS = {
    # 文件类型：0=PDF，1=图像，null=自动推断
    'fileType': None,

    # 文档方向分类
    'useDocOrientationClassify': False,

    # 文档矫正
    'useDocUnwarping': False,

    # 版面检测

    'useLayoutDetection': True,
    
    # 版面检测阈值
    'layoutThreshold': None,
    
    # 版面NMS
    'layoutNms': True,
    
    # 版面扩展比例
    'layoutUnclipRatio': None,
    
    # 版面合并模式
    'layoutMergeBboxesMode': None,
    
    # 印章检测限制边长（不限制）
    'sealDetLimitSideLen': None,
    
    # 印章检测限制类型（不限制）
    'sealDetLimitType': None,
    
    # 印章检测阈值
    'sealDetThresh': 0.2,
    
    # 印章检测框阈值
    'sealDetBoxThresh': 0.6,
    
    # 印章检测扩展比例
    'sealDetUnclipRatio': 0.5,
    
    # 印章识别分数阈值（不过滤，保留所有结果）
    'sealRecScoreThresh': 0,
    
    # 可视化结果
    'visualize': False,
}


# --- PaddleStructureV3 原 解析参数配置 ---
# 用于非信息披露申请书的其他文件，支持单元格级别坐标
# PADDLE_STRUCTURE_OPTIONS = {
#     # 文件类型：0=PDF，1=图像，null=自动推断
#     'fileType': None,
    
#     # 图表识别
#     'useChartRecognition': True,
    
#     # 区域检测
#     'useRegionDetection': True,
    
#     # 文档方向分类
#     'useDocOrientationClassify': False,

#     # 文档矫正
#     'useDocUnwarping': False,
    
#     # 可视化结果
#     'visualize': False,
    
#     # 公式识别
#     'useFormulaRecognition': False,
    
#     # 表格识别（核心功能，提供单元格坐标）
#     'useTableRecognition': True,
    
#     # 版面检测阈值
#     'layoutThreshold': 0.3,
    
#     # 版面NMS
#     'layoutNms': True,
    
#     # 版面扩展比例
#     'layoutUnclipRatio': 1,
    
#     # 文本检测限制类型
#     'textDetLimitType': 'min',
    
#     # 文本检测限制边长
#     'textDetLimitSideLen': 64,
    
#     # 文本检测阈值
#     'textDetThresh': 0.3,
    
#     # 文本检测框阈值
#     'textDetBoxThresh': 0.6,
    
#     # 文本检测扩展比例
#     'textDetUnclipRatio': 1.5,
    
#     # 文本识别分数阈值
#     'textRecScoreThresh': 0,
    
#     # 印章检测限制类型
#     'sealDetLimitType': 'min',
    
#     # 印章检测限制边长
#     'sealDetLimitSideLen': 736,
    
#     # 印章检测阈值
#     'sealDetThresh': 0.2,
    
#     # 印章检测框阈值
#     'sealDetBoxThresh': 0.6,
    
#     # 印章检测扩展比例
#     'sealDetUnclipRatio': 0.5,
    
#     # 印章识别分数阈值
#     'sealRecScoreThresh': 0,
    
#     # 表格方向分类
#     'useTableOrientationClassify': True,
    
#     # 使用 OCR 结果填充表格单元格
#     'useOcrResultsWithTableCells': True,
    
#     # 端到端有线表格识别模型
#     'useE2eWiredTableRecModel': False,
    
#     # 端到端无线表格识别模型
#     'useE2eWirelessTableRecModel': False,
    
#     # 有线表格单元格转 HTML
#     'useWiredTableCellsTransToHtml': False,
    
#     # 无线表格单元格转 HTML
#     'useWirelessTableCellsTransToHtml': False,
    
#     # 注意：parseLanguage 参数在 PP-StructureV3 API 中不存在，已移除
# }

# --- PaddleStructureV3 解析参数配置 ---
# 用于非信息披露申请书的其他文件，支持单元格级别坐标
PADDLE_STRUCTURE_OPTIONS = {
    # 文件类型：0=PDF，1=图像，null=自动推断
    'fileType': None,
    
    # 图表识别
    'useChartRecognition': True,
    
    # 区域检测
    'useRegionDetection': True,
    
    # 文档方向分类
    'useDocOrientationClassify': False,
    
    # 文档矫正
    'useDocUnwarping': False,
    
    # 可视化结果
    'visualize': False,
    
    # 公式识别
    'useFormulaRecognition': False,
    
    # 表格识别（核心功能，提供单元格坐标）
    'useTableRecognition': True,
    
    # 版面检测阈值
    'layoutThreshold': 0.3,
    
    # 版面NMS
    'layoutNms': True,
    
    # 版面扩展比例
    'layoutUnclipRatio': 1,
    
    # 文本检测限制类型
    'textDetLimitType': 'min',
    
    # 文本检测限制边长
    'textDetLimitSideLen': 64,
    
    # 文本检测阈值
    'textDetThresh': 0.3,
    
    # 文本检测框阈值
    'textDetBoxThresh': 0.6,
    
    # 文本检测扩展比例
    'textDetUnclipRatio': 1.5,
    
    # 文本识别分数阈值
    'textRecScoreThresh': 0,
    
    # 印章检测限制类型
    'sealDetLimitType': 'min',
    
    # 印章检测限制边长
    'sealDetLimitSideLen': 736,
    
    # 印章检测阈值
    'sealDetThresh': 0.2,
    
    # 印章检测框阈值
    'sealDetBoxThresh': 0.6,
    
    # 印章检测扩展比例
    'sealDetUnclipRatio': 0.5,
    
    # 印章识别分数阈值
    'sealRecScoreThresh': 0,
    
    # 表格方向分类
    'useTableOrientationClassify': True,
    
    # 使用 OCR 结果填充表格单元格
    'useOcrResultsWithTableCells': True,
    
    # 端到端有线表格识别模型
    'useE2eWiredTableRecModel': False,
    
    # 端到端无线表格识别模型
    'useE2eWirelessTableRecModel': False,
    
    # 有线表格单元格转 HTML
    'useWiredTableCellsTransToHtml': False,
    
    # 无线表格单元格转 HTML
    'useWirelessTableCellsTransToHtml': False,
    
    # 注意：parseLanguage 参数在 PP-StructureV3 API 中不存在，已移除
}



# --- 文件类型支持配置 ---
PADDLE_SUPPORTED_FORMATS = {
    # 文档格式
    'documents': ['.pdf'],
    
    # 图片格式
    'images': ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'],
    
    # 最大文件大小（字节）
    'max_file_size': {
        'pdf': 100 * 1024 * 1024,      # 100MB
        'image': 100 * 1024 * 1024,    # 100MB
    }
}


# --- 错误处理配置 ---
PADDLE_ERROR_CONFIG = {
    # API错误时是否自动重试
    'auto_retry': True,
    
    # 可重试的错误状态码
    'retryable_status_codes': [408, 429, 500, 502, 503, 504],
    
    # 超时后的行为
    'timeout_behavior': 'raise',  # raise | return_none | fallback_to_mineru
    
    # 是否记录详细的错误日志
    'verbose_logging': True,
    
    # 服务故障时是否降级到 MinerU
    'fallback_to_mineru': True,
}


# --- 性能优化配置 ---
PADDLE_PERFORMANCE_CONFIG = {
    # 是否使用异步请求
    'async_enabled': True,
    
    # OCR-VL 服务的并发数（用于信息披露申请书）
    # 注意：VL 模型较重，并发数不宜过高
    'max_concurrent_requests_ocr_vl': 3,
    
    # PaddleStructureV3 服务的并发数（用于其他文件类型）
    # 注意：Structure 相对轻量，可以适当提高并发
    'max_concurrent_requests_structure': 5,
    
    # 印章识别服务的并发数（仅用于 VL 模式）
    # 注意：印章识别较轻量，可以适当提高并发
    'max_concurrent_requests_seal': 50,
}


# --- 印章提取配置 ---
PADDLE_SEAL_CONFIG = {
    # 是否启用印章文本提取（OCR-VL / Structure 二次识别）
    'enabled': True,
    
    # 印章识别的最低置信度
    'min_confidence': 0.6,
    
    # 是否将印章文本合并到主文本中
    'merge_seal_text': True,
    
    # 印章文本的标记格式
    'seal_text_format': '【印章：{text}】',
    
    # === 表格内印章识别配置 ===
    'table_seal_recognition': {
        # 是否启用表格内印章识别
        'enabled': True,
        
        # 是否将印章文本合并到表格 HTML
        'merge_to_html': True,
        
        # 位置计算：9宫格划分
        'position_grid': 9,
        
        # 是否尝试匹配单元格
        'match_cell': True,
        
        # HTML 中的印章标记模板
        'seal_item_template': '<div class="seal-item" data-text="{text}" data-score="{score}" data-bbox-table="{bbox_table}" data-bbox-page="{bbox_page}" data-position="{position}" data-position-ratio=\'{position_ratio}\' data-matched-cell="{cell}" data-matched-row="{matched_row}" data-matched-col="{matched_col}">【印章：{text}】(位置:{position}, 临近模糊匹配单元格:{cell})</div>',
        
        # 印章信息块包装模板
        'seal_block_template': '\n<!-- TABLE_SEALS_START -->\n<div class="table-seal-info" data-seal-count="{count}">\n{items}\n</div>\n<!-- TABLE_SEALS_END -->',
    }
}


# --- PDF 文本层补全配置（OCR 表格缺行时注入内置文本） ---
TEXT_LAYER_SUPPLEMENT_CONFIG = {
    # 是否启用
    "enabled": True,
    # 适用的业务 file_type
    "file_types": ["info_disclosure_application"],
    # 整页高亮溯源（144 DPI bbox）
    "highlight_full_page": True,
    # 补全模式：page_diff = 逐页对比文本层与 OCR（方案 A）
    "mode": "page_diff",
    # 逻辑行最少字符数（归一化后），低于此值不注入
    "min_line_chars": 6,
    # 单页最多注入行数，防止异常 PDF 灌入过多内容
    "max_lines_per_page": 20,
    # 必须在同页文本层中检索到 bbox 才注入（宁缺毋滥）
    "require_bbox_on_page": True,
    # 常规 diff：OCR 页正文低于此值且不满足「整页丢失」条件时跳过（防分页错位误注入）
    "min_ocr_page_chars": 30,
    # 整页 OCR 丢失恢复（须分页对齐可信 + 文本层该页有足够内容 + 逐行 bbox 校验）
    "whole_page_loss_enabled": True,
    "whole_page_loss_ocr_max_chars": 30,
    "whole_page_loss_native_min_chars": 40,
    "whole_page_loss_max_lines": 15,
}


# --- 调试配置 ---
PADDLE_DEBUG_CONFIG = {
    # 是否启用调试模式
    'enabled': False,
    
    # 是否保存原始API响应
    'save_raw_response': False,
    
    # 调试文件保存路径
    'debug_output_dir': 'logs/paddle_debug',
    
    # 是否打印请求和响应详情
    'verbose': False,
    
    # 是否输出 DPI 诊断信息（默认关闭，调试时开启）
    'show_dpi_diagnostics': False,
}


def get_paddle_config(env: str = None) -> Dict[str, Any]:
    """
    获取Paddle配置
    
    Args:
        env: 环境名称（dev/prod/production），默认使用CURRENT_ENV
        
    Returns:
        dict: Paddle配置字典
    """
    if env is None:
        env = CURRENT_ENV
    
    # 标准化环境名称：production -> prod
    if env == 'production':
        env = 'prod'
    
    return {
        'api': {
            'ocr_vl': PADDLE_API_CONFIG['ocr_vl'].get(env, PADDLE_API_CONFIG['ocr_vl']['dev']),
            'structure': PADDLE_API_CONFIG['structure'].get(env, PADDLE_API_CONFIG['structure']['dev']),
            'seal_recognition': PADDLE_API_CONFIG['seal_recognition'].get(env, PADDLE_API_CONFIG['seal_recognition']['dev']),
        },
        'ocr_vl_options': PADDLE_OCR_VL_OPTIONS,
        'structure_options': PADDLE_STRUCTURE_OPTIONS,
        'seal_recognition_options': PADDLE_SEAL_RECOGNITION_OPTIONS,
        'supported_formats': PADDLE_SUPPORTED_FORMATS,
        'seal_config': PADDLE_SEAL_CONFIG,
        'error': PADDLE_ERROR_CONFIG,
        'performance': PADDLE_PERFORMANCE_CONFIG,
        'debug': PADDLE_DEBUG_CONFIG,
        'text_layer_supplement': TEXT_LAYER_SUPPLEMENT_CONFIG,
    }


def get_text_layer_supplement_config() -> Dict[str, Any]:
    """获取 PDF 文本层补全配置"""
    return dict(TEXT_LAYER_SUPPLEMENT_CONFIG)


def get_api_endpoint(service: str, env: str = None) -> str:
    """
    获取完整的API端点URL
    
    Args:
        service: 服务类型（'ocr_vl'、'structure' 或 'seal_recognition'）
        env: 环境名称 (dev/prod/production)
        
    Returns:
        str: 完整的URL
    """
    if env is None:
        env = CURRENT_ENV
    
    # 标准化环境名称：production -> prod
    if env == 'production':
        env = 'prod'
    
    if service not in PADDLE_API_CONFIG:
        raise ValueError(f"不支持的服务类型: {service}")
    
    config = PADDLE_API_CONFIG[service].get(env, PADDLE_API_CONFIG[service]['dev'])
    base_url = config['base_url']
    endpoint = config['endpoint']
    
    return f"{base_url.rstrip('/')}{endpoint}"


def get_structure_token(env: str = None) -> str:
    """
    获取 PaddleStructureV3 服务的认证 Token
    
    Args:
        env: 环境名称 (dev/prod/production)
        
    Returns:
        str: 认证 Token
    """
    if env is None:
        env = CURRENT_ENV
    
    # 标准化环境名称：production -> prod
    if env == 'production':
        env = 'prod'
    
    config = PADDLE_API_CONFIG['structure'].get(env, PADDLE_API_CONFIG['structure']['dev'])
    return config.get('token', '')


# ========== 流水线提取优化配置 ==========
# 控制是否启用流水线模式（解析和提取并发执行）
# 设为 False 可回退到串行模式（先全部解析，再全部提取）
PIPELINE_EXTRACTION_ENABLED = True


def is_pipeline_extraction_enabled() -> bool:
    """
    检查是否启用流水线提取模式
    
    流水线模式下：
    - 文件解析和字段提取并发执行
    - 每个 file_type 解析完成后立即触发对应的字段提取
    - 可显著降低端到端延迟
    
    串行模式下：
    - 先等待所有文件解析完成
    - 再统一执行字段提取
    - 更稳定，适合调试
    
    Returns:
        bool: 是否启用流水线模式
    """
    return PIPELINE_EXTRACTION_ENABLED

