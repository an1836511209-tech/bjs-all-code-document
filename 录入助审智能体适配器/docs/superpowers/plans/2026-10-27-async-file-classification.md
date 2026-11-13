# 文件分类异步化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将文件分类接口改为与字段提取一致的「同步等待 + 超时转异步」，默认超时 300000ms，超时返回 `task_id`，可通过任务查询接口查看进度与结果。

**Architecture:** 复用提取 endpoint 编排：`classification_` 前缀 task_id → Redis TaskStore → `asyncio.create_task` + `wait_for_task_with_timeout`；分类 service 按文件更新 `completed_count`/`progress`；查询/取消走现有 `/task` 并支持 `type=classification`。

**Tech Stack:** FastAPI, asyncio, Redis TaskStore, Pydantic, pytest（Mock 分类/慢任务）

**Spec:** `docs/superpowers/specs/2026-10-27-async-file-classification-design.md`

## Global Constraints

- 对齐提取接口协议，不自创异步协议
- 分类默认 `timeout=300000`（毫秒），最小 `1000`
- 内部 task_id 前缀：`classification_`
- 进度：`completed_count` = 已处理文件数；`success_count`/`failed_count` 另计
- 单文件异常仍返回 `file_type=other_documents`，计入 `failed_count`
- 不改审核内部分类服务 `src/services/classification_service.py`
- 不上 MQ、不抽公共 AsyncSyncFacade
- **所有 git commit message 使用中文**

---

## File Structure

| 文件 | 职责 |
|------|------|
| `src/schemas/classification.py` | 请求加 `task_id`/`timeout`；响应加 status/counts；状态枚举 |
| `src/schemas/task.py` | `TaskType.CLASSIFICATION`；查询接口对 classification 的计数字段语义 |
| `src/api/v1/utils/task_handler.py` | 前缀剥离与 `resolve_task_by_id` 支持 classification |
| `src/api/v1/endpoints/task.py` | 查询时读取 classification 的 `total_files`/`completed_count` |
| `src/services/classification/service.py` | 可选 task_id、进度更新、返回 `ClassificationData` |
| `src/api/v1/endpoints/classification.py` | 对齐 extraction 的超时编排 |
| `src/platform_gw/router.py` | 任务 type 文案补充 classification（逻辑已转发） |
| `docs/api/平台接入接口文档.md` | 分类章节改为同步可超时 + 查询说明 |
| `tests/api/test_classification_async.py` | 超时/进度/重复 task_id 等单测 |

---

### Task 1: Schema 与 TaskType

**Files:**
- Modify: `src/schemas/classification.py`
- Modify: `src/schemas/task.py`
- Test: `tests/api/test_classification_async.py`（先写 schema 相关断言，后续 Task 再补接口）

**Interfaces:**
- Produces: `ClassificationStatus`；`ClassificationRequest.task_id` / `timeout`；`ClassificationData` 新字段；`TaskType.CLASSIFICATION`

- [ ] **Step 1: 扩展 classification schema**

在 `src/schemas/classification.py` 中：

1. 新增状态枚举：

```python
from enum import Enum

class ClassificationStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    PENDING = "pending"
```

2. `ClassificationRequest` 增加字段（保留原 `files`/`request_id`）：

```python
task_id: Optional[str] = Field(None, description="任务ID（可选，用于继续未完成的任务）")
timeout: Optional[int] = Field(default=300000, description="超时时间（毫秒）", ge=1000)
```

3. 将 `ClassificationData` 改为：

```python
class ClassificationData(BaseModel):
    request_id: str = Field(..., description="请求ID")
    task_id: Optional[str] = Field(None, description="任务ID（异步处理时返回）")
    status: ClassificationStatus = Field(..., description="任务整体状态")
    results: List[ClassificationResultItem] = Field(default_factory=list, description="文件分类结果列表")
    total_files: int = Field(0, description="总文件数")
    success_count: int = Field(0, description="无异常完成的文件数")
    failed_count: int = Field(0, description="异常兜底文件数")
    processing_time_ms: int = Field(..., description="处理时间（毫秒）")
```

同步更新该文件内 `json_schema_extra` 示例。

- [ ] **Step 2: TaskType 增加 CLASSIFICATION**

在 `src/schemas/task.py`：

```python
class TaskType(str, Enum):
    EXTRACTION = "extraction"
    AUDIT = "audit"
    CLASSIFICATION = "classification"
```

