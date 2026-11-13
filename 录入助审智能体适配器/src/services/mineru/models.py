"""
MinerU数据模型（严格按照官方文档定义）

参考文档: https://opendatalab.github.io/MinerU/zh/reference/output_files/
支持pipeline和VLM两种后端
"""

from enum import IntEnum, Enum
from typing import List, Optional, Dict, Any, Union
from dataclasses import dataclass, field
from pydantic import BaseModel, Field


# ==================== Pipeline后端数据模型 ====================

class CategoryType(IntEnum):
    """
    内容类别枚举（Pipeline后端）
    
    参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/#_5
    """
    TITLE = 0               # 标题
    PLAIN_TEXT = 1          # 文本
    ABANDON = 2             # 包括页眉页脚页码和页面注释
    FIGURE = 3              # 图片
    FIGURE_CAPTION = 4      # 图片描述
    TABLE = 5               # 表格
    TABLE_CAPTION = 6       # 表格描述
    TABLE_FOOTNOTE = 7      # 表格注释
    ISOLATE_FORMULA = 8     # 行间公式
    FORMULA_CAPTION = 9     # 行间公式的标号
    EMBEDDING = 13          # 行内公式
    ISOLATED = 14           # 行间公式
    TEXT = 15               # OCR 识别结果


class BlockType(str, Enum):
    """块类型（Pipeline后端）"""
    TEXT = "text"
    TITLE = "title"
    INTERLINE_EQUATION = "interline_equation"
    IMAGE = "image"
    IMAGE_BODY = "image_body"
    IMAGE_CAPTION = "image_caption"
    IMAGE_FOOTNOTE = "image_footnote"
    TABLE = "table"
    TABLE_BODY = "table_body"
    TABLE_CAPTION = "table_caption"
    TABLE_FOOTNOTE = "table_footnote"
    CODE = "code"
    CODE_BODY = "code_body"
    CODE_CAPTION = "code_caption"
    LIST = "list"
    LIST_ITEM = "list_item"


class ContentListType(str, Enum):
    """内容列表类型（Pipeline后端）"""
    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"
    INTERLINE_EQUATION = "interline_equation"
    EQUATION = "equation"  # VLM 使用 equation 而不是 interline_equation
    CODE = "code"
    LIST = "list"
    # 废弃内容类型
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    ASIDE_TEXT = "aside_text"
    PAGE_FOOTNOTE = "page_footnote"
    PHONETIC = "phonetic"  # VLM 新增：拼音类型


class ContentSubType(str, Enum):
    """内容子类型"""
    TEXT = "text"
    CODE = "code"
    ALGORITHM = "algorithm"
    REF_TEXT = "ref_text"


# ==================== 坐标相关模型 ====================

