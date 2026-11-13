# 文件分类异步化（超时转任务）设计

**日期：** 2026-10-27  
**状态：** 已确认  
**对齐对象：** 字段提取同步接口（`POST /extraction/sync`）+ 任务查询（`GET /task/{task_id}`）

## 目标

将 `POST /file/classification` 从纯同步改为「同步等待 + 超时转异步」：

- 默认等待 **300000ms**；可传 `timeout`（最小 1000ms）
- 超时内完成：直接返回完整分类结果
- 超时后：返回 `status=pending` + `task_id`，后台继续执行
- 客户端用现有任务查询接口查看进度（已完成文件数 / 占比）与最终结果

## 非目标

- 不抽公共 AsyncSyncFacade
- 不上独立 MQ/Worker
- 不改审核流程内的 `classification_service`（内部分类）
- 不改变单文件异常时 `results[]` 仍返回 `other_documents` 的结果项形态

## 方案

完全复用提取接口的 endpoint 编排模式：

1. 生成带前缀的内部 `task_id`（`classification_`）
2. `task_store.create_task`
3. `asyncio.create_task` 跑分类
4. `wait_for_task_with_timeout`（超时不取消后台任务）
5. 查询/取消走现有 `/task` 接口，`type=classification`

## API 契约

### 请求 `ClassificationRequest`

| 字段 | 说明 |
|------|------|
| `files` | 待分类文件列表（至少 1 个），不变 |
| `request_id` | 可选，幂等/日志 |
| `task_id` | 可选，指定任务标识（对齐提取） |
| `timeout` | 可选，毫秒；默认 `300000`；`ge=1000` |

### 响应 `ClassificationData`

对齐 `ExtractionData` 形态：

| 字段 | 说明 |
|------|------|
| `request_id` | 请求 ID |
| `task_id` | 对外任务 ID（无前缀）；超时时用于查询 |
| `status` | `success` / `partial` / `failed` / `pending` |
| `results` | `{file_name, file_url, file_type}[]` |
| `total_files` | 总文件数 |
| `success_count` | 无异常完成的文件数 |
| `failed_count` | 异常兜底为 `other_documents` 的文件数 |
| `processing_time_ms` | 处理耗时（超时响应可为等待时长） |

超时响应：`status=pending`，`results=[]`，counts 为 0，`message` 为「任务处理中，请稍后查询结果」。

### 任务查询

- `GET /task/{task_id}?type=classification`（平台：`GET .../task?task_id=&type=classification`）
- `progress` = `completed_count / total_files`
- `total_count` / `completed_count` 来自 task `context`
- 完成后 `result` 为完整 `ClassificationData`

### 计数口径

- `completed_count`：已处理完的文件数（含异常兜底）
- `success_count`：无异常完成数
- `failed_count`：异常兜底数（结果项仍为 `other_documents`）
- 整体 `status`：全成功 → `success`；全失败 → `failed`；混合 → `partial`；超时未完成 → `pending`

## 内部改造

### TaskType / ID

- `TaskType.CLASSIFICATION = "classification"`
- 内部前缀：`classification_`
- 扩展 `external_task_id` / `resolve_task_by_id`；未传 `type` 时查找顺序：extraction → audit → classification

### Endpoint

对齐 `src/api/v1/endpoints/extraction.py`：

- 同 `task_id` 且 `PENDING`/`PROCESSING`：不重跑，返回 pending
- 已完成再提交：`create_task(..., reset_if_exists=True)` 后重跑
- `convert_timeout_to_seconds(timeout, default_seconds=300)`

### Service

- `classify_files` 支持可选 `task_id`；有则更新 Redis 进度
- 每完成一文件：更新 `completed_count` / `progress` / `status_message`
- 结束：写入 `result` + `COMPLETED`；整体失败：`FAILED`
- 取消：循环中检查 cancel subscriber（与提取同粒度）

### 平台与文档

- 平台网关继续转发同一 endpoint
- 更新平台接入文档分类章节与任务 `type` 说明

## 错误处理

| 场景 | 行为 |
|------|------|
| 参数错误 | 400 |
| 同步窗口内整体未捕获异常 | 500；task → FAILED |
| 单文件异常 | failed_count++，结果项 `other_documents` |
| 任务不存在 / type 不匹配 | 404 |
| 取消 | 仅 pending/processing |

## 测试要点

1. 超时内完成 → 完整结果、非 pending
2. 强制超时 → pending + task_id；查询可见进度至完成
3. total/completed/progress 与文件完成数一致
4. 单文件失败 → failed_count，结果项 other_documents
5. 重复 task_id 不双开
6. type=classification 与无 type 解析正确
7. 默认 timeout=300000；更小 timeout 可触发 pending

## 验收

- 与提取同一套「同步等待 + 超时转异步 + 任务查询」协议  
- 默认等待 300s；超时后可用 task_id 查到已完成数与占比
