# Excel 提取溯源设计文档

**日期:** 2026-07-18
**状态:** 已实现
**目标:** 为 Excel 文件新增单元格级别的提取溯源能力，支持锚点定位和高亮预览

---

## 1. 背景与问题

当前 Excel 文件（`.xlsx`, `.xlsm`）的提取流程存在以下问题：

- **无单元格级解析：** Excel 文件仅通过 Tika 提取纯文本，丢失了单元格位置信息
- **无锚点生成：** 整个文档被当作一个文本块，生成一个 dummy anchor，无法定位到具体单元格
- **无高亮预览：** `is_text_only=True` 标记导致溯源和高亮生成被完全跳过
- **无 segment_map：** 没有单元格级别的坐标映射，无法实现溯源

**现有架构参考：**
- `src/utils/anchor_markdown_converter.py` — PDF/图片的锚点 Markdown 转换器
- `src/services/extraction/service.py` — 提取服务主流程
- `src/utils/pdf_highlighter.py` — PDF 高亮渲染器
- `src/services/llm/models.py` — `Region`, `UnifiedExtractionResult` 模型
- `src/schemas/extraction.py` — `SourceInfo`, `RegionInfo` 模型

---

## 2. 设计方案

### 2.1 锚点格式

采用 Sheet 索引格式 `(¶S-R-C)`，与现有 PDF 锚点风格 `(¶P-ID)` 一致：

| 字段 | 含义 | 示例 |
|------|------|------|
| S | Sheet 索引（0-based） | `0` |
| R | 行号（0-based） | `1` |
| C | 列号（0-based） | `2` |

**示例：**
```
办公楼A (¶0-1-0) | 1200万 (¶0-1-1) | 已抵押 (¶0-1-2)
```

**选择理由：**
- 与现有 `(¶P-ID)` 格式风格一致，LLM 无需额外学习
- 索引比名称更可靠（避免中文/特殊字符导致的解析问题）
- 解析简单，split("-") 即可

### 2.2 空单元格处理

只给有值的单元格生成锚点。理由：
- 减少锚点数量，提高 LLM 处理效率
- LLM 只会引用有数据的单元格
- 空单元格无提取价值

### 2.3 合并单元格处理

合并单元格作为整体一个锚点：
- anchor_id 指向合并区域的左上角单元格坐标
- bbox 覆盖整个合并区域
- text 取合并区域左上角单元格的值

### 2.4 高亮方案

采用方案 A：服务端渲染单元格高亮 PNG
- 用 openpyxl 读取 Excel 样式（列宽、行高）
- 用 PIL/Pillow 将目标 sheet 渲染为 PNG
- 在对应单元格画黄色半透明底色 + 红色边框
- 上传 MinIO，返回 `preview_image_url`
- 与现有 API 结构完全兼容

---

## 3. 新增模块

### 3.1 `ExcelAnchorConverter` — Excel 锚点转换器

**文件：** `src/utils/excel_anchor_converter.py`

**职责：** 用 openpyxl 遍历 Excel 单元格，生成 Anchor Markdown + segment_map

**类设计：**

```python
class ExcelAnchorConverter:
    """Excel 锚点 Markdown 转换器"""
    
    ANCHOR_SYMBOL = "¶"
    
    @classmethod
    def convert(
        cls,
        file_bytes: bytes,
        file_name: str
    ) -> Tuple[str, Dict[str, SegmentInfo], int]:
        """
        解析 Excel 文件，生成带锚点的 Markdown 和 segment_map
        
        Args:
            file_bytes: Excel 文件字节内容
            file_name: 文件名
            
        Returns:
            Tuple[str, Dict[str, SegmentInfo], int]:
                - 带锚点的 Markdown 文本（给 LLM）
                - segment_map {anchor_id: SegmentInfo}
                - sheet_count（sheet 数量）
        """
```

**处理流程：**

1. 用 `openpyxl.load_workbook()` 打开 Excel（`data_only=True` 获取计算后的值）
2. 遍历每个 sheet：
   - 记录 sheet 标题（`# Sheet: Sheet1`）
   - 收集合并单元格范围（`sheet.merged_cells.ranges`）
   - 遍历每个有值的单元格：
     - 跳过空单元格
     - 生成 anchor_id: `f"{sheet_idx}-{row}-{col}"`
     - 计算 bbox（像素坐标，基于列宽和行高）
     - 创建 `SegmentInfo` 存入 segment_map
     - 在 Markdown 中追加 `(¶S-R-C)` 锚点标记