@dataclass
class BBox:
    """
    边界框坐标类
    
    坐标系统说明（参考官方文档）：
    - 原点：左上角(0, 0)
    - X轴：向右为正
    - Y轴：向下为正
    - 单位：点（1/72英寸） - Pipeline后端
    - 单位：百分比（0-1） - VLM后端
    - 格式：[x0, y0, x1, y1] 左上角和右下角坐标
    """
    x0: float
    y0: float
    x1: float
    y1: float
    
    @classmethod
    def from_list(cls, bbox: List[float], page_width: Optional[float] = None, page_height: Optional[float] = None) -> 'BBox':
        """
        从列表创建 [x0, y0, x1, y1]
        
        Args:
            bbox: 坐标列表
            page_width: 页面宽度（用于将百分比坐标转换为绝对坐标）
            page_height: 页面高度（用于将百分比坐标转换为绝对坐标）
        
        Returns:
            BBox: 边界框对象
        """
        if len(bbox) != 4:
            raise ValueError(f"BBox列表必须包含4个元素，当前有 {len(bbox)} 个")
        
        # 如果坐标是百分比格式（0-1之间）且提供了页面尺寸，则转换为绝对坐标
        if page_width and page_height and all(0 <= coord <= 1 for coord in bbox):
            return cls(
                bbox[0] * page_width,
                bbox[1] * page_height,
                bbox[2] * page_width,
                bbox[3] * page_height
            )
        
        return cls(bbox[0], bbox[1], bbox[2], bbox[3])
    
    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> 'BBox':
        """
        从字典创建BBox
        
        支持格式：
        - {'x0': ..., 'y0': ..., 'x1': ..., 'y1': ...}
        - {'x': ..., 'y': ..., 'width': ..., 'height': ...}
        - {'left': ..., 'top': ..., 'right': ..., 'bottom': ...}
        """
        if all(k in data for k in ['x0', 'y0', 'x1', 'y1']):
            return cls(data['x0'], data['y0'], data['x1'], data['y1'])
        elif all(k in data for k in ['x', 'y', 'width', 'height']):
            x, y, w, h = data['x'], data['y'], data['width'], data['height']
            return cls(x, y, x + w, y + h)
        elif all(k in data for k in ['left', 'top', 'right', 'bottom']):
            return cls(data['left'], data['top'], data['right'], data['bottom'])
        else:
            raise ValueError(f"不支持的BBox格式: {data.keys()}")
    
    def to_list(self) -> List[float]:
        """转换为列表 [x0, y0, x1, y1]"""
        return [self.x0, self.y0, self.x1, self.y1]
    
    def to_dict(self) -> Dict[str, float]:
        """转换为字典"""
        return {'x0': self.x0, 'y0': self.y0, 'x1': self.x1, 'y1': self.y1}
    
    def to_xywh(self) -> Dict[str, float]:
        """转换为x,y,width,height格式"""
        return {
            'x': self.x0,
            'y': self.y0,
            'width': self.x1 - self.x0,
            'height': self.y1 - self.y0
        }
    
    @property
    def width(self) -> float:
        """宽度"""
        return self.x1 - self.x0
    
    @property
    def height(self) -> float:
        """高度"""
        return self.y1 - self.y0
    
    @property
    def area(self) -> float:
        """面积"""
        return self.width * self.height
    
    @property
    def center(self) -> tuple[float, float]:
        """中心点"""
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)


# ==================== Pipeline后端 - model.json模型 ====================

@dataclass
class PageInfo:
    """页面信息（model.json）"""
    page_no: int  # 页码序号，第一页是0
    height: int   # 页面高度
    width: int    # 页面宽度


@dataclass
class ObjectInferenceResult:
    """
    对象识别结果（model.json）
    
    参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/#modeljson
    """
    category_id: CategoryType      # 类别ID
    poly: List[float]              # 多边形坐标 [x0,y0,x1,y1,x2,y2,x3,y3]
    score: float                   # 置信度分数
    latex: Optional[str] = None    # LaTeX解析结果（公式）
    html: Optional[str] = None     # HTML解析结果（表格）
    
    def get_bbox(self) -> BBox:
        """从poly获取bbox"""
        if len(self.poly) >= 4:
            x_coords = [self.poly[i] for i in range(0, len(self.poly), 2)]
            y_coords = [self.poly[i] for i in range(1, len(self.poly), 2)]
            return BBox(min(x_coords), min(y_coords), max(x_coords), max(y_coords))
        raise ValueError(f"无效的poly坐标: {self.poly}")


# ==================== Pipeline后端 - middle.json模型 ====================

@dataclass
class Span:
    """
    文本片段（middle.json中的最小单元）
    
    参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/#_12
    """
    bbox: BBox           # 边界框
    text: str            # 文本内容（使用 text 与 TextContent 保持一致）
    type: str            # 类型（text/inline_equation等）
    score: float = 1.0   # 置信度
    
    @property
    def content(self) -> str:
        """兼容性属性：返回 text"""
        return self.text


@dataclass
class Line:
    """文本行（middle.json）"""
    bbox: BBox                  # 边界框
    spans: List[Span]           # 片段列表
    

@dataclass
class Block:
    """
    内容块（middle.json中的二级块）
    
    参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/#_10
    """
    bbox: BBox                      # 边界框
    lines: List[Line]               # 行列表
    type: BlockType                 # 块类型
    index: int                      # 块索引
    angle: float = 0.0              # 旋转角度


