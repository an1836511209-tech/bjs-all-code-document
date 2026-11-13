# Paddle 坐标系统说明

## 概述

本文档说明 Paddle 和 MinerU 的坐标系统差异，以及我们如何处理这些差异以确保无缝集成。

## 坐标系统对比

### 1. Paddle OCR-VL 坐标系统

- **单位**：像素（Pixel）
- **渲染 DPI**：144 DPI（推测）
- **坐标格式**：`[x0, y0, x1, y1]` - 左上角和右下角
- **坐标系**：左上角为原点 (0,0)，X轴向右，Y轴向下
- **示例**：
  - 页面尺寸：`width: 1186, height: 1672` (像素)
  - 文本框：`[129, 94, 459, 177]` (像素)

### 2. MinerU 坐标系统

- **单位**：点（Point，1/72 英寸）
- **渲染 DPI**：72 DPI（PDF 标准）
- **坐标格式**：`[x0, y0, x1, y1]` - 左上角和右下角
- **坐标系**：左上角为原点 (0,0)，X轴向右，Y轴向下
- **示例**：
  - 页面尺寸（A4）：`width: 595, height: 842` (点)
  - 文本框：`[64.5, 47, 229.5, 88.5]` (点)

### 3. PDF 标准坐标系统

- **单位**：点（Point，1/72 英寸）
- **DPI**：72 DPI
- **页面尺寸（A4）**：595 x 842 点

## 坐标转换

### 转换公式

```python
# Paddle像素坐标 -> PDF点坐标
paddle_dpi = 144  # Paddle 渲染 DPI
pdf_dpi = 72      # PDF 标准 DPI
scale_factor = pdf_dpi / paddle_dpi  # 0.5

pdf_coord = paddle_pixel_coord * scale_factor
```

### 示例

Paddle 像素坐标：`[129, 94, 459, 177]`

转换为 PDF 点坐标：
- `x0 = 129 * 0.5 = 64.5`
- `y0 = 94 * 0.5 = 47`
- `x1 = 459 * 0.5 = 229.5`
- `y1 = 177 * 0.5 = 88.5`

结果：`[64.5, 47, 229.5, 88.5]`

## 实现细节

### 1. 在哪里进行转换

坐标转换在 `PaddleClient._convert_to_parse_result()` 方法中统一进行：

```python
# 计算缩放因子
paddle_dpi = 144
pdf_dpi = 72
scale_factor = pdf_dpi / paddle_dpi  # 0.5

# 转换页面尺寸
page_width = page_pixel_width * scale_factor
page_height = page_pixel_height * scale_factor

# 转换 bbox 坐标
bbox_value = [
    bbox_normalized[0] * scale_factor,
    bbox_normalized[1] * scale_factor,
    bbox_normalized[2] * scale_factor,
    bbox_normalized[3] * scale_factor
]
```

### 2. 转换范围

以下数据会进行坐标转换：

1. **页面尺寸**：`PaddlePage.width` 和 `PaddlePage.height`
2. **内容块 bbox**：`PaddleContent.bbox`
3. **布局块 bbox**：`PaddleLayoutBlock.bbox`
4. **文本行 bbox**：`PaddleLine.bbox`
5. **文本片段 bbox**：`PaddleSpan.bbox`
6. **印章 bbox**：`SealDetection.bbox`

### 3. 为什么不在提取阶段转换

我们选择在 `_convert_to_parse_result` 中统一转换，而不是在 `_extract_seal_texts` 等方法中转换，原因：

1. **职责分离**：提取方法专注于提取数据，转换方法专注于数据格式化
2. **统一处理**：所有坐标转换在一个地方进行，便于维护和调试
3. **避免重复**：不需要在多个方法中重复转换逻辑

## 验证方法

### 1. 检查转换后的坐标

```python
# 查看转换后的页面尺寸
logger.info(f"页面尺寸: {page.width} x {page.height}")

# 查看转换后的 bbox
for content in page.contents:
    if content.bbox:
        logger.info(f"{content.type}: bbox={content.bbox}")
```

### 2. PDF 高亮验证

最直观的验证方法是生成 PDF 高亮：

```python
# 使用转换后的坐标生成高亮
highlight_url = PDFHighlighter.highlight_single_region(
    pdf_path=file_path,
    page_num=page_idx,
    bbox=content.bbox  # 应该是点坐标
)
```

如果高亮位置正确，说明坐标转换正确。

### 3. 对比 MinerU 和 Paddle 的结果

对同一个文件分别使用 MinerU 和 Paddle 解析，对比它们的坐标：

```python
# MinerU 结果
mineru_bbox = [64.5, 47, 229.5, 88.5]  # 点坐标

# Paddle 结果（转换后）
paddle_bbox = [64.5, 47, 229.5, 88.5]  # 应该相同

# 验证
assert paddle_bbox == mineru_bbox
```

## 常见问题

### Q1: 为什么 Paddle 使用 144 DPI？

A: 这是根据实际测试推测的。Paddle 返回的页面尺寸（1186 x 1672）约为标准 A4 PDF 尺寸（595 x 842）的 2 倍，因此推测 Paddle 使用 144 DPI（72 DPI * 2）。

### Q2: 如果 Paddle 的 DPI 不是 144 怎么办？

A: 可以根据实际情况调整 `paddle_dpi` 变量：

```python
# 在 config/paddle_config.py 中添加配置
PADDLE_RENDER_DPI = 144  # 可调整
```

### Q3: 坐标转换会影响精度吗？

A: 使用浮点数坐标（如 64.5），精度足够高。PDF 高亮器会将浮点坐标转换为整数像素坐标（乘以 DPI 缩放比例）。

### Q4: 如何处理不同尺寸的 PDF？

A: 坐标转换是相对的，基于页面的实际尺寸：

```python
# Paddle 返回的页面像素尺寸
page_pixel_width = 1186  # 可能不同
page_pixel_height = 1672  # 可能不同

# 转换为点尺寸
page_width = page_pixel_width * scale_factor
page_height = page_pixel_height * scale_factor
```

因此，无论 PDF 实际尺寸如何，转换都是正确的。

## 参考资料

- [PDF 坐标系统](https://www.adobe.com/content/dam/acom/en/devnet/pdf/pdfs/pdf_reference_archives/PDFReference.pdf)
- [MinerU 文档](https://opendatalab.github.io/MinerU/)
- [PaddleOCR-VL 文档](https://www.paddleocr.ai/latest/version3.x/pipeline_usage/PaddleOCR-VL.html)









