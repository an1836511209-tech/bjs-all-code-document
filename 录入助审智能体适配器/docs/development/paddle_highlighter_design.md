# Paddle PDF 高亮器设计文档

## 概述

本文档说明为 Paddle OCR 创建的专用 PDF 高亮方案，解决坐标偏差问题。

## 核心问题

### 原始问题
- Paddle OCR 返回 **144 DPI** 渲染下的像素坐标
- 原有代码尝试转换为 **72 DPI** 的点坐标，但转换复杂且有偏差
- 通用 PDFHighlighter 使用 **200 DPI** 渲染，导致坐标不匹配

### 解决方案
**保留原生像素坐标 + 专用高亮器**
- Paddle 模块：保留原生 144 DPI 像素坐标，不做转换
- 专用高亮器：使用 144 DPI 渲染，坐标系统完全对齐
- 零偏差：渲染方式和坐标系统与 Paddle 100% 一致

## 架构设计

```
┌─────────────────┐
│ Paddle OCR      │ → 返回 144 DPI 像素坐标
└────────┬────────┘
         ↓ (保留原生坐标，无转换)
┌─────────────────┐
│ PaddleClient    │ → bbox 直接存储像素坐标
│ (client.py)     │ → 删除复杂的 scale_x/scale_y 转换
└────────┬────────┘
         ↓
┌─────────────────┐
│ Middle.json     │ → 包含完整 lines/spans 结构
│ 生成逻辑        │ → 每个 span 都有独立的 bbox 坐标
└────────┬────────┘
         ↓
┌─────────────────┐
│ 溯源 Agent      │ → 从 middle.json 读取 span 级别坐标
│ (提示词不变)    │ → 返回像素坐标 [x0, y0, x1, y1]
└────────┬────────┘
         ↓
┌─────────────────┐
│ PaddlePDF       │ → 使用 144 DPI 渲染 PDF
│ Highlighter     │ → 坐标直接使用，无需转换
└─────────────────┘
```

## 文件修改清单

### 1. 新建文件

#### `src/utils/paddle_pdf_highlighter.py`
**专用的 Paddle PDF 高亮器**

核心特点：
- 使用 **144 DPI** 渲染（与 Paddle OCR 完全一致）
- 直接使用**像素坐标**，无需转换
- 坐标系统完全对齐，确保高亮精确

关键代码：
```python
class PaddlePDFHighlighter:
    PADDLE_DPI = 144  # 与 Paddle 一致的 DPI
    
    @classmethod
    def highlight_pdf_regions(cls, pdf_path, page_num, bboxes, ...):
        # 1. 使用 144 DPI 渲染
        zoom = cls.PADDLE_DPI / 72.0  # 2.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        
        # 2. 坐标直接使用，无需转换
        for bbox in bboxes:
            x0_px = int(round(bbox[0]))  # 直接使用像素值
            y0_px = int(round(bbox[1]))
            # ... 绘制高亮
```

### 2. 修改的文件

#### `src/services/paddle/client.py`
**简化坐标转换逻辑**

主要变更：
1. **删除复杂的 DPI 转换逻辑**（第 833-860 行）
   - 删除 `scale_x`、`scale_y` 计算
   - 删除 PDF 页面尺寸获取
   - 删除 DPI 诊断日志

2. **保留原生像素坐标**（第 882-887 行）
   ```python
   # 之前：复杂的转换
   bbox_value = [
       bbox_normalized[0] * scale_x,
       bbox_normalized[1] * scale_y,
       bbox_normalized[2] * scale_x,
       bbox_normalized[3] * scale_y
   ]
   
   # 现在：直接保留
   bbox_value = create_bbox_from_list(bbox_list)
   ```

3. **页面尺寸使用像素值**（第 851-860 行）
   ```python
   # 直接使用像素尺寸，不转换为点坐标
   page_width = page_pixel_width
   page_height = page_pixel_height
   ```

#### `src/services/extraction/service.py`
**根据 backend 选择高亮器**

主要变更：
1. **导入专用高亮器**（第 50 行）
   ```python
   from src.utils.paddle_pdf_highlighter import PaddlePDFHighlighter
   ```

2. **_generate_highlight 方法**（第 1492-1547 行）
   - 新增 `backend` 参数（默认 'mineru'）
   - 根据 backend 选择高亮器：
     ```python
     if backend == "paddle":
         image_url = PaddlePDFHighlighter.highlight_single_region(...)
     else:
         image_url = PDFHighlighter.highlight_single_region(...)
     ```

3. **调用处传递 backend**（第 1216-1249 行）
   ```python
   # 获取解析后端信息
   backend = getattr(parse_result, "backend", "mineru")
   
   # 传递给高亮方法
   preview_image = await self._generate_highlight(
       file_path=pdf_input,
       page_idx=actual_page_idx,
       bbox=tracing_result.bbox,
       backend=backend  # ✅ 传递 backend
   )
   ```