@dataclass
class LayoutBlock:
    """
    布局块（middle.json中的一级块）
    
    根据实际 MinerU API 返回的 pdf_info 数据结构调整
    """
    bbox: BBox                      # 边界框
    lines: List[Line]               # 行列表（直接包含 lines，而不是二级 blocks）
    category_type: str              # 类别类型（如 'text', 'title' 等）
    
    # 为兼容性保留的属性
    @property  
    def type(self) -> str:
        """返回类别类型"""
        return self.category_type
    
    @property
    def blocks(self) -> List['Block']:
        """兼容性属性：返回空列表"""
        return []


@dataclass
class MiddlePageInfo:
    """middle.json中的页面信息"""
    page_no: int
    height: float
    width: float


@dataclass
class MiddleResult:
    """
    middle.json完整结构
    
    参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/#middlejson
    """
    page_info: MiddlePageInfo              # 页面信息
    layout_dets: List[ObjectInferenceResult]  # 布局检测结果
    preproc_blocks: List[LayoutBlock]      # 预处理块列表


# ==================== Pipeline后端 - content_list.json模型 ====================

@dataclass
class TextContent:
    """
    文本内容（content_list.json）
    
    参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/#content_listjson
    """
    type: str                            # 固定值: "text"
    text: str                            # 文本内容
    bbox: BBox                           # 边界框
    page_idx: int                        # 页码（从0开始）
    block_type: str = "text"             # 块类型（text/title等）
    text_level: Optional[int] = None     # 标题级别（0=正文，1=一级标题，2=二级标题...）


@dataclass
class ImageContent:
    """
    图片内容（content_list.json）
    
    参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/#content_listjson
    """
    type: str                                  # 固定值: "image"
    img_path: str                              # 图片路径
    bbox: BBox                                 # 边界框
    page_idx: int                              # 页码（从0开始）
    image_caption: List[str] = field(default_factory=list)   # 图片描述列表
    image_footnote: List[str] = field(default_factory=list)  # 图片脚注列表


@dataclass
class TableContent:
    """
    表格内容（content_list.json）
    
    参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/#content_listjson
    """
    type: str                                     # 固定值: "table"
    bbox: BBox                                    # 边界框
    page_idx: int                                 # 页码（从0开始）
    img_path: str                                 # 表格图片路径
    table_body: str = ""                          # 表格HTML内容
    table_caption: List[str] = field(default_factory=list)   # 表格描述列表
    table_footnote: List[str] = field(default_factory=list)  # 表格脚注列表
    
    @property
    def html(self) -> str:
        """兼容性属性：返回 table_body"""
        return self.table_body


@dataclass
class FormulaContent:
    """
    公式内容（content_list.json）
    
    参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/#content_listjson
    注意：官方文档中 type 为 "equation"
    """
    type: str                        # 固定值: "equation"
    bbox: BBox                       # 边界框
    page_idx: int                    # 页码（从0开始）
    img_path: str                    # 公式图片路径
    text: str                        # LaTeX公式文本
    text_format: str = "latex"       # 固定值: "latex"
    
    @property
    def latex(self) -> str:
        """兼容性属性：返回 text"""
        return self.text


@dataclass
class CodeContent:
    """
    代码内容
    
    参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/#_22
    """
    type: ContentListType
    sub_type: ContentSubType  # code 或 algorithm
    code_body: str
    code_caption: Optional[str] = None
    bbox: BBox = None
    page_idx: int = 0


@dataclass
class ListContent:
    """
    列表内容
    
    参考: https://opendatalab.github.io/MinerU/zh/reference/output_files/#_22
    """
    type: ContentListType
    sub_type: ContentSubType  # text 或 ref_text
    list_items: List[str]
    bbox: BBox
    page_idx: int


@dataclass
class DiscardedContent:
    """废弃内容（页眉、页脚、页码等）"""
    type: ContentListType  # header, footer, page_number, aside_text, page_footnote
    text: str
    bbox: BBox
    page_idx: int


# ==================== 统一的解析结果模型 ====================

