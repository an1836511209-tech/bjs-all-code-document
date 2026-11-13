# 统一提取溯源架构 (Anchor Markdown)

## 概述

本文档描述了 v3.3 版本中对提取和溯源流程的重大架构重构。核心改动是将原本分离的「提取」和「溯源」两次 LLM 调用合并为单次调用，通过创新的 **Anchor Markdown** 格式实现一次性完成提取和溯源。

## 背景与动机

### 原有架构问题

```
旧流程（两次 LLM 调用）：
1. 提取 Agent：从文档中提取字段值
2. 溯源 Agent：定位字段值在文档中的位置
   ↓
问题：
- Token 消耗大（文档内容发送两次）
- 延迟高（两次 API 调用）
- 信息不一致风险（提取和溯源可能定位到不同位置）
```

### 新架构优势

```
新流程（单次 LLM 调用）：
1. 统一提取溯源 Agent：同时完成提取和定位
   ↓
优势：
- Token 消耗减少 50%+
- 延迟降低 40%+
- 提取和溯源结果完全一致
```

## 核心概念

### Anchor Markdown

**Anchor Markdown** 是一种带有位置锚点的 Markdown 格式，将文档内容与坐标信息融合：

```markdown
# 信息披露申请书

## 一、基本信息

标的名称：广东省海珠区光大花园转让 (¶0-1)

坐落位置：广州市海珠区新港西路 (¶0-2)

| 项目 | 内容 |
|------|------|
| 联系人 (¶1-0) | 张三 (¶1-1) |
| 联系电话 (¶1-2) | 13800138000 (¶1-3) |

[印章: 广州市某某公司] (¶2-0)
```

### 锚点格式

- **格式**：`(¶P-ID)`
- **P**：页码索引（0-based）
- **ID**：该页内的片段索引
- **示例**：`(¶0-12)` 表示第 0 页的第 12 个片段

### Segment Map（片段映射表）

后端维护一个映射表，将锚点 ID 映射到精确坐标：

```python
segment_map = {
    "0-1": SegmentInfo(
        anchor_id="0-1",
        page_idx=0,
        bbox=[100, 200, 500, 250],  # [x0, y0, x1, y1]
        text="广东省海珠区光大花园转让",
        segment_type="text"
    ),
    "0-2": SegmentInfo(
        anchor_id="0-2",
        page_idx=0,
        bbox=[100, 260, 450, 310],
        text="广州市海珠区新港西路",
        segment_type="text"
    ),
    "2-0": SegmentInfo(
        anchor_id="2-0",
        page_idx=2,
        bbox=[300, 500, 450, 650],
        text="广州市某某公司",
        segment_type="seal",
        score=0.95
    )
}
```

## 架构设计

### 处理流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        统一提取溯源流程                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. 文件解析（Paddle/MinerU）                                    │
│     └─→ parse_results: List[PaddleParseResult]                  │
│                                                                 │
│  2. Anchor Markdown 转换                                        │
│     └─→ AnchorMarkdownConverter.convert(file_data)              │
│         ├─→ tagged_markdown: str  (给 LLM 看)                   │
│         └─→ segment_map: Dict[str, SegmentInfo]  (给后端查表)    │
│                                                                 │
│  3. RAG 检索（如需）                                             │
│     └─→ 如果内容超过阈值，检索相关页面                            │
│                                                                 │
│  4. 调用统一提取 Agent                                           │
│     └─→ 输入：tagged_markdown + 字段名 + 提取逻辑                │
│     └─→ 输出：extracted_value + anchor_ids                      │
│                                                                 │
│  5. 坐标查表                                                     │
│     └─→ 根据 anchor_ids 从 segment_map 获取 bbox                │
│                                                                 │
│  6. 高亮生成                                                     │
│     └─→ 在 PDF 对应位置绘制高亮框                                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 核心组件

#### 1. AnchorMarkdownConverter

位置：`src/utils/anchor_markdown_converter.py`

职责：
- 将 Paddle/MinerU 解析结果转换为 Anchor Markdown
- 生成片段映射表（segment_map）
- 支持多文件合并（全局页码连续）
- 处理印章、表格等特殊元素

