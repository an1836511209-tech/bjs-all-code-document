# Report Agent 当前架构

> 状态：当前实现说明，不是迁移计划
>
> 事实基线：`apps/report_agent`、`contracts/mcp` 与三套环境配置
>
> 更新日期：2026-09-11

历史迁移分析保存在 [`archive/`](archive/)；当前开发与扩展以本文和代码为准。

## 1. 设计结论

Report Agent 是一个受约束的单主 Agent 文档应用，不是多 Agent 团队，也不是固定流水线：模型根据 Skill 自主读取材料、调用工具、写作和修订；应用代码负责权限、状态、契约、证据、预算、Word 结构和发布真实性。

核心边界：

1. Data MCP 负责外部事实、计算和候选；Agent 负责查询参数、材料理解和写作。
2. 材料解析结果和 Data MCP 完整响应都进入 Evidence；聊天记录不是事实库。
3. 当前写作主路径是 Markdown -> `ReportContent` -> DOCX，不使用旧 `ReportDraft/FactClaim`。
4. Skill 决定“做什么、按什么顺序、缺数据如何表达”；代码决定“允许什么、什么结果算成功”。
5. 模型不直接写 OOXML、不接触凭据、不传发布路径、不生成最终下载 URL。
6. 没有真实 `PublishedArtifact`，run 不能是 `completed`。

## 2. 服务和分层

```text
FastAPI / CLI entrypoints
  -> application
     -> domain
     -> harness ports
     -> infrastructure adapters
        -> Data MCP / MySQL / MinIO / OCR / LibreOffice / filesystem
```

| 层 | 主要目录 | 责任 |
| --- | --- | --- |
| API/entrypoints | `api/`、`entrypoints/` | HTTP、进程启动、显式数据库迁移 |
| application | `application/` | run、材料、Evidence、报告、Word 和发布用例编排 |
| domain | `domain/` | identity、状态、事件、Evidence、ReportContent、Artifact 模型 |
| harness | `harness/` | Deep Agents adapter、工具、预算、中间件 |
| infrastructure | `infrastructure/` | MCP、MySQL、MinIO、解析、Word 等外部实现 |
| runtime | `runtime/` | task workspace、路径边界、Bubblewrap/filesystem backend |
| settings | `settings/` | Pydantic 严格配置与 fingerprint |
| skills | `skills/` 与应用外 `skills/*` | Skill 发现、工具策略、写作规则、Word 脚本 |

第三方 Harness 只能从 `harness/factory.py` 构建，业务层不直接依赖 Deep Agents 私有实现。

## 3. HTTP 到最终产物的完整链路

```text
POST /api/dev/runs
  -> 校验消息/上传大小
  -> RunIdentity.create()
     task_id / session_id / run_id / workspace_id 各自独立
  -> TaskWorkspace.initialize()
  -> 上传文件保存到 /workspace/input
  -> MySQL repository.create()
  -> ConfiguredAgentExecutor
     -> 构建模型、backend、Evidence Store、Context Store
     -> 初始化 run-state/index/working memory
     -> 构建 Streamable HTTP Data MCP gateway
     -> readiness：五个契约工具必须可发现
     -> 激活 investment-report Skill、暂存 references
     -> 组装 ToolPolicy 允许的项目工具和 middleware
     -> create_deep_agent().ainvoke(thread_id=session_id)
  -> 收集模型消息、工具轨迹和 PublishedArtifact
  -> 有 artifact: completed
     无 artifact + 未解决工具失败: failed
     其余: needs_input
  -> MySQL repository.finish()
```

当前 `/api/dev/runs` 立即接受请求并在后台执行，同任务追问复用 workspace/session。投资报告及旧任务仍构造新 Agent，利用任务记忆继续；显式启用后新建的一页纸任务使用专用 MySQL checkpoint、真实 interrupt 和 Command(resume)，恢复完整工具上下文与执行位置。详见 [ADR-0003](adr/0003-one-pager-resumable-harness.md)。

## 4. Agent 是怎样构建的

### 4.1 组合根

`application/bootstrap.py` 是每次 run 的依赖组合根：

- 从不可变 Settings 解析模型和外部服务引用；
- 选择 test filesystem 或 Bubblewrap backend；
- 创建 Data MCP transport/contract registry/gateway；
- 激活 Skill、暂存 references、选择工具；
- 创建预算和 middleware；
- 调用 `harness.factory.build_agent()`。

密钥只用于构造 model、MinIO、MySQL、OCR 等 adapter，不进入模型工具参数。

### 4.2 Deep Agents profile

项目 profile 明确：

- 排除框架 `SummarizationMiddleware`，使用项目自己的压缩逻辑；
- 排除框架 `task` 工具；
- 关闭通用 subagent；
- 只保留一个主 Agent；
- 通过 `AgentBuildSpec` 注入 model/backend/tools/middleware/permissions。