更新 `TaskStatusData.total_count` / `completed_count` 的 description，注明分类任务为总文件数 / 已完成文件数。

- [ ] **Step 3: Commit**

```bash
git add src/schemas/classification.py src/schemas/task.py
git commit -m "feat(classification): 扩展分类请求响应与 TaskType.CLASSIFICATION"
```

---

### Task 2: 任务 ID 解析与查询进度

**Files:**
- Modify: `src/api/v1/utils/task_handler.py`
- Modify: `src/api/v1/endpoints/task.py`
- Modify: `src/platform_gw/router.py`（Query description 文案）

**Interfaces:**
- Consumes: `TaskType.CLASSIFICATION`
- Produces: `external_task_id` / `resolve_task_by_id` 支持 `classification_`；查询返回 classification 的 total/completed

- [ ] **Step 1: 扩展 task_handler 前缀逻辑**

修改 `external_task_id`：

```python
def external_task_id(task_id: str) -> str:
    for prefix in ("extraction_", "audit_", "classification_"):
        if task_id.startswith(prefix):
            return task_id[len(prefix):]
    return task_id
```

修改 `resolve_task_by_id`：在 `task_type == TaskType.CLASSIFICATION` 时查 `classification_{external_id}`；`task_type is None` 时顺序为 extraction → audit → classification。

- [ ] **Step 2: task 查询接口支持 classification 计数**

在 `src/api/v1/endpoints/task.py` 的 `get_task_status` 中，对 `TaskType.CLASSIFICATION`：

- 完成态：优先 `context.total_files` / `context.completed_count`；否则从 `result.total_files` / `success_count+failed_count`
- 处理中：`context.total_files` 与 `context.completed_count`（无则用 `progress` 估算）

同步更新 endpoint description 中的任务类型说明与 Query `type` 文案（含 classification）。

平台网关 `platform_gw/router.py` 中两处 `task_type` Query description 改为「extraction、audit 或 classification」。

- [ ] **Step 3: Commit**

```bash
git add src/api/v1/utils/task_handler.py src/api/v1/endpoints/task.py src/platform_gw/router.py
git commit -m "feat(task): 任务查询与解析支持 classification"
```

---

### Task 3: Classification Service 进度与 ClassificationData 返回

**Files:**
- Modify: `src/services/classification/service.py`

**Interfaces:**
- Consumes: `get_task_store()`, `TaskStatus`, cancel subscriber（与提取相同用法）
- Produces: `classify_files(..., task_id=None, request_id=None, base_task_id=None) -> ClassificationData`

- [ ] **Step 1: 调整 `classify_files` 签名与返回值**

将返回类型从 `Tuple[List[ClassificationResultItem], int]` 改为 `ClassificationData`。

增加参数：

```python
async def classify_files(
    self,
    files: List[ClassificationFileInput],
    task_id: Optional[str] = None,
    request_id: Optional[str] = None,
    base_task_id: Optional[str] = None,
) -> ClassificationData:
```

- [ ] **Step 2: 有 task_id 时更新进度**

逻辑要点（对齐提取，保持现有并发 semaphore）：

1. 开始：`update_task(status=PROCESSING, progress=0, status_message="正在分类文件...", context={total_files, completed_count:0})`
2. 将 `asyncio.gather` 改为按完成增量更新：可用 `as_completed`，或 gather 后无法中途更新进度——**必须**改为逐文件完成即回调，以便查询可见进度。推荐：

```python
completed = 0
success_count = 0
failed_count = 0
results_by_index: Dict[int, ClassificationResultItem] = {}

async def run_one(idx: int, file_input: ClassificationFileInput):
    # 可选：检查 cancel
    try:
        item = await classify_with_semaphore(file_input)
        return idx, item, True
    except Exception as e:
        logger.error(...)
        item = ClassificationResultItem(
            file_name=file_input.file_name,
            file_url=file_input.file_url,
            file_type=FileType.OTHER_DOCUMENTS.value,
        )
        return idx, item, False

indexed = [asyncio.create_task(run_one(i, f)) for i, f in enumerate(files)]
for coro in asyncio.as_completed(indexed):
    idx, item, ok = await coro
    results_by_index[idx] = item
    completed += 1
    if ok:
        success_count += 1
    else:
        failed_count += 1
    if task_id:
        progress = completed / len(files)
        await task_store.update_task(
            task_id,
            progress=progress,
            status_message=f"正在分类文件... ({completed}/{len(files)})",
            context={"total_files": len(files), "completed_count": completed},
        )
```

