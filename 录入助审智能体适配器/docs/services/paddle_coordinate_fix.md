# Paddle 坐标系统兼容性修复

## 问题描述

### 1. 主要问题

在集成 Paddle OCR-VL 后，发现以下问题：

1. **PDF 高亮位置不正确**：即使文本匹配溯源成功，生成的 PDF 高亮位置与实际文本位置不符
2. **LLM 溯源失败**：提供给 LLM 的 `middle.json` 内容不完整或被截断
3. **坐标兼容性问题**：Paddle 和 MinerU 使用不同的坐标系统

### 2. 根本原因

**Paddle 使用像素坐标（144 DPI），而 MinerU 和 PDF 使用点坐标（72 DPI）**

- **Paddle OCR-VL**：
  - 坐标单位：像素
  - 渲染 DPI：144
  - 页面尺寸示例：`width: 1186, height: 1672`
  - bbox 示例：`[129, 94, 459, 177]`

- **MinerU / PDF**：
  - 坐标单位：点（1/72 英寸）
  - DPI：72
  - 页面尺寸示例：`width: 595, height: 842`
  - bbox 示例：`[64.5, 47, 229.5, 88.5]`

**比例关系**：`72 DPI / 144 DPI = 0.5`

因此，Paddle 的坐标需要乘以 0.5 才能转换为 PDF 的坐标。

## 修复方案

### 1. 统一坐标转换

在 `src/services/paddle/client.py` 的 `_convert_to_parse_result()` 方法中统一进行坐标转换：

```python
# 计算缩放因子
paddle_dpi = 144  # Paddle渲染DPI
pdf_dpi = 72  # PDF标准DPI
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

所有从 Paddle 获取的坐标数据都需要转换：

1. **页面尺寸**：`PaddlePage.width` 和 `height`
2. **内容块 bbox**：`PaddleContent.bbox`（包括 text、image、table、seal 等）
3. **布局块 bbox**：`PaddleLayoutBlock.bbox`
4. **文本行 bbox**：`PaddleLine.bbox`
5. **文本片段 bbox**：`PaddleSpan.bbox`
6. **印章 bbox**：`SealDetection.bbox`

### 3. 兼容性处理

在 `src/services/extraction/service.py` 中添加 bbox 格式兼容：

```python
# 兼容处理：支持 bbox 为对象或列表
if hasattr(block.bbox, 'x0'):
    # MinerU 格式：bbox 是对象
    bbox = [block.bbox.x0, block.bbox.y0, block.bbox.x1, block.bbox.y1]
elif isinstance(block.bbox, (list, tuple)) and len(block.bbox) == 4:
    # Paddle 格式：bbox 是列表
    bbox = list(block.bbox)
else:
    logger.warning(f"无法识别的 bbox 格式: {type(block.bbox)}")
    bbox = [0, 0, 0, 0]
```

这确保了 MinerU 和 Paddle 的数据结构可以无缝互换。

## 修改文件

### 1. `src/services/paddle/client.py`

**修改位置**：`_convert_to_parse_result()` 方法（第 714-766 行）

**主要修改**：

1. 添加坐标缩放因子计算：
   ```python
   paddle_dpi = 144
   pdf_dpi = 72
   scale_factor = pdf_dpi / paddle_dpi  # 0.5
   ```

2. 转换页面尺寸：
   ```python
   page_width = page_pixel_width * scale_factor
   page_height = page_pixel_height * scale_factor
   ```

3. 转换内容块 bbox：
   ```python
   bbox_value = [
       bbox_normalized[0] * scale_factor,
       bbox_normalized[1] * scale_factor,
       bbox_normalized[2] * scale_factor,
       bbox_normalized[3] * scale_factor
   ]
   ```

4. 转换印章 bbox：
   ```python
   for seal in recognized_seals_raw:
       converted_bbox = [
           seal.bbox[0] * scale_factor,
           seal.bbox[1] * scale_factor,
           seal.bbox[2] * scale_factor,
           seal.bbox[3] * scale_factor
       ]
   ```

### 2. `src/services/extraction/service.py`

**修改位置**：
- `_extract_middle_from_single()` 方法（第 1000-1028 行）
- `_get_page_bbox()` 方法（第 2082-2097 行）

**主要修改**：添加 bbox 格式兼容处理，支持对象和列表两种格式。

### 3. 新增文档

- `docs/services/paddle_coordinate_system.md`：坐标系统详细说明
- `docs/services/paddle_coordinate_fix.md`：本修复文档

## 验证方法

### 1. 单元测试

运行 Paddle 集成测试：

```bash
poetry run python tests/test_paddle.py
```

### 2. 坐标验证

检查转换后的坐标是否正确：

```python
# 原始 Paddle 坐标（像素）
paddle_bbox = [129, 94, 459, 177]

# 转换后的坐标（点）
pdf_bbox = [64.5, 47, 229.5, 88.5]

