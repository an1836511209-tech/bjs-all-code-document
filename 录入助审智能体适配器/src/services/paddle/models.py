"""
Paddle 数据模型

定义 PaddleOCR-VL 和印章识别的响应数据模型
确保与 MinerU 的数据模型兼容，以便上下游无缝切换
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum


# ==================== API 响应模型 ====================

@dataclass
class PaddleAPIResponse:
    """Paddle API 统一响应格式"""
    logId: str
    errorCode: int
    errorMsg: str
    result: Optional[Dict[str, Any]] = None
    
    @property
    def is_success(self) -> bool:
        """判断响应是否成功"""
        return self.errorCode == 0


# ==================== PaddleOCR-VL 响应模型 ====================

class LayoutBlockType(str, Enum):
    """版面块类型"""
    TEXT = "text"
    TITLE = "title"
    FIGURE = "figure"
    TABLE = "table"
    EQUATION = "equation"
    SEAL = "seal"  # 印章


@dataclass
class LayoutBlock:
    """版面块（从 prunedResult 解析）"""
    block_type: str  # 块类型
    bbox: List[float]  # 边界框 [x0, y0, x1, y1]
    text: Optional[str] = None  # 文本内容
    image_base64: Optional[str] = None  # 图像 base64（用于印章）
    score: float = 1.0  # 置信度


@dataclass
class MarkdownResult:
    """Markdown 结果"""
    text: str  # Markdown 文本
    images: Dict[str, str]  # 图片映射（相对路径 -> base64）
    is_start: bool  # 是否为段开始
    is_end: bool  # 是否为段结束


@dataclass
class PaddleLayoutParsingResult:
    """版面解析结果（单页）"""
    pruned_result: Dict[str, Any]  # 简化的结果
    markdown: MarkdownResult  # Markdown 结果
    output_images: Optional[Dict[str, str]] = None  # 输出图像（base64）
    input_image: Optional[str] = None  # 输入图像（base64）
    rotation_angle: int = 0  # 文档旋转角度（逆时针，度），从 doc_preprocessor_res.angle 获取


@dataclass
class PaddleOCRVLResponse:
    """PaddleOCR-VL 完整响应"""
    log_id: str
    error_code: int
    error_msg: str
    layout_parsing_results: List[PaddleLayoutParsingResult]  # 每页的结果
    data_info: Dict[str, Any]  # 输入数据信息
    
    @property
    def is_success(self) -> bool:
        """判断是否成功"""
        return self.error_code == 0


# ==================== Paddle 印章识别响应模型 ====================

@dataclass
class SealDetection:
    """印章检测结果"""
    bbox: List[float]  # 边界框
    text: str  # 识别的文本
    score: float  # 置信度
    image_key: Optional[str] = None  # 对应的图片相对路径
    image_base64: Optional[str] = None  # 原始 base64，用于对齐


@dataclass
class TableSealInfo:
    """
    表格内印章详细信息
    
    用于存储从表格中识别出的印章，包含完整的位置信息和单元格匹配结果
    """
    # 印章识别结果
    text: str  # 印章文本，如 "北京电视台"
    score: float  # 置信度
    
    # 坐标信息
    bbox_in_table: List[float]  # 在表格内的坐标 [x0, y0, x1, y1]
    bbox_in_page: List[float]  # 在页面中的坐标（转换后）
    
    # 位置描述（9宫格）
    position: str  # "左上", "中上", "右上", "左", "中", "右", "左下", "中下", "右下"
    position_ratio: Dict[str, float]  # {"x": 0.25, "y": 0.85} 精确比例
    
    # 单元格匹配（尝试推算）
    matched_cell_text: Optional[str] = None  # 推算的单元格文本，如 "被评估单位盖章"
    matched_cell_row: Optional[int] = None  # 推算的行号
    matched_cell_col: Optional[int] = None  # 推算的列号


@dataclass
class PaddleTableCell:
    """
    表格单元格信息
    
    用于 PaddleStructureV3 返回的单元格级别坐标定位
    从 table_res_list[].cell_box_list 和 pred_html 中提取
    """
    bbox: List[float]      # 单元格坐标 [x0, y0, x1, y1]（页面绝对坐标）
    text: str              # 单元格文本内容
    row: int               # 起始行号（从 0 开始）
    col: int               # 起始列号（从 0 开始）
    rowspan: int = 1       # 行跨度
    colspan: int = 1       # 列跨度
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "bbox": self.bbox,
            "text": self.text,
            "row": self.row,
            "col": self.col,
            "rowspan": self.rowspan,
            "colspan": self.colspan
        }


@dataclass
class PaddleSealRecognitionResult:
    """印章识别结果（单页）"""
    pruned_result: Dict[str, Any]  # 简化的结果
    output_images: Optional[Dict[str, str]] = None  # 输出图像
    input_image: Optional[str] = None  # 输入图像
    seals: List[SealDetection] = None  # 提取的印章列表
    
    def __post_init__(self):
        if self.seals is None:
            self.seals = []


@dataclass
class PaddleSealRecognitionResponse:
    """Paddle 印章识别完整响应"""
    log_id: str
    error_code: int
    error_msg: str
    seal_rec_results: List[PaddleSealRecognitionResult]  # 每页的结果
    data_info: Dict[str, Any]  # 输入数据信息
    
    @property
    def is_success(self) -> bool:
        """判断是否成功"""
        return self.error_code == 0


# ==================== 统一解析结果模型（兼容 MinerU） ====================

@dataclass
class PaddleContent:
    """
    内容块（兼容 MinerU 的 Content 模型）
    
    为了确保上下游兼容，这个模型与 MinerU 的 Content 模型保持一致
    """
    type: str  # 类型：text, image, table, equation, seal
    text: Optional[str] = None  # 文本内容
    bbox: Optional[List[float]] = None  # 边界框（可能为 None）
    page_idx: int = 0  # 页码索引
    
    # 类型特定的字段
    img_path: Optional[str] = None  # 图片路径（对于 image、table）
    image_base64: Optional[str] = None  # 图片 base64（对于 seal）
    table_body: Optional[str] = None  # 表格 HTML（对于 table）
    text_format: Optional[str] = None  # 文本格式（对于 equation）
    score: Optional[float] = None  # 置信度（例如印章识别）
    
    # 扩展字段
    image_caption: List[str] = None
    table_caption: List[str] = None
    
    # 表格单元格信息（仅 table 类型，由 PaddleStructureV3 提供）
    cells: Optional[List['PaddleTableCell']] = None
    
    def __post_init__(self):
        if self.image_caption is None:
            self.image_caption = []
        if self.table_caption is None:
            self.table_caption = []


@dataclass
class PaddleSpan:
    """
    文本片段（兼容 MinerU 的 Span 模型）
    """
    bbox: List[float]
    text: str
    type: str = "text"
    score: float = 1.0


@dataclass
class PaddleLine:
    """
    文本行（兼容 MinerU 的 Line 模型）
    """
    bbox: List[float]
    spans: List[PaddleSpan]


@dataclass
class PaddleLayoutBlock:
    """
    布局块（兼容 MinerU 的 LayoutBlock 模型）
    """
    bbox: List[float]
    lines: List[PaddleLine]
    category_type: str
    
    # 可选字段：用于保留原始内容
    text: Optional[str] = None  # 纯文本内容
    table_body: Optional[str] = None  # 表格的HTML内容（仅 table 类型）
    score: Optional[float] = None  # 置信度
    
    # 表格单元格信息（仅 table 类型，由 PaddleStructureV3 提供）
    cells: Optional[List['PaddleTableCell']] = None
    
    @property
    def type(self) -> str:
        """返回类别类型"""
        return self.category_type


@dataclass
class PaddlePage:
    """
    页面（兼容 MinerU 的 ParsedPage 模型）
    
    确保具有与 MinerU 相同的属性和方法
    """
    page_num: int  # 页码（从 0 开始）
    width: float
    height: float
    
    # 内容列表
    contents: List[PaddleContent]
    
    # 布局块（用于溯源）
    layout_blocks: List[PaddleLayoutBlock]
    
    # 页面旋转角度（逆时针，度），从 Paddle doc_preprocessor_res.angle 获取，用于高亮时旋转渲染
    rotation_angle: int = 0

    # 本地旋转检测模型测得的旋转角度（逆时针，度）
    # 当 useDocOrientationClassify=False 时，Paddle 返回的 rotation_angle 恒为 0，
    # 由本地 RotationDetector 检测并存储于此字段，供下游高亮器做 bbox 逆变换
    local_rotation_angle: int = 0
    
    def get_all_text(self, separator: str = '\n') -> str:
        """获取页面所有文本"""
        texts = []
        for content in self.contents:
            if content.text:
                texts.append(content.text)
        return separator.join(texts)


@dataclass
class PaddleParseResult:
    """
    Paddle 解析结果（完全兼容 MinerU 的 ParseResult）
    
    这个类确保 Paddle 的解析结果可以无缝替换 MinerU 的结果
    """
    success: bool
    file_name: str
    file_type: str
    total_pages: int
    backend: str = "paddle"  # 标识为 paddle 后端
    
    pages: List[PaddlePage] = None
    metadata: Dict[str, Any] = None
    
    # Markdown 内容（用于 LLM 提取）
    md_content: Optional[str] = None
    
    error_message: Optional[str] = None
    parse_time: Optional[float] = None

    # 旋转检测修正后的文件内容（仅当 PDF 被本地 RotationDetector 修改了 /Rotate 时非空）
    # 高亮器必须使用此修正后的 PDF 以保证 bbox 坐标系一致
    corrected_file_content: Optional[bytes] = None
    
    def __post_init__(self):
        if self.pages is None:
            self.pages = []
        if self.metadata is None:
            self.metadata = {}
    
    def get_page(self, page_num: int) -> Optional[PaddlePage]:
        """获取指定页面"""
        for page in self.pages:
            if page.page_num == page_num:
                return page
        return None
    
    def get_all_text(self, separator: str = '\n\n') -> str:
        """获取所有文本"""
        texts = [page.get_all_text() for page in self.pages]
        return separator.join(texts)


# ==================== 辅助函数 ====================

def create_bbox_from_list(bbox_list: List[float]) -> List[float]:
    """
    创建边界框（确保格式为 [x0, y0, x1, y1]）
    
    Args:
        bbox_list: 边界框列表
        
    Returns:
        List[float]: 标准格式的边界框
    """
    if len(bbox_list) == 4:
        return bbox_list
    elif len(bbox_list) == 8:
        # 多边形格式 [x0,y0,x1,y1,x2,y2,x3,y3] -> 转换为矩形
        x_coords = [bbox_list[i] for i in range(0, 8, 2)]
        y_coords = [bbox_list[i] for i in range(1, 8, 2)]
        return [min(x_coords), min(y_coords), max(x_coords), max(y_coords)]
    else:
        raise ValueError(f"不支持的 bbox 格式，长度: {len(bbox_list)}")