3. 表格以 Markdown 表格格式输出（与现有 Anchor Markdown 风格一致）

**Anchor Markdown 输出格式：**

```markdown
# Sheet: Sheet1

| 资产名称 | 评估价值 | 备注 |
|---------|---------|------|
| 办公楼A (¶0-0-0) | 1200万 (¶0-0-1) | 已抵押 (¶0-0-2) |
| 厂房B (¶0-1-0) | 800万 (¶0-1-1) | 无 (¶0-1-2) |

# Sheet: 汇总表

| 项目 | 合计 |
|-----|-----|
| 总价值 (¶1-0-0) | 2000万 (¶1-0-1) |
```

**SegmentInfo 映射：**

| 字段 | 值 | 说明 |
|------|-----|------|
| `anchor_id` | `"0-0-0"` | sheet_idx-row-col |
| `page_idx` | `0` | 复用 page_idx 字段存储 sheet_idx |
| `bbox` | `[x0, y0, x1, y1]` | 单元格像素坐标 |
| `text` | `"办公楼A"` | 单元格文本内容 |
| `segment_type` | `"excel_cell"` | 新增类型，区分于 text/table |
| `score` | `None` | 无需置信度 |
| `cells` | `None` | 无需子单元格 |

**合并单元格处理逻辑：**

```python
# 收集合并单元格信息
merged_ranges = {}
for merged_range in sheet.merged_cells.ranges:
    min_row, min_col = merged_range.min_row - 1, merged_range.min_col - 1
    max_row, max_col = merged_range.max_row - 1, merged_range.max_col - 1
    # 遍历合并区域内的所有单元格，映射到左上角
    for r in range(min_row, max_row + 1):
        for c in range(min_col, max_col + 1):
            merged_ranges[(r, c)] = (min_row, min_col, max_row, max_col)

# 遍历单元格时检查是否在合并区域内
if (row, col) in merged_ranges:
    # 跳过非左上角的合并单元格
    if (row, col) != (merged_ranges[(row, col)][0], merged_ranges[(row, col)][1]):
        continue
    # bbox 覆盖整个合并区域
    min_r, min_c, max_r, max_c = merged_ranges[(row, col)]
    bbox = calculate_merged_bbox(min_r, min_c, max_r, max_c)
```

**坐标计算：**

```python
def _calculate_cell_bbox(cls, sheet, row, col) -> List[float]:
    """计算单元格的像素坐标 [x0, y0, x1, y1]"""
    # 列宽：openpyxl 的 width 是字符单位，约 width * 7 像素
    x0 = sum(
        (sheet.column_dimensions[get_column_letter(c + 1)].width or 8.43) * 7
        for c in range(col)
    )
    col_width = (sheet.column_dimensions[get_column_letter(col + 1)].width or 8.43) * 7
    x1 = x0 + col_width
    
    # 行高：openpyxl 的 height 是磅，1磅 = 96/72 像素
    y0 = sum(
        (sheet.row_dimensions[r + 1].height or 15) * 96 / 72
        for r in range(row)
    )
    row_height = (sheet.row_dimensions[row + 1].height or 15) * 96 / 72
    y1 = y0 + row_height
    
    return [x0, y0, x1, y1]
```

---

### 3.2 `ExcelCellHighlighter` — Excel 单元格高亮渲染器

**文件：** `src/utils/excel_cell_highlighter.py`

**职责：** 将 Excel sheet 渲染为 PNG 图片，并在指定单元格画高亮

**类设计：**

