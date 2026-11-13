# 文本匹配与溯源优化

## 问题描述

### 1. 文本匹配过于宽泛

**现象**：
- 搜索"浙江省"（3个字）
- 匹配到"浙江省编号：3301051201601321146 国用（2016）第001912"（整个文本块）
- 返回整个文本块的 bbox

**问题**：
- 使用简单的 `if search_text in text_content` 导致子串匹配
- 短文本（如"浙江省"）容易误匹配到包含该文本的长文本块
- 返回的 bbox 是整个块的范围，不是精确的文本位置

### 2. PDF 高亮位置不准确

**现象**：
- 即使匹配到正确的文本块
- PDF 高亮的位置与实际文本位置有偏差

**可能原因**：
1. **坐标转换问题**：Paddle 像素坐标 vs PDF 点坐标
2. **块级 bbox 不够精确**：Paddle 只提供块级 bbox，无法精确到某几个字
3. **PDF 页面缩放**：PDF 实际渲染尺寸与坐标系不一致

## 解决方案

### 1. 优化文本匹配逻辑 ✅

**位置**: `src/services/llm/text_matcher.py` → `_exact_match()` 方法

**优化策略**：

#### 1.1 完全匹配优先

```python
# 完全匹配（最高优先级）
if text_content_clean == search_text:
    return TracingResult(...)
```

- 如果文本块内容完全等于搜索文本，直接返回
- 置信度：1.0

#### 1.2 包含匹配评分

```python
# 计算匹配分数：搜索文本占比越高，分数越高
match_score = len(search_text) / len(text_content_clean)
```

- 搜索文本在文本块中的占比
- 占比越高，匹配越精确

#### 1.3 短文本严格匹配

```python
is_short_text = len(search_text) <= 3

if is_short_text:
    # 短文本要求：
    # - 搜索文本长度 >= 文本内容长度的 50%，或
    # - 文本内容长度不超过搜索文本的 2 倍
    if match_score < 0.5 or len(text_content_clean) > len(search_text) * 2:
        continue  # 跳过不符合条件的匹配
```

**示例**：
- 搜索"浙江省"（3个字）
- 匹配到"浙江省编号：3301051201601321146..."（约30个字）
- 匹配分数：3 / 30 = 0.1（10%）
- 判断：0.1 < 0.5，且 30 > 3 * 2 = 6
- **结果：跳过此匹配**

#### 1.4 长文本宽松匹配

```python
else:
    # 长文本要求：搜索文本至少占 30%
    if match_score < 0.3:
        continue
```

**示例**：
- 搜索"浙江省杭州市拱墅区耀江国际大厦B座21层"（约20个字）
- 匹配到"标的名称:浙江省杭州市拱墅区耀江国际大厦B座21层 A、B、C、D 室房产..."（约40个字）
- 匹配分数：20 / 40 = 0.5（50%）
- 判断：0.5 >= 0.3
- **结果：接受此匹配，置信度 0.5**

#### 1.5 最佳匹配选择

```python
# 记录最佳匹配
if match_score > best_match_score:
    best_match_score = match_score
    best_match = TracingResult(...)

# 返回最佳匹配（如果有）
if best_match and best_match_score >= 0.5:  # 至少 50% 匹配度
    return best_match
```

- 遍历所有可能的匹配，选择匹配分数最高的
- 最终匹配分数必须 >= 0.5（50%）

### 2. PDF 高亮位置问题

#### 2.1 坐标转换验证

**已完成的优化**：
- ✅ Paddle 像素坐标 → PDF 点坐标（缩放因子 0.5）
- ✅ 页面尺寸统一转换
- ✅ 所有 bbox 统一转换

**验证方法**：

```python
# 检查转换后的坐标
logger.info(f"原始坐标（像素）: {paddle_bbox}")
logger.info(f"转换后坐标（点）: {pdf_bbox}")
logger.info(f"页面尺寸（点）: {page_width} x {page_height}")

# 验证坐标是否在页面范围内
assert 0 <= pdf_bbox[0] < pdf_bbox[2] <= page_width
assert 0 <= pdf_bbox[1] < pdf_bbox[3] <= page_height
```