### 4.3 Prompt 组成

```text
investment-report/SKILL.md 正文
  + Skill reference 使用说明
  + bootstrap 增补的 artifact-id 发布约束
  + WorkspaceContextMiddleware 注入的当前工作状态
```

`agents/openai.yaml` 提供 Skill 展示元数据，不是另一套系统 Prompt。

## 5. Skill 驱动的模型行为顺序

当前 `investment-report` Skill 固定业务意图，但保留模型逐步决策：

```text
1. parse_materials
2. 对每个 material_id 完整读取所有 blocks
   若 ToolMessage offloaded：按 next_offset 反复 read_result_chunk 到 null
3. 从已读材料确认 company_name、tags 等查询参数
4. 五个 Data MCP 工具全部尝试
   extract_project_profile
   -> query_track_labels
   -> match_listed_peers
   -> query_comparable_valuation
   -> match_investors
5. 逐个判断 success/partial/empty/failed
6. read_evidence/search_evidence 读取实际事实
7. write_file/edit_file 逐段维护 /workspace/report/report.md
8. read_file 完整自检内容、表格、数字、章节和 citation
9. create_word_from_md
10. read_evidence 后 add_report_comments 覆盖核心事实
11. validate_and_publish_word
```

单个 MCP 工具失败不连锁中止其他工具。无数据章节省略；全部没有可写事实时，不创建 Word。

Skill 是软流程，以下约束由代码硬执行：workspace 路径边界、只读目录、工具白名单、MCP schema、Evidence 引用状态、预算、DOCX 校验、MinIO 上传和最终成功状态。

## 6. 工具面与权限

`build_investment_report_tools()` 先组装全部可用项目工具，再由 Skill `allowed-tools` 与 `ToolPolicy` 精确选择。

| 组 | 当前主 Agent 工具 | 说明 |
| --- | --- | --- |
| Context | `get_working_context`、`list_context_indexes`、`load_skill_reference`、`read_result_chunk`、`search_result`、`list_result_paths` | 稳定状态、引用和外溢读取 |
| Materials | `parse_materials`、`read_material_chunk` | 材料解析和有界读取 |
| Data MCP | 五个标准工具 | 契约驱动的外部事实工具 |
| Evidence | `read_evidence`、`search_evidence` | 精确读取完整 Evidence |
| Word | `create_word_from_md`、`edit_word_document`、`add_report_comments`、`manage_word_comments`、`validate_and_publish_word` | 报告生产和交付 |

Deep Agents 自带的 workspace 文件工具服务 Markdown 编辑。项目权限明确禁止模型写入：

```text
/workspace/input/**
/workspace/references/**
/workspace/evidence/**
/workspace/state/**
/workspace/memory/**
```

报告写作区和受控输出由对应工具管理；模型不能通过路径绕过业务服务发布任意文件。

## 7. 材料与 Evidence

### 7.1 Material Evidence

```text
input file
  -> 类型检测/解析/必要的识别路由
  -> material_id + blocks
  -> 相同解析结果封装为统一 Evidence
  -> evidence_id
```

- `material_id`：只给 `read_material_chunk`。
- `evidence_id`：给 `ReportContent` citation 和 Word 来源批注。
- 二者是独立生成的 ID，不能替换前缀或互相推导。

### 7.2 Data MCP Evidence

```text
模型 tool arguments
  -> McpContractRegistry.validate_input
  -> MCP transport
  -> McpContractRegistry.validate_output
  -> WorkspaceEvidenceStore.put(完整 envelope)
  -> EvidenceView(轻量定位信息)
```

模型首次只看到 `evidence_id/tool/status/summary/warnings/path/sha256/size/json_roots`，要写具体事实必须再调用 Evidence 读取工具。

### 7.3 引用门禁

`ReportContentService.validate()` 检查所有引用的 Evidence 存在且可用；`empty/failed` Evidence 不能支持正文。当前 `EvidenceCitation` 只持有 `evidence_id`，不再保存 locator；模型通过读取原文理解语义，再显式编写面向读者的 Word 批注。

这意味着“citation 校验通过”证明引用对象可用，不单独证明每句话与原文语义完全一致；Skill 的完整读取、自检和真实材料验收仍是必要质量门禁。

## 8. ReportContent 与 Markdown

主 Agent 不逐字段构造大型 Pydantic 参数，而是在 workspace 编辑 Markdown：

```markdown
# 报告标题

## 一、章节标题

正文事实。
<!-- cite: evidence_xxx -->

| 指标 | 数值 |
| --- | --- |
| 示例 | 示例值 |
<!-- cite: evidence_xxx -->
```

`infrastructure/word/md_parser.py` 解析 Markdown 与尾随 citation，构造：

