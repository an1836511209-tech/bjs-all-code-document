# Paddle 集成文档

## 概述

本系统已集成 PaddleOCR-VL 和 Paddle 印章文本识别服务，作为主要的文档解析引擎，MinerU 作为降级备选方案。

## 架构设计

### 服务优先级

```
PDF/图片文件解析流程：
1. 优先使用 Paddle（PaddleOCR-VL + 印章识别）
2. Paddle 服务故障 → 自动降级到 MinerU
3. 确保服务高可用性
```

### 核心能力

#### 1. PaddleOCR-VL
- **功能**：版面解析、OCR 识别、表格识别、公式识别
- **特点**：高精度、支持印章检测（但不识别印章文本）
- **API 地址**：`https://uu219808-b8d0-9a9ee4b7.westx.seetacloud.com:8443/layout-parsing`

#### 2. Paddle 印章识别
- **功能**：印章文本识别
- **特点**：专门识别印章中的文字内容
- **API 地址**：`http://35.187.206.132:8081/seal-recognition`

#### 3. 印章处理流程
```
1. PaddleOCR-VL 识别文档 → 检测到印章，标记为 'seal'，输出 base64
2. 提取印章 base64 图像
3. 调用印章识别服务 → 识别印章中的文字
4. 将印章文字合并到文档内容中 → 【印章：xxx】
5. 返回完整的解析结果
```

## 数据兼容性

### 与 MinerU 的兼容性

Paddle 解析结果完全兼容 MinerU 的数据结构，确保上下游无缝切换：

| 数据模型 | Paddle | MinerU | 说明 |
|---------|--------|--------|------|
| ParseResult | ✅ | ✅ | 顶层解析结果 |
| ParsedPage | ✅ | ✅ | 页面对象 |
| Content | ✅ | ✅ | 内容块（text/table/image等） |
| LayoutBlock | ✅ | ✅ | 布局块（用于溯源） |
| md_content | ✅ | ✅ | Markdown 文本（LLM 提取） |

### 新增字段

Paddle 解析结果新增了印章相关字段：

```python
@dataclass
class PaddleContent:
    type: str  # 新增类型：'seal'
    image_base64: Optional[str]  # 印章图像（base64）
    text: Optional[str]  # 印章文本（格式：【印章：xxx】）
```

## 配置说明

### 配置文件

```python
# config/paddle_config.py

# API 配置
PADDLE_API_CONFIG = {
    'ocr_vl': {
        'base_url': 'https://uu219808-b8d0-9a9ee4b7.westx.seetacloud.com:8443',
        'endpoint': '/layout-parsing',
        'timeout': 300,
    },
    'seal_recognition': {
        'base_url': 'http://35.187.206.132:8081',
        'endpoint': '/seal-recognition',
        'timeout': 60,
    }
}

# 印章提取配置
PADDLE_SEAL_CONFIG = {
    'enabled': True,  # 是否启用印章文本提取
    'merge_seal_text': True,  # 是否将印章文本合并到主文本中
    'seal_text_format': '【印章：{text}】',  # 印章文本格式
}

# 错误处理配置
PADDLE_ERROR_CONFIG = {
    'fallback_to_mineru': True,  # Paddle 故障时是否降级到 MinerU
}
```

### 关键配置项

| 配置项 | 说明 | 默认值 |
|-------|------|-------|
| `enabled` | 是否启用印章识别 | True |
| `merge_seal_text` | 是否将印章文本合并到 Markdown | True |
| `seal_text_format` | 印章文本的标记格式 | `【印章：{text}】` |
| `fallback_to_mineru` | 是否启用降级策略 | True |

## 使用示例

### 基本使用

```python
from src.services.paddle.client import PaddleClient

# 创建客户端
async with PaddleClient() as client:
    # 解析文件
    result = await client.parse_file(
        file_path='document.pdf'
    )
    
    # 查看结果
    print(f"解析成功: {result.success}")
    print(f"总页数: {result.total_pages}")
    print(f"Markdown 内容:\n{result.md_content}")
    
    # 查看印章
    for page in result.pages:
        seal_contents = [c for c in page.contents if c.type == 'seal']
        for seal in seal_contents:
            print(f"印章文本: {seal.text}")
```

### 在 ExtractionService 中的使用

