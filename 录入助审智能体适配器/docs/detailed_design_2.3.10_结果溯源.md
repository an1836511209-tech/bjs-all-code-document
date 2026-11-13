# 2.3.10 录入-结果溯源子模块详细设计

> **⚠️ 文档已废弃**  
> **状态**: ❌ 已废弃（2025-12-04）  
> **替代方案**: 请查看 [v3 统一提取溯源架构](./detailed_design_2.3.10_结果溯源_v2.md)

---

## 废弃说明

本文档描述的是 **v1 传统溯源方案**，采用三级溯源策略：
1. 精确匹配（字符串匹配）
2. 模糊匹配（相似度算法）
3. LLM溯源（兜底方案）

该方案已在 **v3.3 架构升级**中被完全替代，不再使用。

## 为什么废弃？

| 问题 | v1 传统溯源 | v3.3 统一提取溯源 |
|------|------------|-----------------|
| **LLM 调用次数** | 2 次（提取 + 溯源） | ✅ 1 次 |
| **Token 消耗** | ~8000 tokens | ✅ ~4000 tokens |
| **溯源准确率** | ~85% | ✅ ~100% |
| **跨页支持** | 困难，需要复杂算法 | ✅ 原生支持 |
| **维护成本** | 高（三级策略） | ✅ 低（单一流程） |

---

## 新架构核心改进

### 1. Anchor Markdown 方案

将文档内容与坐标信息融合为一体，每个文本片段后附加锚点标签：

```markdown
甲方：北京某某公司 (¶0-0)
合同编号：2023-001 (¶0-2)
[印章: 合同专用章] (¶0-3)
```

### 2. 统一提取溯源

单次 LLM 调用同时完成提取和溯源：

**输入**：带锚点的 Markdown
**输出**：
```json
{
    "field_name": "甲方名称",
    "extracted_value": "北京某某公司",
    "confidence": 0.98,
    "anchor_ids": ["0-0"]  // 锚点 ID
}
```

**溯源**：
```python
# 根据 anchor_ids 查表获取坐标
bbox_infos = segment_map["0-0"]
# → {"page_idx": 0, "bbox": [100, 200, 500, 230]}
```

### 3. 性能提升

- ⚡ Token 消耗减少 **50%+**
- ⚡ 延迟降低 **40%+**
- ⚡ 准确率提升至 **~100%**
- ✅ 原生支持跨页/多框高亮
- ✅ 原生支持多文件合并

---

## 迁移指南

如果你正在使用 v1 传统溯源方案，请参考以下步骤迁移到 v3.3：

### 步骤1：移除废弃组件

```python
# ❌ 移除
from src.services.llm.text_matcher import TextMatcher
from src.services.llm.client import TracingAgent

# ✅ 使用新组件
from src.services.llm.client import UnifiedExtractionAgent
from src.utils.anchor_markdown_converter import AnchorMarkdownConverter
```

### 步骤2：更新提取流程

**旧方案**（v1）：
```python
# 1. 提取
result = await extraction_agent.extract_field(...)

# 2. 溯源
tracing_result = await text_matcher.find_in_middle_json(...)
if not tracing_result.success:
    tracing_result = await tracing_agent.trace_field(...)

# 3. 高亮
preview_url = await generate_highlight(...)
```

**新方案**（v3.3）：
```python
# 1. Anchor Markdown 转换
tagged_markdown, segment_map = AnchorMarkdownConverter.convert(file_data)

# 2. 统一提取溯源（单次调用）
result = await unified_agent.extract_and_trace(
    file_content=tagged_markdown,
    field_name=field_name,
    extraction_logic=extraction_logic
)

# 3. 坐标查表
bbox_infos = AnchorMarkdownConverter.lookup_bboxes_by_anchors(
    result.anchor_ids, segment_map
)

# 4. 高亮生成
preview_url = await generate_highlight_from_anchors(bbox_infos, ...)
```

### 步骤3：更新配置

**移除**：
```python
# config/llm_config.py
EXTRACTION_AGENT = {...}  # ❌ 废弃
TRACING_AGENT = {...}     # ❌ 废弃
```

**新增**：
```python
# config/llm_config.py
UNIFIED_EXTRACTION_AGENT = {
    "agent_id": "9c5ed10b9a82488ca2e6e36c189a8272",
    "timeout": 300,
    "max_retries": 2
}

CONCURRENCY = {
    "unified_extraction_workers": 5,
    "highlight_workers": 30
}
```

---

## 参考文档

- ✅ [v3.3 统一提取溯源架构](./detailed_design_2.3.10_结果溯源_v2.md) - **推荐阅读**
- ✅ [v3.3 字段提取子模块设计](./detailed_design_2.3.9_字段提取.md)
- ✅ [统一提取溯源服务文档](../services/unified_extraction_tracing.md)
- ✅ [README.md - v3.3 更新日志](../../README.md#v33-2025-12-01)

---

## 历史存档

如需查看原始 v1 设计文档（仅供参考），请查看 Git 历史记录：

```bash
# 查看 v1 版本的设计文档
git show v3.2:docs/detailed_design_2.3.10_结果溯源.md
```

---

**文档版本**: v1 (废弃)  
**废弃日期**: 2025-12-04  
**替代方案**: [v3 统一提取溯源架构](./detailed_design_2.3.10_结果溯源_v2.md)