#### 2.2 块级 bbox 精度问题

**根本限制**：
- Paddle 只提供**块级 bbox**
- 无法精确到某几个字的位置
- 高亮会覆盖整个文本块

**示例**：

```
文本块：浙江省编号：3301051201601321146 国用（2016）第001912
搜索：浙江省
bbox：[x0, y0, x1, y1]  ← 整个文本块的范围

高亮结果：整个文本块都被高亮
期望结果：只高亮"浙江省"三个字
```

**可能的解决方案**：

##### 方案 A：字符级位置估算

```python
def estimate_text_bbox(
    block_bbox: List[float],
    block_text: str,
    search_text: str
) -> Optional[List[float]]:
    """
    根据搜索文本在块文本中的位置，估算其精确 bbox
    
    假设：
    - 文本均匀分布在块中
    - 水平方向：根据字符位置比例计算 x 坐标
    - 垂直方向：使用整个块的高度
    """
    # 查找搜索文本在块文本中的位置
    start_index = block_text.find(search_text)
    if start_index == -1:
        return None
    
    end_index = start_index + len(search_text)
    
    # 计算字符位置比例
    total_length = len(block_text)
    start_ratio = start_index / total_length
    end_ratio = end_index / total_length
    
    # 估算 x 坐标
    x0, y0, x1, y1 = block_bbox
    width = x1 - x0
    
    estimated_x0 = x0 + width * start_ratio
    estimated_x1 = x0 + width * end_ratio
    
    # y 坐标保持不变（使用整个块的高度）
    return [estimated_x0, y0, estimated_x1, y1]
```

**使用**：

```python
# 在 _exact_match 中
if search_text in text_content:
    block_bbox = layout.get("bbox", [])
    
    # 尝试估算精确位置
    estimated_bbox = estimate_text_bbox(
        block_bbox,
        text_content,
        search_text
    )
    
    return TracingResult(
        bbox=estimated_bbox or block_bbox,  # 优先使用估算的 bbox
        ...
    )
```

**优点**：
- 可以部分提高精度
- 简单易实现

**缺点**：
- 假设文本均匀分布（实际可能不是）
- 无法处理换行、多行文本
- 仍然不如真正的字符级 bbox

##### 方案 B：使用 LLM 溯源（推荐）

对于精度要求高的场景，放弃文本匹配，直接使用 LLM 溯源：

```python
# 在 extraction/service.py 中
async def _trace_field(self, ...):
    middle_json = file_data["middle_json"]
    
    # 如果搜索文本过短或过长，跳过文本匹配，直接用 LLM
    if len(extracted_value) <= 3 or len(extracted_value) > 50:
        logger.info(f"字段 {field_name} 长度不适合文本匹配，直接使用 LLM 溯源")
        return await self._llm_trace(...)
    
    # 尝试文本匹配
    match_result = self.text_matcher.find_in_middle_json(...)
    
    if match_result and match_result.success:
        # 验证匹配质量
        if match_result.confidence >= 0.8:
            return match_result
        else:
            logger.info(f"文本匹配置信度较低 ({match_result.confidence:.2f})，使用 LLM 溯源")
            return await self._llm_trace(...)
    
    # 文本匹配失败，使用 LLM 溯源
    return await self._llm_trace(...)
```

##### 方案 C：降级到 MinerU（如果可用）

对于需要高精度溯源的场景，使用 MinerU 解析：

```python
# 在配置中设置
PADDLE_CONFIG = {
    'prefer_mineru_for_tracing': True,  # 溯源时优先使用 MinerU
}

# 在 extraction/service.py 中
if need_high_precision_tracing:
    # 使用 MinerU 重新解析（提供更精确的坐标）
    mineru_result = await self.mineru_client.parse_file(file_path)
```

**优点**：
- MinerU 提供**行级、span级** bbox
- 精度远高于 Paddle 的块级 bbox

**缺点**：
- 需要额外的解析时间
- 增加系统复杂度

### 3. 综合策略（推荐）

