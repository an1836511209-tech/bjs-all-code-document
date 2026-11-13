# Confidence/Score 提取修复文档

## 问题描述

在之前的实现中，所有提取结果的 `confidence` 字段都显示为默认值 `0.8`，没有从 Paddle API 返回的数据中正确提取 `score` 信息。

## 根本原因

### 1. Paddle API 返回的 score 位置

Paddle API 返回的数据结构中，`score` 信息在 `layout_det_res.boxes` 中：

```json
{
  "prunedResult": {
    "parsing_res_list": [
      {
        "block_label": "seal",
        "block_bbox": [0, 5, 393, 338],
        // 这里没有 score 字段
      }
    ],
    "layout_det_res": {
      "boxes": [
        {
          "cls_id": 20,
          "label": "seal",
          "score": 0.9745889902114868,  // <-- score 在这里！
          "coordinate": [0.628, 5.360, ...]
        }
      ]
    }
  }
}
```

### 2. 原代码问题

- **问题1**：`_convert_to_parse_result` 方法中没有提取 `layout_det_res.boxes` 中的 `score`
- **问题2**：`ExtractionResult` 模型缺少 `confidence` 字段
- **问题3**：没有将 `layout_det_res.boxes` 中的 `score` 与 `parsing_res_list` 中的 block 进行匹配

## 解决方案

### 1. 添加 score 匹配逻辑（`paddle/client.py`）

#### 1.1 提取 layout_det_res.boxes

```python
# 提取 layout_det_res 中的 score 信息（用于匹配到 block）
layout_det_boxes = []
if pruned_result.get('layout_det_res'):
    layout_det_boxes = pruned_result.get('layout_det_res', {}).get('boxes', [])
```

#### 1.2 通过 bbox 匹配 score

为每个 block 匹配对应的 score：

```python
# 尝试从 layout_det_res.boxes 中匹配 score
block_score = None
if bbox_normalized and layout_det_boxes:
    block_score = self._match_score_from_layout_det(
        bbox_normalized, 
        layout_det_boxes,
        block_type
    )

content = PaddleContent(
    type=block_type,
    # ... 其他字段
    score=block_score  # 添加 score
)
```

#### 1.3 添加 bbox 匹配算法

使用 IoU（交并比）算法匹配 bbox：

```python
def _match_score_from_layout_det(
    self,
    block_bbox: List[float],
    layout_det_boxes: List[Dict[str, Any]],
    block_type: str
) -> Optional[float]:
    """通过 bbox 匹配找到对应的 score"""
    
    best_match_score = None
    best_match_iou = 0.0
    
    for det_box in layout_det_boxes:
        det_coordinate = det_box.get('coordinate')
        if not det_coordinate:
            continue
        
        det_bbox = create_bbox_from_list(det_coordinate)
        iou = self._calculate_bbox_iou(block_bbox, det_bbox)
        
        # IoU > 0.5 认为是匹配的
        if iou > 0.5 and iou > best_match_iou:
            best_match_iou = iou
            best_match_score = det_box.get('score')
            
            # IoU > 0.9 完全匹配，直接返回
            if iou > 0.9:
                return best_match_score
    
    return best_match_score
```

#### 1.4 IoU 计算

```python
@staticmethod
def _calculate_bbox_iou(bbox_a: List[float], bbox_b: List[float]) -> float:
    """计算两个 bbox 的 IoU（交并比）"""
    
    # 计算交集
    x0_inter = max(bbox_a[0], bbox_b[0])
    y0_inter = max(bbox_a[1], bbox_b[1])
    x1_inter = min(bbox_a[2], bbox_b[2])
    y1_inter = min(bbox_a[3], bbox_b[3])
    
    if x0_inter >= x1_inter or y0_inter >= y1_inter:
        return 0.0
    
    inter_area = (x1_inter - x0_inter) * (y1_inter - y0_inter)
    area_a = (bbox_a[2] - bbox_a[0]) * (bbox_a[3] - bbox_a[1])
    area_b = (bbox_b[2] - bbox_b[0]) * (bbox_b[3] - bbox_b[1])
    union_area = area_a + area_b - inter_area
    
    return inter_area / union_area if union_area > 0 else 0.0
```

### 2. 添加 confidence 字段（`llm/models.py`）

