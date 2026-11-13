# 一页纸 BP 路由与前后端交互排查

日期：2026-10-29。范围：当前工作区的 console.js、API、运行服务、技能选择、提问工具及事件流；未修改业务实现。已有用户未提交修改保持原样。

## 结论与边界

首轮 `skill=one-pager route=keyword` 已说明关键词路由成功。之前提供的标题超时发生在独立的自动命名请求，异常被捕获并使用文本标题兜底，不能据此判定 BP 主流程失败。

主要问题是任务、单轮运行、待回答问题、前端聊天四种状态没有统一归属。当前实现一方面按聊天复用工作区，另一方面每轮重新选技能；UI 又持有一份全局状态和一份聊天状态，刷新后只重放部分事件。因而首轮正常，问答、切换、重连后出现异常。

以下“复现”指调用本地实现的最小探针，使用模拟模型，不是完整模型生成或浏览器端到端测试。

## 1. P1：回答问题后会切换技能（已复现）

位置：`application/bootstrap.py::_resolve_skill_name`、`frontend/assets/console.js::resolveApproval`。

触发：自动路由生成一页纸 → 模型问产权/增资 → 点击“产权”。前端只提交 `message=产权` 和当前下拉框值；自动模式下不传 `selected_skill`。后端只看本轮消息，历史在选择技能之后才读取。

探针结果：首轮 `one-pager/keyword`；相同 task_id 的“产权”追问变成 `investment-report/fallback`。“继续”“增资”“yes”“skip”同样回落。单独的“单页BP”“BP”也未命中一页纸，但 BP 可能指完整商业计划书，不宜把所有 BP 无条件映射成一页纸。

修复：后端持久化任务的 `active_skill` 和初始目标；回答待处理问题必须继承该技能。新任务才使用“显式选择 → 部署策略 → 首轮意图识别”。切换已有任务技能应是独立的显式操作，不能靠简短回答触发。前端分别保存 `requestedSkill` 与后端返回的 `activeSkill`，下拉框按聊天恢复。

## 2. P1：两条继续路径语义不一致（已复现/代码确认）

位置：`application/runs.py::resume`、`console.js::resolveApproval/postResume`。

当前在用的回答卡走新提交、复用 task_id，但丢技能；后端 `/resume` 把原消息与回答拼接后调用 submit，没有传 task_id，创建全新工作区，原证据、报告、历史不再沿用。探针验证 `resume_same_task=false`。前端 `postResume` 没有调用方，而且调用 `subscribeEvents(data.run_id)` 与实际签名 `(conversation, runId)` 不符。

修复：统一一个回答入口，接收 task_id、run_id、question_id、option_value 或 text、client_message_id；沿用原工作区，创建新 run，保存 `continued_from_run_id`。当前无需先引入完整图检查点，先实现“同一任务、持久化业务状态、新运行继续”即可。删除或修复未使用的旧路径，更新事件契约。

## 3. P1：前端异步共享状态会被覆盖（已复现）

位置：`console.js::enterRuntime/exitRuntime/submitLive`。

`savedState` 只有一个槽位，submitLive 在 enterRuntime 后 await fetch。另一聊天提交或已有 SSE 回调在这个等待区间进入 enterRuntime，会覆盖备份；内层 exitRuntime 将它置空，外层随后访问 savedState.aiEl 抛异常。

探针结果：`Cannot read properties of null (reading 'aiEl')`。这是对原函数的交错调用复现，具体真实页面出现频率仍需浏览器测试。

修复：所有 reducer、渲染、计时器、预览以 conversation/runtime 为显式参数；禁止在 await 两侧借用全局渲染状态。短期把请求与同步渲染阶段分开，状态备份仅限同步回调局部 try/finally。每个异步回调捕获 conversationId、runId，并丢弃不属于当前运行的迟到事件。后端增加每 task 单个活动运行约束，防止两个标签页同时写同一工作区。

## 4. P1：刷新损坏问题卡和下载链接（已复现）

位置：`console.js::trimEvent/saveState/replayEvents/hydrateFromBackend`。

trimEvent 删除全部对象和数组，因此 approval.required 的 options 消失；所有字符串最多保留 200 字符，因此长问题与下载 URL 被截断。探针中完整选项丢失，长下载 URL 保存为 201 字符（含省略号）。刷新后会把选择题还原为通用“确认无误”，改变问题含义。

此外仅存最后 300 条事件，可能移除 skill.activated；每轮又清空 conversation.events，无法完整恢复多轮执行。lastRunId 虽保存，但启动路径没有用它重新订阅事件。后端 hydrate 只追加未知 task，已知任务不校准当前状态。

