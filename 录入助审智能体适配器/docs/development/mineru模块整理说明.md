# MinerU模块整理说明

## 整理概述

对MinerU文档解析服务模块进行了全面整理，删除旧版本文件，统一使用严格按照[MinerU官方文档](https://opendatalab.github.io/MinerU/zh/reference/output_files/)定义的新版本。

## 整理内容

### 删除的文件

1. **src/services/mineru/mineru_client.py** (旧版客户端)
   - 已被 `client.py` 替代
   - 新版客户端更加规范，错误处理更完善

2. **src/services/mineru/models_v2.py** (临时文件)
   - 内容已合并到 `models.py`
   - 避免版本混淆

### 保留的文件

1. **src/services/mineru/models.py** ✅
   - 严格按照MinerU官方文档定义的数据模型
   - 支持pipeline和VLM两种后端
   - 包含完整的类型定义和辅助函数

2. **src/services/mineru/client.py** ✅
   - 新版MinerU API客户端
   - 支持异步调用和自动重试
   - 完善的错误处理和日志记录

3. **src/services/mineru/parser.py** ✅
   - MinerU响应解析器
   - 支持多种响应格式
   - 兼容pipeline和VLM后端

4. **src/services/mineru/__init__.py** ✅
   - 模块导出文件
   - 统一的API接口

## 文件结构

```
src/services/mineru/
├── __init__.py          # 模块导出（统一API）
├── models.py            # 数据模型（官方标准）
├── client.py            # API客户端
└── parser.py            # 响应解析器
```

## 主要改进

### 1. 严格遵循官方文档

所有数据模型都严格按照[MinerU官方文档](https://opendatalab.github.io/MinerU/zh/reference/output_files/)定义：

- **CategoryType**: Pipeline后端的内容类别枚举（官方定义0-15）
- **BlockType**: 块类型（text, title, image, table, code, list等）
- **ContentListType**: 内容列表类型
- **ContentSubType**: 内容子类型（支持code和list的子分类）

### 2. 支持MinerU 2.5版本新特性

- ✅ 支持 `code` 类型（包含code和algorithm子类型）
- ✅ 支持 `list` 类型（包含text和ref_text子类型）
- ✅ 支持废弃内容类型（header, footer, page_number等）

### 3. 坐标系统统一

根据官方文档统一坐标系统：
- 原点：左上角(0, 0)
- X轴：向右为正
- Y轴：向下为正
- 单位：点（1/72英寸）
- 格式：[x0, y0, x1, y1]

支持多种输入格式但内部统一使用 `x0, y0, x1, y1` 格式存储。

### 4. 后端兼容性

- **Pipeline后端**：当前首选，完整支持
- **VLM后端**：数据结构已准备好，易于切换

## 数据模型说明

### 核心模型

1. **BBox** - 边界框坐标类
   ```python
   bbox = BBox(x0=100, y0=100, x1=300, y1=200)
   ```

2. **TextContent** - 文本内容
3. **ImageContent** - 图片内容
4. **TableContent** - 表格内容
5. **FormulaContent** - 公式内容
6. **CodeContent** - 代码内容（新增）
7. **ListContent** - 列表内容（新增）
8. **DiscardedContent** - 废弃内容

### 统一模型

1. **ParsedPage** - 解析的页面
   - 整合 middle.json 和 content_list.json 信息
   - 提供便捷的内容访问方法

2. **ParseResult** - 完整的解析结果
   - 包含所有页面信息
   - 支持文本搜索和内容查询

## 使用方法

### 基本用法

```python
from src.services.mineru import parse_file

# 解析PDF
result = await parse_file(file_path="document.pdf")

if result.success:
    print(f"总页数: {result.total_pages}")
    print(f"后端: {result.backend}")
    
    # 获取所有文本
    all_text = result.get_all_text()
```

### 提取坐标用于高亮

```python
from src.services.mineru import parse_file
from src.utils.pdf_highlighter import highlight_pdf_page

# 解析PDF
result = await parse_file(file_path="document.pdf")

if result.success and result.pages:
    page = result.pages[0]
    text_blocks = page.get_text_blocks()
    
    # 提取坐标
    regions = [block.bbox.to_xywh() for block in text_blocks[:3]]
    
    # 生成高亮图
    base64_image = highlight_pdf_page(
        pdf_path="document.pdf",
        page_num=page.page_num,
        regions=regions
    )
```

## 配置文件

**config/mineru_config.py**

```python
# API配置
MINERU_API_CONFIG = {
    'dev': {
        'base_url': 'http://34.92.192.76:8001',
        'timeout': 300,
        'max_retries': 3,
        'retry_delay': 2,
    }
}

# 解析选项
MINERU_PARSE_OPTIONS = {
    'parse_image_text': True,
    'parse_tables': True,
    'parse_formulas': True,
    'keep_coordinates': True,
}
```

## 测试验证

所有测试通过：

```bash
# 导入测试
poetry run python -c "from src.services.mineru import *; print('导入测试成功')"
# ✅ 成功

# Linter检查
# ✅ 无错误
```

## 文档

详细文档请参考：
- [MinerU使用文档](../services/mineru_usage.md)
- [MinerU官方文档](https://opendatalab.github.io/MinerU/zh/reference/output_files/)
- [配置文件](../../config/mineru_config.py)

## 注意事项

1. **导入路径统一**: 
   - ✅ 正确: `from src.services.mineru import parse_file`
   - ❌ 错误: `from src.services.mineru.mineru_client import ...`

2. **模型导入**:
   - ✅ 正确: `from src.services.mineru import BBox, ParseResult`
   - ❌ 错误: `from src.services.mineru.models_v2 import ...`

3. **后端类型**:
   - 当前使用 `pipeline` 后端
   - 数据结构已为 `vlm` 后端准备好
   - 切换时无需修改业务代码

## 版本历史

### v2.0.0 (2024-11-03) ✅
- 完成模块整理
- 删除旧版文件
- 统一数据模型
- 严格遵循官方文档
- 支持MinerU 2.5新特性

### v1.0.0 (2024-11-03)
- 初始版本
- 基本功能实现

## 后续计划

1. ⬜ 添加更多测试用例
2. ⬜ 完善VLM后端支持
3. ⬜ 添加缓存机制
4. ⬜ 性能优化

## 相关链接

- [MinerU官方文档](https://opendatalab.github.io/MinerU/zh/reference/output_files/)
- [PDF高亮工具](../utils/pdf_highlighter_usage.md)
- [项目README](../../README.md)

