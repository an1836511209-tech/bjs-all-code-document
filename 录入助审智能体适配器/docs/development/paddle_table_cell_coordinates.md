# PaddleOCR 表格单元格坐标获取说明

## 概述

本文档说明如何从 PaddleOCR (PP-Structure) 的返回结果中正确获取表格单元格的精确坐标，用于文档溯源高亮功能。

## 背景问题

在使用 PaddleOCR 进行表格识别时，我们需要获取每个单元格文本的精确坐标位置。最初的实现尝试对齐 `cell_box_list` 和 `pred_html`，但这种方式存在严重的鲁棒性问题。

### 原方案的问题

```
cell_box_list[i] ↔ HTML <td>[i]  ❌ 数量不一致，对齐困难
```

**问题原因**：
1. `cell_box_list` 包含所有视觉上的单元格框（包括空单元格）
2. `pred_html` 中有 `colspan`/`rowspan` 导致逻辑单元格数量不一致
3. HTML 可能解析出额外的空行（如 merged cell 导致的格式行）
4. 两者的行划分标准可能不同

## PaddleOCR 返回数据结构分析

### 完整数据结构

```json
{
  "layoutParsingResults": [{
    "prunedResult": {
      "table_res_list": [{
        "cell_box_list": [...],      // 90个单元格框（包含空单元格）
        "pred_html": "...",          // HTML 表格结构
        "table_ocr_pred": {          // ⭐ 关键数据源
          "rec_texts": [...],        // 53个 OCR 识别的文本
          "rec_boxes": [...],        // 53个对应的精确坐标
          "rec_scores": [...]        // 识别置信度
        }
      }]
    }
  }]
}
```

### 关键发现：`table_ocr_pred` 的完美对应关系

`table_ocr_pred` 中的 `rec_texts` 和 `rec_boxes` 是**天然一一对应**的：

```json
"rec_texts": ["评估基准日：", "2022年05月31日", "备案编号：", ...],
"rec_boxes": [
  [219, 135, 321, 161],    // "评估基准日：" 的精确坐标
  [333, 138, 465, 166],    // "2022年05月31日" 的精确坐标
  [516, 141, 601, 169],    // "备案编号：" 的精确坐标
  ...
]
```

**这是 OCR 直接检测的结果，天然保证了文本与坐标的一致性！**

### 数据字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `cell_box_list` | `List[List[float]]` | 单元格边界框列表，包含空单元格，格式 `[x0, y0, x1, y1]` |
| `pred_html` | `str` | HTML 格式的表格结构，包含 `colspan`/`rowspan` |
| `table_ocr_pred.rec_texts` | `List[str]` | OCR 识别的文本列表 |
| `table_ocr_pred.rec_boxes` | `List[List[int]]` | 文本边界框，格式 `[x0, y0, x1, y1]` |
| `table_ocr_pred.rec_scores` | `List[float]` | 识别置信度 |

## 推荐方案：基于 `table_ocr_pred` 的文本-坐标匹配

### 方案对比

| 对比项 | 旧方案 (cell_box_list) | 新方案 (table_ocr_pred) |
|--------|------------------------|-------------------------|
| 数据来源 | `cell_box_list` + `pred_html` | `rec_texts` + `rec_boxes` |
| 对应关系 | 需要复杂对齐算法 | **天然一一对应** |
| 空单元格 | 包含，导致错位 | 不包含，无错位风险 |
| 坐标精度 | 单元格边界框（含空白区域） | **文本精确边界框** |
| 匹配方式 | 位置索引匹配 | **内容文本匹配** |
| 鲁棒性 | 低 | **高** |

### 实现流程