```text
ReportContent
  report_id / title / company_name / status
  title_citations[]
  sections[]
    paragraphs[]: text + citations
    bullet_items[]: text + citations
    tables[]
      headers[]
      rows[]: values + row citations + optional cell citations
  missing_items[]
```

`create_word_from_md` 先保存 ReportContent，再执行 Evidence 校验并标记 `ready`，最后才允许生成 DOCX。

底层仍保留 `create_report_content/upsert_report_section/get_report_content/validate_report_content` 供测试或其他 Skill 使用，但当前投资报告主链未把它们加入 `allowed-tools`。

## 9. Word 创建、批注与版本

```text
report.md
  -> parse_report_markdown
  -> ReportContentService.save/validate
  -> WordReportService.create
  -> WordReportAuthor (python-docx)
  -> WordReportValidator
  -> DocumentArtifact A
  -> add_report_comments
  -> word-document scripts 修改 OOXML
  -> 校验
  -> DocumentArtifact B
```

首次创建不自动生成来源批注；模型必须先读取 Evidence 原文，再使用正文精确子串作为锚点调用 `add_report_comments`。批注内容面向报告读者，不写内部工具名、Evidence ID、JSON 路径、凭据或服务器路径。

真实 Word 批注至少要求：`word/comments.xml`、正文 start/end/reference 锚点、relationship、content type 相互一致。编辑和批注修改都生成新的 artifact ID，已发布版本不原地覆盖。

`edit_word_document` 当前只支持 `replace_text`，并要求目标文本在单个 run 中连续出现；复杂结构编辑应回到 Markdown 重新生成，或先扩展确定性 Word service 和测试。

## 10. 校验、视觉复核与发布

```text
validate_and_publish_word(artifact_id)
  -> 解析内存 artifact registry
  -> WordReportService.validate_and_stage
     -> ZIP/OOXML/批注结构校验
     -> visual_review_required=true 时：
        当前 SHA 的 render receipt 必须存在
        且每个 page PNG 都已实际 inspect
  -> workspace staging
  -> MinioArtifactService.publish(path)
  -> PublishedArtifact
  -> context/artifact index + MySQL run result
```

修改 DOCX 会改变 SHA，因此开启视觉门禁时必须重新渲染和逐页检查。当前投资报告 Skill 未暴露独立 render/inspect 工具，三套环境默认策略必须与实际工具面保持一致；若开启视觉门禁，应先补齐并验证可达的模型工具流程，避免发布必然阻塞。

最终响应的 `filename/artifact_id/bucket/object_key/download_url/expires_at/sha256` 只能来自 `PublishedArtifact`。应用层会忽略模型自行声称的“已发布”。

## 11. Workspace、权威状态与上下文

```text
/workspace/input/                     用户材料，模型只读
/workspace/references/                Skill references，模型只读
/workspace/evidence/                  完整 Evidence + index，模型只读
/workspace/report/report.md           模型编辑稿
/workspace/report/report-content.json 程序化 ReportContent 状态
/workspace/output/                    DOCX 版本
/workspace/staging/                   通过门禁的待发布版本
/workspace/state/run-state.json       当前阶段、ID、已完成/失败工具
/workspace/state/result-index.json    大结果外溢索引
/workspace/artifacts/index.json       artifact 投影
/workspace/memory/working.md          简短恢复摘要，程序维护
/workspace/memory/conversation-history.md  压缩前完整旧消息
```

Context Store 在材料、Evidence、ReportContent 和 Artifact 状态变化后更新投影。聊天历史只保留短期推理；不确定时必须读取权威 state/index，而不是从摘要猜 ID。

### 大结果外溢

超过 `inline_tool_output_chars` 的普通成功工具输出写入 `/workspace/logs/tool-results/<result_id>.json`，上下文只保留摘要、哈希和 `next_actions`。模型必须用 `read_result_chunk` 直到 `next_offset=null`，或用路径/搜索工具定位。

失败 ToolMessage 保持简短内联，不外溢为看似成功的结果。Evidence 有自己的完整存储和读取工具，不依赖普通外溢文件。

### 对话压缩与硬停

- 达到 `compression_trigger_ratio` 时，项目 middleware 使用同一模型压缩旧消息，保留最近若干消息。
- 完整旧消息追加到 conversation history 文件。
- 达到 `hard_stop_ratio` 时阻止继续扩张上下文。
- `LLM_MAX_CONTEXT_TOKENS` 从环境变量解析，小于 4096 直接失败。

## 12. Middleware

当前组合顺序：

