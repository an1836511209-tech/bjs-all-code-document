# 字段提取API开发文档

## 概述

本文档描述字段提取功能的实现细节，包括LLM对接、文本匹配、溯源定位和PDF高亮等核心功能。

## 技术架构

### 1. 核心流程

```
用户请求 → API端点 → 提取服务 → MinerU解析 → LLM提取 → 文本匹配/LLM溯源 → PDF高亮 → 返回结果
```

### 2. 目录结构

```
config/
  └── llm_config.py              # LLM Agent配置（开发和生产环境）

src/
  ├── api/v1/endpoints/
  │   └── extraction.py          # 字段提取API端点
  │
  ├── schemas/
  │   └── extraction.py          # 提取请求和响应模型
  │
  └── services/
      ├── extraction/
      │   ├── __init__.py
      │   └── service.py         # 字段提取服务（核心逻辑）
      │
      └── llm/
          ├── __init__.py
          ├── client.py          # LLM客户端（提取和溯源Agent）
          ├── models.py          # LLM数据模型
          └── text_matcher.py    # 文本匹配工具
```

## LLM Agent配置

### 配置文件：`config/llm_config.py`

配置包含：
- **开发环境配置**（DEV_CONFIG）：当前使用的UAT环境
- **生产环境配置**（PROD_CONFIG）：待配置
- **并发配置**（CONCURRENCY_CONFIG）：
  - extraction_workers: 5（字段提取并发数）
  - tracing_workers: 3（字段溯源并发数）
  - audit_workers: 3（字段审核并发数）

### 环境切换

```python
from config.llm_config import LLMConfig

# 切换到生产环境
LLMConfig.set_environment("prod")

# 获取配置
extraction_config = LLMConfig.get_extraction_agent_config()
tracing_config = LLMConfig.get_tracing_agent_config()
```

## LLM Agent调用

### 1. 字段提取Agent

**Agent ID**: `f526d16a58db42698d574adfba7fb397`

**输入参数**:
```python
{
    "agentId": "f526d16a58db42698d574adfba7fb397",
    "userChatInput": "",
    "state": {
        "file_content": "文件内容（content_list.json）",
        "field_name": "字段名称",
        "extraction_logic": "提取逻辑描述",
        "reference_materials": "参考材料名称"
    }
}
```

**响应解析**:
- 取 `choices` 数组的最后一个元素
- 使用正则提取 ```json ... ``` 中的JSON对象
- 从JSON中提取 `提取结果` 字段

### 2. 字段溯源Agent

**Agent ID**: `34f65628b11c41a8ad16c5aa32c7b458`

**输入参数**:
```python
{
    "agentId": "34f65628b11c41a8ad16c5aa32c7b458",
    "userChatInput": "",
    "state": {
        "file_content": "文件内容（middle.json）",
        "field_name": "字段名称",
        "extraction_logic": "提取逻辑",
        "reference_materials": "参考材料",
        "extraction_result": "提取结果"
    }
}
```

**响应解析**:
- 取 `choices` 数组的最后一个元素
- 使用正则提取 ```json ... ``` 中的JSON对象
- 从JSON中提取 `定位结果` 字段，包含：
  - matched_text: 匹配的文本
  - page_idx: 页码索引
  - bbox: 边界框坐标 [x0, y0, x1, y1]
  - match_type: 匹配类型
  - confidence: 置信度

## 核心功能实现

### 1. 文件解析

使用MinerU将文件解析为两种格式：
- **content_list.json**: 用于LLM字段提取
- **middle.json**: 用于字符串匹配和LLM溯源

### 2. 字段提取流程

```python
for rule in extraction_rules:
    for reference_material in rule.reference_materials:
        # 1. 找到对应的解析文件
        file_data = find_file_by_material(reference_material)
        
        # 2. 调用LLM提取Agent
        extraction_result = await extraction_agent.extract_field(
            file_content=file_data["content_list_json"],
            field_name=rule.field_name,
            extraction_logic=rule.extraction_logic,
            reference_materials=reference_material
        )
        
        # 3. 溯源定位
        tracing_result = await trace_field(extraction_result)
        
        # 4. 生成PDF高亮
        preview_image = await generate_highlight(tracing_result)
        
        # 5. 返回结果
        return FieldExtractionResult(...)
```

### 3. 字段溯源流程

溯源采用三级策略：

**Level 1: 精确匹配**
- 在middle.json中查找完全匹配的文本
- 如果找到，直接返回位置信息
- 置信度: 1.0

**Level 2: 模糊匹配**
- 使用SequenceMatcher计算文本相似度
- 阈值: 0.8
- 如果找到唯一匹配，返回位置信息
- 置信度: 相似度分数

**Level 3: LLM溯源**
- 如果前两级都失败，调用LLM溯源Agent
- 让LLM在middle.json中定位提取结果
- 置信度: 0.8（默认）

### 4. PDF高亮生成

```python
from src.utils.pdf_highlighter import PDFHighlighter, BBox

highlighter = PDFHighlighter(pdf_path)
bbox = BBox.from_list([x0, y0, x1, y1])
base64_image = highlighter.highlight_and_convert_to_base64(
    page_idx=page_idx,
    bboxes=[bbox]
)
```

## API接口

### 同步字段提取

