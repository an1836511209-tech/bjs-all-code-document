# Run Console 事件契约

前端「运行控制台」消费的事件流约定。后端应以 `text/event-stream` 推送，每条消息体为 JSON。

## 传输

```
GET /api/runs/{run_id}/events
Accept: text/event-stream
```

服务端格式：

```
id: 1
event: message
data: {"schema_version":"1.0","seq":1,"type":"run.started",...}

```

要求：

- `id` 单调递增；断线重连时客户端带 `Last-Event-ID` 续传。
- 每 15s 发送一次注释心跳 `:\n\n`。
- 终态事件（`run.completed` / `run.failed`）之后关闭流。
- `approval.required` 表示本轮等待补充，关闭本轮事件流；业务任务继续保留。
- 重连可以通过 `Last-Event-ID` 或 `after_seq` 传游标；前端按 `(run_id, seq)` 去重。

## 通用信封

```jsonc
{
  "schema_version": "1.0",
  "seq": 12,                       // 单调递增
  "type": "tool.completed",
  "occurred_at": "2025-06-12T09:31:02.431Z",
  "task_id": "task_xxx",
  "session_id": "session_xxx",
  "run_id": "run_xxx",
  "workspace_id": "ws_xxx",
  "payload": { }
}
```

对应后端 `report_agent.domain.events.AgentEvent`。前端只依赖 `type` 与 `payload`，其余字段透传。

## 事件类型

### 生命周期

| type | payload | 前端表现 |
|---|---|---|
| `run.started` | `{ run_id, task_id, skill_hint? }` | 开始计时，显示运行条 |
| `run.completed` | `{ duration_ms, status }` | 终态，展示产物与总耗时 |
| `run.failed` | `{ error, retryable }` | 终态，红色错误条 |
| `run.paused` | `{ reason }` | 暂停态 |
| `skill.activated` | `{ skill: "one-pager"\|"investment-report", route, description? }` | 顶部 Skill 徽章 |
| `plan.updated` | `{ items: [{ id, text, status }] }` | 兼容旧语义，优先用 `todo.updated` |

### 步骤（skill 的 write_todos）

| type | payload |
|---|---|
| `todo.updated` | `{ items: [{ id, text, status: "pending"\|"in_progress"\|"done" }], current? }` |
| `step.started` | `{ step_no, title, skill }` |
| `step.completed` | `{ step_no, summary?, duration_ms? }` |

前端以 `step_no` 为键维护步骤轴；`todo.updated` 用于在步骤内拆子项。

### 工具 / MCP

| type | payload |
|---|---|
| `tool.started` | `{ call_id, tool, step?, provider?: "data_mcp"\|"local" }` |
| `tool.progress` | `{ call_id, stage: "connecting"\|"waiting"\|"receiving", percent? }` |
| `tool.completed` | `{ call_id, tool, status: "success"\|"partial"\|"empty"\|"failed", duration_ms, summary?, output_preview? }` |
| `tool.failed` | `{ call_id, tool, error, retryable }` |

`status` 的四个值来自 Data MCP 契约：`success / partial / empty / failed`。前端对 `partial` 与 `empty` 使用**橙色**而非红色——skill 明确要求它们不连锁放弃。

### 证据

| type | payload |
|---|---|
| `evidence.created` | `{ evidence_id, kind: "material"\|"project_profile"\|"investor_candidates"\|"valuation"\|"peer_match"\|"track_labels", summary, count?, preview? }` |

`preview` 是给 UI 用的轻量结构（如候选名单前 5 条），**不是完整 Evidence**。完整数据由 agent 按需 `read_evidence` 读取，前端不展示全文。

### 待人工确认

| type | payload |
|---|---|
| `approval.required` | `{ approval_id, question_id, run_id, kind: "choice"\|"text"\|"upload_prompt", question, options: [{ value, label }], context, allow_free_text }` |
| `approval.resolved` | `{ approval_id, answer }` |

对应后端已有事件。前端在暂停态把它渲染为内联确认卡，用户选择后调用：

```
POST /api/runs/{run_id}/resume
{ "approval_id": "...", "answer": "增资" }
```

工作台统一走 `POST /api/dev/runs` 的表单提交：`task_id`、`question_id`、可选 `choice_value` 和 `message`（额外说明），也支持补传材料。已有 `/resume` 接口兼容纯文本回答，沿用原 `task_id`，不再复制成新任务。返回的新 `run_id` 仅表示继续执行的一轮。问题卡用具体业务选项和文本输入，不能把缺省选项统一画成“确认无误/有些出入”。

刷新先读取 `GET /api/tasks/{task_id}/state`，恢复技能、当前运行、待回答问题和产物，再续接事件。卡片草稿保存在当前聊天中；已发送答案及说明进入后端同一任务的对话记忆。

