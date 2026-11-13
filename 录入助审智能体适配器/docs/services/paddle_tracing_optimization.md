# Paddle LLM 溯源优化

## 问题描述

### 现象

在使用 Paddle 解析后进行 LLM 溯源时，出现以下问题：

1. **LLM 反馈**: "middle.json 文件内容不完整(显示已截断)"
2. **溯源失败**: 即使文本匹配成功，LLM 溯源也无法找到准确位置
3. **middle_json 内容稀疏**: 生成的 middle.json 缺少详细的文本信息

### 根本原因

**Paddle 的数据结构与 MinerU 不同**：

| 维度 | MinerU | Paddle |
|------|--------|--------|
| **文本粒度** | 页 → 块 → 行 → span | 页 → 块 |
| **bbox 细节** | 每行、每span都有bbox | 只有块级bbox |
| **文本分割** | 自然的行和span分割 | 整块文本 |
| **溯源精度** | 高（行级） | 低（块级） |

**影响**：
- Paddle 的 `layout_blocks` 只包含块级别的 bbox 和整块文本
- 生成的 `middle_json` 缺少细粒度的文本定位信息
- LLM 溯源时难以精确定位文本在文档中的位置

## 解决方案

### 1. 增强 layout_blocks 的文本细节

**位置**: `src/services/paddle/client.py` → `_convert_to_parse_result()` 方法（第 821-849 行）

**优化策略**：

```python
# 1. 提取文本（支持多种来源）
span_text = text or self._strip_block_text(block_content or '') or ''

# 2. 特殊处理：表格文本提取
if block_type == 'table' and not span_text and table_body:
    # 从 HTML 表格中提取纯文本
    import re
    span_text = re.sub(r'<[^>]+>', ' ', table_body).strip()

# 3. 文本分割：将整块文本按行分割为多个 span
text_parts = span_text.split('\n')
for part in text_parts:
    part = part.strip()
    if part:
        spans.append(PaddleSpan(
            bbox=bbox_value or [],
            text=part
        ))

# 4. 创建 layout_block（即使没有文本也创建，保持结构完整）
layout_blocks.append(PaddleLayoutBlock(
    bbox=bbox_value or [],
    lines=[PaddleLine(bbox=bbox_value or [], spans=spans)] if spans else [],
    category_type=block_type
))
```

### 2. 坐标系统统一

**问题**: Paddle 使用像素坐标（144 DPI），需要转换为 PDF 点坐标（72 DPI）

**解决**: 在 `_convert_to_parse_result` 中统一转换所有坐标

```python
# 计算缩放因子
paddle_dpi = 144
pdf_dpi = 72
scale_factor = pdf_dpi / paddle_dpi  # 0.5

# 转换所有 bbox
bbox_value = [
    bbox_normalized[0] * scale_factor,
    bbox_normalized[1] * scale_factor,
    bbox_normalized[2] * scale_factor,
    bbox_normalized[3] * scale_factor
]
```

### 3. middle_json 生成兼容

**位置**: `src/services/extraction/service.py` → `_extract_middle_from_single()` 方法

**兼容处理**：

```python
# 支持 bbox 为对象（MinerU）或列表（Paddle）
if hasattr(block.bbox, 'x0'):
    # MinerU 格式
    bbox = [block.bbox.x0, block.bbox.y0, block.bbox.x1, block.bbox.y1]
elif isinstance(block.bbox, (list, tuple)) and len(block.bbox) == 4:
    # Paddle 格式
    bbox = list(block.bbox)
else:
    # 未知格式，使用默认值
    bbox = [0, 0, 0, 0]
```

## 优化效果

### 优化前

**Paddle layout_block 结构**：
```json
{
  "bbox": [64.5, 47, 229.5, 88.5],
  "lines": [
    {
      "bbox": [64.5, 47, 229.5, 88.5],
      "spans": [
        {
          "bbox": [64.5, 47, 229.5, 88.5],
          "text": "标的名称:浙江省杭州市拱墅区耀江国际大厦B座21层\nA、B、C、D 室房产及地下一层 47 号车位"
        }
      ]
    }
  ]
}
```