```python
class AnchorMarkdownConverter:
    @classmethod
    def convert(cls, file_data: Dict) -> Tuple[str, Dict[str, SegmentInfo]]:
        """转换为 Anchor Markdown"""
        pass
    
    @classmethod
    def lookup_bboxes_by_anchors(
        cls, 
        anchor_ids: List[str], 
        segment_map: Dict[str, SegmentInfo]
    ) -> List[AnchorBboxInfo]:
        """根据锚点 ID 查找坐标"""
        pass
    
    @classmethod
    def merge_bboxes(cls, bboxes: List[List[float]]) -> List[float]:
        """合并多个 bbox 为一个包围框"""
        pass
```

#### 2. UnifiedExtractionAgent

位置：`src/services/llm/client.py`

职责：
- 调用统一提取溯源 Agent
- 解析 LLM 返回的 JSON 结果
- 提取 anchor_ids 列表

```python
class UnifiedExtractionAgent:
    async def extract_and_trace(
        self,
        file_content: str,      # Anchor Markdown
        field_name: str,
        extraction_logic: str,
        reference_materials: str
    ) -> UnifiedExtractionResult:
        pass
```

#### 3. RegionInfo

位置：`src/schemas/extraction.py`

用于保存多个高亮区域信息：

```python
class RegionInfo(BaseModel):
    page_idx: int           # 页面索引（0-based）
    bbox: List[float]       # 坐标 [x0, y0, x1, y1]

class SourceInfo(BaseModel):
    # ... 其他字段
    regions: Optional[List[RegionInfo]]  # 所有高亮区域
```

## LLM Prompt 设计

### System Prompt

```markdown
# Role
你是一个高精度高性能的文档信息提取与溯源专家。

# Input Format (Anchor Markdown)
输入的文档内容是 Markdown 格式，但经过了特殊处理：
1. **文本锚点**：每个文本片段后面都紧跟一个位置标签，格式为 `(¶P-ID)`
2. **印章/手写体**：印章或手写内容会被特殊标记

# Task
1. 根据【目标字段】和【提取逻辑】，在文档中定位信息
2. 提取字段的文本值
3. 收集该信息来源的所有锚点 ID

# Constraints
1. **精准引用**：anchor_ids 必须严格对应提取值所在的文本片段
2. **印章优先**：如果提取逻辑要求"以印章为准"，必须引用印章锚点
3. **表格处理**：引用包含具体值的单元格锚点，不要引用表头
4. **空值处理**：如果未找到，extracted_value 设为 ""，anchor_ids 设为 []
5. **严禁臆造 ID**：绝对不要生成文档中不存在的 ID

# Output Format
### Analysis:
[简要分析提取思路]

### Result:
```json
{
    "field_name": "目标字段名",
    "extracted_value": "提取到的值",
    "confidence": 0.95,
    "anchor_ids": ["0-12", "0-13"]
}
```
```

## RAG 集成

### 配置文件

位置：`config/rag_config.py`

```python
# RAG 核心配置
RAG_ENABLED = True
RAG_MAX_LENGTH = 10000      # 触发阈值（字符数）
RAG_TOP_K = 10              # Embedding 召回数
RAG_FINAL_TOP_K = 5         # Rerank 后保留数

# Embedding 服务
EMBEDDING_MODEL = "Qwen3-Embedding-0.6B"
EMBEDDING_URL = "http://10.224.98.172/v1/embeddings"

# Rerank 服务
RERANKER_MODEL = "Qwen3-Reranker-0.6B"
RERANKER_URL = "http://10.224.98.172/v1/rerank"
```

### RAG 处理流程

```
1. 检查 Anchor Markdown 长度
   └─→ 如果 > RAG_MAX_LENGTH，启用 RAG

2. 构建查询
   └─→ query = f"{field_name} {extraction_logic}"

3. 检索相关页面
   └─→ Embedding 召回 → Rerank 排序 → 取 Top K

4. 过滤 parse_results
   └─→ 只保留 RAG 命中的页面

5. 重新生成 Anchor Markdown
   └─→ 基于过滤后的 parse_results
```

## 多文件高亮合并

### 问题场景