```python
# ExtractionService 会自动使用 Paddle
# 无需修改调用代码，完全透明

# 示例：提取字段
result = await extraction_service.extract_fields(request)

# 解析引擎选择逻辑：
# 1. 尝试使用 Paddle 解析
# 2. Paddle 失败 → 自动降级到 MinerU
# 3. 返回统一格式的结果
```

## 降级策略

### 自动降级场景

1. **Paddle 服务不可用**
   - 网络超时
   - 服务返回错误状态码
   - API 调用失败

2. **解析失败**
   - Paddle 返回 `errorCode != 0`
   - 解析结果为空
   - 数据转换异常

### 降级行为

```
Paddle 失败 → 记录警告日志 → 调用 MinerU → 返回结果
```

### 日志示例

```
[WARNING] Paddle 服务故障: 请求超时，降级到 MinerU
[INFO] 使用 MinerU 解析文件: document.pdf
[INFO] MinerU 解析成功（降级）: document.pdf
```

## API 响应格式

### PaddleOCR-VL 响应

```json
{
  "logId": "uuid",
  "errorCode": 0,
  "errorMsg": "Success",
  "result": {
    "layoutParsingResults": [
      {
        "prunedResult": {
          "page_info": {
            "page_idx": 0,
            "width": 595,
            "height": 842
          },
          "layout_dets": [
            {
              "category_type": "text",
              "bbox": [100, 100, 500, 150],
              "text": "文本内容"
            },
            {
              "category_type": "seal",
              "bbox": [200, 300, 400, 500],
              "image_base64": "base64..."
            }
          ]
        },
        "markdown": {
          "text": "Markdown 文本",
          "images": {},
          "isStart": true,
          "isEnd": true
        }
      }
    ]
  }
}
```

### Paddle 印章识别响应

```json
{
  "logId": "uuid",
  "errorCode": 0,
  "errorMsg": "Success",
  "result": {
    "sealRecResults": [
      {
        "prunedResult": {
          "seal_texts": [
            {
              "text": "公司印章",
              "score": 0.95
            }
          ]
        }
      }
    ]
  }
}
```

## 性能优化

### 并发处理

- 支持多文件并发解析
- 印章识别异步处理
- 自动失败重试（最多 3 次）

### 缓存机制

- 解析结果自动缓存（基于文件哈希）
- 避免重复解析相同文件

## 监控与日志

### 关键日志

```python
# 解析开始
logger.info(f"开始解析文件 | 文件: {file_name} | 大小: {size} 字节")

# Paddle 成功
logger.info(f"Paddle 解析成功: {file_name}")

# Paddle 失败，降级
logger.warning(f"Paddle 服务故障: {error}，降级到 MinerU")

# MinerU 降级成功
logger.info(f"MinerU 解析成功（降级）: {file_name}")

# 印章识别
logger.info(f"页面 {page_idx} 发现 {count} 个印章，开始识别")
logger.info(f"印章识别成功: {text}")
```

### 监控指标

- Paddle 成功率
- MinerU 降级率
- 平均解析时间
- 印章识别成功率

## 故障排查

### 常见问题

#### 1. Paddle 服务连接失败

**现象**：
```
PaddleError: API调用失败: 请求超时
```

**解决方案**：
- 检查网络连接
- 检查 Paddle 服务是否运行
- 查看配置中的 API 地址是否正确
- 系统会自动降级到 MinerU

#### 2. 印章识别失败

**现象**：
```
WARNING: 印章识别失败: ...
```

**解决方案**：
- 印章图像质量不佳
- 印章文字模糊
- 不影响主流程，只是印章文本为空

#### 3. 降级到 MinerU

**现象**：
```
INFO: MinerU 解析成功（降级）
```

**说明**：
- 这是正常的降级行为
- 确保服务高可用性
- 如果频繁降级，需要检查 Paddle 服务状态

## 参考资料

- [PaddleOCR-VL 文档](https://www.paddleocr.ai/latest/version3.x/pipeline_usage/PaddleOCR-VL.html)
- [Paddle 印章识别文档](https://www.paddleocr.ai/latest/version3.x/pipeline_usage/seal_recognition.html)
- MinerU 集成文档：`docs/services/mineru_usage.md`

## 更新日志

### 2025-11-12

- ✅ 集成 PaddleOCR-VL 服务
- ✅ 集成 Paddle 印章识别服务
- ✅ 实现 Paddle → MinerU 降级策略
- ✅ 确保数据格式兼容性
- ✅ 支持印章文本提取和合并