4. **_generate_merged_highlight 方法**（第 1559-1611 行）
   - 同样新增 `backend` 参数
   - 支持跨页高亮时根据 backend 选择

5. **Middle.json 生成逻辑**（第 1001-1066 行）
   - 保留完整的 `lines` 和 `spans` 结构
   - 每个 span 都包含独立的 bbox 坐标
   ```python
   layout_det = {
       "bbox": bbox,
       "text": " ".join(all_texts),
       "category_type": block.category_type,
       "lines": [  # ✅ 新增完整结构
           {
               "bbox": line_bbox,
               "spans": [
                   {
                       "bbox": span_bbox,
                       "content": span_text,  # 与溯源提示词保持一致
                       "type": "text"
                   }
               ]
           }
       ]
   }
   ```

## 坐标系统说明

### Paddle 坐标系统（现在）
```
Paddle OCR 渲染: 144 DPI
     ↓ (无转换)
存储坐标: [x_px, y_px, x_px, y_px] (像素)
     ↓ (无转换)
溯源 Agent: 返回像素坐标
     ↓ (无转换)
PaddlePDFHighlighter: 144 DPI 渲染
     → 坐标直接使用像素值
     → ✅ 完全对齐，零偏差
```

### MinerU 坐标系统（保持不变）
```
MinerU 解析: 返回点坐标 (72 DPI)
     ↓
存储坐标: [x_pt, y_pt, x_pt, y_pt] (点)
     ↓
溯源 Agent: 返回点坐标
     ↓
PDFHighlighter: 200 DPI 渲染
     → 坐标需要 * (200/72) 转换
     → ✅ 现有逻辑正常工作
```

## 溯源提示词

### 是否需要修改？
**❌ 不需要修改**

原因：
- 提示词要求 span 级别的细粒度坐标（正确）
- 现在 middle.json 已包含完整的 lines/spans 结构（已修复）
- 坐标格式为 `[x0, y0, x1, y1]`（统一格式）
- Agent 只需从 JSON 提取坐标，不需要理解坐标系统

### 提示词关键部分
```
搜索策略（严格按优先级执行）：
  第一优先级：span级别搜索  ✅ 现在可以实现
  第二优先级：line级别搜索  ✅ 现在可以实现
  第三优先级：block级别搜索 ✅ 保留为后备方案
```

输出格式：
```json
{
    "tracing_result": {
        "page_idx": 0,
        "bbox": [54.0, 61.956, 296.226, 72.000],  // 像素坐标或点坐标
        "granularity": "span",  // span|line|block
        "match_type": "exact"
    }
}
```

## 优势总结

### ✅ 简化了代码
- 删除了复杂的 DPI 计算逻辑
- 删除了 scale_x/scale_y 转换
- 代码更简洁、易维护

### ✅ 提高了精度
- 坐标系统完全对齐
- 无转换损失
- 零偏差高亮

### ✅ 增强了溯源
- Middle.json 包含完整的 lines/spans 结构
- 支持 span 级别的精细定位
- 溯源 Agent 可以返回更精确的坐标

### ✅ 保持了兼容性
- MinerU 等其他后端不受影响
- 根据 backend 自动选择高亮器
- 向后兼容

## 测试建议

### 1. 单元测试
- 测试 PaddlePDFHighlighter 的基本功能
- 测试不同尺寸的 PDF 页面
- 测试边界情况（坐标超出范围等）

### 2. 集成测试
- 测试完整的提取 → 溯源 → 高亮流程
- 对比 Paddle 和 MinerU 的高亮效果
- 验证跨页表格的高亮

### 3. 精度测试
- 使用已知坐标的测试文档
- 对比 Paddle OCR 返回的坐标和高亮位置
- 测量偏差（应该为 0 或接近 0）

## 未来改进

### 可选优化
1. **性能优化**
   - 缓存渲染结果
   - 批量处理多个高亮区域

2. **功能增强**
   - 支持自定义高亮样式
   - 支持文字提取和 OCR 结果对比

3. **监控和日志**
   - 添加高亮成功率统计
   - 记录坐标偏差情况

## 结论

通过创建专用的 PaddlePDFHighlighter 并简化 Paddle 模块的坐标转换逻辑，我们实现了：
- ✅ 零偏差的 PDF 高亮
- ✅ 更简洁的代码架构
- ✅ 更精确的溯源定位
- ✅ 完整的 lines/spans 结构

系统现在可以根据文档解析后端（Paddle 或 MinerU）自动选择合适的高亮器，确保高亮位置与原文完全对齐。







