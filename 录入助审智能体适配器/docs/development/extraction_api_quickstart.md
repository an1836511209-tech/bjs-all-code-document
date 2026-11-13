# 字段提取API快速入门

## 前置准备

### 1. 安装依赖

```bash
poetry install
```

### 2. 启动服务

```bash
poetry run python -m src.main
```

服务将在 `http://localhost:8580` 启动。

### 3. 访问API文档

浏览器打开: http://localhost:8580/docs

## 快速测试

### 步骤1: 创建规则配置

如果还没有规则配置，先创建一个：

```bash
poetry run python scripts/create_sample_rules.py
```

这将创建示例规则配置，记下返回的 `config_id`。

### 步骤2: 准备测试文件

准备PDF、Word或图片文件，确保文件可访问（本地路径或URL）。

### 步骤3: 调用提取API

#### 使用curl测试

```bash
curl -X POST "http://localhost:8580/api/v1/extraction/sync" \
  -H "Content-Type: application/json" \
  -d '{
    "extraction_type": "大宗实物",
    "files": [
      {
        "file_url": "/path/to/your/file.pdf",
        "file_name": "信息披露申请书.pdf",
        "file_type": "info_disclosure_application"
      }
    ],
    "rule_config_id": "YOUR_CONFIG_ID",
    "timeout": 1000,
    "request_id": "test_001"
  }'
```

#### 使用Python测试

```python
import requests

url = "http://localhost:8580/api/v1/extraction/sync"

payload = {
    "extraction_type": "大宗实物",
    "files": [
        {
            "file_url": "/path/to/your/file.pdf",
            "file_name": "信息披露申请书.pdf",
            "file_type": "info_disclosure_application"
        }
    ],
    "rule_config_id": "YOUR_CONFIG_ID",
    "timeout": 1000,
    "request_id": "test_001"
}

response = requests.post(url, json=payload)
print(response.json())
```

### 步骤4: 查看结果

响应包含：
- 提取的字段值
- 溯源信息（来源文件、页码、坐标）
- PDF高亮预览图（base64）
- 置信度

```json
{
  "status": "success",
  "results": [
    {
      "field_name": "坐落位置",
      "extracted_value": "北京市朝阳区xxx",
      "tracing_info": {
        "source_file_name": "信息披露申请书.pdf",
        "page_idx": 0,
        "bbox": [52, 61.96, 294, 82.99],
        "confidence": 0.95,
        "preview_image": "data:image/png;base64,..."
      }
    }
  ]
}
```

## 文件类型说明

支持的文件类型（FileType枚举）：

| 枚举值 | 中文名称 |
|--------|---------|
| info_disclosure_application | 《信息披露申请书》 |
| evaluation_report | 《评估报告》 |
| evaluation_filing | 《评估备案表》 |
| internal_decision | 《内部决议文件》 |
| business_license | 《营业执照》 |
| asset_list | 《资产清单》 |
| inspection_management | 《踏勘管理办法》 |
| property_certificate | 《房屋产权证》 |
| land_use_contract | 《国有建设用地使用权出让合同》 |
| vehicle_certificate | 《机动车登记证书》 |
| ship_certificate | 《船舶所有权证书》 |
| aircraft_certificate | 《适航证》 |
| patent_certificate | 《专利证书》 |

## 常见问题排查

### 1. 提取失败

**检查项**:
- MinerU服务是否可用
- LLM Agent接口是否可访问
- 文件路径是否正确
- 规则配置是否存在

**查看日志**:
```bash
tail -f logs/app.log
```

### 2. 溯源失败

**可能原因**:
- 提取结果与原文差异较大
- middle.json格式问题
- LLM溯源Agent异常

**解决方法**:
- 检查提取逻辑描述是否清晰
- 调整模糊匹配阈值
- 查看溯源Agent响应日志

### 3. 性能较慢

**优化建议**:
- 调整并发配置（config/llm_config.py）
- 减少不必要的规则
- 使用文件缓存

## 配置调整

### 调整并发数

编辑 `config/llm_config.py`:

```python
CONCURRENCY_CONFIG = ConcurrencyConfig(
    extraction_workers=10,  # 增加到10个并发
    tracing_workers=5,
    audit_workers=3
)
```

### 调整模糊匹配阈值

编辑 `src/services/extraction/service.py`:

```python
self.text_matcher = TextMatcher(fuzzy_threshold=0.7)  # 降低阈值
```

### 调整LLM超时

编辑 `config/llm_config.py`:

```python
AgentConfig(
    ...
    timeout=600,  # 增加到600秒
    max_retries=5  # 增加重试次数
)
```

## 完整示例

### 示例1: 提取单个文件的多个字段

```python
import requests
import json

def test_extraction():
    url = "http://localhost:8580/api/v1/extraction/sync"
    
    payload = {
        "extraction_type": "大宗实物",
        "files": [
            {
                "file_url": "tests/fixtures/sample_application.pdf",
                "file_name": "信息披露申请书.pdf",
                "file_type": "info_disclosure_application"
            }
        ],
        "rule_config_id": "827f1bc9-69e9-4847-9229-7112913e4707",
        "request_id": "test_single_file"
    }
    
    print("发送提取请求...")
    response = requests.post(url, json=payload)
    
    if response.status_code == 200:
        result = response.json()
        print(f"\n提取状态: {result['status']}")
        print(f"成功字段: {result['success_count']}/{result['total_fields']}")
        print(f"处理时间: {result['processing_time_ms']}ms\n")
        
        # 打印每个字段的结果
        for field in result['results']:
            print(f"字段: {field['field_name']}")
            print(f"  值: {field['extracted_value']}")
            print(f"  状态: {field['extraction_status']}")
            
            if field.get('tracing_info'):
                tracing = field['tracing_info']
                print(f"  来源: {tracing['source_file_name']}")
                print(f"  页码: {tracing['page_idx']}")
                print(f"  置信度: {tracing['confidence']}")
            print()
    else:
        print(f"请求失败: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    test_extraction()
```

### 示例2: 提取多个文件

```python
def test_multi_file_extraction():
    url = "http://localhost:8580/api/v1/extraction/sync"
    
    payload = {
        "extraction_type": "大宗实物",
        "files": [
            {
                "file_url": "tests/fixtures/application.pdf",
                "file_name": "信息披露申请书.pdf",
                "file_type": "info_disclosure_application"
            },
            {
                "file_url": "tests/fixtures/property_cert.pdf",
                "file_name": "房屋产权证.pdf",
                "file_type": "property_certificate"
            }
        ],
        "rule_config_id": "827f1bc9-69e9-4847-9229-7112913e4707",
        "request_id": "test_multi_files"
    }
    
    response = requests.post(url, json=payload)
    return response.json()
```

## 下一步

- 查看详细开发文档: `docs/extraction_api_development.md`
- 查看API规范: `docs/api/api-specification.yaml`
- 配置生产环境: 编辑 `config/llm_config.py`
- 添加自定义规则: 访问 http://localhost:8580/web/rule-configs

## 技术支持

如遇问题，请查看：
1. 服务日志: `logs/app.log`
2. API文档: http://localhost:8580/docs
3. 开发文档: `docs/extraction_api_development.md`