工商名称补正使用 `kind="registry_name"`、`gate="company_registry"`，选择值为 `correct_name`（展开名称输入，名称必填）或 `skip`（不要求输入，不再查询工商）。它表示可选补数的告警处理，不表示 BP 任务失败；后端持久化补正名称或跳过决定。

业务类型判定使用 `kind="business_type"`、`gate="one_pager_business_type"`，固定选择值为 `产权` 和 `增资`。判定工具通过 question_request 直接触发，无需 ask_user 或问题文本关键词；此步骤不可跳过。用户选择和附加说明进入同一任务，已确认值保存在 business_type_selection 中，并供判定与渲染工具校验。

### 产物

| type | payload |
|---|---|
| `artifact.created` | `{ artifact_id, kind: "docx"\|"md"\|"pdf", filename, size_bytes, version }` |
| `artifact.validated` | `{ artifact_id, valid, download_url?, sha256?, expires_at? }` |

发布成功前 `download_url` 必须为空。前端不得凭 `artifact.created` 就显示下载按钮。

### 其他

| type | payload | 说明 |
|---|---|---|
| `workspace.changed` | `{ path, action }` | 调试用，控制台默认折叠 |
| `context.compacted` | `{ before, after }` | 调试用 |
| `tool.recovery` | `{ call_id, action }` | 工具失败恢复提示 |

## 前端状态机

```
idle ──run.started──▶ running
running ──approval.required──▶ waiting
waiting ──approval.resolved──▶ running
running ──run.completed──▶ completed
running ──run.failed──▶ failed
```

`waiting` 状态下停止自动滚动，但**不遮挡**已完成内容。

## 断线重连

客户端保存最后收到的 `seq`，重连时：

```
GET /api/runs/{run_id}/events
Last-Event-ID: 42
```

服务端从 43 开始重发。若 run 已终态，重连应立即补发全部历史事件后关闭。

## 兼容性

- `schema_version` 变化时前端降级为"原始事件 JSON 列表"。
- 未知 `type` 一律折叠显示，不报错。

## 一页纸检查点续跑（第一批）

仅检查点任务的待回答载荷增加 `checkpointed=true`、稳定 `question_id`、`interrupt_id`、`origin_tool`、`resume_node`。客户端仍按现有提交接口传 task_id/question_id/choice_value/message，后端转成恢复命令；不能让客户端指定任意图节点。

`skill.activated` 可带 `resuming` 和 `plan`，恢复时保留完成进度。任务快照的 `execution` 包含 plan、next、checkpoint_id 和 event_stream_id；刷新以快照为准，stream_id 变化时重置旧进程的 SSE 游标。投资报告及旧任务无需这些字段。

## 可选投资机构匹配附件

提交表单独立携带 `institution_workbook=true/false`，省略时继承当前对话选项。用户消息不包含开关指令。`GET /api/features` 返回 `institution_workbook.enabled/worker_online`。

辅助任务独立于 run SSE：主报告 `run.completed` 后关闭 SSE，前端继续轮询 `GET /api/tasks/{task_id}/auxiliary-jobs`，返回有界 `jobs` 与已登记 `artifacts`。切换对话、页面隐藏时暂停；刷新/重新进入从快照恢复。模块 unavailable/failed/skipped/cancelled 不改变主报告状态或计划。

`POST /api/tasks/{task_id}/institution-workbook` 使用 `client_request_id` 幂等提交，可带 `selected_tags` 或 `refresh_tags`，不启动新 run。取消通过 `POST /api/tasks/{task_id}/auxiliary-jobs/{job_id}/cancel`。

自动附件优先记录并复用当前报告 `match_investors` 的实际 `track_tags`（一个或多个），不再次调用精选模型；没有这项关联的旧任务明确跳过自动生成，保留手选/更新标签入口。自动复用最多 10 个标签；手选上限仍由任务的 `max_selected_tags` 给出，超限不截断。

辅助任务增加 `tag_group_fingerprint` 和失败时的 `error_code`。重新生成提交 `source_job_id`、`expected_context_fingerprint`、`expected_tag_group_fingerprint`，使界面候选与服务端校验绑定同一任务快照；更新后的候选不覆盖原报告证据。省略 `selected_tags` 时可复用来源任务的手动选择和已经校验的工作簿。材料或标签组变化返回 422，要求刷新选择。

一次请求响应丢失后，前端保留 `client_request_id`，再次提交相同参数时复用，避免重复任务。请求 ID 兼容没有 `crypto.randomUUID` 的浏览器上下文。

新增 XLSX 通过 artifact_id 去重、按任务绑定；默认保留 Word 预览。`GET /api/artifacts/{artifact_id}/preview` 提供四列前 20 行与来源版本；下载统一使用 `/api/artifacts/{artifact_id}/content`，MIME 按扩展名区分 DOCX/XLSX。
