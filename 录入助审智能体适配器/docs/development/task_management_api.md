# 任务管理API使用文档

## 概述

任务管理API提供了查询和取消长时间运行任务的功能，适用于需要追踪异步任务执行状态的场景。

## 接口列表

### 1. 查询任务状态

**端点**: `GET /api/v1/task/{taskId}`

**描述**: 查询任务的当前状态、进度和结果

**请求参数**:
- **路径参数**:
  - `taskId` (string, required): 任务ID
- **查询参数**:
  - `include_details` (boolean, optional, default: true): 是否包含详细结果

**响应示例**:

```json
{
  "task_id": "req_20251103_001",
  "task_type": "extraction",
  "status": "completed",
  "progress": 1.0,
  "result": {
    "status": "success",
    "total_fields": 10,
    "success_count": 10,
    "failed_count": 0,
    "processing_time_ms": 5230
  },
  "error_message": null,
  "created_at": "2025-11-03T10:00:00Z",
  "updated_at": "2025-11-03T10:05:30Z",
  "completed_at": "2025-11-03T10:05:30Z"
}
```

### 2. 取消任务

**端点**: `POST /api/v1/task/{taskId}/cancel`

**描述**: 取消正在执行的任务

**请求参数**:
- **路径参数**:
  - `taskId` (string, required): 任务ID

**响应示例**:

```json
{
  "task_id": "req_20251103_001",
  "status": "cancelled",
  "message": "任务已取消"
}
```

## 任务状态说明

| 状态 | 说明 |
|------|------|
| pending | 等待中 - 任务已创建但尚未开始处理 |
| processing | 处理中 - 任务正在执行 |
| completed | 已完成 - 任务成功完成 |
| failed | 失败 - 任务执行失败 |
| timeout | 超时 - 任务执行超时 |
| cancelled | 已取消 - 任务被手动取消 |

## 任务类型

| 类型 | 说明 |
|------|------|
| extraction | 字段提取任务 |
| audit | 规则审核任务 |

## 使用场景

### 场景1: 同步提取后查询结果

```python
import requests
import time

# 1. 发起同步提取请求
response = requests.post(
    "http://localhost:8580/api/v1/extraction/sync",
    json={
        "extraction_type": "有纸大宗实物",
        "files": [...],
        "rule_config_id": "config_id",
        "request_id": "req_20251103_001"  # 提供request_id
    }
)

result = response.json()
task_id = result.get("task_id")  # 获取task_id

# 2. 如果任务返回了task_id，可以查询任务状态
if task_id:
    task_response = requests.get(
        f"http://localhost:8580/api/v1/task/{task_id}"
    )
    task_status = task_response.json()
    
    print(f"任务状态: {task_status['status']}")
    print(f"进度: {task_status['progress'] * 100}%")
```

### 场景2: 流式提取过程中查询任务

```python
import requests
import threading
import time

def stream_extraction():
    """流式提取"""
    response = requests.post(
        "http://localhost:8580/api/v1/extraction/stream",
        json={
            "extraction_type": "有纸大宗实物",
            "files": [...],
            "rule_config_id": "config_id",
            "request_id": "req_20251103_002"
        },
        stream=True
    )
    
    for line in response.iter_lines():
        if line:
            print(line.decode())

def check_task_status(task_id):
    """轮询任务状态"""
    while True:
        response = requests.get(
            f"http://localhost:8580/api/v1/task/{task_id}"
        )
        task = response.json()
        
        print(f"任务进度: {task['progress'] * 100:.1f}%")
        
        if task['status'] in ['completed', 'failed', 'cancelled']:
            print(f"任务结束: {task['status']}")
            break
        
        time.sleep(1)

# 启动流式提取
stream_thread = threading.Thread(target=stream_extraction)
stream_thread.start()

# 同时查询任务状态
time.sleep(0.5)  # 等待任务创建
check_task_status("req_20251103_002")
```

### 场景3: 取消长时间运行的任务

```python
import requests

# 取消任务
response = requests.post(
    "http://localhost:8580/api/v1/task/req_20251103_003/cancel"
)

if response.status_code == 200:
    result = response.json()
    print(f"任务已取消: {result['message']}")
elif response.status_code == 400:
    print("任务无法取消（可能已完成）")
elif response.status_code == 404:
    print("任务不存在")
```

## 错误处理