```python
class ExcelCellHighlighter:
    """Excel 单元格高亮渲染器"""
    
    # 高亮样式（与现有 PDF 高亮器一致）
    HIGHLIGHT_COLOR = (255, 255, 0)   # 黄色 (RGB)
    BORDER_COLOR = (255, 0, 0)        # 红色 (RGB)
    ALPHA = 0.3                       # 透明度
    BORDER_WIDTH = 2                  # 边框宽度
    
    # 渲染参数
    DEFAULT_DPI = 150                 # 渲染 DPI
    MAX_WIDTH = 2000                  # 最大渲染宽度（像素）
    MAX_HEIGHT = 3000                 # 最大渲染高度（像素）
    
    @classmethod
    def render_highlight(
        cls,
        file_bytes: bytes,
        sheet_idx: int,
        target_bboxes: List[List[float]],
    ) -> bytes:
        """
        渲染指定 sheet 为 PNG 图片，并在 target_bboxes 位置画高亮
        
        Args:
            file_bytes: Excel 文件字节内容
            sheet_idx: Sheet 索引（0-based）
            target_bboxes: 需要高亮的单元格坐标列表 [[x0,y0,x1,y1], ...]
            
        Returns:
            PNG 图片字节
        """
```

**渲染流程：**

1. 用 openpyxl 打开 Excel，获取指定 sheet
2. **裁剪渲染范围：** 不渲染整个 sheet，只渲染目标单元格周围 ±5 行/±3 列的区域（避免大表性能问题）
3. 计算裁剪区域的像素尺寸
4. 用 PIL 创建白色画布
5. 绘制表格：
   - 网格线（浅灰色）
   - 单元格文本（黑色，左对齐，使用系统中文字体如 SimHei/Microsoft YaHei）
   - 表头行加粗/灰色底色（可选）
6. 在 target_bboxes 位置绘制高亮（坐标需减去裁剪偏移量）：
   - 先画黄色半透明矩形（`ImageDraw.rectangle` + alpha 混合）
   - 再画红色边框
7. 如果图片超过 MAX_WIDTH/MAX_HEIGHT，按比例缩放
8. 输出 PNG 字节

**PIL 渲染核心逻辑：**

```python
# 创建画布
img = Image.new('RGB', (canvas_width, canvas_height), 'white')
draw = ImageDraw.Draw(img)

# 绘制网格线
for x in column_positions:
    draw.line([(x, 0), (x, canvas_height)], fill='#CCCCCC', width=1)
for y in row_positions:
    draw.line([(0, y), (canvas_width, y)], fill='#CCCCCC', width=1)

# 绘制单元格文本
for row in sheet.iter_rows():
    for cell in row:
        if cell.value is not None:
            x, y = get_cell_position(cell.row, cell.column)
            draw.text((x + 2, y + 2), str(cell.value), fill='black')

# 绘制高亮（alpha 混合）
highlight_layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
highlight_draw = ImageDraw.Draw(highlight_layer)
for bbox in target_bboxes:
    x0, y0, x1, y1 = bbox
    # 半透明黄色填充
    highlight_draw.rectangle([x0, y0, x1, y1], fill=(255, 255, 0, 77))  # 0.3 * 255 ≈ 77
    # 红色边框
    highlight_draw.rectangle([x0, y0, x1, y1], outline=(255, 0, 0), width=2)

# 合并高亮层
img = Image.alpha_composite(img.convert('RGBA'), highlight_layer)
img = img.convert('RGB')
```

**与现有高亮器的一致性：**

| 属性 | PDFHighlighter | ExcelCellHighlighter |
|------|---------------|---------------------|
| 高亮颜色 | 黄色 (BGR: 0,255,255) | 黄色 (RGB: 255,255,0) |
| 边框颜色 | 红色 (BGR: 0,0,255) | 红色 (RGB: 255,0,0) |
| 透明度 | 0.3 | 0.3 |
| 输出格式 | PNG/JPEG | PNG |
| 上传方式 | MinIO | MinIO（复用） |

---

## 4. 集成改动

### 4.1 ExtractionService._parse_files() — Excel 分支

**文件：** `src/services/extraction/service.py`

**改动位置：** `_parse_files()` 方法，约第 1426 行

**改动内容：** 在现有的 `is_text_document_format` 分支之前，新增 Excel 专用分支：