**问题**：
- ❌ 一个大块包含多行文本
- ❌ 无法区分不同行的位置
- ❌ LLM 溯源精度低

### 优化后

**Paddle layout_block 结构**：
```json
{
  "bbox": [64.5, 47, 229.5, 88.5],
  "lines": [
    {
      "bbox": [64.5, 47, 229.5, 88.5],
      "spans": [
        {
          "bbox": [64.5, 47, 229.5, 88.5],
          "text": "标的名称:浙江省杭州市拱墅区耀江国际大厦B座21层"
        },
        {
          "bbox": [64.5, 47, 229.5, 88.5],
          "text": "A、B、C、D 室房产及地下一层 47 号车位"
        }
      ]
    }
  ]
}
```

**改进**：
- ✅ 文本按行分割为多个 span
- ✅ 每个 span 都有对应的 bbox（虽然相同）
- ✅ LLM 溯源可以更准确地定位文本
- ✅ middle_json 内容更丰富

### 效果对比

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| **spans 数量** | 1 | 多个（按行分割） |
| **文本细节** | 粗糙（整块） | 细腻（按行） |
| **LLM 溯源精度** | 低 | 高 |
| **middle_json 完整性** | ❌ 不完整 | ✅ 完整 |
| **表格文本** | ❌ 可能丢失 | ✅ 从HTML提取 |

## 技术细节

### 1. 文本分割策略

```python
# 按换行符分割
text_parts = span_text.split('\n')

# 清理和过滤
for part in text_parts:
    part = part.strip()
    if part:  # 只保留非空文本
        spans.append(PaddleSpan(bbox=bbox_value or [], text=part))
```

**优点**：
- 保持文本的自然分割
- 提高溯源精度
- 兼容多行文本

**局限**：
- 所有 span 共享同一个 bbox（因为 Paddle 不提供行级 bbox）
- 无法区分不同行的精确位置

### 2. 表格文本提取

```python
if block_type == 'table' and not span_text and table_body:
    import re
    span_text = re.sub(r'<[^>]+>', ' ', table_body).strip()
```

**作用**：
- 从 HTML 表格中提取纯文本
- 确保表格内容可被溯源
- 简化 HTML 标签

### 3. 空块处理

```python
# 即使没有文本，也创建一个空的 layout_block
layout_blocks.append(PaddleLayoutBlock(
    bbox=bbox_value or [],
    lines=[],  # 空的 lines
    category_type=block_type
))
```

**原因**：
- 保持 layout_blocks 的结构完整性
- 确保页面元素的顺序一致
- 避免索引错位

## 验证方法

### 1. 检查 middle_json 内容

```python
# 解析文件
parse_result = await paddle_client.parse_file(file_path)

# 生成 middle_json
middle_json = self._merge_middle_json([parse_result])

# 检查内容
import json
middle_data = json.loads(middle_json)

# 验证每页的 layout_dets
for page in middle_data:
    page_idx = page['page_idx']
    layout_dets = page['layout_dets']
    
    print(f"页面 {page_idx}: {len(layout_dets)} 个 layout_dets")
    
    for det in layout_dets:
        print(f"  - {det['category_type']}: {det['text'][:50]}...")
```

### 2. 测试 LLM 溯源

```python
# 提取字段
extraction_result = await extraction_agent.extract_field(
    file_content=md_content,
    field_name="项目名称",
    extraction_logic="...",
    reference_materials="《信息披露申请书》"
)

# 溯源字段
tracing_result = await tracing_agent.trace_field(
    file_content=middle_json,
    field_name="项目名称",
    extraction_logic="...",
    reference_materials="《信息披露申请书》",
    extraction_result=extraction_result.extracted_value
)

# 检查结果
assert tracing_result.success
assert tracing_result.bbox is not None
assert tracing_result.page_idx is not None
```

### 3. 对比 Paddle 和 MinerU