@dataclass
class ParsedPage:
    """
    解析的页面（统一模型）
    
    整合了middle.json和content_list.json的信息
    """
    page_num: int
    width: float
    height: float
    
    # 来自middle.json的原始块
    layout_blocks: List[LayoutBlock] = field(default_factory=list)
    
    # 来自content_list.json的结构化内容
    contents: List[Union[
        TextContent, 
        ImageContent, 
        TableContent, 
        FormulaContent,
        CodeContent,
        ListContent,
        DiscardedContent
    ]] = field(default_factory=list)
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_all_text(self, separator: str = '\n') -> str:
        """获取页面所有文本"""
        texts = []
        for content in self.contents:
            if isinstance(content, TextContent):
                texts.append(content.text)
            elif isinstance(content, (ImageContent, TableContent)) and content.img_caption:
                texts.append(content.img_caption)
            elif isinstance(content, CodeContent):
                if content.code_caption:
                    texts.append(content.code_caption)
                texts.append(content.code_body)
            elif isinstance(content, ListContent):
                texts.extend(content.list_items)
        return separator.join(texts)
    
    def get_contents_by_type(self, content_type: ContentListType) -> List[Any]:
        """根据类型获取内容"""
        return [c for c in self.contents if c.type == content_type]
    
    def get_text_blocks(self) -> List[TextContent]:
        """获取所有文本块"""
        return [c for c in self.contents if isinstance(c, TextContent)]
    
    def get_image_blocks(self) -> List[ImageContent]:
        """获取所有图片块"""
        return [c for c in self.contents if isinstance(c, ImageContent)]
    
    def get_table_blocks(self) -> List[TableContent]:
        """获取所有表格块"""
        return [c for c in self.contents if isinstance(c, TableContent)]


@dataclass
class ParseResult:
    """
    完整的解析结果
    
    整合所有MinerU输出信息
    """
    success: bool
    file_name: str
    file_type: str
    total_pages: int
    backend: str = "pipeline"  # pipeline 或 vlm
    
    pages: List[ParsedPage] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Markdown 内容（用于 LLM 提取）
    md_content: Optional[str] = None
    
    error_message: Optional[str] = None
    parse_time: Optional[float] = None
    
    def get_page(self, page_num: int) -> Optional[ParsedPage]:
        """获取指定页面"""
        for page in self.pages:
            if page.page_num == page_num:
                return page
        return None
    
    def get_all_text(self, separator: str = '\n\n') -> str:
        """获取所有文本"""
        texts = [page.get_all_text() for page in self.pages]
        return separator.join(texts)
    
    def search_text(
        self, 
        query: str, 
        case_sensitive: bool = False
    ) -> List[tuple[int, Union[TextContent, CodeContent, ListContent]]]:
        """搜索文本"""
        results = []
        search_query = query if case_sensitive else query.lower()
        
        for page in self.pages:
            for content in page.contents:
                text = None
                
                if isinstance(content, TextContent):
                    text = content.text
                elif isinstance(content, CodeContent):
                    text = f"{content.code_caption or ''}\n{content.code_body}"
                elif isinstance(content, ListContent):
                    text = '\n'.join(content.list_items)
                
                if text:
                    check_text = text if case_sensitive else text.lower()
                    if search_query in check_text:
                        results.append((page.page_num, content))
        
        return results
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'success': self.success,
            'file_name': self.file_name,
            'file_type': self.file_type,
            'total_pages': self.total_pages,
            'backend': self.backend,
            'pages': [
                {
                    'page_num': page.page_num,
                    'width': page.width,
                    'height': page.height,
                    'contents_count': len(page.contents),
                    'metadata': page.metadata
                }
                for page in self.pages
            ],
            'metadata': self.metadata,
            'error_message': self.error_message,
            'parse_time': self.parse_time
        }


# ==================== 辅助函数 ====================

def parse_bbox_from_any(bbox_data: Union[List[float], Dict[str, float]]) -> BBox:
    """
    从任意格式解析BBox
    
    Args:
        bbox_data: 列表或字典格式的坐标
        
    Returns:
        BBox: 边界框对象
    """
    if isinstance(bbox_data, list):
        return BBox.from_list(bbox_data)
    elif isinstance(bbox_data, dict):
        return BBox.from_dict(bbox_data)
    else:
        raise ValueError(f"不支持的bbox类型: {type(bbox_data)}")
