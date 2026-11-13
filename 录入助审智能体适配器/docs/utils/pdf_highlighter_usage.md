# PDF高亮工具使用文档

## 简介

`PDFHighlighter` 是一个用于在PDF页面上高亮指定区域的工具模块，主要用于生成提取结果的原文预览图。该工具可以根据MinerU等解析工具提供的坐标信息，在PDF页面上绘制高亮区域，并输出base64编码的图片。

## 主要功能

- ✅ 支持在PDF指定页面的指定坐标区域绘制高亮
- ✅ 支持多种坐标格式（列表、字典、BBox对象）
- ✅ 支持MinerU格式的坐标 `{x, y, width, height}`
- ✅ 支持自定义高亮颜色、边框颜色、透明度
- ✅ 支持自定义DPI，控制输出图片清晰度
- ✅ 输出base64编码的图片，方便前端展示
- ✅ 支持PNG和JPEG两种输出格式

## 快速开始

### 基本用法

```python
from src.utils.pdf_highlighter import highlight_pdf_page

# 定义要高亮的区域（坐标格式：[x0, y0, x1, y1]）
regions = [
    [100, 100, 300, 200],  # 第一个区域
    [150, 250, 350, 350],  # 第二个区域
]

# 生成高亮图片
base64_image = highlight_pdf_page(
    pdf_path="document.pdf",
    page_num=0,  # 第一页（从0开始）
    regions=regions
)

# 可以直接返回给前端使用
# <img src="data:image/png;base64,{base64_image}" />
```

## 坐标格式

### 1. 列表格式 `[x0, y0, x1, y1]`

```python
regions = [
    [100, 100, 300, 200],  # 左上角(100,100)，右下角(300,200)
]
```

### 2. 标准字典格式 `{x0, y0, x1, y1}`

```python
regions = [
    {'x0': 100, 'y0': 100, 'x1': 300, 'y1': 200}
]
```

### 3. 备用字典格式 `{left, top, right, bottom}`

```python
regions = [
    {'left': 100, 'top': 100, 'right': 300, 'bottom': 200}
]
```

### 4. MinerU格式 `{x, y, width, height}`

```python
regions = [
    {'x': 100, 'y': 100, 'width': 200, 'height': 100}
]
```

### 5. BBox对象

```python
from src.utils.pdf_highlighter import BBox

bbox1 = BBox(100, 100, 300, 200)
bbox2 = BBox.from_list([100, 100, 300, 200])
bbox3 = BBox.from_dict({'x': 100, 'y': 100, 'width': 200, 'height': 100})

regions = [bbox1, bbox2, bbox3]
```

## 自定义样式

### 自定义颜色和透明度

```python
base64_image = highlight_pdf_page(
    pdf_path="document.pdf",
    page_num=0,
    regions=regions,
    highlight_color=(255, 0, 0),  # 蓝色高亮（BGR格式）
    border_color=(0, 255, 0),     # 绿色边框（BGR格式）
    alpha=0.5,                     # 透明度（0.0-1.0）
    border_width=3                 # 边框宽度（像素）
)
```

### 颜色参考（BGR格式）

| 颜色 | BGR值 |
|------|-------|
| 黄色 | `(0, 255, 255)` |
| 红色 | `(0, 0, 255)` |
| 绿色 | `(0, 255, 0)` |
| 蓝色 | `(255, 0, 0)` |
| 橙色 | `(0, 165, 255)` |
| 紫色 | `(128, 0, 128)` |

### 自定义DPI和输出格式

```python
base64_image = highlight_pdf_page(
    pdf_path="document.pdf",
    page_num=0,
    regions=regions,
    dpi=300,                  # 高清晰度（默认200）
    output_format='JPEG'      # 输出格式（默认PNG）
)
```

## API参考

### `highlight_pdf_page()`

便捷函数，用于快速高亮PDF页面。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `pdf_path` | `str/Path/bytes` | 必填 | PDF文件路径或字节内容 |
| `page_num` | `int` | 必填 | 页码（从0开始） |
| `regions` | `List` | 必填 | 区域列表 |
| `dpi` | `int` | 200 | 渲染DPI |
| `highlight_color` | `Tuple[int, int, int]` | `(0, 255, 255)` | 高亮颜色（BGR） |
| `border_color` | `Tuple[int, int, int]` | `(0, 0, 255)` | 边框颜色（BGR） |
| `alpha` | `float` | 0.3 | 透明度（0.0-1.0） |
| `border_width` | `int` | 2 | 边框宽度（像素） |
| `output_format` | `str` | 'PNG' | 输出格式（PNG/JPEG） |

**返回：**

- `str`: base64编码的图片字符串

### `PDFHighlighter` 类方法

#### `highlight_pdf_regions()`

完整功能的高亮方法，参数同 `highlight_pdf_page()`。

#### `highlight_single_region()`

单个区域高亮的便捷方法。

```python
from src.utils.pdf_highlighter import PDFHighlighter

base64_image = PDFHighlighter.highlight_single_region(
    pdf_path="document.pdf",
    page_num=0,
    bbox=[100, 100, 300, 200]
)
```

#### `get_page_dimensions()`

获取PDF页面尺寸。

```python
width, height = PDFHighlighter.get_page_dimensions("document.pdf", 0)
print(f"页面尺寸: {width} x {height} 点")
```

## 实际应用场景

### 场景1：提取结果预览