```
┌─────────────────────────────────────────────────────────────┐
│                    PaddleOCR 返回结果                        │
└─────────────────────────────────────────────────────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            ▼                                   ▼
┌───────────────────────┐           ┌───────────────────────┐
│     table_ocr_pred    │           │      pred_html        │
│  rec_texts + rec_boxes│           │   表格结构信息         │
│  (天然一一对应)        │           │ (row, col, rowspan,   │
│                       │           │  colspan)             │
└───────────────────────┘           └───────────────────────┘
            │                                   │
            │ 构建 text → bbox 映射              │ 解析 HTML 单元格
            ▼                                   ▼
┌───────────────────────┐           ┌───────────────────────┐
│  text_to_boxes Map    │           │    html_cells List    │
│  {                    │           │  [                    │
│    "评估基准日：":     │           │    {text, row, col,   │
│      [[219,135,321,161]]│         │     rowspan, colspan},│
│    ...                │           │    ...                │
│  }                    │           │  ]                    │
└───────────────────────┘           └───────────────────────┘
            │                                   │
            └───────────┬───────────────────────┘
                        │ 文本内容匹配
                        ▼
            ┌───────────────────────┐
            │   PaddleTableCell     │
            │  - bbox (精确坐标)     │
            │  - text               │
            │  - row, col           │
            │  - rowspan, colspan   │
            └───────────────────────┘
```

### 核心代码实现

```python
def _extract_cells_from_table_res(
    self,
    table_res_list: List[Dict[str, Any]],
    table_bbox: List[float]
) -> List[PaddleTableCell]:
    """
    从 table_res_list 提取单元格信息
    
    使用 table_ocr_pred.rec_texts 和 rec_boxes 的天然对应关系
    """
    cells = []
    
    for table_res in table_res_list:
        pred_html = table_res.get('pred_html', '')
        table_ocr_pred = table_res.get('table_ocr_pred', {})
        
        # 1. 从 table_ocr_pred 获取精确的文本-坐标对应
        rec_texts = table_ocr_pred.get('rec_texts', [])
        rec_boxes = table_ocr_pred.get('rec_boxes', [])
        
        # 2. 解析 HTML 获取表格结构信息
        html_cells = self._parse_table_html_cells(pred_html)
        
        # 3. 构建文本->坐标映射（处理重复文本）
        text_to_boxes: Dict[str, List[List[float]]] = {}
        for text, box in zip(rec_texts, rec_boxes):
            text_stripped = str(text).strip()
            if text_stripped and len(box) >= 4:
                if text_stripped not in text_to_boxes:
                    text_to_boxes[text_stripped] = []
                text_to_boxes[text_stripped].append(box[:4])
        
        # 4. 匹配 HTML 单元格和 OCR 坐标
        for html_cell in html_cells:
            cell_text = str(html_cell.get('text', '')).strip()
            if not cell_text:
                continue  # 跳过空单元格
            
            # 查找匹配的坐标
            bbox = None
            if cell_text in text_to_boxes and text_to_boxes[cell_text]:
                bbox = text_to_boxes[cell_text].pop(0)  # 按顺序使用
            else:
                # 尝试模糊匹配
                for ocr_text, boxes in text_to_boxes.items():
                    if boxes and (ocr_text in cell_text or cell_text in ocr_text):
                        bbox = boxes.pop(0)
                        break
            
            if bbox:
                cells.append(PaddleTableCell(
                    bbox=bbox,
                    text=cell_text,
                    row=html_cell['row'],
                    col=html_cell['col'],
                    rowspan=html_cell.get('rowspan', 1),
                    colspan=html_cell.get('colspan', 1)
                ))
    
    return cells
```

### 处理重复文本

表格中可能出现相同的文本（如 "0", "519.0567"），我们使用以下策略：

```python
# 同一文本可能出现多次，按出现顺序存储
text_to_boxes: Dict[str, List[List[float]]] = {}

for text, box in zip(rec_texts, rec_boxes):
    if text not in text_to_boxes:
        text_to_boxes[text] = []
    text_to_boxes[text].append(box)

# 匹配时按顺序消费
if cell_text in text_to_boxes and text_to_boxes[cell_text]:
    bbox = text_to_boxes[cell_text].pop(0)  # 使用并移除第一个
```