修复：按事件类型保存必需字段，保留选项、问题 id、完整标识；展示摘要和可执行 URL 分字段。刷新先读取服务端任务快照，再按游标补事件。文档下载使用 artifact_id 对应的稳定接口，下载时刷新签名 URL。历史消息按 run_id 关联，不能把全部用户消息放在最后一轮事件前重放。

## 5. P1：提问并没有强制暂停执行（代码确认，模型行为待端到端验证）

位置：`harness/ask_user_tools.py`、`application/runs.py::_execute`。

ask_user 只是普通工具返回 JSON 和“请暂停”文字，没有流程中断控制。模型可能继续调用工具。服务层是模型结束后才依据“有产物/工具错误/其他”推断 completed/failed/needs_input；没有结构化待回答问题时，正常说明或业务错误也可能被当成需要确认。

修复：把 ask_user 结果交给运行控制层，登记待处理问题并结束本轮可执行流程；存在待回答问题时禁止后续写作、渲染、发布。问题包含 gate（业务类型/公司名称/公开搜索/挂牌状态）、选项和回答 schema。回答验证、消费、提交下一运行必须原子化且幂等；无产物但非提问应明确返回失败或草稿状态。

## 6. P2：提问字段在实时页面也被丢弃（已复现）

位置：`console.js::handleLiveEvent/showApproval`。

approval.required 事件已有 context 与 allow_free_text，但 handler 只传 question/impact/options。探针确认 showApproval 收不到上下文及自由输入约束；allow_free_text=false 仍会显示“其他”。无选项问题被渲染成“确认无误/有些出入”，不适合要求输入公司全称。

修复：完整透传类型化问题模型。区分选择题、文本输入、补传材料、真正确认四类交互；回答成功后才标记为已处理，失败保留卡片允许重试；卡片绑定所属 conversation/question，不能在点击时读取全局 currentConversation。

业务类型工具的 _parse_user_hint 只接受“产权/增资/property/capital”；探针确认“股权转让”“增资扩股”返回 None。按钮内部值可保持规范枚举，自由文本应做同义词归一化并保留原始回答。

## 7. P2：SSE 断线与等待状态不闭环（代码确认）

位置：`api/app.py::stream_run_events`、`application/event_bus.py`、`console.js::subscribeEvents`。

服务端每次从 cursor=0 回放，未读取 Last-Event-ID；前端不按 run_id/seq 去重。自动重连可能重复追加卡片、问题、回复。等待输入时不发运行结束事件，bus.is_terminal=false（探针确认），旧流会一直等待。没有注释心跳，服务器重启后内存事件也无法恢复。断线 onerror 没有状态对账或错误提示。

修复：持久化或可从快照重建的事件序列，读取 Last-Event-ID/after_seq；客户端按 `(run_id, seq)` 去重。单轮结束等待回答时发明确的 run.waiting_input/turn.ended 并结束该运行的流；区分“本轮结束”和“业务任务完成”。15 秒注释心跳；断线后显示重连状态并用快照对账。当前等待信号清除存在竞争时最长延迟约 1 秒，不是主要根因。

## 8. P2：页面进度和工具颜色会误导（已复现/代码确认）

位置：`console.js::advancePlanForTool`、`bootstrap.py::_summarize_tool_output/_handle_stream_event`。

一个阶段中第一个工具结束就标记整阶段完成，忽略 failed/partial；后端只发送工具事件，没有把 write_todos 结果转成计划更新事件。工具状态通过字符串含 error/failed 推断，探针中 needs_user_input 显示 success，`status=ok,errors=[]` 反而显示 failed。invalid_outline 只有状态字段时也会被识别 success；实际大纲工具额外 error 字段通常使它显示 failed，不能把该探针等同于实际大纲成功着色。

修复：从工具结构化 status 提取 UI 状态，区分成功、待输入、待修正、部分、失败；异常与业务状态分开。计划由后端步骤事件或明确业务凭据更新，工具完成只影响工具行。等待输入时停计时或显示等待时长。当前排队消息仅在 finishTurn 排出，进入 waiting/failed 时应显示队列并让用户决定作为补充回答或保留，不能静默挂起。

## 9. P1：一页纸画像输入链路未接齐（代码确认）

位置：`bootstrap.py` 的 one-pager 工具组装、`skills/one-pager/SKILL.md`、`harness/material_tools.py`。

