# API限流说明

## 概述

系统已为字段提取和规则审核接口实现了并发限流功能，防止过多的并发请求导致系统过载。

## 限流配置

### 默认配置

每个API端点的默认最大并发数为 **10个请求**：

- `extraction/sync` - 字段提取同步接口：10个并发
- `extraction/stream` - 字段提取流式接口：10个并发
- `audit/sync` - 规则审核同步接口：10个并发
- `audit/stream` - 规则审核流式接口：10个并发

### 通过环境变量配置

可以通过设置环境变量来自定义各端点的最大并发数：

```bash
# 字段提取同步接口最大并发数
export EXTRACTION_SYNC_MAX_CONCURRENT=15

# 字段提取流式接口最大并发数
export EXTRACTION_STREAM_MAX_CONCURRENT=15

# 规则审核同步接口最大并发数
export AUDIT_SYNC_MAX_CONCURRENT=20

# 规则审核流式接口最大并发数
export AUDIT_STREAM_MAX_CONCURRENT=20
```

### 通过代码配置

也可以在应用启动时通过代码设置：

```python
from config.api_config import APIConfig, RateLimitConfig

# 创建自定义配置
config = RateLimitConfig(
    extraction_sync_max_concurrent=15,
    extraction_stream_max_concurrent=15,
    audit_sync_max_concurrent=20,
    audit_stream_max_concurrent=20
)

# 应用配置
APIConfig.set_rate_limit_config(config)
```

## 工作原理

### 并发控制

- 使用 `asyncio.Semaphore` 实现异步并发控制
- 每个端点维护独立的信号量，互不影响
- 当并发请求数达到上限时，新请求会自动排队等待
- 无需超时清除逻辑，请求会一直等待直到获得执行机会

### 请求流程

1. **请求到达**：客户端发送API请求
2. **检查并发数**：系统检查当前活跃请求数
3. **获取执行权**：
   - 如果未达上限：立即执行
   - 如果已达上限：排队等待
4. **执行请求**：获得执行权后处理请求
5. **释放资源**：请求完成后释放信号量，允许下一个请求执行

### 日志记录

系统会记录以下信息：

- 请求开始排队（如果需要等待）
- 请求获得执行权（包含等待时间）
- 请求执行完成（包含执行时间）

日志示例：

```
[限流] extraction_sync 请求#15 等待执行 (活跃: 10, 排队: 5)
[限流] extraction_sync 请求#15 开始执行 (等待: 2.35s, 活跃: 10)
[限流] extraction_sync 请求#15 执行完成 (耗时: 8.42s, 剩余活跃: 9)
```

## 监控和调试

### 获取限流统计信息

可以通过代码获取当前的限流统计：

```python
from src.api.v1.middleware.rate_limiter import get_rate_limit_stats

# 获取统计信息
stats = get_rate_limit_stats()
# 返回格式：
# {
#   "extraction_sync": {
#     "max_concurrent": 10,
#     "available": 3,
#     "active": 7,
#     "total_requests": 156
#   },
#   ...
# }
```

### 查看日志

限流相关的日志都带有 `[限流]` 标签，可以通过以下命令过滤：

```bash
# 查看限流日志
tail -f logs/app_*.log | grep "限流"

# 查看特定端点的限流日志
tail -f logs/app_*.log | grep "extraction_sync"
```

## 性能影响

- **排队开销**：极小，基于异步信号量实现
- **内存开销**：每个端点仅维护一个Semaphore对象
- **CPU开销**：几乎无额外开销

## 注意事项

1. **独立限流**：每个端点的限流是独立的，不会相互影响
2. **无超时**：排队的请求不会因超时而被取消，会一直等待
3. **公平性**：请求按照到达顺序排队，先到先得
4. **建议配置**：
   - 根据服务器资源和预期负载设置合适的并发数
   - 生产环境建议通过环境变量配置，便于调整
   - 监控日志中的等待时间，如果频繁出现长时间等待，考虑增加并发数

## 配置文件位置

- **限流配置**：`config/api_config.py`
- **限流实现**：`src/api/v1/middleware/rate_limiter.py`
- **应用位置**：
  - `src/api/v1/endpoints/extraction.py`
  - `src/api/v1/endpoints/audit.py`
- **初始化位置**：`src/main.py`（应用启动时）