**假设前提**：HTML 解析和 OCR 检测的阅读顺序一致（从上到下、从左到右）。

### 模糊匹配

有时 HTML 中的文本与 OCR 识别的文本略有不同，可以使用模糊匹配：

```python
# 精确匹配失败时，尝试包含关系匹配
for ocr_text, boxes in text_to_boxes.items():
    if boxes and (ocr_text in cell_text or cell_text in ocr_text):
        bbox = boxes.pop(0)
        break
```

## 坐标系说明

### 坐标格式

所有坐标都是 `[x0, y0, x1, y1]` 格式：
- `x0, y0`: 左上角坐标
- `x1, y1`: 右下角坐标

### 坐标系原点

- 原点在图像左上角
- X 轴向右为正
- Y 轴向下为正

### 坐标单位

- 单位为像素
- 基于输入图像的实际尺寸
- 如果输入是 PDF，需要考虑 DPI 转换

## 实际数据示例

### 输入图像

一张包含资产评估结果表格的图像（929 x 1183 像素）。

### PaddleOCR 返回的 table_ocr_pred

```json
{
  "rec_texts": [
    "评估基准日：",
    "2022年05月31日",
    "备案编号：",
    "备北京市金隅202200735142",
    "评估结果使用有效期至：",
    "2023年05月30日",
    "金额单位：人民币万元",
    "项目",
    "账面价值",
    "评估价值",
    ...
  ],
  "rec_boxes": [
    [219, 135, 321, 161],
    [333, 138, 465, 166],
    [516, 141, 601, 169],
    [623, 143, 880, 174],
    [128, 190, 320, 218],
    [332, 194, 464, 222],
    [588, 200, 770, 229],
    [175, 250, 218, 274],
    [358, 253, 437, 278],
    [499, 255, 579, 283],
    ...
  ]
}
```

### 匹配结果

```
"评估基准日：" → [219, 135, 321, 161] ✅
"2022年05月31日" → [333, 138, 465, 166] ✅
"备案编号：" → [516, 141, 601, 169] ✅
```

## 回退方案

当 `table_ocr_pred` 不可用时，可以回退到 `cell_box_list` + `pred_html` 的对齐方案，但这种方案不够可靠。

```python
def _extract_cells_fallback(self, table_res, table_bbox):
    """
    回退方案：使用 cell_box_list 和 pred_html 简单顺序匹配
    注意：这种方案可能不准确
    """
    cell_box_list = table_res.get('cell_box_list', [])
    pred_html = table_res.get('pred_html', '')
    
    html_cells = self._parse_table_html_cells(pred_html)
    
    # 简单顺序匹配（可能不准确）
    limit = min(len(html_cells), len(cell_box_list))
    
    for i in range(limit):
        # ...
```

## 注意事项

1. **空单元格**：`rec_texts`/`rec_boxes` 不包含空单元格，这对于高亮来说是正确的行为（我们不需要高亮空白区域）

2. **跨行/跨列单元格**：结构信息（`rowspan`/`colspan`）从 HTML 中获取，坐标从 OCR 结果获取

3. **文本识别错误**：OCR 可能识别错误，但坐标仍然是准确的。使用模糊匹配可以缓解这个问题

4. **PDF 坐标转换**：如果输入是 PDF，需要注意 DPI 转换：
   - PaddleOCR 处理的是渲染后的图像
   - 坐标基于图像像素
   - 需要根据渲染 DPI 换算回 PDF 点坐标

## 相关文件

- `src/services/paddle/client.py`: PaddleOCR 客户端实现
- `src/services/paddle/highlighter.py`: 高亮生成器
- `docs/development/paddle_highlighter_design.md`: 高亮器设计文档

## 更新历史

| 日期 | 版本 | 说明 |
|------|------|------|
| 2025-12-26 | 1.0 | 初始版本，使用 `table_ocr_pred` 替代 `cell_box_list` 对齐方案 |