one-pager 的 allowed-tools 未包含 export_parsed_md/export_material_text，尽管 material_tools 定义了它们；该分支也未传 upload_markdown。skill 3.2 引用“3.1 的 material_url 或 file_info”，但 3.1 是工商查询，不会提供材料 URL。模型缺少明确完整材料出口，容易自行摘要后传入画像。

修复：共享材料导出构造，接好 upload_markdown 并开放两个导出工具；skill 写明“导出完整解析材料 → material_url；失败则完整 file_info”，禁止把工商查询结果当材料全文。MCP readiness 也应在确定 skill 后按实际依赖检查，当前先检查全局工具再路由会使无关工具缺失阻断任务。

## 建议落地顺序

1. **先稳定任务和问答**：持久化 active_skill、原始目标、pending_question；统一回答接口；task 运行互斥与请求幂等；修复前端异步状态归属。验收首轮、产权/增资、搜索 yes/skip、挂牌 yes/no/unknown 的多轮回答全部保持同 task、同 skill。
2. **补齐一页纸业务输入**：完整材料出口、业务类型同义词、明确的提问停止机制；澄清 skill 中投资人“至少 1 个”与“全空可占位”的口径，避免无数据时反复重试。
3. **再做刷新与重连**：快照恢复、持久化待回答卡、事件游标/去重、稳定下载接口、过期签名刷新。
4. **最后修正展示和可观测性**：真实步骤进度、准确工具状态、每聊天计时/预览/选择器、非阻塞标题失败提示。自动命名保持独立降级，不应与主流程错误混为一谈。

建议接口骨架：

```text
POST /api/tasks                         创建任务，解析并返回 active_skill
POST /api/tasks/{task_id}/messages      普通后续消息，沿用任务
POST /api/tasks/{task_id}/answers       消费 question_id，返回新的 run_id
GET  /api/tasks/{task_id}/state         skill/phase/active_run/pending_question/artifacts/last_seq
GET  /api/runs/{run_id}/events          游标续传
GET  /api/artifacts/{artifact_id}/content  稳定下载
```

已有接口可以先增加兼容适配，不要求一次性迁移 URL。回答请求必须同时带稳定选项值与 question_id，不能只发送无上下文的“yes”。

## 验收矩阵

| 场景 | 必须结果 |
|---|---|
| 自动路由一页纸 → “产权/增资” | task_id/active_skill 不变，新 run 关联旧 run |
| 输入“股权转让/增资扩股” | 正确归一化，不重复追问 |
| 查不到公司后自由补公司名 | 只补对应 gate，原材料和证据保留 |
| 回答搜索 skip、挂牌 unknown | 分支正确且答案绑定对应问题 |
| 传错材料后重传 | 明确替换/追加语义，旧错误材料不继续混用 |
| 双击回答、提交超时重试、双标签页 | 一次消费、一条运行、无并发写工作区 |
| A 运行、B 提交、切回 A | 不串技能、卡片、预览、计时器，无 JS 异常 |
| 问题卡刷新 | 问题、选项、约束、处理状态完整恢复 |
| 生成过程中刷新或 SSE 断线 | 续接原 run，不重复工具行或卡片 |
| 服务重启后恢复 | 状态明确可继续或可恢复失败，不永久“运行中” |
| 发布后刷新/签名过期 | 用 artifact_id 获取有效下载 |
| 画像或匹配失败/为空 | UI 准确显示，不自动当作确认题 |

## 验证记录

- `.runtime/diagnostics/probe_bp.py`：模拟执行器验证技能回落、resume 新任务、等待事件不闭合、用户提示词归一化及工具摘要分类。Windows 沙箱的异步运行受限，使用获准的沙箱外本地进程完成；未调用模型或外部服务。
- `.runtime/diagnostics/probe_bp.cjs`：抽取当前前端函数，在隔离 JS 上下文中复现共享备份覆盖、选项丢失、URL 截断和提问字段丢弃；未操作用户浏览器。
- 现有 `test_async_runs.py` 执行结果为 **4 passed / 1 failed**。失败用例为 `test_investment_page_downloads_artifact_through_agent`：模拟 executor 没有接受服务新增的 `selected_skill` 关键字参数，运行先发生 TypeError，随后下载断言得到 404。这是测试替身接口未同步，不能当作生产下载接口故障。该文件未覆盖上述交互路径。
- 没有运行完整 BP 生成，因此模型是否越过 ask_user、页面出现竞态的实际频率、外部 MCP 行为仍需上述验收矩阵补测。