```python
# 新增：Excel 文件走 openpyxl + Anchor Markdown 路径（支持溯源）
if file_extension in FileHandler.SUPPORTED_EXCEL_FORMATS:
    logger.info(f"检测到 Excel 格式: {file_extension}，使用 openpyxl 提取（支持溯源）")
    
    file_content = await get_file_content()
    
    # 用 ExcelAnchorConverter 生成 Anchor Markdown + segment_map
    from src.utils.excel_anchor_converter import ExcelAnchorConverter
    anchor_markdown, segment_map, sheet_count = ExcelAnchorConverter.convert(
        file_content, file_input.file_name
    )
    
    # 构建模拟的 parse_result（兼容现有流程）
    parse_result = self._create_excel_parse_result(
        anchor_markdown=anchor_markdown,
        segment_map=segment_map,
        file_name=file_input.file_name,
        sheet_count=sheet_count,
    )
    
    # 注意：Excel 需要将 file_bytes 存入 parsed_files，供高亮渲染使用
    # 在调用方中，file_data['file_bytes'] = file_content
    return parse_result, None  # Excel 不需要 PDF 文件
```

**注意：** 此分支需放在 `is_text_document_format` 检查之前，因为 `.xlsx` 同时属于 `SUPPORTED_TEXT_DOCUMENT_FORMATS` 和 `SUPPORTED_EXCEL_FORMATS`。优先走新的溯源路径。

### 4.2 _create_excel_parse_result() — 新增方法

**文件：** `src/services/extraction/service.py`

```python
def _create_excel_parse_result(
    self,
    anchor_markdown: str,
    segment_map: Dict[str, Any],
    file_name: str,
    sheet_count: int,
) -> Any:
    """为 Excel 文件创建解析结果对象（支持溯源）"""
    from types import SimpleNamespace
    
    # 创建模拟的 layout_block
    mock_layout_block = SimpleNamespace(
        bbox=SimpleNamespace(x0=0, y0=0, x1=100, y1=100),
        category_type="text",
        lines=[SimpleNamespace(spans=[SimpleNamespace(text=anchor_markdown)])]
    )
    
    # 创建模拟的 page（一个 sheet 对应一个 page）
    mock_page = SimpleNamespace(
        page_num=0,
        text=anchor_markdown,
        width=0,
        height=0,
        contents=[SimpleNamespace(type="text", text=anchor_markdown)],
        layout_blocks=[mock_layout_block],
    )
    
    # 创建 parse_result
    parse_result = SimpleNamespace(
        pages=[mock_page],
        file_name=file_name,
        total_pages=sheet_count,
        # 关键：不标记为 text_only，这样会走溯源流程
        is_text_only=False,
        # 标记为 Excel，高亮时路由到 Excel 高亮器
        is_excel=True,
        # 存储 segment_map 供后续查表
        excel_segment_map=segment_map,
        raw_text=anchor_markdown,
        md_content=anchor_markdown,
    )
    
    return parse_result
```

### 4.3 _batch_generate_highlights() — Excel 高亮路由

**文件：** `src/services/extraction/service.py`

**改动位置：** `_batch_generate_highlights()` 方法，约第 4352 行

**改动内容：** 在高亮生成逻辑中检测 `is_excel` 标记，路由到 Excel 高亮器：

```python
# 在 generate_highlight_image_only() 函数内部
# 检测是否为 Excel 文件
is_excel = getattr(file_data.get('parse_results', [None])[0], 'is_excel', False)

if is_excel:
    # 使用 Excel 高亮器
    from src.utils.excel_cell_highlighter import ExcelCellHighlighter
    file_bytes = file_data.get('file_bytes')
    sheet_idx = task_info['regions'][0].page_idx  # page_idx 复用为 sheet_idx
    target_bboxes = [r.bbox for r in task_info['regions']]
    
    image_bytes = ExcelCellHighlighter.render_highlight(
        file_bytes=file_bytes,
        sheet_idx=sheet_idx,
        target_bboxes=target_bboxes,
    )
else:
    # 现有 PDF 高亮逻辑（不变）
    ...
```

### 4.4 Anchor 查表兼容性

**无需修改 `AnchorMarkdownConverter`。**

原因：
- `lookup_bboxes_by_anchors()` 方法接收 `segment_map: Dict[str, SegmentInfo]` 参数
- Excel 的 segment_map 结构完全兼容（key 是 anchor_id 字符串，value 是 SegmentInfo）
- 只需在 Excel 路径中传入自建的 segment_map 即可

在提取流程中，Excel 的 segment_map 需要从 `parse_result.excel_segment_map` 传递到查表逻辑。具体实现在 `_trace_source_with_anchor()` 或类似方法中，检查 `is_excel` 标记并使用 `excel_segment_map`。

---

## 5. 不改动的部分

以下模块**完全保留**，不做任何修改：

