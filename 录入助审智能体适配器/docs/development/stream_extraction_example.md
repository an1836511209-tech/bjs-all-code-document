# 流式字段提取使用示例

## 概述

流式字段提取接口使用SSE（Server-Sent Events）实时返回提取进度和结果，适用于需要实时反馈的场景。

## 接口信息

- **URL**: `POST /api/v1/extraction/stream`
- **Content-Type**: `application/json`
- **Response-Type**: `text/event-stream`

## 事件类型

### 1. task_start - 任务开始
```json
{
  "task_id": "req_20251103_001",
  "total_fields": 10,
  "extraction_type": "大宗实物"
}
```

### 2. field_progress - 字段处理进度
```json
{
  "field_id": "field_001",
  "field_name": "坐落位置",
  "progress": 0.3,
  "current": 3,
  "total": 10
}
```

### 3. field_complete - 字段完成
```json
{
  "field_id": "field_001",
  "field_name": "坐落位置",
  "field_type": "text",
  "extracted_value": "北京市朝阳区xxx",
  "extraction_status": "success",
  "tracing_info": {
    "source_file_name": "信息披露申请书.pdf",
    "page_idx": 0,
    "bbox": [52, 61.96, 294, 82.99],
    "confidence": 0.95,
    "preview_image": "data:image/png;base64,..."
  },
  "error_message": null
}
```

### 4. task_complete - 任务完成
```json
{
  "task_id": "req_20251103_001",
  "status": "success",
  "total_fields": 10,
  "success_count": 10,
  "failed_count": 0,
  "processing_time_ms": 5230
}
```

### 5. error - 错误事件
```json
{
  "error_message": "错误描述",
  "request_id": "req_20251103_001"
}
```

## Python客户端示例

### 示例1: 使用httpx处理SSE

```python
import httpx
import json

async def stream_extraction():
    """流式字段提取"""
    url = "http://localhost:8580/api/v1/extraction/stream"
    
    payload = {
        "extraction_type": "大宗实物",
        "files": [
            {
                "file_url": "/path/to/file.pdf",
                "file_name": "信息披露申请书.pdf",
                "file_type": "info_disclosure_application"
            }
        ],
        "rule_config_id": "827f1bc9-69e9-4847-9229-7112913e4707",
        "request_id": "test_stream_001"
    }
    
    async with httpx.AsyncClient(timeout=600) as client:
        async with client.stream(
            "POST",
            url,
            json=payload,
            headers={"Accept": "text/event-stream"}
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    event_type = line[7:]
                    print(f"\n事件类型: {event_type}")
                    
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
                    print(f"事件数据: {json.dumps(data, ensure_ascii=False, indent=2)}")
                    
                    # 根据事件类型处理
                    if event_type == "task_start":
                        print(f"任务开始，共{data['total_fields']}个字段")
                        
                    elif event_type == "field_progress":
                        progress = data['progress'] * 100
                        print(f"处理进度: {progress:.1f}% - {data['field_name']}")
                        
                    elif event_type == "field_complete":
                        status = data['extraction_status']
                        value = data['extracted_value']
                        print(f"字段完成: {data['field_name']} = {value} ({status})")
                        
                    elif event_type == "task_complete":
                        print(f"任务完成: {data['success_count']}/{data['total_fields']} 成功")
                        
                    elif event_type == "error":
                        print(f"错误: {data['error_message']}")


# 运行
import asyncio
asyncio.run(stream_extraction())
```

### 示例2: 使用requests-sse处理SSE

```python
from sseclient import SSEClient
import requests
import json

def stream_extraction_sync():
    """同步流式字段提取"""
    url = "http://localhost:8580/api/v1/extraction/stream"
    
    payload = {
        "extraction_type": "大宗实物",
        "files": [
            {
                "file_url": "/path/to/file.pdf",
                "file_name": "信息披露申请书.pdf",
                "file_type": "info_disclosure_application"
            }
        ],
        "rule_config_id": "827f1bc9-69e9-4847-9229-7112913e4707",
        "request_id": "test_stream_002"
    }
    
    response = requests.post(
        url,
        json=payload,
        headers={"Accept": "text/event-stream"},
        stream=True
    )
    
    client = SSEClient(response)
    
    for event in client.events():
        event_type = event.event
        data = json.loads(event.data)
        
        print(f"\n[{event_type}] {json.dumps(data, ensure_ascii=False)}")
        
        if event_type == "task_complete":
            print("\n提取完成！")
            break
        elif event_type == "error":
            print(f"\n提取失败: {data['error_message']}")
            break

# 运行
stream_extraction_sync()
```

## JavaScript客户端示例