注意：当前实现把 `gather` 的 Exception 转成 `other_documents`，**不要**让异常冒泡出 `run_one` 的外层未处理；`ok=False` 表示异常兜底。`_classify_single_file` 自身若已吞掉异常则按现有行为：只有 `gather` 层 Exception 才算 failed——保持与现网一致：`classify_with_semaphore` 抛错 → failed；正常返回含 `other_documents` 的 LLM 结果 → success。

3. 组装有序列表 `classification_results = [results_by_index[i] for i in range(len(files))]`
4. 计算 `status`：`failed_count==0` → SUCCESS；`success_count==0` → FAILED；否则 PARTIAL
5. 构建并返回 `ClassificationData`；若有 `task_id`：`update_task(COMPLETED, progress=1.0, result=data.model_dump(), status_message="处理完成")`
6. 整体 try/except：失败则 `update_task(FAILED, error_message=...)` 再抛出

取消检查：在 `run_one` 开头参考提取：

```python
from src.services.redis.task_cancel_subscriber import get_task_cancel_subscriber
if task_id and get_task_cancel_subscriber().is_cancelled(task_id):
    raise asyncio.CancelledError(...)
```

（若项目 cancel 语义要求静默停止，跟随提取现有写法，勿自创。）

- [ ] **Step 3: Commit**

```bash
git add src/services/classification/service.py
git commit -m "feat(classification): 分类服务支持任务进度与 ClassificationData 返回"
```

---

### Task 4: Classification Endpoint 超时编排

**Files:**
- Modify: `src/api/v1/endpoints/classification.py`

**Interfaces:**
- Consumes: `generate_task_id_with_prefix`, `convert_timeout_to_seconds`, `wait_for_task_with_timeout`, `replace_task_id_in_response`, `get_task_store`, `TaskType.CLASSIFICATION`
- Produces: 与提取同构的同步/pending 响应

- [ ] **Step 1: 按 extraction.py 重写 classify_files endpoint**

核心结构（对照 `src/api/v1/endpoints/extraction.py` 54–212 行）：

```python
timeout_seconds = convert_timeout_to_seconds(request.timeout, default_seconds=300)
task_id, base_task_id = generate_task_id_with_prefix(
    prefix="classification_",
    task_id=request.task_id,
    request_id=request.request_id,
)
task_store = get_task_store()

# 重复执行中 → pending
existing = await task_store.get_task(task_id)
if existing and existing.status in (TaskStatus.PENDING, TaskStatus.PROCESSING):
    pending = ClassificationData(
        request_id=request.request_id or base_task_id,
        task_id=base_task_id,
        status=ClassificationStatus.PENDING,
        results=[],
        total_files=existing.context.get("total_files", len(request.files)),
        success_count=0,
        failed_count=0,
        processing_time_ms=request.timeout or 300000,
    )
    return success_response(data=pending.model_dump(), message="任务处理中，请稍后查询结果")

await task_store.create_task(
    task_id=task_id,
    task_type=TaskType.CLASSIFICATION,
    context={
        "total_files": len(request.files),
        "completed_count": 0,
        "base_task_id": base_task_id,
    },
    status_message="等待处理",
    reset_if_exists=True,
)

classification_task = asyncio.create_task(
    classification_service.classify_files(
        files=request.files,
        task_id=task_id,
        request_id=request.request_id,
        base_task_id=base_task_id,
    )
)

def create_pending_data():
    return ClassificationData(
        request_id=request.request_id or base_task_id,
        task_id=base_task_id,
        status=ClassificationStatus.PENDING,
        results=[],
        total_files=len(request.files),
        success_count=0,
        failed_count=0,
        processing_time_ms=int(timeout_seconds * 1000),
    )

is_done, result_data = await wait_for_task_with_timeout(
    task=classification_task,
    timeout_seconds=timeout_seconds,
    base_task_id=base_task_id,
    full_task_id=task_id,
    pending_data_factory=create_pending_data,
    task_name="文件分类",
)

if is_done:
    data = result_data.model_dump() if hasattr(result_data, "model_dump") else result_data
    data = replace_task_id_in_response(data, base_task_id)
    return success_response(data=data, message="success")
return success_response(
    data=result_data.model_dump(),
    message="任务处理中，请稍后查询结果",
)
```

