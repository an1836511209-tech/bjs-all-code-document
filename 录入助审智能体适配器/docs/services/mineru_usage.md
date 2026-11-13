# MinerU文档解析服务使用文档

## 概述

MinerU文档解析服务提供了完整的文档解析功能，严格按照[MinerU官方文档](https://opendatalab.github.io/MinerU/zh/reference/output_files/)实现，支持pipeline和VLM两种后端。

## 主要特性

- ✅ 严格按照官方文档定义的数据结构
- ✅ 支持pipeline后端（当前首选）
- ✅ 为VLM后端做好准备，易于切换
- ✅ 支持多种文件格式（PDF、Word、图片等）
- ✅ 完整的类型定义和数据模型
- ✅ 自动重试和错误处理
- ✅ 异步API调用
- ✅ 详细的日志记录

## 快速开始

### 1. 基本用法

```python
from src.services.mineru import parse_file

# 解析PDF文件
result = await parse_file(file_path="document.pdf")

if result.success:
    print(f"解析成功，总页数: {result.total_pages}")
    print(f"后端类型: {result.backend}")  # pipeline 或 vlm
    
    # 遍历页面
    for page in result.pages:
        print(f"页面 {page.page_num + 1}:")
        print(f"  尺寸: {page.width} x {page.height}")
        print(f"  内容块数: {len(page.contents)}")
else:
    print(f"解析失败: {result.error_message}")
```

### 2. 使用客户端对象

```python
from src.services.mineru import MinerUClient

async with MinerUClient(env='dev') as client:
    result = await client.parse_file(file_path="document.pdf")
    
    if result.success:
        # 处理结果
        all_text = result.get_all_text()
        print(all_text)
```

### 3. 解析字节内容

```python
from src.services.mineru import parse_file

# 从内存解析
with open("document.pdf", "rb") as f:
    file_content = f.read()

result = await parse_file(
    file_content=file_content,
    file_name="document.pdf"
)
```

## 配置说明

### API配置

配置文件：`config/mineru_config.py`

```python
# 开发环境配置
MINERU_API_CONFIG = {
    'dev': {
        'base_url': 'http://34.92.192.76:8001',
        'timeout': 300,  # 超时时间（秒）
        'max_retries': 3,  # 最大重试次数
        'retry_delay': 2,  # 重试延迟（秒）
    }
}

# 当前环境
CURRENT_ENV = 'dev'  # 从环境变量读取
```

### 解析选项

```python
MINERU_PARSE_OPTIONS = {
    'parse_image_text': True,   # 解析图片中的文字
    'parse_tables': True,       # 解析表格
    'parse_formulas': True,     # 解析公式
    'output_format': 'json',    # 输出格式
    'keep_coordinates': True,   # 保留坐标信息
    'return_layout': True,      # 返回布局信息
}
```

### 自定义选项

```python
result = await parse_file(
    file_path="document.pdf",
    options={
        'parse_tables': True,
        'parse_formulas': False,  # 不解析公式
    }
)
```

## 数据模型

### 1. 坐标模型（BBox）

```python
from src.services.mineru import BBox, parse_bbox_from_any

# 创建BBox
bbox = BBox(100, 100, 300, 200)  # x0, y0, x1, y1

# 从列表创建
bbox = BBox.from_list([100, 100, 300, 200])

# 从字典创建（支持多种格式）
bbox = BBox.from_dict({'x0': 100, 'y0': 100, 'x1': 300, 'y1': 200})
bbox = BBox.from_dict({'x': 100, 'y': 100, 'width': 200, 'height': 100})

# 从任意格式解析
bbox = parse_bbox_from_any([100, 100, 300, 200])
bbox = parse_bbox_from_any({'x': 100, 'y': 100, 'width': 200, 'height': 100})

# 属性
print(bbox.width)   # 宽度
print(bbox.height)  # 高度
print(bbox.area)    # 面积
print(bbox.center)  # 中心点

# 转换
bbox_list = bbox.to_list()    # [x0, y0, x1, y1]
bbox_dict = bbox.to_dict()    # {'x0': ..., 'y0': ..., ...}
bbox_xywh = bbox.to_xywh()    # {'x': ..., 'y': ..., 'width': ..., 'height': ...}
```

### 2. 内容类型

根据[MinerU官方文档](https://opendatalab.github.io/MinerU/zh/reference/output_files/#content_listjson)，支持以下内容类型：

#### TextContent（文本）

```python
from src.services.mineru import TextContent, ContentListType, BBox

text = TextContent(
    type=ContentListType.TEXT,
    text="这是一段文本",
    bbox=BBox(100, 100, 300, 200),
    page_idx=0
)
```

#### ImageContent（图片）

```python
from src.services.mineru import ImageContent

image = ImageContent(
    type=ContentListType.IMAGE,
    img_path="images/image_0.png",
    img_caption="图1：示例图片",
    bbox=BBox(100, 300, 400, 500),
    page_idx=0
)
```

#### TableContent（表格）

```python
from src.services.mineru import TableContent

table = TableContent(
    type=ContentListType.TABLE,
    img_path="tables/table_0.png",
    table_caption="表1：数据统计",
    bbox=BBox(100, 600, 500, 800),
    page_idx=0
)
```

#### FormulaContent（公式）

```python
from src.services.mineru import FormulaContent

formula = FormulaContent(
    type=ContentListType.INTERLINE_EQUATION,
    latex="E = mc^2",
    bbox=BBox(200, 400, 350, 450),
    page_idx=0
)
```

#### CodeContent（代码）

根据[MinerU 2.5版本](https://opendatalab.github.io/MinerU/zh/reference/output_files/#_22)新增的代码类型：

```python
from src.services.mineru import CodeContent, ContentSubType

# 普通代码
code = CodeContent(
    type=ContentListType.CODE,
    sub_type=ContentSubType.CODE,
    code_body="def hello():\n    print('Hello')",
    code_caption="代码清单1",
    bbox=BBox(100, 100, 500, 300),
    page_idx=0
)

# 算法代码
algorithm = CodeContent(
    type=ContentListType.CODE,
    sub_type=ContentSubType.ALGORITHM,
    code_body="Algorithm 1: Example",
    code_caption="算法1：示例算法",
    bbox=BBox(100, 100, 500, 400),
    page_idx=0
)
```

#### ListContent（列表）

根据[MinerU 2.5版本](https://opendatalab.github.io/MinerU/zh/reference/output_files/#_22)新增的列表类型：

```python
from src.services.mineru import ListContent

list_content = ListContent(
    type=ContentListType.LIST,
    sub_type=ContentSubType.TEXT,
    list_items=["项目1", "项目2", "项目3"],
    bbox=BBox(100, 100, 300, 200),
    page_idx=0
)
```

#### DiscardedContent（废弃内容）

包括页眉、页脚、页码等：

```python
from src.services.mineru import DiscardedContent

header = DiscardedContent(
    type=ContentListType.HEADER,
    text="第一章 引言",
    bbox=BBox(100, 50, 500, 80),
    page_idx=0
)
```

### 3. 枚举类型

#### CategoryType（Pipeline后端）

```python
from src.services.mineru import CategoryType

# 官方定义的类别
CategoryType.TITLE              # 0 - 标题
CategoryType.PLAIN_TEXT         # 1 - 文本
CategoryType.ABANDON            # 2 - 页眉页脚页码
CategoryType.FIGURE             # 3 - 图片
CategoryType.FIGURE_CAPTION     # 4 - 图片描述
CategoryType.TABLE              # 5 - 表格
CategoryType.TABLE_CAPTION      # 6 - 表格描述
CategoryType.TABLE_FOOTNOTE     # 7 - 表格注释
CategoryType.ISOLATE_FORMULA    # 8 - 行间公式
CategoryType.FORMULA_CAPTION    # 9 - 公式标号
CategoryType.EMBEDDING          # 13 - 行内公式
CategoryType.ISOLATED           # 14 - 行间公式
CategoryType.TEXT               # 15 - OCR结果
```

#### ContentListType（内容列表类型）

```python
from src.services.mineru import ContentListType

ContentListType.TEXT                # 文本
ContentListType.IMAGE               # 图片
ContentListType.TABLE               # 表格
ContentListType.INTERLINE_EQUATION  # 行间公式
ContentListType.CODE                # 代码
ContentListType.LIST                # 列表
ContentListType.HEADER              # 页眉
ContentListType.FOOTER              # 页脚
ContentListType.PAGE_NUMBER         # 页码
```

## 使用示例

### 示例1：提取所有文本

```python
from src.services.mineru import parse_file

result = await parse_file(file_path="document.pdf")

if result.success:
    # 获取所有文本
    all_text = result.get_all_text()
    print(all_text)
    
    # 获取每页文本
    for page in result.pages:
        page_text = page.get_all_text()
        print(f"页面 {page.page_num + 1}:\n{page_text}\n")
```

### 示例2：搜索关键词

```python
result = await parse_file(file_path="document.pdf")

if result.success:
    # 搜索关键词
    search_results = result.search_text("关键词")
    
    print(f"找到 {len(search_results)} 个匹配")
    for page_num, content in search_results:
        print(f"页面 {page_num + 1}:")
        if hasattr(content, 'text'):
            print(f"  文本: {content.text}")
        if hasattr(content, 'bbox'):
            print(f"  位置: {content.bbox.to_dict()}")
```

### 示例3：按类型获取内容

```python
from src.services.mineru import ContentListType

result = await parse_file(file_path="document.pdf")

if result.success:
    for page in result.pages:
        # 获取文本块
        texts = page.get_text_blocks()
        print(f"页面 {page.page_num + 1} 文本块数: {len(texts)}")
        
        # 获取图片
        images = page.get_image_blocks()
        print(f"  图片数: {len(images)}")
        
        # 获取表格
        tables = page.get_table_blocks()
        print(f"  表格数: {len(tables)}")
        
        # 按类型获取
        codes = page.get_contents_by_type(ContentListType.CODE)
        print(f"  代码块数: {len(codes)}")
```

### 示例4：提取坐标用于高亮

```python
from src.services.mineru import parse_file
from src.utils.pdf_highlighter import highlight_pdf_page

# 解析PDF
result = await parse_file(file_path="document.pdf")

if result.success and result.pages:
    # 获取第一页的所有文本块坐标
    page = result.pages[0]
    text_blocks = page.get_text_blocks()
    
    # 提取坐标（前3个）
    regions = [block.bbox.to_xywh() for block in text_blocks[:3]]
    
    # 生成高亮预览图
    base64_image = highlight_pdf_page(
        pdf_path="document.pdf",
        page_num=page.page_num,
        regions=regions,
        highlight_color=(0, 255, 255),  # 黄色
        border_color=(0, 0, 255),       # 红色
        alpha=0.3
    )
    
    print(f"高亮图生成成功，长度: {len(base64_image)}")
```

### 示例5：处理代码块

```python
from src.services.mineru import ContentListType

result = await parse_file(file_path="document.pdf")

if result.success:
    for page in result.pages:
        # 获取代码块
        codes = page.get_contents_by_type(ContentListType.CODE)
        
        for code in codes:
            print(f"代码类型: {code.sub_type}")
            print(f"标题: {code.code_caption or '无'}")
            print(f"内容:\n{code.code_body}")
            print(f"位置: {code.bbox.to_dict() if code.bbox else '无'}")
            print("-" * 60)
```

### 示例6：提取表格和图片

```python
result = await parse_file(file_path="document.pdf")

if result.success:
    for page in result.pages:
        # 提取图片
        images = page.get_image_blocks()
        for img in images:
            print(f"图片: {img.img_path}")
            print(f"  说明: {img.img_caption or '无'}")
            print(f"  位置: {img.bbox.to_dict() if img.bbox else '无'}")
        
        # 提取表格
        tables = page.get_table_blocks()
        for table in tables:
            print(f"表格: {table.img_path}")
            print(f"  说明: {table.table_caption or '无'}")
            print(f"  位置: {table.bbox.to_dict() if table.bbox else '无'}")
```

## 高级用法

### 1. 自定义解析器

```python
from src.services.mineru import MinerUParser

parser = MinerUParser()

# 直接解析API响应
api_response = {...}  # 从API获取的响应
result = parser.parse_response(api_response, "document.pdf", ".pdf")
```

### 2. 环境切换

```python
from src.services.mineru import MinerUClient

# 使用生产环境
async with MinerUClient(env='prod') as client:
    result = await client.parse_file(file_path="document.pdf")
```

### 3. 错误处理

```python
from src.services.mineru import parse_file, MinerUError

try:
    result = await parse_file(file_path="document.pdf")
    
    if not result.success:
        print(f"解析失败: {result.error_message}")
        # 处理失败情况
    else:
        # 处理成功情况
        pass
        
except MinerUError as e:
    print(f"MinerU错误: {e}")
except Exception as e:
    print(f"未知错误: {e}")
```

## API参考

### parse_file()

便捷函数，用于快速解析文件。

**参数:**

| 参数 | 类型 | 说明 |
|------|------|------|
| `file_path` | `str/Path` | 文件路径 |
| `file_content` | `bytes` | 文件字节内容 |
| `file_name` | `str` | 文件名 |
| `options` | `dict` | 解析选项 |
| `env` | `str` | 环境名称 |

**返回:** `ParseResult`

### MinerUClient

MinerU API客户端类。

**方法:**

- `__init__(env: str = None)`: 初始化客户端
- `async parse_file(...)`: 解析文件
- `async close()`: 关闭客户端

## 坐标系统说明

根据[MinerU官方文档](https://opendatalab.github.io/MinerU/zh/reference/output_files/#_7)：

- **原点**: 左上角(0, 0)
- **X轴**: 向右为正
- **Y轴**: 向下为正
- **单位**: 点（1/72英寸）
- **格式**: `[x0, y0, x1, y1]` 左上角和右下角坐标

## 后端兼容性

### Pipeline后端（当前首选）

- 完整支持所有内容类型
- 支持代码块（code）和列表（list）
- 支持废弃内容（页眉、页脚等）

### VLM后端（未来切换）

- 数据结构已为VLM后端做好准备
- 切换时只需更新配置，代码无需改动
- 详见[官方文档](https://opendatalab.github.io/MinerU/zh/reference/output_files/#vlm)

## 注意事项

1. **API超时**: 文档解析可能较慢，默认超时300秒
2. **重试机制**: 自动重试3次，每次间隔2秒
3. **坐标格式**: 始终使用`[x0, y0, x1, y1]`格式存储，但支持多种输入格式
4. **内容类型**: 2.5版本新增code和list类型
5. **废弃内容**: 页眉、页脚等内容会被标记为discarded

## 性能优化

1. **使用异步**: 所有API调用都是异步的
2. **批量处理**: 如需处理多个文件，可并发调用
3. **缓存**: 可在配置中启用缓存功能

## 测试

```bash
# 运行所有测试
pytest tests/test_mineru_client.py -v

# 运行特定测试
pytest tests/test_mineru_client.py::TestBBox -v
```

## 更新日志

### v2.0.0 (2024-11-03)
- ✅ 严格按照[MinerU官方文档](https://opendatalab.github.io/MinerU/zh/reference/output_files/)重构
- ✅ 支持pipeline后端所有功能
- ✅ 为VLM后端做好准备
- ✅ 支持新增的code和list类型
- ✅ 完整的类型定义和数据模型

## 相关文档

- [MinerU官方文档](https://opendatalab.github.io/MinerU/zh/reference/output_files/)
- [PDF高亮工具文档](../utils/pdf_highlighter_usage.md)
- [API配置文档](../../config/mineru_config.py)

