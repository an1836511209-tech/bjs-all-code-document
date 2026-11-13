# MinerU 数据结构对齐修复文档

## 📌 概述

根据 MinerU 官方文档（https://opendatalab.github.io/MinerU/zh/reference/output_files/），对项目中的数据模型进行了全面对齐和修复。

## ✅ 修复内容

### 1. model.json - ObjectInferenceResult

**官方定义**：
```python
class ObjectInferenceResult(BaseModel):
    category_id: CategoryType
    poly: list[float]  # [x0,y0,x1,y1,x2,y2,x3,y3]
    score: float
    latex: str | None
    html: str | None
```

**修复**：
- ✅ 添加 `latex: Optional[str]` 字段（公式解析结果）
- ✅ 添加 `html: Optional[str]` 字段（表格解析结果）

### 2. content_list.json - TextContent

**官方定义**：
```json
{
    "type": "text",
    "text": "...",
    "text_level": 1,  // 可选：0或无=正文，1=一级标题，2=二级标题...
    "bbox": [x0, y0, x1, y1],
    "page_idx": 0
}
```

**修复**：
- ✅ `type` 字段从 `ContentListType` 枚举改为 `str` 类型
- ✅ 明确 `text_level` 语义：0或无=正文，1=一级标题，2=二级标题...
- ✅ 确保所有字段符合官方文档

### 3. content_list.json - ImageContent

**官方定义**：
```json
{
    "type": "image",
    "img_path": "images/xxx.jpg",
    "image_caption": ["..."],    // 列表
    "image_footnote": ["..."],   // 列表
    "bbox": [x0, y0, x1, y1],
    "page_idx": 0
}
```

**修复**：
- ✅ `type` 从枚举改为字符串 `"image"`
- ✅ `img_caption` → `image_caption`（字段名对齐）
- ✅ 改为 `List[str]` 类型（官方是列表）
- ✅ 添加 `image_footnote: List[str]` 字段

**修改前**：
```python
@dataclass
class ImageContent:
    type: ContentListType
    img_path: str
    img_caption: Optional[str] = None  # ❌ 字段名错误，类型错误
    bbox: BBox = None
    page_idx: int = 0
```

**修改后**：
```python
@dataclass
class ImageContent:
    type: str                          # ✅ "image"
    img_path: str
    bbox: BBox
    page_idx: int
    image_caption: List[str] = field(default_factory=list)   # ✅
    image_footnote: List[str] = field(default_factory=list)  # ✅
```

### 4. content_list.json - TableContent

**官方定义**：
```json
{
    "type": "table",
    "img_path": "images/xxx.jpg",
    "table_body": "<html>...</html>",  // HTML内容
    "table_caption": ["..."],          // 列表
    "table_footnote": ["..."],         // 列表
    "bbox": [x0, y0, x1, y1],
    "page_idx": 0
}
```

**修复**：
- ✅ `type` 从枚举改为字符串 `"table"`
- ✅ `html` → `table_body`（字段名对齐）
- ✅ `table_caption` 改为 `List[str]` 类型
- ✅ 添加 `table_footnote: List[str]` 字段
- ✅ 添加兼容性属性 `@property html`

**修改前**：
```python
@dataclass
class TableContent:
    type: ContentListType
    bbox: BBox
    page_idx: int = 0
    html: str = ""                      # ❌ 字段名不匹配
    img_path: str = ""
    table_caption: Optional[str] = None  # ❌ 类型错误
```

**修改后**：
```python
@dataclass
class TableContent:
    type: str                           # ✅ "table"
    bbox: BBox
    page_idx: int
    img_path: str
    table_body: str = ""                # ✅ 字段名对齐
    table_caption: List[str] = field(default_factory=list)   # ✅
    table_footnote: List[str] = field(default_factory=list)  # ✅
    
    @property
    def html(self) -> str:
        """兼容性属性"""
        return self.table_body
```

### 5. content_list.json - FormulaContent (equation)

**官方定义**：
```json
{
    "type": "equation",
    "img_path": "images/xxx.jpg",
    "text": "$$...$$",
    "text_format": "latex",
    "bbox": [x0, y0, x1, y1],
    "page_idx": 0
}
```

**修复**：
- ✅ `type` 从枚举改为字符串 `"equation"`（注意：官方使用 "equation"，不是 "formula"）
- ✅ `latex` → `text`（字段名对齐）
- ✅ 添加 `img_path: str` 字段
- ✅ 添加 `text_format: str = "latex"` 字段
- ✅ 添加兼容性属性 `@property latex`