更新路由 description：说明超时行为与任务查询方式。保留 ValueError→400、其它→500。

- [ ] **Step 2: Commit**

```bash
git add src/api/v1/endpoints/classification.py
git commit -m "feat(classification): 分类接口支持超时转异步与 task_id"
```

---

### Task 5: 文档

**Files:**
- Modify: `docs/api/平台接入接口文档.md`（§4 文件分类；§任务查询 type 说明）
- Modify: `docs/api/API接口文档.md`（若有分类章节，同步；没有则跳过）

- [ ] **Step 1: 更新平台文档分类章节**

将「同步异步 | 同步」改为与提取一致的表述：「同步；超时后任务继续后台执行，可用任务查询接口拉取结果」。

请求表增加 `task_id`、`timeout`（默认 300000，最小 1000）。

响应 `data` 增加 `request_id`/`task_id`/`status`/`total_files`/`success_count`/`failed_count`。

增加「超时未完成」响应示例，并指向 `GET .../task?task_id=&type=classification`。

任务查询章节：`type` 增加 `classification`；说明 `total_count`/`completed_count` 对分类为文件数。

- [ ] **Step 2: Commit**

```bash
git add docs/api/平台接入接口文档.md docs/api/API接口文档.md
git commit -m "docs: 文件分类接口异步超时与任务查询说明"
```

---

### Task 6: 测试

**Files:**
- Create: `tests/api/test_classification_async.py`

**Interfaces:**
- Consumes: FastAPI TestClient / httpx ASGI；Mock `FileClassificationAPIService.classify_files` 或内部 `_classify_single_file`

- [ ] **Step 1: 编写测试**

覆盖：

1. **快速完成**：mock service 立即返回 `ClassificationData(status=success, ...)`，`timeout=30000` → 响应非 pending，含 results  
2. **超时转 pending**：mock service `await asyncio.sleep(2)` 后返回；请求 `timeout=1000` → `status=pending` 且有 `task_id`；之后轮询/直接读 task_store 最终 COMPLETED（可用短 sleep + get_task）  
3. **进度字段**：在 service 真实走多文件 mock（每个 sleep 少量）时，超时后查 task，`completed_count` 递增或最终等于 `total_files`  
4. **重复 task_id**：第一次未完成时第二次同 id → pending，不双开（可 spy create_task / classify 调用次数）  
5. **resolve**：`type=classification` 能查到；错误 type → 404  

测试需 Mock Redis TaskStore 或使用测试环境已有 fixture；若项目已有 task_store 测试夹具则复用。禁止依赖真实 LLM/OCR。

示例骨架：

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_classification_timeout_returns_pending(client):
    async def slow_classify(*args, **kwargs):
        await asyncio.sleep(2)
        from src.schemas.classification import ClassificationData, ClassificationStatus
        return ClassificationData(
            request_id="r1",
            task_id="t1",
            status=ClassificationStatus.SUCCESS,
            results=[],
            total_files=1,
            success_count=1,
            failed_count=0,
            processing_time_ms=2000,
        )

    with patch(
        "src.api.v1.endpoints.classification.get_classification_api_service"
    ) as m:
        svc = m.return_value
        svc.classify_files = AsyncMock(side_effect=slow_classify)
        # POST /api/v1/file/classification with timeout=1000
        ...
```

按仓库实际 app fixture 名称调整（查找 `tests/conftest.py` 中的 client fixture）。

- [ ] **Step 2: 跑测试**

```bash
pytest tests/api/test_classification_async.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/api/test_classification_async.py
git commit -m "test(classification): 覆盖分类异步超时与任务查询"
```

---

## Self-Review Checklist

- [x] Spec 覆盖：API 契约、TaskType、endpoint 编排、service 进度、查询、取消、文档、测试均有对应 Task  
- [x] 无 TBD/占位步骤  
- [x] 命名一致：`total_files` / `completed_count` / `classification_` / `ClassificationStatus.PENDING`  
- [x] 默认超时 300000ms 与 `convert_timeout_to_seconds(..., 300)` 一致  

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-27-async-file-classification.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — 每 Task 新开 subagent，Task 间复查  
2. **Inline Execution** — 本会话按 executing-plans 连续执行并设检查点  

Which approach?