- `src/utils/anchor_markdown_converter.py` — PDF/图片的锚点转换器，逻辑不变
- `src/utils/pdf_highlighter.py` — PDF 高亮器，逻辑不变
- `src/utils/paddle_pdf_highlighter.py` — Paddle 高亮器，逻辑不变
- `src/services/llm/client.py` — `UnifiedExtractionAgent`，它只看到锚点文本，格式变化对它透明
- `src/services/llm/models.py` — `Region`, `UnifiedExtractionResult` 模型，结构不变
- `src/schemas/extraction.py` — `SourceInfo`, `RegionInfo` 模型，结构不变

旧的 Tika 文本提取路径也**完全保留**，作为不支持溯源的回退方案。`SUPPORTED_TEXT_DOCUMENT_FORMATS` 中的 `.xlsx` 条件保留，但在 `_parse_files()` 中 Excel 优先走新路径。

---

## 6. 数据流总览

```
Excel 文件上传
    │
    ▼
_parse_files() 检测到 .xlsx
    │
    ▼
ExcelAnchorConverter.convert(file_bytes, file_name)
    │
    ├── 1. openpyxl 遍历单元格
    ├── 2. 生成 Anchor Markdown: "| 办公楼A (¶0-0-0) | 1200万 (¶0-0-1) |"
    ├── 3. 构建 segment_map: {"0-0-0": SegmentInfo(...), "0-0-1": SegmentInfo(...)}
    │
    ▼
_create_excel_parse_result(anchor_markdown, segment_map, ...)
    │  is_text_only=False, is_excel=True, excel_segment_map=segment_map
    │
    ▼
UnifiedExtractionAgent.extract_and_trace(file_content=anchor_markdown, ...)
    │  LLM 返回: {"extracted_value": "1200万", "anchor_ids": ["0-0-1"]}
    │
    ▼
lookup_bboxes_by_anchors(anchor_ids, segment_map=excel_segment_map)
    │  返回: [Region(page_idx=0, bbox=[x0,y0,x1,y1])]
    │
    ▼
SourceInfo 构建
    │  page_number = sheet_idx + 1
    │  coordinates = {x, y, width, height}
    │
    ▼
_batch_generate_highlights() 检测 is_excel
    │
    ▼
ExcelCellHighlighter.render_highlight(file_bytes, sheet_idx, bboxes)
    │  PIL 渲染 sheet + 高亮单元格 → PNG 字节
    │
    ▼
上传 MinIO → preview_image_url
```

---

## 7. 依赖

| 依赖 | 版本 | 用途 | 状态 |
|------|------|------|------|
| openpyxl | 已有 | Excel 解析、单元格遍历 | ✅ 已安装 |
| Pillow (PIL) | 已有 | 图片渲染 | ✅ 已安装（pdf_highlighter 已用） |
| loguru | 已有 | 日志 | ✅ 已安装 |

**无需新增任何依赖。**

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 大 Excel 文件（>1000行）渲染性能慢 | 高亮生成超时 | 限制渲染范围：只渲染目标单元格周围区域，而非整个 sheet |
| 合并单元格嵌套/复杂格式 | 坐标计算错误 | 使用 openpyxl 的 merged_cells.ranges，只处理一级合并 |
| 列宽/行高自定义值不准确 | 高亮位置偏移 | 提供 fallback 默认值（列宽 8.43 字符，行高 15 磅） |
| LLM 拼错锚点 ID | 溯源失败 | 锚点 ID 为纯数字，解析容错（strip、split） |
| Excel 中有图表/图片 | 无法提取 | 只处理单元格数据，图表/图片忽略 |

---

## 9. 测试要点

1. **基本功能：** 单 sheet Excel，验证锚点生成、LLM 提取、高亮渲染
2. **多 sheet：** 多个 sheet 的 Excel，验证 sheet 分离和锚点前缀
3. **合并单元格：** 有合并单元格的 Excel，验证 bbox 覆盖整个合并区域
4. **空单元格：** 大量空单元格的 Excel，验证只生成有值单元格的锚点
5. **大文件：** 100+ 行的 Excel，验证渲染性能
6. **中文内容：** 中文 sheet 名和单元格内容，验证编码正确
7. **与现有流程兼容：** 确认 PDF/图片提取不受影响