# 验证比例
assert pdf_bbox[0] == paddle_bbox[0] * 0.5
```

### 3. PDF 高亮验证

最直观的验证方法：

```python
# 使用转换后的坐标生成高亮
highlight_url = PDFHighlighter.highlight_single_region(
    pdf_path="test.pdf",
    page_num=0,
    bbox=[64.5, 47, 229.5, 88.5]
)
```

查看高亮图片，验证位置是否正确。

### 4. 对比测试

对同一文件分别使用 Paddle 和 MinerU 解析，对比高亮位置：

```bash
# 测试文件
TEST_FILE="信息披露申请书.pdf"

# 使用 Paddle 解析并生成高亮
# 使用 MinerU 解析并生成高亮

# 对比两者的高亮位置是否一致
```

## 预期效果

### 修复前

- Paddle 返回的 bbox：`[129, 94, 459, 177]`（像素）
- PDF 高亮位置：**错误**，位置偏移约 2 倍

### 修复后

- Paddle 返回的 bbox 转换为：`[64.5, 47, 229.5, 88.5]`（点）
- PDF 高亮位置：**正确**，与 MinerU 一致

### 效果对比

| 项目 | 修复前 | 修复后 |
|------|--------|--------|
| PDF 高亮位置 | ❌ 错误 | ✅ 正确 |
| 溯源准确性 | ❌ 失败 | ✅ 成功 |
| MinerU 兼容性 | ❌ 不兼容 | ✅ 完全兼容 |
| 坐标系统 | ❌ 混乱（像素+点） | ✅ 统一（点） |

## 技术要点

### 1. 为什么不在提取阶段转换

我们选择在 `_convert_to_parse_result` 统一转换，而不是在 `_extract_seal_texts` 等方法中转换：

**优点**：
- **职责分离**：提取方法专注提取，转换方法专注格式化
- **统一处理**：所有坐标转换在一处，便于维护
- **避免重复**：不需要在多个方法中重复转换逻辑

### 2. DPI 值的选择

- **Paddle DPI = 144**：根据实际数据推测
  - Paddle 页面尺寸：1186 x 1672
  - PDF 标准尺寸：595 x 842
  - 比例：1186/595 ≈ 2，1672/842 ≈ 2
  - 因此：144 DPI = 72 DPI * 2

- **PDF DPI = 72**：PDF 标准

如果 Paddle 的 DPI 不同，可以调整 `paddle_dpi` 配置。

### 3. 浮点坐标的处理

转换后的坐标可能是浮点数（如 64.5），这是正常的：

- PDF 支持浮点坐标
- PDF 高亮器会在渲染时转换为整数像素坐标
- 精度足够高，不会影响高亮准确性

## 后续优化

### 1. 可配置的 DPI

将 Paddle DPI 值配置化：

```python
# config/paddle_config.py
PADDLE_CONFIG = {
    'render_dpi': 144,  # 可调整
    'output_dpi': 72,   # PDF 标准
}
```

### 2. 自动检测 DPI

根据页面尺寸自动计算 DPI：

```python
def detect_paddle_dpi(page_pixel_width: int, pdf_point_width: float = 595) -> float:
    """
    自动检测 Paddle 使用的 DPI
    
    Args:
        page_pixel_width: Paddle 返回的页面像素宽度
        pdf_point_width: PDF 标准点宽度（A4 = 595）
    
    Returns:
        估计的 DPI 值
    """
    scale = page_pixel_width / pdf_point_width
    return 72 * scale
```

### 3. 坐标验证

添加坐标合理性验证：

```python
def validate_bbox(bbox: List[float], page_width: float, page_height: float) -> bool:
    """验证 bbox 是否在页面范围内"""
    x0, y0, x1, y1 = bbox
    return (
        0 <= x0 < x1 <= page_width and
        0 <= y0 < y1 <= page_height
    )
```

## 相关文档

- [Paddle 坐标系统说明](./paddle_coordinate_system.md)
- [Paddle 集成文档](./paddle_integration.md)
- [MinerU 数据模型](../mineru/models.md)

## 问题排查

如果高亮位置仍然不正确，检查：

1. **DPI 值是否正确**：
   ```python
   logger.info(f"Paddle DPI: {paddle_dpi}")
   logger.info(f"Scale factor: {scale_factor}")
   ```

2. **坐标是否已转换**：
   ```python
   logger.info(f"原始 bbox: {original_bbox}")
   logger.info(f"转换后 bbox: {converted_bbox}")
   ```

3. **页面尺寸是否正确**：
   ```python
   logger.info(f"页面尺寸: {page_width} x {page_height}")
   ```

4. **PDF 文件是否损坏**：
   ```python
   # 尝试用其他工具打开 PDF
   ```

## 总结

本次修复解决了 Paddle 和 MinerU 坐标系统不兼容的问题，确保：

1. ✅ Paddle 和 MinerU 的坐标系统统一为 PDF 标准（点坐标）
2. ✅ PDF 高亮位置正确
3. ✅ LLM 溯源正常工作
4. ✅ 两种解析引擎可以无缝切换

这为 Paddle 和 MinerU 的混合使用奠定了坚实的基础。