当 LLM 返回的锚点来自不同文件时（如 `info_disclosure_application` 包含 2 个 PDF），需要分别生成高亮并合并。

### 解决方案

```python
async def _generate_multi_file_highlight(
    self,
    file_data: Dict,
    file_regions_map: Dict[int, List[Tuple[int, List[float]]]],
    parse_results: List,
    file_paths: List[str]
) -> Optional[str]:
    """
    多文件高亮合并流程：
    1. 按文件索引分组 regions
    2. 计算每个文件的全局页码偏移
    3. 为每个文件分别生成高亮图
    4. 按全局页码排序
    5. 垂直拼接所有高亮图
    6. 上传合并后的图片
    """
```

### 页码计算

```
文件1: 8 页 (全局页码 0-7)
文件2: 5 页 (全局页码 8-12)

锚点 "10-3" 表示：
- 全局第 10 页
- 属于文件2（因为 10 >= 8）
- 在文件2中的实际页码 = 10 - 8 = 2
```

## 性能优化

### Anchor Markdown 缓存

同一文件只转换一次，多字段复用：

```python
# 预处理阶段
anchor_markdown_cache: Dict[str, Tuple[str, Dict]] = {}
for file_type, file_data in parsed_files.items():
    tagged_markdown, segment_map = AnchorMarkdownConverter.convert(file_data)
    anchor_markdown_cache[file_type] = (tagged_markdown, segment_map)

# 提取阶段（复用缓存）
if file_type in anchor_markdown_cache:
    tagged_markdown, segment_map = anchor_markdown_cache[file_type]
```

### 异步 RAG

RAG 检索改为异步方法，避免阻塞：

```python
async def get_relevant_content(
    self,
    parse_results: List,
    query: str,
    top_k: Optional[int] = None
) -> Tuple[str, str]:
    # 异步调用 Embedding 和 Rerank 服务
    pass
```

## 配置说明

### LLM 配置

位置：`config/llm_config.py`

```python
# 统一提取溯源 Agent
"unified_extraction_agent": AgentConfig(
    agent_id="xxx",
    base_url="https://xxx/openapi/agents/chat/completions/v1",
    api_key="xxx",
    timeout=300,
    max_retries=2
)

# 并发配置
unified_extraction_workers: int = 5
```

## 迁移指南

### 从旧版本升级

1. **更新依赖**
   ```bash
   poetry install
   ```

2. **配置新 Agent**
   - 在 `config/llm_config.py` 中添加 `unified_extraction_agent` 配置
   - 配置 RAG 服务地址（`config/rag_config.py`）

3. **验证功能**
   - 运行提取测试，检查日志中的 "Anchor Markdown 转换完成"
   - 验证高亮图是否正确显示

### 兼容性说明

- API 接口保持不变
- 响应格式保持不变
- 旧的提取/溯源 Agent 配置可以保留（作为降级方案）

## 故障排查

### 常见问题

#### 1. 锚点 ID 不存在

**现象**：LLM 返回的 anchor_ids 在 segment_map 中找不到

**原因**：
- LLM 幻觉，生成了不存在的 ID
- RAG 过滤后 segment_map 被重新生成，ID 变化

**解决**：
- 检查 Prompt 是否强调"严禁臆造 ID"
- 确保 RAG 过滤后保留原始 segment_map

#### 2. 页码超出范围

**现象**：`页码 11 超出范围（PDF 共 8 页）`

**原因**：多文件场景下，全局页码没有正确转换为文件内页码

**解决**：
- 使用 `_locate_file_by_page` 定位正确的文件
- 使用 `_calculate_actual_page_idx` 计算文件内页码

#### 3. 高亮位置偏移

**现象**：高亮框位置与实际文本不符

**原因**：
- 坐标系统不一致（Paddle vs MinerU）
- 页面尺寸计算错误

**解决**：
- 检查 `backend` 参数是否正确传递
- 验证 bbox 坐标单位（像素 vs 点）

## 相关文档

- [Paddle 集成文档](paddle_integration.md)
- [Paddle 坐标系统](paddle_coordinate_system.md)
- [RAG 配置说明](../../config/rag_config.py)

---

**文档版本**: v1.0  
**最后更新**: 2025-12-01