1. `ToolArgumentRecoveryMiddleware`：修复结构化参数，次数受配置限制。
2. `EmptyToolCallsGuardMiddleware`：处理模型返回空 tool calls 的协议异常。
3. `BudgetMiddleware`：模型次数、工具次数、总时间上限。
4. `ToolFailureEnvelopeMiddleware`：统一工具失败语义。
5. `ToolOutputOffloadMiddleware`：大型成功结果写 workspace。
6. `ContextCompressionMiddleware`：接近窗口时压缩旧消息。
7. `ContextHardStopMiddleware`：超过硬阈值停止。
8. `WorkspaceContextMiddleware`：把当前权威进度注入请求。
9. `MessageIntegrityGuardMiddleware`：保护 AI tool call 与 ToolMessage 配对。
10. `AgentCallLoggerMiddleware`：最内层记录最终请求和响应，执行脱敏。

新增 middleware 时必须明确它作用于 model request、tool call 还是 tool result，并验证顺序不会破坏消息配对、错误状态或敏感信息边界。

## 13. 配置与持久化

```text
runtime.env
  -> REPORT_AGENT_CONFIG
  -> report-agent.yaml
  -> load_settings()
  -> ReportAgentSettings(extra=forbid, frozen=true)
  -> bootstrap
```

配置组：`service/model/harness/context/sandbox/data_mcp/document_processing/persistence`。非法额外字段、非绝对路径、缺少 Streamable HTTP URL、工具清单不是恰好五个、或 UAT/生产使用 filesystem backend都会使启动失败。

test 本地 YAML 可以使用 `${REPO_ROOT}`；`load_settings()` 会从配置文件位置向上定位仓库根并在 Pydantic 校验前展开，使 Windows 本地配置不依赖固定 clone 路径。容器和 UAT/生产仍使用明确的绝对 POSIX 路径。

MySQL 保存 task/session/run/artifact 元数据；DDL 只由显式迁移执行。一页纸 checkpoint 使用独立 schema，迁移命令为 `report-agent-db-migrate --checkpoints --apply`，启动不建表。投资报告不连接该 schema；Redis 队列尚未接入。当前一页纸恢复限单 worker 与持久共享工作区。

## 14. 扩展指南

| 需求 | 改动入口 | 关键回归 |
| --- | --- | --- |
| 调整报告结构/写作 | Skill + references | 完整读取、缺失章节、Markdown/citation、真实材料 |
| 修改模型可用工具 | Skill `allowed-tools` + ToolPolicy | 未授权工具不可见、工具名唯一 |
| 新增 MCP 工具/字段 | `contracts/mcp` + 两端实现 | 双端 schema、readiness、四状态、Evidence |
| 新材料格式/OCR 路由 | materials application/infrastructure | 类型检测、blocks、Material Evidence、分页 |
| 改 ReportContent | domain + reports + md_parser + authoring | schema、幂等验证、Word、批注、旧文件行为 |
| 复杂 Word 编辑 | Word service/scripts | 新版本、OOXML、批注锚点、结构与视觉 |
| 跨请求续跑 | checkpointer + identity/API 语义 | 同 session 恢复、并发、进程重启、迁移 |
| 异步任务 | API/worker/queue + Redis | 幂等、取消、重试、状态机、artifact 真值 |
| 开启视觉门禁 | tools + runtime + YAML | render receipt、逐页 inspect、修改后重渲染 |

原则：Prompt/Skill 能表达的业务策略不要硬编码成固定流水线；安全、契约、状态、证据和发布真实性不要交给 Prompt 保证。

## 15. 当前边界和已知风险

- 同步开发 API，不是生产异步任务平台；正式鉴权和用户端未实现。
- 投资报告仍未使用持久 checkpointer；一页纸可选的恢复能力不能视为所有 Skill 已有生产队列或跨主机恢复。
- Redis 未进入队列主链。
- Word artifact registry 当前在单次 executor 内存中；同 run 内可编辑，跨进程恢复需补持久 artifact 解析/registry。
- citation 当前只存 `evidence_id`，语义一致性依赖模型读取、自检和验收。
- `add_report_comments` 使用文本子串定位；重复或跨 run 文本可能需要更稳定的锚点策略。
- 开启视觉复核前需确保 render/inspect 工具面与 Skill 一致。
- 真正上线前必须跑真实材料、真实五工具、MySQL、MinIO、OCR、模型和 Linux sandbox 端到端验收。

## 16. 验证

```powershell
uv run --package bjs-report-agent pytest apps/report_agent/tests
uv run --package bjs-report-agent ruff check apps/report_agent/src apps/report_agent/tests
uv run --package bjs-report-agent mypy apps/report_agent/src/report_agent
uv run --package bjs-report-agent report-agent-spike --workspace-root .runtime/spike
```

与框架和持久化有关的决策见 [ADR-0001](adr/0001-deep-agents-harness-boundary.md) 和 [ADR-0002](adr/0002-use-existing-mysql-for-langgraph-checkpoints.md)。