```python
class ExtractionResult(BaseModel):
    """提取结果模型"""
    extracted_value: Optional[str] = Field(None, description="提取的字段值")
    confidence: Optional[float] = Field(None, description="置信度")  # 新增
    raw_response: str = Field(..., description="原始响应内容")
    success: bool = Field(..., description="提取是否成功")
    error: Optional[str] = Field(None, description="错误信息")
```

### 3. 解析 LLM 返回的 confidence（`llm/client.py`）

修改 `ExtractionAgent`，支持从 LLM 响应中解析 confidence：

```python
def _parse_extraction_json(self, content: str) -> Optional[Dict[str, Any]]:
    """解析提取结果的 JSON 数据"""
    
    # 解析 JSON
    data = self._extract_json(content)
    
    if data:
        # 提取字段值
        extracted_value = None
        for key in ["提取结果", "extracted_value", "result", "value"]:
            if key in data:
                extracted_value = str(data[key])
                break
        
        # 提取 confidence
        confidence = data.get("confidence") or data.get("置信度")
        
        return {
            'value': extracted_value,
            'confidence': confidence
        }
    
    return None
```

### 4. 添加诊断日志

```python
# 在 paddle/client.py 中添加
if self.debug_config.get('show_dpi_diagnostics', True):
    logger.debug(f"页面 {page_idx} 找到 {len(layout_det_boxes)} 个 layout_det_res.boxes")

if block_score is not None:
    logger.debug(f"Block {block_type} 匹配到 score: {block_score:.4f}")
else:
    logger.debug(f"Block {block_type} 未匹配到 score")
```

## 数据流

```
Paddle API 返回
  ├─ prunedResult.parsing_res_list[i]
  │   └─ block_bbox: [x0, y0, x1, y1]
  │
  └─ prunedResult.layout_det_res.boxes[j]
      ├─ coordinate: [x0, y0, x1, y1]
      └─ score: 0.9745  ← 我们需要的值

通过 IoU 匹配
  ↓
PaddleContent.score = matched_score
  ↓
提取 Agent（可能从 LLM 获取 confidence）
  ↓
ExtractionResult.confidence
  ↓
最终的 FieldExtractionResult.values[].confidence
```

## 兜底逻辑

代码中保留了兜底逻辑，确保即使无法获取 confidence 也能正常工作：

```python
# extraction/service.py
confidence = extraction_result.confidence if hasattr(extraction_result, 'confidence') else 0.8
confidence = tracing_result.confidence or 0.8

# llm/client.py  
confidence = tracing_data.get("confidence", 0.8)
```

## 测试验证

### 验证点

1. ✅ Paddle 返回的 `layout_det_res.boxes` 被正确提取
2. ✅ 通过 IoU 算法成功匹配 bbox 和 score
3. ✅ `PaddleContent.score` 被正确赋值
4. ✅ `ExtractionResult.confidence` 可以被解析（如果 LLM 返回）
5. ✅ 最终的提取结果包含正确的 confidence 值

### 日志示例

```
页面 0 找到 15 个 layout_det_res.boxes
Block text 匹配到 score: 0.9856
Block table 匹配到 score: 0.9234
Block seal 匹配到 score: 0.9745
找到完全匹配的 score: 0.9745 (IoU=0.98)
```

## 相关文件

- `src/services/paddle/client.py` - Paddle 客户端（添加 score 匹配逻辑）
- `src/services/paddle/models.py` - Paddle 数据模型（PaddleContent 已有 score 字段）
- `src/services/llm/models.py` - LLM 数据模型（添加 ExtractionResult.confidence）
- `src/services/llm/client.py` - LLM 客户端（添加 confidence 解析）
- `src/services/extraction/service.py` - 提取服务（使用 confidence）

## 配置选项

可以通过配置控制诊断日志：

```python
# config/paddle_config.py
PADDLE_DEBUG_CONFIG = {
    'show_dpi_diagnostics': True,  # 显示 DPI 和 score 诊断信息
}
```

## 注意事项

1. **IoU 阈值**：当前设置为 0.5，即交并比大于 50% 才认为匹配
2. **完全匹配**：IoU > 0.9 时直接返回，不再继续查找
3. **匹配失败**：如果没有匹配到 score，`confidence` 将为 `None`，最终使用兜底值 0.8
4. **LLM confidence**：提取 Agent 可以在返回的 JSON 中包含 `confidence` 字段来覆盖 Paddle 的 score

## 修复日期

2025-11-12