结合多种方案，提供分层策略：

```python
async def _trace_field_with_strategy(self, ...):
    """
    分层溯源策略：
    1. 文本完全匹配（置信度 1.0）→ 使用，即使 bbox 粗糙
    2. 文本部分匹配（置信度 >= 0.8）→ 尝试估算精确 bbox
    3. 文本匹配失败或置信度低（< 0.8）→ LLM 溯源
    4. LLM 溯源失败 → 如果可用，降级到 MinerU
    """
    
    # 1. 尝试文本匹配
    match_result = self.text_matcher.find_in_middle_json(...)
    
    if match_result and match_result.confidence == 1.0:
        # 完全匹配，直接使用
        logger.info(f"字段 {field_name} 完全匹配成功")
        return match_result
    
    if match_result and match_result.confidence >= 0.8:
        # 高置信度匹配，尝试估算精确 bbox
        logger.info(f"字段 {field_name} 高置信度匹配，尝试估算精确位置")
        estimated_bbox = estimate_text_bbox(
            match_result.bbox,
            match_result.matched_text,
            extracted_value
        )
        if estimated_bbox:
            match_result.bbox = estimated_bbox
            match_result.match_type = "exact_estimated"
        return match_result
    
    # 2. LLM 溯源
    logger.info(f"字段 {field_name} 文本匹配置信度较低或失败，使用 LLM 溯源")
    llm_result = await self._llm_trace(...)
    
    if llm_result and llm_result.success:
        return llm_result
    
    # 3. （可选）降级到 MinerU
    if self.config.get('enable_mineru_fallback'):
        logger.info(f"字段 {field_name} LLM 溯源失败，降级到 MinerU")
        return await self._trace_with_mineru(...)
    
    return None
```

## 优化效果

### 优化前

| 场景 | 搜索文本 | 匹配结果 | 问题 |
|------|----------|----------|------|
| 短文本 | "浙江省" | "浙江省编号：3301051201601321146..." | ❌ 误匹配 |
| 长文本 | "浙江省杭州市...B座21层" | "标的名称:浙江省杭州市...A、B、C、D 室..." | ✅ 正确，但 bbox 粗糙 |

### 优化后

| 场景 | 搜索文本 | 匹配结果 | 改进 |
|------|----------|----------|------|
| 短文本 | "浙江省" | 跳过误匹配 → LLM 溯源 | ✅ 精确 |
| 长文本 | "浙江省杭州市...B座21层" | 正确匹配 + 估算 bbox | ✅ 更精确 |
| 完全匹配 | "国用（2016）第001912 号" | "国用（2016）第001912 号" | ✅ 完美 |

## 实施计划

### Phase 1: 优化文本匹配（已完成）✅

- ✅ 实现完全匹配优先
- ✅ 实现匹配度评分
- ✅ 短文本严格匹配
- ✅ 长文本宽松匹配
- ✅ 最佳匹配选择

### Phase 2: 估算精确 bbox（待实施）

- [ ] 实现 `estimate_text_bbox()` 函数
- [ ] 在 `_exact_match()` 中集成
- [ ] 测试验证精度提升

### Phase 3: 分层溯源策略（待实施）

- [ ] 实现 `_trace_field_with_strategy()`
- [ ] 配置化策略选择
- [ ] 性能优化

### Phase 4: MinerU 降级（可选）

- [ ] 实现 MinerU 降级逻辑
- [ ] 缓存机制（避免重复解析）
- [ ] 成本评估

## 总结

本次优化主要解决了**文本匹配过于宽泛**的问题：

1. ✅ **完全匹配优先**：避免子串误匹配
2. ✅ **匹配度评分**：量化匹配质量
3. ✅ **短文本严格**：避免"浙江省"匹配到长文本
4. ✅ **最佳匹配**：选择最合适的结果

对于 **PDF 高亮位置不准确**的问题：

- **根本原因**：Paddle 只提供块级 bbox
- **短期方案**：字符级位置估算
- **长期方案**：LLM 溯源 + MinerU 降级

建议根据实际需求和性能要求，选择合适的方案组合。