```javascript
async function streamExtraction() {
    const url = "http://localhost:8580/api/v1/extraction/stream";
    
    const payload = {
        extraction_type: "大宗实物",
        files: [
            {
                file_url: "/path/to/file.pdf",
                file_name: "信息披露申请书.pdf",
                file_type: "info_disclosure_application"
            }
        ],
        rule_config_id: "827f1bc9-69e9-4847-9229-7112913e4707",
        request_id: "test_stream_js_001"
    };
    
    const response = await fetch(url, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "text/event-stream"
        },
        body: JSON.stringify(payload)
    });
    
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    
    let buffer = "";
    
    while (true) {
        const { done, value } = await reader.read();
        
        if (done) break;
        
        buffer += decoder.decode(value, { stream: true });
        
        const lines = buffer.split("\n");
        buffer = lines.pop(); // 保留未完成的行
        
        let eventType = null;
        
        for (const line of lines) {
            if (line.startsWith("event: ")) {
                eventType = line.substring(7);
            } else if (line.startsWith("data: ")) {
                const data = JSON.parse(line.substring(6));
                
                console.log(`[${eventType}]`, data);
                
                // 处理不同事件
                switch (eventType) {
                    case "task_start":
                        console.log(`任务开始，共${data.total_fields}个字段`);
                        break;
                        
                    case "field_progress":
                        const progress = (data.progress * 100).toFixed(1);
                        console.log(`进度: ${progress}% - ${data.field_name}`);
                        break;
                        
                    case "field_complete":
                        console.log(`完成: ${data.field_name} = ${data.extracted_value}`);
                        break;
                        
                    case "task_complete":
                        console.log(`提取完成: ${data.success_count}/${data.total_fields} 成功`);
                        return; // 结束
                        
                    case "error":
                        console.error(`错误: ${data.error_message}`);
                        return; // 结束
                }
            }
        }
    }
}

// 运行
streamExtraction();
```

## 前端React示例

```jsx
import React, { useState, useEffect } from 'react';

function ExtractionProgress() {
    const [progress, setProgress] = useState(0);
    const [currentField, setCurrentField] = useState('');
    const [results, setResults] = useState([]);
    const [status, setStatus] = useState('idle'); // idle, running, completed, error
    
    const startExtraction = async () => {
        setStatus('running');
        setResults([]);
        
        const url = "http://localhost:8580/api/v1/extraction/stream";
        
        const payload = {
            extraction_type: "大宗实物",
            files: [
                {
                    file_url: "/path/to/file.pdf",
                    file_name: "信息披露申请书.pdf",
                    file_type: "info_disclosure_application"
                }
            ],
            rule_config_id: "827f1bc9-69e9-4847-9229-7112913e4707",
            request_id: `req_${Date.now()}`
        };
        
        try {
            const response = await fetch(url, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream"
                },
                body: JSON.stringify(payload)
            });
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            
            let buffer = "";
            let eventType = null;
            
            while (true) {
                const { done, value } = await reader.read();
                
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop();
                
                for (const line of lines) {
                    if (line.startsWith("event: ")) {
                        eventType = line.substring(7);
                    } else if (line.startsWith("data: ")) {
                        const data = JSON.parse(line.substring(6));
                        
                        switch (eventType) {
                            case "field_progress":
                                setProgress(data.progress * 100);
                                setCurrentField(data.field_name);
                                break;
                                
                            case "field_complete":
                                setResults(prev => [...prev, data]);
                                break;
                                
                            case "task_complete":
                                setStatus('completed');
                                setProgress(100);
                                return;
                                
                            case "error":
                                setStatus('error');
                                console.error(data.error_message);
                                return;
                        }
                    }
                }
            }
        } catch (error) {
            setStatus('error');
            console.error('提取失败:', error);
        }
    };
    
    return (
        <div>
            <button onClick={startExtraction} disabled={status === 'running'}>
                开始提取
            </button>
            
            {status === 'running' && (
                <div>
                    <div>进度: {progress.toFixed(1)}%</div>
                    <div>当前字段: {currentField}</div>
                    <progress value={progress} max="100"></progress>
                </div>
            )}
            
            <div>
                <h3>提取结果 ({results.length})</h3>
                {results.map((result, idx) => (
                    <div key={idx}>
                        <strong>{result.field_name}:</strong> {result.extracted_value}
                        <span>({result.extraction_status})</span>
                    </div>
                ))}
            </div>
            
            {status === 'completed' && <div>✅ 提取完成！</div>}
            {status === 'error' && <div>❌ 提取失败</div>}
        </div>
    );
}

export default ExtractionProgress;
```

## 优势对比

### 同步接口 vs 流式接口

| 特性 | 同步接口 | 流式接口 |
|------|---------|----------|
| 响应时间 | 等待全部完成 | 实时返回 |
| 进度反馈 | 无 | 有 |
| 用户体验 | 等待焦虑 | 实时可见 |
| 超时风险 | 高 | 低 |
| 适用场景 | 批量后台任务 | 交互式前端 |

## 注意事项

1. **连接保活**: SSE连接会保持打开状态，确保客户端正确处理
2. **超时设置**: 设置足够长的超时时间（建议10分钟以上）
3. **错误处理**: 监听error事件，及时处理异常
4. **重连机制**: 如果连接中断，实现自动重连
5. **资源释放**: 完成后及时关闭连接，释放资源

## 性能建议

1. 流式接口适合字段数量较多（>5个）的场景
2. 字段数量少时，同步接口更简单高效
3. 前端建议使用虚拟滚动处理大量结果
4. 可以根据进度百分比显示加载动画

## 错误处理

```python
async def stream_extraction_with_retry():
    """带重试的流式提取"""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            async for event in stream_extraction():
                yield event
            break  # 成功完成
            
        except Exception as e:
            retry_count += 1
            if retry_count >= max_retries:
                raise
            
            print(f"连接失败，重试 {retry_count}/{max_retries}...")
            await asyncio.sleep(2 ** retry_count)  # 指数退避
```

---

**相关文档**:
- 开发文档: `docs/extraction_api_development.md`
- 快速入门: `docs/extraction_api_quickstart.md`
- API规范: `docs/api/api-specification.yaml`