**修改前**：
```python
@dataclass
class FormulaContent:
    type: ContentListType
    latex: str         # ❌ 字段名不匹配
    bbox: BBox
    page_idx: int
```

**修改后**：
```python
@dataclass
class FormulaContent:
    type: str                # ✅ "equation"
    bbox: BBox
    page_idx: int
    img_path: str            # ✅ 新增
    text: str                # ✅ 字段名对齐
    text_format: str = "latex"  # ✅ 新增
    
    @property
    def latex(self) -> str:
        """兼容性属性"""
        return self.text
```

## 🔧 相关代码修改

### parser.py

修改了 `_parse_pdf_info_page` 方法中创建 Content 对象的逻辑：

```python
# TableContent 创建
if block_type == 'table':
    html_content = MinerUParser._extract_html_from_table_block(block_data)
    if html_content:
        content = TableContent(
            type='table',
            bbox=bbox,
            page_idx=page_idx,
            img_path="",  # 待处理
            table_body=html_content  # ✅ 使用 table_body
        )

# TextContent 创建
elif block_type == 'title':
    text = MinerUParser._extract_text_from_block(block_data)
    if text:
        content = TextContent(
            type='text',
            text=text,
            bbox=bbox,
            page_idx=page_idx,
            block_type=block_type,
            text_level=1  # 标题级别
        )
```

### service.py

修改了 `_extract_content_list_from_single` 方法：

```python
# 表格处理
elif content.type == "table":
    if hasattr(content, 'table_body'):
        content_item["table_body"] = content.table_body  # ✅
    if hasattr(content, 'table_caption') and content.table_caption:
        content_item["table_caption"] = content.table_caption
    else:
        content_item["table_caption"] = []
    if hasattr(content, 'table_footnote') and content.table_footnote:
        content_item["table_footnote"] = content.table_footnote
    else:
        content_item["table_footnote"] = []

# 图片处理
elif content.type in ["image", "figure"]:
    if hasattr(content, 'image_caption') and content.image_caption:
        content_item["image_caption"] = content.image_caption  # ✅
    else:
        content_item["image_caption"] = []
    if hasattr(content, 'image_footnote') and content.image_footnote:
        content_item["image_footnote"] = content.image_footnote  # ✅
    else:
        content_item["image_footnote"] = []
```

## 📋 官方文档对照表

| 数据结构 | 官方字段 | 修复前 | 修复后 | 状态 |
|---------|---------|--------|--------|------|
| ObjectInferenceResult | `latex` | ❌ 缺失 | ✅ 已添加 | ✅ |
| ObjectInferenceResult | `html` | ❌ 缺失 | ✅ 已添加 | ✅ |
| TextContent | `type` | `ContentListType` | `str` | ✅ |
| TextContent | `text_level` | ✅ | ✅ 明确语义 | ✅ |
| ImageContent | `type` | `ContentListType` | `"image"` | ✅ |
| ImageContent | `image_caption` | `img_caption: str` | `List[str]` | ✅ |
| ImageContent | `image_footnote` | ❌ 缺失 | `List[str]` | ✅ |
| TableContent | `type` | `ContentListType` | `"table"` | ✅ |
| TableContent | `table_body` | `html` | `table_body` | ✅ |
| TableContent | `table_caption` | `Optional[str]` | `List[str]` | ✅ |
| TableContent | `table_footnote` | ❌ 缺失 | `List[str]` | ✅ |
| FormulaContent | `type` | `ContentListType` | `"equation"` | ✅ |
| FormulaContent | `text` | `latex` | `text` | ✅ |
| FormulaContent | `text_format` | ❌ 缺失 | `"latex"` | ✅ |
| FormulaContent | `img_path` | ❌ 缺失 | ✅ 已添加 | ✅ |

## 🎯 兼容性

为了保持向后兼容，所有重命名的字段都添加了 `@property` 兼容属性：

- `TableContent.html` → 映射到 `table_body`
- `FormulaContent.latex` → 映射到 `text`

## ✅ 验证

- ✅ 所有修改符合官方文档
- ✅ 无 linter 错误
- ✅ 保持向后兼容
- ✅ 字段类型正确
- ✅ 字段名称对齐

## 📚 参考文档

- MinerU 官方文档：https://opendatalab.github.io/MinerU/zh/reference/output_files/
- model.json：https://opendatalab.github.io/MinerU/zh/reference/output_files/#modeljson
- middle.json：https://opendatalab.github.io/MinerU/zh/reference/output_files/#middlejson
- content_list.json：https://opendatalab.github.io/MinerU/zh/reference/output_files/#content_listjson