### 404 - 任务不存在

```json
{
  "detail": "任务不存在: req_invalid_id"
}
```

### 400 - 无法取消任务

```json
{
  "detail": "任务状态为 completed，无法取消"
}
```

**可取消的状态**:
- `pending` (等待中)
- `processing` (处理中)

**不可取消的状态**:
- `completed` (已完成)
- `failed` (失败)
- `cancelled` (已取消)
- `timeout` (超时)

## 最佳实践

### 1. 使用request_id创建任务

在调用提取接口时，提供 `request_id` 参数：

```python
{
    "extraction_type": "有纸大宗实物",
    "files": [...],
    "request_id": "req_20251103_001"  # 推荐使用时间戳或UUID
}
```

系统会自动将 `request_id` 作为 `task_id` 创建任务。

### 2. 轮询间隔建议

- **快速任务** (<30秒): 每1秒查询一次
- **中等任务** (30秒-5分钟): 每3-5秒查询一次
- **长任务** (>5分钟): 每10-30秒查询一次

### 3. 任务生命周期管理

任务会自动清理，默认保留时间为1小时。已完成的任务建议及时获取结果。

### 4. 错误重试

如果任务失败，可以通过查询任务获取错误信息：

```python
task = requests.get(f"/api/v1/task/{task_id}").json()

if task['status'] == 'failed':
    print(f"任务失败原因: {task['error_message']}")
    # 根据错误信息决定是否重试
```

## 与流式接口的对比

| 特性 | 流式接口 (SSE) | 任务查询接口 |
|------|---------------|-------------|
| 实时性 | 高（实时推送） | 中（需要轮询） |
| 网络要求 | 长连接 | 短连接 |
| 适用场景 | 前端实时展示 | 后台任务追踪 |
| 连接稳定性 | 需要保持 | 无要求 |
| 取消支持 | 断开连接 | API调用 |

**推荐使用**:
- **前端Web应用**: 优先使用流式接口
- **后端服务集成**: 优先使用任务查询接口
- **移动应用**: 根据网络环境选择

## JavaScript/TypeScript示例

```typescript
interface TaskStatus {
  task_id: string;
  task_type: 'extraction' | 'audit';
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  result?: any;
  error_message?: string;
  created_at: string;
  updated_at: string;
  completed_at?: string;
}

async function getTaskStatus(taskId: string): Promise<TaskStatus> {
  const response = await fetch(
    `http://localhost:8580/api/v1/task/${taskId}`
  );
  
  if (!response.ok) {
    throw new Error(`获取任务状态失败: ${response.status}`);
  }
  
  return await response.json();
}

async function cancelTask(taskId: string): Promise<void> {
  const response = await fetch(
    `http://localhost:8580/api/v1/task/${taskId}/cancel`,
    { method: 'POST' }
  );
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail);
  }
}

// 轮询任务状态
async function pollTaskStatus(
  taskId: string,
  onProgress: (status: TaskStatus) => void,
  interval: number = 1000
): Promise<TaskStatus> {
  return new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      try {
        const status = await getTaskStatus(taskId);
        onProgress(status);
        
        if (['completed', 'failed', 'cancelled'].includes(status.status)) {
          clearInterval(timer);
          resolve(status);
        }
      } catch (error) {
        clearInterval(timer);
        reject(error);
      }
    }, interval);
  });
}

// 使用示例
pollTaskStatus(
  'req_20251103_001',
  (status) => {
    console.log(`进度: ${(status.progress * 100).toFixed(1)}%`);
  }
).then((finalStatus) => {
  console.log('任务完成:', finalStatus);
}).catch((error) => {
  console.error('任务失败:', error);
});
```

## 注意事项

1. **任务ID唯一性**: 同一个 `task_id` 不能重复创建任务
2. **任务清理**: 已完成的任务会在1小时后自动清理
3. **并发限制**: 没有并发查询限制，但建议合理控制轮询频率
4. **取消时机**: 只有在 `pending` 或 `processing` 状态的任务可以取消
5. **结果保留**: 任务完成后，结果会保留在内存中，直到任务被清理

## API文档

完整的API文档可访问: http://localhost:8580/docs

---

**相关文档**:
- 字段提取API: `docs/extraction_api_development.md`
- 流式提取示例: `docs/stream_extraction_example.md`
- API规范对比: `docs/api_specification_compliance.md`