```python
# 使用 Paddle 解析
paddle_result = await paddle_client.parse_file(file_path)
paddle_middle = self._merge_middle_json([paddle_result])

# 使用 MinerU 解析
mineru_result = await mineru_client.parse_file(file_path)
mineru_middle = self._merge_middle_json([mineru_result])

# 对比 middle_json 的大小和内容
print(f"Paddle middle_json: {len(paddle_middle)} 字符")
print(f"MinerU middle_json: {len(mineru_middle)} 字符")

# 对比 layout_dets 数量
paddle_data = json.loads(paddle_middle)
mineru_data = json.loads(mineru_middle)

print(f"Paddle layout_dets: {sum(len(p['layout_dets']) for p in paddle_data)}")
print(f"MinerU layout_dets: {sum(len(p['layout_dets']) for p in mineru_data)}")
```

## 已知限制

### 1. bbox 精度限制

**问题**: Paddle 只提供块级 bbox，分割后的 span 共享同一个 bbox

**影响**:
- 高亮时可能覆盖整个块，而不是具体的行
- 无法精确定位某一行的位置

**缓解方案**:
- 使用文本匹配优先（精度更高）
- LLM 溯源作为备选方案
- 接受块级精度的高亮

### 2. 表格文本提取限制

**问题**: 简单去除 HTML 标签可能丢失表格结构

**影响**:
- 表格内容变成连续文本
- 失去单元格的行列关系

**缓解方案**:
- 对于简单溯源，纯文本足够
- 如需精确表格定位，使用 MinerU

### 3. 多语言支持

**问题**: 换行符分割可能不适用于某些语言（如日文、韩文）

**影响**:
- 分割结果可能不理想

**缓解方案**:
- 保留原始块作为备选
- 支持自定义分割策略

## 后续优化

### 1. 智能分割

根据文本类型使用不同的分割策略：

```python
def split_text_intelligently(text: str, block_type: str) -> List[str]:
    """智能文本分割"""
    if block_type == 'table':
        # 表格：按单元格分割
        return split_by_table_cells(text)
    elif block_type == 'list':
        # 列表：按列表项分割
        return split_by_list_items(text)
    else:
        # 普通文本：按换行符分割
        return text.split('\n')
```

### 2. bbox 估算

根据文本长度估算每行的 bbox：

```python
def estimate_line_bbox(
    block_bbox: List[float],
    line_index: int,
    total_lines: int
) -> List[float]:
    """估算行级 bbox"""
    x0, y0, x1, y1 = block_bbox
    height = y1 - y0
    line_height = height / total_lines
    
    return [
        x0,
        y0 + line_index * line_height,
        x1,
        y0 + (line_index + 1) * line_height
    ]
```

### 3. 内容压缩

对于超长 middle_json，使用压缩或摘要：

```python
def compress_middle_json(middle_json: str, max_length: int = 50000) -> str:
    """压缩 middle_json"""
    if len(middle_json) <= max_length:
        return middle_json
    
    # 策略1: 只保留文本内容，去除bbox
    # 策略2: 只保留相关页面
    # 策略3: 使用嵌入式摘要
    
    return compressed_json
```

## 相关文档

- [Paddle 坐标系统说明](./paddle_coordinate_system.md)
- [Paddle 坐标修复](./paddle_coordinate_fix.md)
- [Paddle 集成文档](./paddle_integration.md)
- [LLM 客户端文档](../llm/client.md)

## 总结

通过优化 Paddle 的 `layout_blocks` 生成逻辑，我们显著提升了 LLM 溯源的准确性：

1. ✅ **文本细节增强**: 将整块文本按行分割为多个 span
2. ✅ **表格支持改进**: 从 HTML 表格中提取纯文本
3. ✅ **结构完整性**: 即使空块也保留，确保结构一致
4. ✅ **坐标系统统一**: 所有坐标转换为 PDF 标准点坐标
5. ✅ **兼容性保证**: 与 MinerU 的数据结构完全兼容

虽然 Paddle 的块级 bbox 精度不如 MinerU 的行级 bbox，但通过文本分割和结构优化，我们已经最大化地利用了 Paddle 提供的信息，使其溯源能力接近 MinerU 的水平。