**端点**: `POST /api/v1/extraction/sync`

**请求示例**:
```json
{
    "extraction_type": "大宗实物",
    "files": [
        {
            "file_url": "https://example.com/files/application.pdf",
            "file_name": "信息披露申请书.pdf",
            "file_type": "info_disclosure_application"
        },
        {
            "file_url": "https://example.com/files/certificate.pdf",
            "file_name": "房屋所有权证.pdf",
            "file_type": "property_certificate"
        }
    ],
    "rule_config_id": "827f1bc9-69e9-4847-9229-7112913e4707",
    "timeout": 1000,
    "request_id": "req_20251103_001"
}
```

**响应示例**:
```json
{
    "request_id": "req_20251103_001",
    "task_id": null,
    "status": "success",
    "extraction_type": "大宗实物",
    "rule_config_id": "827f1bc9-69e9-4847-9229-7112913e4707",
    "results": [
        {
            "field_id": "e3a40559-74d2-4a11-b949-a67f3a2cabee",
            "field_name": "坐落位置",
            "field_type": "text",
            "extracted_value": "北京市朝阳区xxx",
            "extraction_status": "success",
            "tracing_info": {
                "source_file_type": "《信息披露申请书》",
                "source_file_name": "信息披露申请书.pdf",
                "field_name": "坐落位置",
                "matched_text": "坐落位置为北京市朝阳区xxx",
                "preview_image": "data:image/png;base64,iVBORw0KG...",
                "page_idx": 0,
                "bbox": [52, 61.96, 294, 82.99],
                "confidence": 0.95,
                "match_type": "exact"
            },
            "error_message": null
        }
    ],
    "total_fields": 3,
    "success_count": 3,
    "failed_count": 0,
    "processing_time_ms": 5230
}
```

## 并发控制

使用asyncio.Semaphore控制并发数：

```python
# 字段提取并发控制
extraction_semaphore = asyncio.Semaphore(5)  # 最多5个并发

# 字段溯源并发控制
tracing_semaphore = asyncio.Semaphore(3)  # 最多3个并发
```

配置位置: `config/llm_config.py` → `CONCURRENCY_CONFIG`

## 错误处理

### 1. LLM调用失败
- 自动重试3次（可配置）
- 记录详细错误日志
- 返回错误信息给用户

### 2. 文件解析失败
- 跳过该文件，继续处理其他文件
- 在结果中标记为失败

### 3. 溯源失败
- 仍然返回提取结果
- tracing_info为空
- 不影响整体流程

## 测试

### 测试准备
1. 确保MinerU服务可用
2. 确保LLM Agent可访问
3. 准备测试文件和规则配置

### 测试命令
```bash
# 启动服务
poetry run python -m src.main

# 访问API文档
http://localhost:8580/docs

# 测试同步提取接口
POST http://localhost:8580/api/v1/extraction/sync
```

## 性能优化建议

1. **并发控制**: 根据服务器性能调整并发数
2. **缓存策略**: 缓存MinerU解析结果
3. **异步处理**: 对于大量字段，使用异步任务队列
4. **批量处理**: 批量调用LLM API减少网络开销
5. **超时控制**: 合理设置各环节超时时间

## 待开发功能

- [ ] 流式提取接口（SSE）
- [ ] 异步任务查询接口
- [ ] 提取结果缓存
- [ ] 提取进度回调
- [ ] 批量提取优化

## 生产环境配置

### 1. 更新LLM配置

编辑 `config/llm_config.py`:

```python
PROD_CONFIG = {
    "extraction_agent": AgentConfig(
        agent_id="PROD_EXTRACTION_AGENT_ID",  # 替换为生产环境ID
        base_url="https://api.agentspro.cn/...",  # 替换为生产环境URL
        api_key="PROD_API_KEY",  # 替换为生产环境Key
        timeout=300,
        max_retries=3
    ),
    "tracing_agent": AgentConfig(
        agent_id="PROD_TRACING_AGENT_ID",
        base_url="https://api.agentspro.cn/...",
        api_key="PROD_API_KEY",
        timeout=300,
        max_retries=3
    )
}
```

### 2. 切换环境

```python
from config.llm_config import LLMConfig

# 启动时切换到生产环境
LLMConfig.set_environment("prod")
```

## 常见问题

### Q1: LLM调用超时怎么办？
A: 增加timeout配置，或使用异步任务处理长时间任务。

### Q2: 溯源匹配不准确怎么办？
A: 调整模糊匹配阈值（fuzzy_threshold），或优化提取逻辑描述。

### Q3: 并发数设置多少合适？
A: 根据服务器CPU核心数和网络带宽决定，建议：
- extraction_workers: CPU核心数
- tracing_workers: CPU核心数 * 0.5

### Q4: 如何调试LLM调用？
A: 查看日志，日志包含完整的请求和响应数据：
```
logger.debug(f"请求参数: {request.model_dump()}")
logger.debug(f"响应数据: {response_data}")
```

## 更新日志

### v1.0.0 (2025-11-03)
- 初始版本
- 实现LLM字段提取和溯源
- 实现三级溯源策略（精确/模糊/LLM）
- 实现PDF高亮生成
- 实现同步提取API

---

**维护者**: AI Assistant  
**最后更新**: 2025-11-03

