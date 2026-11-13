# 跨页表格智能处理 - 图片合并方案

## 问题背景

在文档解析中，表格经常会跨页显示。MinerU 在处理跨页表格时会：
1. **将表格内容合并到第一页**：完整的 HTML 内容存储在起始页
2. **标记延续页**：后续页只保留 bbox 坐标，但 `lines_deleted: true`，内容为空

这导致在溯源和高亮时出现问题：
- 如果溯源结果定位到延续页（第 4 页），但实际内容在起始页（第 3 页）
- 只高亮起始页会让用户误以为延续页没有相关内容
- 用户体验不佳

## 解决方案：后端图片合并

### 1. 解析器标记跨页表格

在 `src/services/mineru/parser.py` 中：

```python
# 检测 lines_deleted 标记
if block_type == 'table' and 'blocks' in block_data:
    for nested_block in block_data['blocks']:
        if nested_block.get('lines_deleted'):
            is_continuation = True
            layout_block.is_continuation = True
```

**效果**：为延续页的表格块添加 `is_continuation` 属性。

### 2. 智能检测跨页表格

在 `src/services/extraction/service.py` 中：

```python
def _detect_cross_page_table(parse_results, file_index, page_idx):
    """
    检测跨页表格并返回所有相关页面
    
    策略：
    1. 如果当前页是延续页，向前查找起始页
    2. 如果当前页是起始页，向后查找所有延续页
    3. 返回完整的页码列表：[3, 4] 表示表格从第 3 页延续到第 4 页
    """
```

**逻辑**：
- **向前查找**：从延续页向前找到第一个有表格内容的页面（起始页）
- **向后查找**：从起始页向后找到所有连续的延续页
- **返回完整范围**：`[3, 4, 5]` 表示表格跨越第 3、4、5 页

### 3. 生成多页高亮

当检测到跨页表格时：

```python
# 为每个相关页面生成高亮图
for page_idx in related_pages:
    page_bbox = self._get_page_bbox(parse_results, file_index, page_idx)
    if page_bbox:
        page_image = await self._generate_highlight(
            file_path=pdf_input,
            page_idx=page_idx,
            bbox=page_bbox
        )
        preview_images.append({
            "page_idx": page_idx,
            "image_url": page_image
        })
```

### 4. 响应结构增强

在 `src/schemas/extraction.py` 的 `SourceInfo` 中添加：

```python
class SourceInfo(BaseModel):
    # ... 原有字段 ...
    
    # 跨页信息（可选）
    cross_page_info: Optional[Dict[str, Any]] = Field(None, description="跨页信息")
    preview_images: Optional[List[Dict[str, Any]]] = Field(None, description="所有页面的预览图")
```

## 响应示例

### 单页内容（普通情况）

```json
{
  "source_info": {
    "source_file_type": "info_disclosure_application",
    "preview_image_url": "https://minio.example.com/preview/page3.png",
    "coordinates": {"x": 100, "y": 200, "width": 300, "height": 50},
    "cross_page_info": null,
    "preview_images": null
  }
}
```

### 跨页内容

```json
{
  "source_info": {
    "source_file_type": "info_disclosure_application",
    "preview_image_url": "https://minio.example.com/preview/page3.png",
    "coordinates": {"x": 100, "y": 200, "width": 300, "height": 50},
    "cross_page_info": {
      "is_cross_page": true,
      "pages": [3, 4],
      "main_page": 3
    },
    "preview_images": [
      {
        "page_idx": 3,
        "image_url": "https://minio.example.com/preview/page3.png"
      },
      {
        "page_idx": 4,
        "image_url": "https://minio.example.com/preview/page4.png"
      }
    ]
  }
}
```

## 前端显示建议

### 1. 检测跨页标记

```javascript
if (sourceInfo.cross_page_info?.is_cross_page) {
  // 显示跨页提示
  showCrossPageIndicator(sourceInfo.cross_page_info.pages);
}
```

### 2. 显示所有预览图

```javascript
// 主图显示第一张
<img src={sourceInfo.preview_image_url} alt="主预览" />

// 如果有多张，提供切换功能
{sourceInfo.preview_images?.map((img, index) => (
  <img 
    key={index}
    src={img.image_url} 
    alt={`第 ${img.page_idx + 1} 页`}
  />
))}
```

### 3. 用户提示

```
✓ 此内容跨越第 3-4 页
  [查看第 3 页] [查看第 4 页]
```

## 优势

✅ **完整性**：用户可以看到所有相关页面的高亮
✅ **准确性**：明确标注跨页信息，避免误解
✅ **灵活性**：前端可以选择显示方式（轮播、并排、折叠等）
✅ **兼容性**：普通单页内容不受影响，跨页信息为可选字段

## 技术细节

### MinerU 的跨页表格结构

**第 3 页（起始页）**：
```json
{
  "type": "table",
  "bbox": [59, 137, 538, 775],
  "blocks": [{
    "type": "table_body",
    "lines": [{
      "spans": [{
        "html": "<table>...</table>"  // 完整内容
      }]
    }]
  }]
}
```

**第 4 页（延续页）**：
```json
{
  "type": "table",
  "bbox": [60, 42, 538, 688],
  "blocks": [{
    "type": "table_body",
    "lines": [],                // 空数组
    "lines_deleted": true       // 标记
  }]
}
```

### 检测逻辑流程

```
溯源到第 4 页
  ↓
检查 layout_blocks
  ↓
发现 is_continuation = true
  ↓
向前查找（第 3 页）
  ↓
找到起始页（有 table 但无 is_continuation）
  ↓
向后查找所有延续页
  ↓
返回完整列表 [3, 4]
  ↓
为每页生成高亮图
```

## 未来优化

1. **图片拼接**：可以将多页高亮图垂直拼接成一张完整图
2. **智能裁剪**：根据实际内容自动裁剪高亮区域
3. **上下文显示**：显示表格前后的上下文内容
4. **缓存优化**：相同跨页表格的高亮图可以复用

## 相关文件

- `src/services/mineru/parser.py` - 解析器标记逻辑
- `src/services/extraction/service.py` - 检测和高亮生成
- `src/schemas/extraction.py` - 响应结构定义
- `docs/cross_page_table_handling.md` - 本文档