```python
from src.utils.pdf_highlighter import highlight_pdf_page

def generate_extraction_preview(pdf_path, extraction_result):
    """
    为提取结果生成原文预览图
    
    Args:
        pdf_path: PDF文件路径
        extraction_result: 提取结果，包含page和fields
        
    Returns:
        str: base64编码的预览图
    """
    # 提取所有字段的bbox
    bboxes = [field['bbox'] for field in extraction_result['fields']]
    
    # 生成高亮图片
    base64_image = highlight_pdf_page(
        pdf_path=pdf_path,
        page_num=extraction_result['page'],
        regions=bboxes,
        highlight_color=(0, 255, 255),  # 黄色高亮
        border_color=(0, 0, 255),       # 红色边框
        alpha=0.3
    )
    
    return base64_image


# 使用示例
extraction_result = {
    'page': 0,
    'fields': [
        {
            'field_name': '坐落位置',
            'value': '北京市朝阳区xxx路xxx号',
            'bbox': {'x': 100, 'y': 150, 'width': 250, 'height': 30}
        },
        {
            'field_name': '房屋面积',
            'value': '120.5平方米',
            'bbox': {'x': 100, 'y': 200, 'width': 200, 'height': 30}
        }
    ]
}

preview_image = generate_extraction_preview("document.pdf", extraction_result)
```

### 场景2：在API端点中使用

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict
from src.utils.pdf_highlighter import highlight_pdf_page

router = APIRouter()


class HighlightRequest(BaseModel):
    pdf_path: str
    page_num: int
    regions: List[Dict]


class HighlightResponse(BaseModel):
    success: bool
    image_base64: str
    page_dimensions: Dict[str, float]


@router.post("/api/v1/preview/highlight", response_model=HighlightResponse)
async def create_highlight_preview(request: HighlightRequest):
    """
    生成PDF页面高亮预览图
    """
    try:
        # 生成高亮图片
        base64_image = highlight_pdf_page(
            pdf_path=request.pdf_path,
            page_num=request.page_num,
            regions=request.regions
        )
        
        # 获取页面尺寸
        from src.utils.pdf_highlighter import PDFHighlighter
        width, height = PDFHighlighter.get_page_dimensions(
            request.pdf_path,
            request.page_num
        )
        
        return HighlightResponse(
            success=True,
            image_base64=base64_image,
            page_dimensions={'width': width, 'height': height}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### 场景3：批量处理多个字段

```python
def generate_field_previews(pdf_path, fields_by_page):
    """
    为多个页面的字段生成预览图
    
    Args:
        pdf_path: PDF文件路径
        fields_by_page: 按页面分组的字段字典
            {
                0: [field1, field2, ...],
                1: [field3, field4, ...],
                ...
            }
    
    Returns:
        Dict[int, str]: 页码到base64图片的映射
    """
    previews = {}
    
    for page_num, fields in fields_by_page.items():
        # 提取该页面所有字段的bbox
        bboxes = [field['bbox'] for field in fields]
        
        # 生成该页面的高亮图
        base64_image = highlight_pdf_page(
            pdf_path=pdf_path,
            page_num=page_num,
            regions=bboxes
        )
        
        previews[page_num] = base64_image
    
    return previews
```

## 注意事项

1. **坐标系统**：PDF坐标系以页面左上角为原点(0,0)，x轴向右，y轴向下
2. **DPI影响**：DPI越高，生成的图片越清晰，但文件也越大
3. **颜色格式**：使用BGR格式，不是RGB！
4. **透明度范围**：alpha参数范围是0.0到1.0，0为完全透明，1为完全不透明
5. **坐标缩放**：工具会自动根据DPI缩放坐标，无需手动调整
6. **边界处理**：超出页面范围的坐标会被自动裁剪

## 性能优化建议

1. **合理设置DPI**：
   - 预览用途：DPI 150-200 即可
   - 高质量输出：DPI 300
   - 快速处理：DPI 72-100

2. **选择合适的输出格式**：
   - PNG：支持透明度，文件较大，适合web展示
   - JPEG：文件较小，适合存储和传输

3. **批量处理**：
   - 如果需要处理多个页面，可以一次性打开PDF，避免重复打开关闭

## 错误处理

```python
from src.utils.pdf_highlighter import highlight_pdf_page
from src.utils.exceptions import PDFConversionError

try:
    base64_image = highlight_pdf_page(
        pdf_path="document.pdf",
        page_num=0,
        regions=regions
    )
except PDFConversionError as e:
    print(f"PDF处理失败: {e}")
except Exception as e:
    print(f"未知错误: {e}")
```

## 测试

运行单元测试：

```bash
# 运行所有测试
pytest tests/test_pdf_highlighter.py -v

# 运行特定测试
pytest tests/test_pdf_highlighter.py::TestPDFHighlighter::test_highlight_single_region -v

# 查看测试覆盖率
pytest tests/test_pdf_highlighter.py --cov=src.utils.pdf_highlighter --cov-report=html
```

## 依赖

- `PyMuPDF (fitz)`: PDF处理
- `opencv-python (cv2)`: 图像绘制
- `Pillow (PIL)`: 图像处理
- `numpy`: 数组操作

所有依赖已在 `pyproject.toml` 中配置。

## 更新日志

### v1.0.0 (2024-11-03)
- ✅ 初始版本
- ✅ 支持多种坐标格式
- ✅ 支持自定义样式
- ✅ 完整的单元测试覆盖

