# Report Agent 目标架构与主分支迁移方案

> 方案日期：2026-09-09\
> 状态：待评审，不执行代码迁移\
> 前置材料：[Report Agent 现状梳理与主分支迁移预研](./report-agent-migration-prestudy.md)\
> 目标分支：`main`

## 1. 建设目标

本次迁移不是把旧 Agent API 原样搬到主分支，而是建设一个面向文档写作、具备自主规划和工具调用能力的 Agent Harness。它应像 Codex/Cursor 一样能够围绕目标持续规划、读取资料、调用工具、操作独立工作空间、执行受控 Shell/Python、检查结果并迭代，但业务边界只覆盖“基于用户材料、Data MCP 数据和写作 Skill 从零生成可交付 Word 文档”。

目标能力包括：

1. 自主任务循环：理解目标、维护计划、选择工具、观察结果、调整计划、完成验收。
2. 标准 Harness：模型、工具、MCP、Skill、上下文、工作空间、执行环境、检查点和事件流均有明确接口。
3. 隔离执行环境：每个任务拥有独立文件系统和进程空间，可创建、读取、修改、暂存、移动、软删除文件，并执行受控 Shell/Python。
4. 上下文治理：长工具结果落盘、按需读取、自动压缩旧对话、持久化检查点，避免超过模型上下文限制。
5. 插件式能力：Data MCP 作为标准 MCP server 接入；写作流程和 Word 操作以 Skill + scripts + tools 组合交付。
6. Word 生产闭环：材料解析、数据取用、草稿、完整 Word 创建、批注/引用、结构验证、渲染和视觉检查均可由 Agent 调用。
7. 可审计和可恢复：每次模型调用、工具调用、文件变化、上下文压缩、用户确认和产物版本均可追溯。

## 2. 明确不做的范围

- 不建设通用编码 IDE，不追求任意仓库的软件开发能力。
- 不在第一阶段引入多 Agent 编队；文档写作使用单主 Agent 即可，后续仅在超长章节并行确有收益时再评估。
- 不让 Agent 直接访问业务数据库、企查查、搜索接口或 Data MCP 内部 Python 模块。
- 不允许模型直接操作宿主机任意目录，也不把生产环境 Shell 设置为无限制访问。
- 不把固定业务流程全部硬编码成不可调整的 pipeline；关键安全和交付约束由代码保证，写作策略由 Skill 控制。
- 不把聊天历史当事实库、证据库或文档版本库。

## 3. 参考方案与技术选择

### 3.1 Codex：采用运行原则，不直接嵌入

Codex 值得复用的不是“编码”场景，而是以下运行原则：

- 沙箱定义 Agent 能自主操作的技术边界，审批策略决定何时暂停；Shell、Git、包管理器等子进程继承同一沙箱限制（[OpenAI Codex Sandbox](https://learn.chatgpt.com/docs/sandboxing.md)）。
- Skill 以 `SKILL.md + references + scripts` 组织，并通过渐进披露先暴露名称和描述、命中后再读取完整说明（[OpenAI Build skills](https://learn.chatgpt.com/docs/build-skills.md)）。
- MCP 需要 server 级和 tool 级 allowlist、超时、输出 token 限制及审批策略，而不是把所有工具无条件交给模型（[OpenAI MCP configuration](https://learn.chatgpt.com/docs/mcp.md)）。
- thread 可继续与恢复，文件修改和执行均受 workspace 边界控制（[OpenAI Codex SDK](https://learn.chatgpt.com/docs/codex-sdk.md)）。

本项目不直接采用 Codex SDK 作为生产内核。原因是它更适合嵌入 Codex 的通用工程 Agent，当前 Report Agent 是 Python 服务，需要完全掌控模型供应商、MCP 数据契约、Word 工具、任务状态和部署环境。我们复用其 workspace、sandbox、approval、Skill 和审计设计，而不绑定 Codex 本地运行时。

### 3.2 LangChain / LangGraph Deep Agents：建议作为 Harness 基座

建议使用 `deepagents`/LangGraph 作为目标 Harness 基座，而不是继续维护旧分支的自制 Agent loop。当前官方能力已经覆盖本项目需要的大部分通用机制：

- 内置任务规划 `write_todos`、文件系统工具和自动摘要/工具结果卸载（[Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview)）。
- 可插拔 filesystem/sandbox backend，支持 `read_file`、`write_file`、`edit_file`、`delete`、`glob`、`grep` 和 `execute`（[Deep Agents backends](https://docs.langchain.com/oss/python/deepagents/backends)）。
- sandbox 内运行 Shell，并区分 Agent 文件工具与宿主应用的文件上传/下载通道（[Deep Agents sandboxes](https://docs.langchain.com/oss/python/deepagents/sandboxes)）。
- Skill 可以携带 scripts，并在 Agent 运行前同步进 sandbox（[Deep Agents skills](https://docs.langchain.com/oss/python/deepagents/skills)）。

采用方式不是“全量默认开启”，而是：使用 Deep Agents 提供的规划、文件系统、上下文和 middleware 体系；关闭首期不需要的 subagent；以自有 ports/adapters 接入 Data MCP、持久化和 Word 工具；通过版本锁和适配层隔离框架升级。

### 3.3 DeepSeek Harness：只借鉴插件内核思想

[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 的“一切皆插件”、model/tool/runtime/session 可替换设计值得参考，但它是另一套以 TypeScript/插件内核为中心的运行体系，与当前 Python monorepo 和 LangGraph 状态模型重叠较大。迁移期不将其引入为第二套运行内核，避免双 Harness、双插件协议和跨语言调试成本。

### 3.4 最终选择

```text
Agent loop / planning / context / filesystem middleware
    = Deep Agents + LangGraph

Task state / evidence / workspace / MCP gateway / Word delivery
    = Report Agent 自有领域层与基础设施层

Execution isolation
    = 自有 SandboxBackend 适配器；开发可本地受限，生产使用容器沙箱

Business behavior
    = Repository Skills + deterministic Word tools
```

## 4. 目标总体架构

```text
                         ┌──────────────────────────┐
                         │ API / CLI / Future UI    │
                         └────────────┬─────────────┘
                                      │ Run / Resume / Events
                         ┌────────────▼─────────────┐
                         │ Report Application Layer │
                         │ task/session/run/artifact│
                         └────────────┬─────────────┘
                                      │
                   ┌──────────────────▼──────────────────┐
                   │ Agent Harness                       │
                   │ planning · middleware · checkpoint  │
                   │ context · skill · tool policy       │
                   └───────┬───────────────┬─────────────┘
                           │               │
              ┌────────────▼──────┐  ┌─────▼────────────────┐
              │ Task Sandbox      │  │ MCP Runtime           │
              │ files · shell · py│  │ Data MCP tools/schema │
              └────────────┬──────┘  └─────┬────────────────┘
                           │               │
             ┌─────────────▼───────────────▼──────────────┐
             │ Document Skills and Deterministic Tools     │
             │ parse · draft · docx · comments · validate │
             │ render · inspect · package                  │
             └─────────────────────┬───────────────────────┘
                                   │
             ┌─────────────────────▼───────────────────────┐
             │ Persistence and Artifact Store              │
             │ checkpoints · evidence · events · versions  │
             └─────────────────────────────────────────────┘
```

### 4.1 领域标识

以下标识必须分离，不能继续全部复用 `task_id`：

| 标识             | 含义                           |
| -------------- | ---------------------------- |
| `task_id`      | 一次文档生产业务任务，可包含多个会话和多次生成      |
| `session_id`   | 用户与 Agent 的连续会话，对应可恢复 thread |
| `run_id`       | 一次 Agent 执行，从输入到暂停、失败或完成     |
| `workspace_id` | 任务沙箱实例及文件版本空间                |
| `artifact_id`  | 输入材料、中间件、DOCX、PDF、预览等产物      |
| `evidence_id`  | 材料片段或 MCP 响应中的稳定证据引用         |

## 5. Harness 设计

### 5.1 自主执行循环

主 Agent 保持 ReAct 式模型自主性，但由 Harness 提供确定性护栏：

```text
接收目标
  → 加载 task runtime context
  → 选择/加载 Skill
  → write_todos 制定计划
  → 调用文件、MCP、Word 或执行工具
  → 工具结果落盘并返回摘要/引用
  → 检查计划与交付约束
  → 必要时压缩上下文或等待用户确认
  → 生成并验证 Word
  → 完成或带可恢复状态退出
```

模型决定下一步工具，代码负责以下不可协商约束：路径隔离、工具权限、MCP schema 校验、运行预算、确认门、文件版本、证据引用、Word 最终验收。

### 5.2 Agent factory

`AgentFactory` 只负责从 profile 组装 Agent，不包含业务逻辑。输入包括：

- model adapter 与模型参数；
- task-scoped sandbox backend；
- checkpointer/store；
- Skill catalog；
- MCP tool provider；
- Word/file tools；
- middleware stack；
- `RuntimeContext(task_id, session_id, workspace_id, user_id, locale)`。

输出是可 `invoke/stream/resume` 的编译 graph。Agent graph 由应用生命周期管理，不能在每个 HTTP 请求里重新创建 checkpointer。

### 5.3 Middleware 顺序

建议固定以下顺序，并用集成测试锁定：

1. `RunIdentityMiddleware`：绑定 task/session/run/workspace。
2. `SkillDiscoveryMiddleware`：只注入 Skill 名称与简述。
3. `SkillActivationMiddleware`：命中后加载完整 `SKILL.md`、references 索引和脚本路径。
4. `ToolPolicyMiddleware`：按 Skill、任务阶段和风险筛选工具。
5. `McpEnvelopeMiddleware`：校验输入和统一响应外壳，记录完整证据。
6. `ContextOffloadMiddleware`：大型工具结果写文件，只把摘要与 artifact/evidence 引用放回消息。
7. `SummarizationMiddleware`：在阈值前压缩旧对话，保持最近工具调用原子对。
8. `BudgetMiddleware`：model/tool call 数、token、时间、Shell 输出和文件大小限制。
9. `ApprovalMiddleware`：外部网络、依赖安装、覆盖正式产物等动作暂停确认。
10. `AuditMiddleware`：记录模型、工具、压缩、审批、异常和产物事件。

旧 `AtomicSafeContextManager` 不直接迁移。先使用框架标准 summarization/context editing，再把“AI tool call 与 ToolMessage 不可拆分”写成回归测试；只有测试证明存在缺口时，才移植最小原子保护逻辑。

### 5.4 计划不是业务状态

`write_todos` 用于模型的动态工作计划；`ReportWorkflowState` 用于系统可恢复状态。两者不可混用。

```text
ReportWorkflowState:
  INGESTED
  MATERIALS_READY
  METADATA_PENDING_CONFIRMATION
  DATA_READY
  DRAFT_READY
  DOCX_RENDERED
  VALIDATED
  COMPLETED / FAILED / CANCELLED
```

用户确认由 LangGraph interrupt/checkpoint 或等价持久机制实现，不能依赖模型在自然语言里“记住下次继续”。

## 6. Task Sandbox 与本地工作空间

### 6.1 每任务目录

Agent 看到统一虚拟根 `/workspace`，宿主实际路径不暴露给模型：

```text
/workspace/
├─ input/             # 只读：原始材料、用户附件
├─ working/           # 可写：提取文本、分析、草稿、脚本输出
├─ references/        # 只读：Skill 写作规范和参考资料
├─ evidence/          # append-only：MCP/材料证据
├─ output/            # 可写：候选 DOCX/PDF/预览
├─ staging/           # 待发布产物和 manifest
├─ .trash/            # 软删除；任务结束后按策略清理
├─ logs/              # Agent 可读的受控运行日志
└─ manifest.json      # 文件哈希、版本、来源、状态
```

文件工具最小集合：`ls`、`glob`、`grep`、`read_file`、`write_file`、`edit_file`、`mkdir`、`move`、`stage_file`、`delete_to_trash`、`restore_file`、`diff_file`。不提供绕过 workspace root 的绝对路径访问。

`input`、`references`、`evidence` 默认禁止覆盖；`output` 可以生成多个候选版本；只有通过验证的文件才能 `stage_file` 到 `staging`。对用户可见的删除默认进入 `.trash`，不直接永久删除。

### 6.2 Shell/Python 执行

统一暴露一个 `execute` 工具，而不是分别实现任意 Python eval 和宿主 Shell。执行策略：

- cwd 固定在 `/workspace/working` 或明确的 workspace 子目录；
- 命令通过 argv/受控 shell adapter 执行，记录 exit code、stdout/stderr、耗时和变更文件；
- CPU、内存、进程数、运行时间、输出大小和磁盘额度均有限制；
- 超大输出自动写入 `logs/commands/{command_id}.log`，上下文只返回摘要和路径；
- 默认禁止读取宿主环境变量、Docker socket、SSH key、云凭证和其他任务目录；
- 默认禁止公网，仅允许 Data MCP/对象存储等明确网络目的地；
- `pip install` 不作为常规运行方式，确需动态安装时进入审批和临时层，且不修改基础镜像。

### 6.3 Runtime 基础镜像

建立版本化 `report-agent-runtime` OCI 镜像，以 lockfile 可重复构建。建议预装：

- 文档：`python-docx`、`lxml`、`docx2python`、`mammoth`；
- PDF/渲染：`PyMuPDF`、`pypdf`、`pdfplumber`、LibreOffice headless、Poppler；
- 表格：`openpyxl`、`pandas`；
- 图片：`Pillow`；
- 数据与校验：`pydantic`、`jsonschema`、`PyYAML`；
- 通用：`httpx`、`tenacity`、`beautifulsoup4`；
- 质量检查脚本及项目自有 Word CLI。

为保持轻量并保证三个环境一致，首期不引入 Kubernetes Job、独立 sandbox SaaS 或“一任务一完整容器”的调度系统。统一采用一个版本化 Report Agent runtime 容器，在容器内为每个 run 启动轻量的 rootless `bubblewrap`/Linux namespace 隔离进程：只绑定该任务 workspace 和必要只读 runtime 文件，限制进程、网络和资源，执行结束即销毁 namespace。test、UAT、prod 使用同一镜像和同一 SandboxBackend，仅通过 `deploy/environments/<env>/report-agent.yaml` 调整额度和服务地址。Windows 本地开发也通过 Docker Compose 进入同一 Linux runtime，不另做行为不同的宿主机 Shell 实现。

## 7. MCP Tool Runtime

### 7.1 接入原则

Report Agent 只通过 MCP transport 获取 Data MCP 工具，不导入 `data_mcp` 业务源码。初期同时支持：

- 本地集成测试：stdio；
- 部署环境：Streamable HTTP。

`McpRegistry` 在启动时执行 `initialize + list_tools`，以 `contracts/mcp/*.json` 校验服务公布的 schema。Data MCP 标记为 required 时，schema 或连接失败应使 readiness 失败，而不是让 Agent 静默使用空工具。

### 7.2 工具暴露策略

Agent 直接看到正式业务工具名：

- `extract_project_profile`
- `query_track_labels`
- `query_comparable_valuation`
- `match_listed_peers`
- `match_investors`

不保留旧 `mcp_invoke(capability=...)` 和 `mcp_mapping.py`。每个调用必须记录：tool、原始 arguments、schema version、status、summary、完整 data、sources、warnings、耗时和 request id。大结果落到 `/workspace/evidence/mcp/`，模型只接收摘要、关键字段和 `evidence_id`。

### 7.3 MCP 与 Shell 的权限边界

Data MCP 是可信业务数据通道，Shell 不是其替代品。即使 sandbox 允许网络，Skill 也不得通过 `curl` 绕过 MCP 直接访问底层数据源。Tool policy 对 Data MCP 使用显式 allowlist；调用失败时按统一外壳降级，不允许模型伪造缺省值。

## 8. Skill 与插件模型

### 8.1 Skill 目录标准

```text
skills/
└─ investment-report/
   ├─ SKILL.md
   ├─ agents/
   │  └─ openai.yaml          # 可选展示/依赖元数据
   ├─ references/
   │  ├─ report-rules.md
   │  ├─ data-field-map.md
   │  └─ document-spec.md
   ├─ scripts/
   │  ├─ inspect_docx.py
   │  ├─ render_docx.py
   │  └─ validate_docx.py
   └─ tests/
      └─ cases.yaml
```

Skill 使用渐进披露：启动只加载 `name/description`；选择后完整读取 `SKILL.md`；references 按需读取；scripts 复制到 sandbox 后执行。Word 的内容范围、章节、表格、版式和写作要求由 Skill 及 references 描述，不依赖预置占位符 DOCX。所有 Skill 文件计算内容哈希并形成 `skill_version`，运行中固定版本，避免热更新导致同一任务前后行为不一致。

### 8.2 Skill 负责什么

Skill 负责：何时触发、写作目标、推荐步骤、Data MCP 调用顺序、章节与版式规范、数据缺失表达、交付验收规则。

Skill 不负责：实现 MCP transport、修改 sys.path、伪造数据、直接写宿主路径、绕过工具授权、保存会话状态。

### 8.3 Tool policy

`allowed-tools` 必须成为运行时强约束。Investment Report Skill 首期只允许：

- workspace 受控文件工具；
- `execute`（受 sandbox policy 限制）；
- 五个 Data MCP 工具；
- 材料解析工具；
- Word 创建、编辑、批注、渲染、验证工具；
- 计划和用户确认工具。

不在列表内的工具不出现在模型工具 schema 中，且即使构造调用也会被 middleware 拒绝。

### 8.4 插件边界

首期不实现复杂的动态插件市场。内部“插件包”仅定义为可版本化能力组合：

```text
PluginManifest = Skill bundle + tool provider + optional MCP config + runtime deps
```

Data MCP adapter、Word toolkit、document-reading toolkit 分别注册为 provider；Investment Report Skill 声明依赖这些 provider。这样保留类似 DeepSeek Harness 的可插拔性，同时不引入第二套通用插件框架。

### 8.5 Codex Documents Skill 的参考与复用边界

Codex 当前 Documents Skill 已形成成熟的 Word 能力矩阵，包括 DOCX 渲染、OOXML patch、批注与修订、内容控件、样式和结构审计、隐私清理、文档合并、渲染差异和逐页视觉检查。其“创建/编辑 → 渲染为逐页 PNG → 检查全部页面 → 修正 → 重新渲染”的闭环，应直接作为本项目 Word Toolkit 的功能和验收基线。

但是，当前 Codex 安装包内的 `LICENSE.txt` 明确限制把其中代码、提示词、资产和其他材料复制或保留到 OpenAI 服务之外，也限制复制和衍生分发。因此不能把 `.codex/plugins/cache` 下的 Documents Skill 或 scripts 直接拷入本仓库，也不能采用逐行改名或近似翻写的方式规避这一限制。

本项目采用以下复用策略：

1. 参考其功能目标、公开工作流、工具划分和验收思想，不复制受限实现代码或长篇提示词。
2. 根据本项目 Word contract 和测试用例重新设计实现，使用 `python-docx`、`lxml`、LibreOffice、Poppler、Pillow 等公开依赖，在本仓库独立编写脚本。
3. Codex 辅助开发期间可以在授权环境内调用已安装的 Skill 做临时处理或对照验证，但生产 Report Agent 不依赖开发者机器上的 Codex cache 路径。
4. 每个项目内脚本记录依赖、许可证、版本和测试范围。如果后续获得可再分发的开源版本或单独授权，再通过 adapter 替换实现，不改变上层 Word tool contract。
5. Skill `scripts/` 只保留薄 CLI：负责参数解析、调用 `report_agent.infrastructure.word` 的公开能力并输出 JSON。核心实现只保留一份，避免 library、Agent tool 和 Skill script 各自维护一套 Word 逻辑。

建议独立实现顺序：

| 优先级 | 能力 | 目标模块 |
|---|---|---|
| P0 | DOCX 转 PDF/逐页 PNG、隔离 LibreOffice profile、错误日志 | `infrastructure/word/rendering.py` |
| P0 | ZIP、rels、content-types、批注锚点、超链接结构校验 | `infrastructure/word/validation.py` |
| P0 | 创建完整 DOCX、章节/表格/图片/样式写入 | `infrastructure/word/authoring.py` |
| P0 | 添加/提取来源批注并绑定 `evidence_id` | `infrastructure/word/comments.py` |
| P1 | heading、section、table、image、style 审计 | `infrastructure/word/audits.py` |
| P1 | 两版 DOCX 的逐页渲染差异 | `infrastructure/word/visual_diff.py` |
| P1 | 作者信息、自定义属性和 rsid 清理 | `infrastructure/word/privacy.py` |
| P2 | 修订、交叉引用、目录、题注、文档合并和保护 | 按报告实际需要逐项增加 |

## 9. 上下文与记忆管理

### 9.1 四类上下文

| 类型        | 内容                 | 保存位置                       |
| --------- | ------------------ | -------------------------- |
| 静态指令      | Harness 规则、工具说明    | system prompt / middleware |
| Skill 上下文 | 当前写作规则与引用索引        | Skill runtime，按需注入         |
| 会话上下文     | 用户消息、近期工具调用、摘要     | LangGraph checkpointer     |
| 任务事实      | 材料、MCP 响应、证据、草稿、文件 | workspace + evidence store |

模型上下文只保存“当前决策需要的信息”，完整事实留在文件和结构化存储中。

### 9.2 压缩策略

采用多层防线：

1. 工具输出预算：每个 tool 定义 inline 最大字符/token；超限自动落盘。
2. 分块读取：材料、日志、MCP 数据和 DOCX 解析结果支持 offset/page/query。
3. 原子保留：最近 AI tool call 与对应 ToolMessage 永远成组保留。
4. 阈值摘要：达到模型上下文约 65% 时预压缩，不能等到 API 报错后处理。
5. 结构化摘要：保存目标、已确认事实、未决问题、计划状态、artifact/evidence 引用和失败记录，不只生成自然语言概述。
6. 压缩可审计：记录压缩前后 token、被替换消息范围、摘要版本和模型。
7. 最终兜底：达到硬预算时暂停并返回可恢复状态，而不是无限递归或静默丢消息。

### 9.3 短期与长期记忆

短期会话使用数据库支持的 checkpointer；任务事实使用 workspace/evidence；跨任务长期记忆首期只保存经过审核的用户偏好和文档风格选择，不让模型自动积累未经确认的业务事实。

## 10. Word 文档生产架构

### 10.1 工具分组

```text
document_reading
  inspect_input, extract_text, extract_tables, OCR, material_search

word_authoring
  create_document, set_page_layout, upsert_section,
  insert_table, insert_image, apply_style

word_review
  add_comment, link_evidence, inspect_structure, compare_docx

word_delivery
  validate_docx, render_docx, inspect_pages, stage_artifact
```

Agent 可以通过脚本组合这些原子能力，但所有 DOCX 修改应调用项目提供的确定性 library/CLI，不鼓励模型临时编写 OOXML 修改代码。

### 10.2 双层产物模型

报告生成不直接从聊天文本写 DOCX，而使用两层结构：

1. `ReportDraft`：章节、段落、表格、图片、脚注、`evidence_id`、缺失项和写作状态。
2. `DocumentArtifact`：Skill 版本、样式方案、DOCX 路径、渲染预览、验证结果和哈希。

模型主要编辑 `ReportDraft`；authoring service 根据 Skill 的内容和版式规范从零创建完整 DOCX；validator 检查生成结果。这能避免段落索引漂移、模型直接操作 XML 和将写作能力锁死在占位符模板中。

### 10.3 必须通过的交付门

- Data MCP response status 与 warnings 已处理；
- 每个关键数字和机构名称存在 `evidence_id`；
- 禁止把 `query_comparable_valuation.data.content` 表述为已核验事实；
- 标题、章节、段落和表格结构符合 Skill 与 Report contract；
- OOXML ZIP、relationships、comments、超链接和媒体引用有效；
- LibreOffice headless 可打开并导出 PDF；
- 页面渲染无明显截断、重叠、空白页和表格越界；
- 最终 DOCX、PDF/预览和 manifest 一起进入 staging。

## 11. 持久化、事件与 API

### 11.1 标准存储方案

- MySQL：task/session/run/checkpoint metadata、workflow state、events、evidence index；
- MinIO：原始附件、完整 MCP 响应、大日志、DOCX/PDF/图片；
- task sandbox：执行期工作副本，结束后按 TTL 清理；
- Redis/队列：可恢复的异步 run 调度、取消和并发控制。

test、UAT、prod 均使用 MySQL + Redis + MinIO 这一套标准中间件拓扑，不实现 SQLite/local storage 作为另一套主运行路径。三个环境只允许连接地址、凭证、容量、并发和保留周期不同，具体值统一维护在 `deploy/environments/<env>`。单元测试可以使用 in-memory fake；会执行建表或写入的集成测试必须使用专用 test schema，不能直接操作共享业务库。

LangGraph 官方目前直接维护 PostgreSQL/SQLite checkpointer，项目现有基础设施则是 MySQL。因此本项目通过自有 persistence adapter 接入 `langgraph-checkpoint-mysql`，并将其锁定在 `uv.lock`。该第三方实现要求 MySQL 8.0.19+ 或 MariaDB 10.7.1+；升级 LangGraph 或 checkpointer 时必须运行官方 checkpointer conformance tests 和本项目恢复测试。若后续兼容性无法满足，再在 ADR 中评估自研 saver 或新增 PostgreSQL，而不是现在预设一套并不存在的数据库。

### 11.2 事件模型

API 通过 SSE 或 WebSocket 输出 typed events：

```text
run.started
plan.updated
skill.activated
tool.started / tool.completed / tool.failed
workspace.changed
context.compacted
approval.required / approval.resolved
artifact.created / artifact.validated
run.paused / run.completed / run.failed
```

日志必须能重建“模型当时看到了什么、调用了什么、文件发生了什么变化”，但敏感值和凭证不进入事件正文。

### 11.3 API 最小集合

- `POST /tasks`：创建任务并上传/绑定材料；
- `POST /tasks/{task_id}/sessions`：创建会话；
- `POST /sessions/{session_id}/runs`：提交用户目标；
- `GET /runs/{run_id}/events`：流式事件；
- `POST /runs/{run_id}/resume`：确认或补充后恢复；
- `POST /runs/{run_id}/cancel`：取消；
- `GET /tasks/{task_id}/files`：工作空间文件与版本；
- `GET /artifacts/{artifact_id}`：下载交付物；
- `GET /tasks/{task_id}/evidence`：查看来源与告警。

## 12. 目标代码目录

```text
bjs-investment-report-agent/
├─ pyproject.toml                         # uv workspace
├─ uv.lock
├─ apps/
│  ├─ data_mcp/                           # 已标准化，保持独立
│  └─ report_agent/
│     ├─ pyproject.toml
│     ├─ Dockerfile.runtime
│     ├─ src/report_agent/
│     │  ├─ entrypoints/
│     │  │  ├─ api.py
│     │  │  ├─ worker.py
│     │  │  └─ cli.py
│     │  ├─ application/
│     │  │  ├─ services/
│     │  │  ├─ workflows/
│     │  │  └─ ports/
│     │  ├─ domain/
│     │  │  ├─ tasks.py
│     │  │  ├─ reports.py
│     │  │  ├─ evidence.py
│     │  │  └─ events.py
│     │  ├─ settings/
│     │  │  ├─ loader.py
│     │  │  ├─ models.py
│     │  │  └─ validation.py
│     │  ├─ harness/
│     │  │  ├─ factory.py
│     │  │  ├─ context.py
│     │  │  ├─ state.py
│     │  │  ├─ profiles.py
│     │  │  └─ middleware/
│     │  ├─ runtime/
│     │  │  ├─ sandbox.py
│     │  │  ├─ workspace.py
│     │  │  ├─ execution.py
│     │  │  └─ policies.py
│     │  ├─ skills/
│     │  │  ├─ catalog.py
│     │  │  ├─ loader.py
│     │  │  ├─ policy.py
│     │  │  └─ versions.py
│     │  ├─ tools/
│     │  │  ├─ filesystem.py
│     │  │  ├─ materials.py
│     │  │  ├─ word.py
│     │  │  └─ planning.py
│     │  └─ infrastructure/
│     │     ├─ mcp/
│     │     ├─ persistence/
│     │     ├─ object_store/
│     │     ├─ parsers/
│     │     └─ word/
│     ├─ skills/
│     │  └─ investment-report/
│     └─ tests/
│        ├─ unit/
│        ├─ contract/
│        ├─ integration/
│        ├─ security/
│        └─ golden/
├─ contracts/
│  ├─ mcp/
│  ├─ agent/
│  ├─ tools/
│  └─ reports/
├─ deploy/
└─ docs/architecture/
```

与此前骨架相比，`skill_runtime` 和 `tool_runtime` 不再作为空顶层概念目录，而分别收敛成 `skills/`、`tools/` 和 `runtime/`；`delivery` 被拆入 application workflow 与 infrastructure/word，避免按含糊阶段名分层。

## 13. 分层职责与修改导航

架构分层不仅要目录整齐，还要让维护者能够根据变更类型直接定位。每层只允许依赖同层或更内层的公开接口，禁止反向导入和跨层读取私有字段。

### 13.1 依赖规则

```text
entrypoints
    ↓
application ─────────────→ harness/runtime/tools/skills ports
    ↓                              ↓
domain                       infrastructure adapters

contracts  ← 所有边界共同依赖，但不依赖任何应用实现
deploy     ← 只被 bootstrap/settings 加载，不被业务模块直接解析
```

- `domain` 不依赖 FastAPI、LangChain、MCP SDK、数据库、对象存储或 Word 库。
- `application` 编排用例和工作流，只依赖 domain 与 ports。
- `harness` 管理模型循环和 middleware，不实现材料解析、MCP 业务映射或 DOCX 排版。
- `runtime` 管理 sandbox、workspace 和命令执行，不理解投资报告业务。
- `tools` 是给模型的稳定能力门面，调用 application ports，不直接拼数据库或宿主路径。
- `infrastructure` 实现 ports，可依赖第三方 SDK，但不能反向让 domain 引用 adapter 类型。
- `entrypoints` 只做协议转换、认证和依赖装配，不在路由中创建 Agent、拼 system prompt 或操作 workspace。
- `skills/` 是业务规则资产，不属于 Python package 源码；`contracts/` 是跨模块唯一公共事实源。

建议通过 Ruff import rules 或 `import-linter` 在 CI 中强制上述方向，避免分层只停留在文档。

### 13.2 “改什么，去哪里”

| 变更类型                   | 唯一主要位置                                                   | 不应修改的位置                      |
| ---------------------- | -------------------------------------------------------- | ---------------------------- |
| 新增/调整 HTTP API         | `entrypoints/api.py` 与 API schema                        | Agent factory、Word renderer  |
| 调整任务阶段和确认节点            | `application/workflows`                                  | Skill 中伪造持久状态、API 路由         |
| 新增领域字段或状态              | `domain` + `contracts/agent`                             | 数据库 adapter 私有 dict          |
| 更换模型供应商                | `infrastructure/models` + 环境配置                           | Skill、业务 workflow            |
| 调整模型名、温度、超时            | `deploy/environments/<env>/report-agent.yaml`            | Python 常量、README 示例          |
| 调整 Agent middleware    | `harness/middleware` + harness profile 配置                | API、Gradio/UI                |
| 调整上下文阈值/预算             | `report-agent.yaml.context`                              | middleware 内硬编码数字            |
| 新增文件/Shell 能力          | `runtime` + `tools/filesystem.py` + tool contract        | Skill 内临时实现宿主命令              |
| 调整 sandbox 资源和网络策略     | `report-agent.yaml.sandbox` + deploy runtime             | Agent prompt                 |
| 新增 Data MCP 工具         | `contracts/mcp`、Data MCP server、Agent MCP registry       | `mcp_mapping.py`、Skill 自定义转译 |
| 调整 MCP 地址、transport、超时 | `report-agent.yaml.mcp`                                  | Agent tool 函数                |
| 修改写作流程或章节要求            | `skills/investment-report/SKILL.md`                      | Harness 或 API                |
| 增加写作参考材料               | Skill `references/`                                      | system prompt 常量             |
| 修改 Word 内容、章节或版式规范      | Skill `SKILL.md` / `references/` + Report contract       | authoring service 中硬编码业务要求     |
| 新增确定性 Word 操作          | `infrastructure/word` + `tools/word.py`                  | Skill 内临时 OOXML 脚本           |
| 参考 Codex Word 能力         | `infrastructure/word` 独立实现 + 自有 fixtures/tests         | 复制或近似翻写 Codex cache 内受限脚本    |
| 调整 Word 验收阈值           | `report-agent.yaml.word.validation`                      | validator 分支里的魔法值            |
| 更换数据库/对象存储/队列          | 对应 infrastructure adapter + deploy 配置                    | domain/application           |
| 新增日志、指标、追踪出口           | `infrastructure/observability` + deploy 配置               | 业务函数散落 print                 |
| 新增 Skill               | `apps/report_agent/skills/<name>` + Skill contract tests | `src/report_agent` 下建业务提示词目录 |

### 13.3 模块公开面

每个一级模块只通过 `__init__.py` 或明确的 `ports.py` 暴露稳定对象；禁止业务代码访问 `_graph`、`_ws`、`_parsed_dir` 等私有字段。应用装配集中在 `entrypoints/bootstrap.py`，所有 adapter 通过构造函数注入。测试替换 adapter 时使用 port fake，不 monkey-patch 跨层私有实现。

## 14. 环境配置架构

### 14.1 单环境事实源

Agent 沿用当前 Data MCP 已落地的配置模式。每个部署环境都是完整、自洽的配置包：

```text
deploy/environments/
├─ README.md
├─ test/
│  ├─ runtime.env
│  ├─ data-mcp.yaml
│  └─ report-agent.yaml
├─ uat/
│  ├─ runtime.env
│  ├─ data-mcp.yaml
│  └─ report-agent.yaml
└─ prod/
   ├─ runtime.env
   ├─ data-mcp.yaml
   └─ report-agent.yaml
```

职责约定：

- `runtime.env` 只放进程启动所需的最小变量和配置文件选择器，例如 `REPORT_AGENT_CONFIG=deploy/environments/test/report-agent.yaml`；不再分散保存业务配置或密钥。
- `report-agent.yaml` 保存该环境完整的 Agent 配置，包括运行参数、功能开关、资源预算、服务地址、模型密钥、中间件账号密码和产物策略。
- `data-mcp.yaml` 继续只由 Data MCP 加载；Report Agent 不读取其内部配置，只使用 MCP 地址和契约。
- 初期允许密钥、token、数据库密码直接维护在对应环境 YAML 中，以减少环境变量、Secret 挂载和密钥服务带来的部署复杂度。
- `deploy/environments/<env>` 因此属于敏感配置目录：只允许进入访问受控的私有仓库和部署链路，不得复制到公开仓库、日志、报告、workspace、测试快照或构建产物。
- 应用目录只保留 `config.example.yaml` 或 schema 文档，不保存环境真实值；真实值只出现在 `deploy/environments/<env>` 的对应配置文件。

同一个配置项只能有一个事实源。禁止出现 YAML、环境变量默认值和 Python 常量三处都能改变同一行为的情况。

该方案接受“密钥进入 Git 历史后难以彻底删除”的风险，以换取初期轻量管理。仓库一旦扩大访问范围、接入外部协作或转为公开，必须先轮换全部密钥，并迁移到容器 Secret 或专用密钥管理服务；迁移时保持 Settings 字段不变，只替换配置值解析 adapter。

### 14.2 `report-agent.yaml` 建议结构

```yaml
schema_version: "1.0"
current_env: test

service:
  host: 127.0.0.1
  port: 8000
  public_base_url: http://127.0.0.1:8000
  worker_concurrency: 2

model:
  provider: openai_compatible
  model: qwen-example
  base_url: https://model-gateway.example.com/v1
  api_key: replace-with-environment-key
  temperature: 0.1
  request_timeout_seconds: 180
  max_retries: 2

harness:
  profile: document_writer
  planning_enabled: true
  subagents_enabled: false
  max_model_calls: 40
  max_tool_calls: 120
  max_run_seconds: 1800

context:
  model_context_tokens: {env: LLM_MAX_CONTEXT_TOKENS}
  compact_at_ratio: 0.65
  hard_stop_ratio: 0.90
  inline_tool_result_tokens: 4000
  preserve_recent_messages: 12
  offload_directory: /workspace/logs/tool-results

workspace:
  root: /data/report-agent/workspaces
  max_bytes_per_task: 2147483648
  task_ttl_hours: 72
  delete_mode: trash
  staging_required: true

sandbox:
  backend: bubblewrap
  image: bjs-report-agent-runtime:0.1.0
  cpu_limit: "2"
  memory_limit: 4Gi
  pids_limit: 128
  command_timeout_seconds: 300
  # Model-controlled shell has no direct egress. Data MCP/MinIO are called by
  # service-owned adapters outside the Bubblewrap namespace.
  network_mode: isolated
  allow_dynamic_package_install: false

mcp:
  data_mcp:
    required: true
    transport: streamable_http
    url: http://data-mcp:8001/mcp
    startup_timeout_seconds: 20
    tool_timeout_seconds: 120
    enabled_tools:
      - extract_project_profile
      - query_track_labels
      - query_comparable_valuation
      - match_listed_peers
      - match_investors
    output_token_limit: 6000

skills:
  roots:
    - apps/report_agent/skills
  default: investment-report
  hot_reload: false
  require_version_lock: true

word:
  authoring_mode: from_scratch
  document_spec: apps/report_agent/skills/investment-report/references/document-spec.md
  render_backend: libreoffice
  output_formats: [docx, pdf, png]
  validation:
    require_comments_relationship: true
    require_evidence_for_numbers: true
    require_skill_structure: true
    reject_table_overflow: true
    max_blank_pages: 0

persistence:
  mysql:
    host: {env: MYSQL_HOST}
    port: {env: MYSQL_PORT}
    database: {env: MYSQL_DATABASE}
    user: {env: MYSQL_USER}
    password: {env: MYSQL_PASSWORD}
    charset: {env: MYSQL_CHARSET}
  redis:
    host: {env: REDIS_HOST}
    port: {env: REDIS_PORT}
    database: {env: REDIS_DB}
    password: {env: REDIS_PASSWORD}
  minio:
    endpoint: {env: MINIO_ENDPOINT}
    access_key: {env: MINIO_ACCESS_KEY}
    secret_key: {env: MINIO_SECRET_KEY}
    bucket: {env: MINIO_BUCKET}
    secure: {env: MINIO_SECURE}

observability:
  log_level: INFO
  emit_model_payloads: false
  emit_tool_payloads: false
  metrics_enabled: true
  tracing_enabled: true
```

示例只定义配置结构，不代表已经确认 UAT/生产参数。实施时应在 test、UAT、prod 中保持同一字段结构和 MySQL + Redis + MinIO 中间件类型，只根据各环境实际资源填写地址、凭证、额度和保留周期，不能把 test 值或密钥直接复制到其他环境。

### 14.3 配置与代码的边界

应配置化的关键数据：

- 模型名称、endpoint、超时、重试和推理参数；
- 模型 API key、数据库密码、Redis 密码、对象存储 access key/secret key 等环境密钥；
- Harness profile、调用预算、确认策略和功能开关；
- 上下文窗口、压缩阈值、工具输出预算和保留消息数；
- workspace 配额、TTL、staging 和删除策略；
- sandbox 镜像、CPU/内存/进程/时间限制、网络 allowlist；
- MCP transport、地址、required、工具 allowlist、超时和输出上限；
- Skill roots、默认 Skill、热更新和版本锁；
- Word 创建模式、文档规范路径、渲染后端、输出格式和验收阈值；
- 数据库、checkpoint、对象存储、队列和可观测性 adapter 选择。

不应配置化的内容：

- 领域状态转换的合法性；
- MCP 统一响应外壳语义；
- 路径逃逸、证据必填、工具权限等安全不变量；
- Word OOXML 有效性规则；
- 接口数据类型和核心业务契约。

这些必须通过代码和 contract 固定，避免配置把系统改到不安全或语义不一致的状态。

### 14.4 配置加载与校验

配置只允许在 `entrypoints/bootstrap.py` 启动时加载一次：

```text
runtime.env
  → REPORT_AGENT_CONFIG
  → YAML loader
  → Pydantic Settings/Config models
  → 跨字段校验
  → immutable Settings snapshot
  → dependency injection
```

禁止业务模块直接调用 `os.getenv()` 或自行读取 YAML。所有配置模型放在 `src/report_agent/settings/`，按 `ServiceSettings`、`ModelSettings`、`HarnessSettings`、`ContextSettings`、`SandboxSettings`、`McpSettings`、`WordSettings` 等拆分。

启动校验至少包括：

- `schema_version` 受支持；
- 必需密钥存在、不是示例占位值且不输出其值；
- context 阈值满足 `0 < compact < hard_stop < 1`；
- production 不允许 local shell/full access sandbox；
- required MCP 可连接且工具 schema 匹配；
- Skill、文档规范、contracts 路径存在；
- workspace 可写、输入/证据目录权限策略可建立；
- renderer 和 runtime 镜像版本可用；
- 配置中的工具名均存在且没有越权。

加载完成后计算脱敏的 `config_fingerprint`，写入 run manifest、日志和报告 provenance。每个 run 固定一份配置快照；配置文件变化只影响新 run，不能在执行中途改变行为。

### 14.5 配置测试和维护规则

- 为 `test/uat/prod/report-agent.yaml` 运行统一 schema 校验和路径检查。
- 单元测试使用 `apps/report_agent/tests/fixtures/config/*.yaml`，不直接修改 deploy 配置。
- 增加配置差异检查，只显示字段路径、是否填写和非敏感值差异；password、token、api key、access key 等字段永远只显示 `***`，不得进入 CI 输出。
- `deploy/environments/README.md` 维护字段归属、启动命令、密钥维护/保护/轮换方式和变更流程。
- 配置对象的 `repr`、异常信息、健康检查和 debug endpoint 必须使用统一脱敏器；禁止直接打印原始 Settings/YAML。
- 提交前运行 secret inventory，只报告“哪些敏感字段已配置”，不把实际值发送到第三方扫描服务。
- 新增配置字段时必须同时修改 Settings model、示例配置、三个环境配置或显式占位、README 和配置测试。
- 删除配置字段时 CI 应拒绝 YAML 中遗留的未知字段，防止拼写错误被静默忽略。

## 15. 旧分支代码复用策略

采用“选择性拷贝进入临时迁移区，再按目标接口提炼”，不直接 merge 整棵目录。

| 旧模块                        | 策略                               | 说明                                                  |
| -------------------------- | -------------------------------- | --------------------------------------------------- |
| PDF/Word/XLSX parsers      | 优先复用并迁入 `infrastructure/parsers` | 补注册、自检、超时和 fixture 测试                               |
| Report schemas             | 提炼复用                             | 升级为 `ReportDraft`，增加 evidence 引用                    |
| DOCX renderer/comments     | 部分复用                             | 改为从零创建完整 Word、使用稳定证据锚点并补 OOXML QA                    |
| Workspace storage          | 重写接口、复用局部实现                      | 加路径校验、manifest、版本、trash/staging                     |
| FileDownloader             | 部分复用                             | 补重定向、DNS、allowlist 和连接地址校验                          |
| SkillRegistry              | 参考重写                             | 支持标准目录、渐进披露、版本和运行时工具授权                              |
| AgentTools                 | 不整体复用                            | 840 行大模块按 tool provider 拆分                          |
| `mcp_mapping.py`           | 删除                               | 直接使用主分支 MCP contracts                               |
| 旧 Agent/MemorySaver        | 不复用                              | 由 Deep Agents/LangGraph factory 与持久 checkpointer 替代 |
| Atomic context scripts     | 暂不迁移                             | 先标准 middleware，按测试补最小逻辑                             |
| Gradio orchestration/cache | 不复用                              | UI 后续只消费公开 API 和事件流                                 |
| `LDZ_TEMP` tests           | 只提取有效场景                          | 测试代码按新公开接口重写                                        |

临时参考代码若需要进入主分支，应放在不参与 package build 的 `_migration_reference/`，完成对应模块迁移后删除；更推荐通过 `git show origin/feature/report-agent:<path>` 查看，避免污染主分支。

## 16. 分阶段迁移计划

### Phase 0：Deep Agents 架构 Spike 与实现边界固化

目标：用最小代码验证 Deep Agents 是否满足核心 Harness 需求。

- 建立独立 sandbox，完成 `write_todos → 文件修改 → execute Python → 自动压缩 → resume`。
- 验证自定义模型 adapter 与当前模型服务兼容。
- 验证 Skill 渐进加载和 `allowed-tools` 真正限制工具。
- 验证 MCP stdio/HTTP 工具发现和统一外壳落盘。
- 验证关闭 subagent 后的最小 Harness profile。

退出条件：形成 ADR，锁定 Deep Agents/LangGraph 版本、扩展点和 adapter 边界；上述链路均有自动化测试。Spike 用于确认正确的接入方式和暴露框架缺口，不用于重新选择 Harness。发现缺口时通过 adapter、自有 middleware 或上游版本约束解决，不保留旧 Agent 内核或另一套回退运行路径。

### Phase 1：工程骨架与运行内核

- 创建 Report Agent package，加入 uv workspace。
- 建立 domain、ports、settings、API factory、worker entrypoint。
- 在 `deploy/environments/{test,uat,prod}` 建立同构 `report-agent.yaml`，接入 MySQL、Redis、MinIO 和 Data MCP 配置。
- 实现 task/session/run/workspace 标识与事件模型。
- 实现 checkpointer 和基础 Agent factory。
- 配置 ruff、mypy、pytest、依赖组和 CI。

退出条件：新进程可创建、执行、暂停和恢复一个只使用内置文件工具的任务；旧 Agent 代码未进入新 package import graph。

### Phase 2：Sandbox、Workspace 与上下文治理

- 实现统一 `BubblewrapSandboxBackend`，test、UAT、prod 共用。
- 构建 runtime 镜像及 namespace、资源、网络、环境变量策略。
- 实现文件 manifest、staging、trash、diff 和 artifact transfer。
- 接入 tool output offload、summarization、预算和审计 middleware。
- 增加路径逃逸、命令超时、磁盘/输出超限等安全测试。

退出条件：Agent 只能修改自己的 workspace；大文件/大输出不进入完整对话；重启后可恢复计划和文件状态。

### Phase 3：Data MCP 与证据链

- 实现 MCP registry/gateway、required readiness 和 tool allowlist。
- 直接接入五个标准工具，删除二次 capability 映射。
- 校验输入/响应 schema，完整结果写 evidence store。
- 实现 `evidence_id`、warnings/status 降级和结果分块读取。
- 建立 mock MCP contract/e2e 测试。

退出条件：五工具 success/partial/empty/failed 全覆盖；Agent 不导入 Data MCP 源码；报告草稿中的数据可定位到 evidence。

### Phase 4：文档 Skill 与 Word Toolkit

- 迁移并重写 Investment Report Skill，修正 Data MCP 调用顺序和字段。
- 提炼材料解析器、Word renderer、comments 等可复用旧代码。
- 按 Codex Documents Skill 的能力矩阵独立实现 P0/P1 Word scripts，不复制或近似翻写受限源码。
- 建立 `ReportDraft`、document contract 和 Word tool provider。
- 实现 create/edit/comment/render/validate/stage 全链路。
- 建立真实匿名材料、Skill 文档规范和期望输出的 golden fixtures。

退出条件：Agent 可自主从材料和 mock MCP 数据按 Skill 要求从零生成完整 DOCX；结构、来源、渲染和视觉验收均通过。

### Phase 5：API、队列与端到端收口

- 完成 task/session/run/artifact/evidence API 和 SSE events。
- worker 化长任务，支持取消、重试、幂等和并发限制。
- 增加用户确认 interrupt 与 resume。
- 如需要演示 UI，只通过公开 API 接入。
- 完成真实 Data MCP 测试环境联调。

退出条件：上传材料到下载报告的端到端流程可恢复、可审计；API 与 UI 不存在两套 Agent 状态。

### Phase 6：清理与主分支切换

- 对照迁移清单删除临时参考代码和空目录。
- 更新 README、部署配置、CODEOWNERS 和运维手册。
- 执行依赖、单测、契约、集成、安全、golden Word 全套检查。
- 形成旧 Agent/旧 API 删除清单、新 API 使用说明和发布回滚点；不建设旧 API 兼容层。

退出条件：主分支只保留新 package；旧分支不再是运行依赖；构建产物与远端提交可复现。

## 17. 测试与验收矩阵

| 层级          | 必测内容                                                                                  |
| ----------- | ------------------------------------------------------------------------------------- |
| Unit        | path policy、Skill parser、tool filtering、context budget、report schema、evidence mapping |
| Contract    | 五个 MCP JSON Schema、Tool schema、ReportDraft、event schema                               |
| Integration | checkpointer resume、sandbox transfer、Skill scripts、DOCX renderer、object storage       |
| Security    | `../`/绝对路径逃逸、符号链接、命令超时、secret env、网络绕过、提示注入                                           |
| E2E         | 上传 → 解析 → 确认 → MCP → 草稿 → DOCX → 批注 → 验证 → 下载                                         |
| Golden      | 标题/表格/批注/链接/Skill 版式/页数/渲染图片对比                                                         |
| Failure     | MCP partial/empty/failed、模型超时、压缩、worker 重启、磁盘满、取消与重试                                  |

总体验收标准：

1. 单任务可以在独立 sandbox 中连续执行至少两个会话轮次并在服务重启后恢复。
2. 上下文达到预警阈值时主动压缩，不能以模型 context length error 作为正常控制流。
3. 未授权工具不可见、不可调用；workspace 外路径不可读写。
4. Data MCP 所有数据保留原始统一外壳，任何降级均可追溯。
5. 任一报告关键事实可定位到材料片段或 MCP evidence。
6. Word 内容和版式由 Skill 驱动从零生成，DOCX 结构和视觉验证均通过。
7. Agent 可自行运行 Word 检查脚本并根据结果修正，直到通过预算或明确暂停。
8. 不依赖旧 Agent 的 sys.path 注入、Gradio cache、MemorySaver 单例假设或 `mcp_mapping.py`。

## 18. 风险与控制

| 风险                   | 控制方式                                              |
| -------------------- | ------------------------------------------------- |
| Deep Agents API 快速变化 | 固定版本、适配层、Phase 0 ADR、核心行为回归测试；不维护第二套 Harness          |
| Shell 带来安全面扩大        | 容器沙箱、网络默认拒绝、workspace root、资源限额、无 secrets         |
| 模型自主性导致重复/失控调用       | todo + workflow state、tool/model budget、幂等键、超时与取消 |
| Skill 规则过长挤占上下文      | 渐进披露、references 按需读、脚本承载确定性逻辑                     |
| Word 修改不稳定           | 结构化 ReportDraft、确定性 toolkit、golden + render QA    |
| MCP 大响应撑爆上下文         | 完整落 evidence store，只返回摘要、分页和引用                    |
| 快速拷贝引入旧耦合            | 按模块提炼，不整体 merge；新 package 禁止旧顶层 import            |
| 各环境 sandbox 行为不一致    | 三环境共用 runtime 镜像和 Bubblewrap backend，配置只改变额度与地址     |

## 19. 已确认架构决策

以下决策已经确认，后续实施不得再把它们作为开放选项：

1. **Harness 唯一路线**：采用 Deep Agents/LangGraph，不保留旧 Agent 内核，也不建设 `create_agent` 自组 Harness 的运行时回退方案。Phase 0 只验证集成边界并补 adapter。
2. **轻量 Sandbox**：采用单一版本化 Linux runtime 容器，run 内使用 rootless bubblewrap/Linux namespace 隔离。首期不引入 Kubernetes Job、独立 sandbox 服务或每任务完整容器调度平台。
3. **三环境标准中间件一致**：test、UAT、prod 均使用现有 MySQL、Redis、MinIO 和同一 Report Agent runtime；环境差异全部维护在 `deploy/environments/{test,uat,prod}`，不另建 SQLite/local 主路径。MySQL checkpointer 通过项目 adapter 隔离第三方实现。
4. **Skill 驱动完整 Word 创建**：Skill 告诉 Agent 应写什么、如何组织和如何验收，Agent 从零创建完整 Word；不依赖占位符模板或内容控件作为主要写作方式。
5. **直接发布新 API**：使用新的 task/session/run/artifact/evidence API，不保留旧 Agent API、Gradio cache 或旧数据结构兼容层。
6. **Codex Word 资产参考方式**：参考 Documents Skill 的能力、流程和验收标准，在本项目中独立实现 scripts；不直接复制、近似翻写或运行时依赖 Codex cache 内受限材料。

下一步按 Phase 0 和 Phase 1 开始实施，同时建立三环境 `report-agent.yaml` 配置骨架。Phase 0 验证 Harness、bubblewrap sandbox、checkpoint、Skill 权限、上下文压缩和标准中间件连接；底座通过后再迁移材料解析与 Word 业务能力。

## 20. 实施登记

实施进度以第 16 节的 Phase 为唯一主坐标；“MVP”只表示 Phase 内的可验证增量，不代表整个 Phase 完成。

| Phase | 当前状态 | 已落地范围 | 主要剩余项 |
|---|---|---|---|
| Phase 0：Deep Agents 架构 Spike 与实现边界固化 | 部分完成 | Deep Agents factory、版本锁定、会话续接、Skill tool policy | 自动压缩触发及真实模型 adapter 验证 |
| Phase 1：工程骨架与运行内核 | 部分完成 | src-layout、三环境配置、标识/事件/状态、MySQL saver adapter | API/worker、专用 MySQL schema 的真实恢复验收 |
| Phase 2：Sandbox、Workspace 与上下文治理 | 进行中 | workspace policy、Linux Bubblewrap、cgroup 限额、Shell 强制断网、tool offload、调用预算、workspace audit、配置化主动压缩与硬停止、压缩后重建续接、artifact transfer、diff 与 workspace 配额 | 真实模型长会话验收、专用 MySQL schema 恢复验收 |
| Phase 3：Data MCP 与证据链 | 代码 MVP 完成，环境验收待补 | MCP registry/gateway、五工具 LangChain tools、required readiness、输入输出契约校验、workspace evidence store、分块读取、调用审计、HTTP 五工具 mock e2e、四状态矩阵、ReportDraft evidence 强引用 | test 环境五工具真实业务响应验收 |
| Phase 4：文档 Skill 与 Word Toolkit | 已完成 | ReportDraft/标题及表格证据门禁、正式 Investment Report Skill、材料解析与识别、完整 Harness 工具集、Agent 自主五工具→Evidence→分章节草稿→Word→逐页检查→暂存、Word P0/P1 与 Docker visual golden | 真实 OCR/Data MCP 业务联调作为环境验收项进入 Phase 5 |
| Phase 5：API、队列与端到端收口 | 进行中 | 同步 RunService、开发者调试 API/页面、材料上传、脱敏工具轨迹、Agent 文本、MinIO 发布、MySQL task/session/run/artifact 元数据和查询 API | worker/队列、SSE、取消/重试/跨进程发布幂等、人工确认恢复、真实 Agent 全链路 E2E |
| Phase 6：清理与主分支切换 | 未开始 | — | 全部 |

### Phase 0/1 · MVP 1：可安装 Harness 与工作空间最小底座（2026-09-09）

状态：**已完成并通过验证**。本批覆盖 Phase 0/1 的最小可执行切片，不表示 Phase 0 或 Phase 1 已整体完成。

本批完成：

- 根 `uv workspace` 纳入 `apps/report_agent`。
- 新建 `bjs-report-agent` Hatchling/src-layout package，并由 `uv.lock` 固定依赖。
- 实际解析并接入 `deepagents==0.5.9`、`langchain==1.4.0`、`langgraph==1.2.11`。
- 建立唯一 Harness 适配入口 `report_agent.harness.factory`，可注入 model、backend、tools、checkpointer 和 store。
- 建立独立 `task_id/session_id/run_id/workspace_id`。
- 建立 `TaskWorkspace` 最小实现：标准目录、虚拟 `/workspace` 路径、写入、manifest/hash、output staging、软删除和恢复。
- 对 `input/references/evidence` 实施只读策略，对 `working/output/staging/.trash/logs` 实施受控写策略。
- 拒绝 `..`、绝对盘符逃逸和 workspace 内符号链接链路。
- 建立 Skill metadata discovery/full-body activation 两阶段接口。
- 建立 `allowed-tools` 运行时选择和授权校验，不再仅解析 frontmatter。
- 增加离线 `report-agent-spike` 命令，用于验证标识和工作空间，不调用远程模型。
- 新增 [ADR-0001](./adr/0001-deep-agents-harness-boundary.md) 固化 Deep Agents 唯一路线和适配边界。

验证结果：

```text
uv lock                                                    PASS
uv sync --package bjs-report-agent --group test --group lint PASS
uv run --package bjs-report-agent pytest apps/report_agent/tests
  9 passed                                                 PASS
uv run --package bjs-report-agent ruff check apps/report_agent
  All checks passed                                        PASS
uv run --package bjs-report-agent mypy apps/report_agent/src/report_agent
  Success: no issues found in 12 source files               PASS
uv run --package bjs-report-agent report-agent-spike ...    PASS
```

其中 Harness 集成测试使用真实 Deep Agent graph 和 `InMemorySaver`，验证同一 `thread_id` 的两轮消息可以续接；它只用于确认框架接入语义，不作为生产持久化方案。

本批明确未完成：

- Bubblewrap/Linux namespace 进程隔离和 `execute`；
- MySQL/Redis/MinIO 的真实环境迁移与持久 checkpointer 验收；
- 自动上下文压缩、tool result offload 和调用预算 middleware；
- 正式 repository Skill 和 Skill scripts 同步；
- Data MCP gateway；
- 材料解析及 Word 工具。

后续增量：进入 Phase 1 的配置模型、事件/状态模型和可恢复 checkpoint。

### Phase 1 · MVP 2：配置契约、工作流状态与 MySQL checkpoint 边界（2026-09-09）

状态：**代码 MVP 已完成并通过离线验证；真实 MySQL DDL/恢复验收待专用 test schema**。

本批完成：

- 建立 test/UAT/prod 同构、严格且不可变的 `report-agent.yaml` 配置模型，密钥仅以环境变量引用表达。
- 配置沿用现有 `MYSQL_*`、`REDIS_*`、`MINIO_*` 契约，不再要求额外 PostgreSQL 或拼装式 Redis URL。
- 建立 task/session/run workflow state、typed event 和状态迁移约束。
- 引入 `langgraph-checkpoint-mysql[pymysql]`，由项目自有 adapter 负责 DSN 解析与 saver 生命周期。
- 将 `setup()` 建表从 worker 正常启动中剥离，只允许显式部署迁移任务调用，避免应用启动擅自修改共享库。
- 增加进程重建后按同一 `thread_id` 恢复的 MySQL 集成测试；仅在显式提供 `REPORT_AGENT_TEST_MYSQL_DSN` 时运行。
- 新增 [ADR-0002](./adr/0002-use-existing-mysql-for-langgraph-checkpoints.md)，固化复用 MySQL 的依据和兼容性治理方式。

本批边界：当前环境未提供专用 checkpoint schema，也未授权在共享 MySQL 中执行 DDL，因此真实 saver 的建表、写入和 resume 测试保持跳过。这不是引入 PostgreSQL 的理由；后续提供满足版本要求的专用 test schema 后再完成验收。

验证结果：依赖已解析为 `langgraph-checkpoint-mysql==3.0.0`；单元及离线集成测试 `16 passed, 1 skipped`，ruff、mypy、wheel/sdist build 均通过。使用现有 test 配置执行只读 `SELECT VERSION()`，确认服务端为 MySQL 8.3.0，满足 saver 的最低版本要求；未执行建表和业务写入。

### Phase 2 · MVP 1：Bubblewrap 执行边界与 Shell 大输出落盘（2026-09-09）

状态：**已完成并在 Docker Desktop Linux runtime 通过真实隔离验证**。

本增量完成：

- 实现 `BubblewrapSandboxBackend` 并适配 Deep Agents `BaseSandbox`，不使用普通宿主 Shell 作为生产回退。
- 每次执行创建 user/pid/uts/ipc/cgroup/network namespace；容器根文件系统只读绑定，仅 task workspace 绑定到可写 `/workspace`。
- 清空继承环境，只注入固定 PATH/HOME 和显式非敏感环境变量；拒绝 key、secret、token、password、credential 类变量进入 Agent shell。
- 命令以参数数组传递给 `bwrap`，用户命令仅作为 sandbox 内 `/bin/sh -lc` 的单个参数，不经过宿主 shell 拼接。
- 实施命令超时上限；超时返回确定性退出码，不回退到宿主执行。
- Shell 输出超过 inline 限额时，完整内容写入 `/workspace/logs/tool-results`，模型上下文只保留预览和文件引用。
- `upload_files/download_files` 复用 `TaskWorkspace` 路径策略，受保护目录仍不可写。
- 新增版本化 `Dockerfile.runtime`，以非 root 用户运行并安装 Bubblewrap 和基础命令行工具。
- 新增显式开启的 Linux Bubblewrap security smoke test，验证 workspace 内可写、只读 root 不可写。

当前边界：配置中的 Data MCP/MinIO 网络 allowlist 尚未接入外部容器网络策略，当前 backend 安全默认值是完全断网。生产持久卷必须由部署初始化任务赋予 UID/GID `10001` 写权限。

验证结果：镜像 `bjs-report-agent-runtime:0.1.0` 构建成功并以非 root `report-agent` 用户运行；只读根文件系统及 `--memory 512m --cpus 1 --pids-limit 64` 下启动通过。真实 Bubblewrap 命令成功写入 `/workspace/working`，对 `/usr/local` 的写入以只读文件系统错误被拒绝。

### Phase 2 · MVP 2：通用输出治理、调用预算与审计基础（2026-09-09）

状态：**已完成并通过自动化验证**。

本增量完成：

- 增加通用 `ToolOutputOffloader`，对字符串或结构化工具结果统一序列化、计算 SHA-256；超过配置阈值后写入 workspace，只向模型返回预览、路径、原始长度和哈希。
- 增加线程安全的 `RunBudget`，独立限制 model call、tool call 和 run wall-clock 时间，超限时在调用前确定性中止。
- 增加 `BudgetMiddleware` 与 `ToolOutputOffloadMiddleware`，并通过 `AgentBuildSpec.middleware` 注入 Deep Agents，不让治理逻辑散落在业务工具中。
- 对普通 `ToolMessage` 执行 offload；对 LangGraph `Command` 保持原语义，后续由 workflow/state 层处理，避免破坏状态更新。
- 增加 append-only workspace NDJSON audit sink，并复用 typed `AgentEvent` 契约。
- 新增可重复执行的 `report-agent-sandbox-smoke` 容器命令及部署验证说明。

本增量仍未实现自动 summarization。下一增量需要基于框架标准 summarization middleware 验证 65% 阈值触发，并加入“AI tool call 与对应 ToolMessage 不可拆分”的回归测试；测试证明标准能力不足时，才补最小原子保护逻辑。

验证结果：Report Agent 全量测试 `27 passed, 2 skipped`，ruff、mypy、wheel/sdist build、lock check 和 `git diff --check` 全部通过。runtime 镜像最终构建为 `sha256:90781a32d6baddc1d447bbd74b670d7aee7934f029caae51e4ddeec4f4169ced`，镜像用户为 `report-agent`；正式 `report-agent-sandbox-smoke` 返回 `status=passed`、workspace 写入退出码 `0`、root 写入退出码 `2`。

### Phase 2 · MVP 3：配置化上下文窗口与主动压缩（2026-09-09）

状态：**配置、阈值控制和 Harness 集成已完成；真实模型长会话压缩待端到端验证**。

本增量完成：

- 在三环境配置中新增必填环境引用 `LLM_MAX_CONTEXT_TOKENS`。该值表示模型允许的输入上下文窗口，不是单次回答的最大输出 token。
- test 环境按当前模型配置为 `131072`；UAT/prod 保留空值，部署负责人必须根据实际模型网关额度填写，禁止无依据复制 test 值。
- 启动时将环境值解析为不可变 `ContextWindow`，拒绝缺失值、非整数以及小于 4096 的配置。
- 根据 `compact_at_ratio=0.65` 和 `hard_stop_ratio=0.90` 计算绝对 token 阈值。以 test 为例，主动压缩阈值为 `85196`，硬停止阈值为 `117964`。
- 增加项目命名的 `ReportAgentSummarizationMiddleware`，使用 Deep Agents 的历史落盘与摘要能力，在 65% 阈值主动触发；Deep Agents 自带的模型感知摘要保留为更高阈值兜底。
- 增加 `ContextHardStopMiddleware`。若摘要后估算上下文仍达到 90%，在请求模型前确定性终止，避免依赖供应商 context-length error 作为正常控制流。
- `build_context_middleware_stack` 固定“先摘要、后硬停止”的顺序，并可直接注入 `AgentBuildSpec.middleware`。
- 回归测试锁定框架行为：当截断点落在 `ToolMessage` 时，向前移动到对应 `AIMessage.tool_calls` 之前，保证调用与结果不会被拆分。
- 集成测试使用真实 Deep Agent graph 验证自定义摘要 middleware 与框架默认 middleware 可同时构建并完成调用。

当前边界：本轮使用 fake model 验证触发判断、原子截断和 graph 编译，没有消耗真实模型 API；长对话的实际摘要质量、checkpoint 恢复后继续压缩以及摘要事件审计，留在 Phase 2 后续端到端验证。

验证结果：加载 test `runtime.env` 后得到 `max_tokens=131072`、`compact_at_tokens=85196`、`hard_stop_tokens=117964`；Report Agent 全量测试 `36 passed, 2 skipped`，ruff、mypy、lock check、wheel/sdist build 和 `git diff --check` 全部通过。包含最新上下文实现的 runtime 镜像构建为 `sha256:fbe122aff3e0315e40cfeaa0a609ad4ede7dc96003148d84d312126d30cda15b`，容器内 context runtime import 与 Bubblewrap security smoke 均通过。

### Phase 1 · MVP 3：仓库目录收敛与生成物清理（2026-09-09）

状态：**已完成**。

- 删除旧设计遗留且只有 `.gitkeep` 的根级 `skills/`、`tools/`、空 contracts/docs/resources 子目录，以及 `apps/report_agent/src` 下旧的平铺式空骨架。
- 删除 Data MCP 下未跟踪且为空的旧 `storage`、`adapters`、`http` 和整套 `capabilities` 目录；当前实现统一以 `features`、`mcp`、`shared` 为有效源码结构。
- 删除仓库内 `.mypy_cache`、`.pytest_cache`、`.ruff_cache`、`.runtime`、`dist`、全部源码/测试 `__pycache__`、`.pyc` 和构建出的 wheel。
- 保留 `.venv` 作为 uv 管理的项目依赖环境；其中第三方包字节码不是仓库产物，不纳入源码目录清理。
- 保留 `resources/reference_data/data_mcp`，因为三个环境配置和 Data MCP 测试仍直接依赖这些参考数据。
- 根 README 的目录树和职责说明已按当前实际结构重写；后续目录仅在对应 Phase 有真实实现时创建，不再提前堆放空目录。
- `.gitignore` 已覆盖 Python 字节码、wheel、egg-info、测试/类型/格式缓存、build/dist 和 runtime 工作目录，防止生成物再次进入版本控制。

清理后扫描确认：除 `.venv` 和 `.git` 外，不再存在 `__pycache__`、`.pyc`、`.pyo`、`.whl`、pytest/mypy/ruff cache、build、dist 或 egg-info；仓库内也没有残留空目录。

### Phase 2 · MVP 4：Artifact Transfer、Workspace Diff 与容量治理（2026-09-09）

状态：**已完成并通过自动化验证**。

本增量完成：

- `TaskWorkspace` 新增服务侧可信导入入口，只允许将上传材料、参考资料和 MCP evidence 写入 Agent 只读的 `input/references/evidence` 区域；Agent 自身仍不能通过普通写入接口修改这些目录。
- 新增 staging-only 导出边界。报告必须先从 `output` 显式 stage，交付层才可读取并上传对象存储，避免任意 workspace 文件直接成为对外交付物。
- 新增 workspace 全量快照与确定性 diff，按 SHA-256 输出 `created/modified/deleted` 变更，覆盖 Agent 修改、创建、软删除及 trash 变化，可用于运行审计和恢复检查。
- 新增 `service.workspace_max_mb` 三环境同构配置，默认 2048 MiB；写入、追加、导入、stage 和恢复均在落盘前检查任务级配额。
- 普通写入改为同目录临时文件加原子替换。配额拒绝不会破坏已有文件，减少大文件或异常中断造成半写文件的风险。
- Deep Agents 文件上传协议的错误枚举不包含独立 quota 类型，因此 backend 对外映射为标准 `permission_denied`；工作区内部保留 `WorkspaceQuotaExceeded` 以供审计层记录准确原因。
- 增加 artifact import/export、路径策略、快照 diff、覆盖写配额原子性和 sandbox 上传配额映射测试。

当前边界：本增量完成的是 task workspace 与 sandbox backend 间的本地 artifact transfer 契约；MinIO 上传下载适配属于 Phase 5 的 artifact service/API。网络 allowlist 仍需结合容器网络策略实现，当前 Bubblewrap 默认完全断网。

验证结果：Report Agent 全量测试 `40 passed, 2 skipped`；跳过项仍为需要专用 MySQL schema 的持久化集成测试和需要 Linux Bubblewrap 的安全测试。Ruff、mypy、`uv lock --check` 与 `git diff --check` 全部通过。

### Phase 2 · MVP 5：强制断网边界与压缩会话续接（2026-09-09）

状态：**代码与离线集成验证已完成；真实模型和真实 MySQL 恢复验收仍受外部环境条件约束**。

本增量完成：

- 移除 `BubblewrapPolicy.network_isolated` 可关闭开关，所有模型控制的 Shell 命令无条件使用 `--unshare-net`，应用代码不能通过配置把 sandbox 切换为宿主网络。
- 三环境配置将原本未被执行的 `network_allowlist: [data-mcp, minio]` 改为可验证的 `network_mode: isolated`。避免配置表面声明 allowlist、实际 Bubblewrap 无法按主机名执行过滤的虚假安全边界。
- Data MCP 和 MinIO 不进入模型 Shell：Data MCP 由 Phase 3 service-owned MCP gateway 访问；MinIO 由 Phase 5 artifact service 访问。各自的 URL、工具 allowlist 和凭据只存在于服务适配层。
- 增加强制 `--unshare-net` 和非法网络模式配置测试，锁定默认拒绝网络且不可通过 YAML 绕过。
- 增加压缩会话续接集成测试：制造超过主动阈值的长历史，确认被裁剪历史写入 `/conversation_history/{thread_id}.md`，再重建 Deep Agent graph，以相同 checkpointer 和 `thread_id` 恢复 `_summarization_event` 并继续对话。

架构说明：当前没有需要从 sandbox Shell 发起的外部网络请求，因此空 allowlist（完全断网）是最小且最强的有效策略。若未来 Word script 确实需要外部服务，必须新增受控代理并按目标解析、DNS 重绑定和 IP 范围进行防护，不能简单删除 `--unshare-net`。

当前边界：离线测试已覆盖真实 Deep Agents summarization middleware、history offload、checkpoint state 和 graph rebuild，但摘要模型仍为 fake model；MySQL saver 的跨进程恢复仍等待专用 test schema。两项不阻塞进入 Phase 3 的 MCP gateway 开发，但在 Phase 2 最终退出验收前必须补齐。

### Phase 3 · MVP 1：Data MCP Gateway 与 Workspace Evidence Store（2026-09-09）

状态：**代码 MVP 已完成并通过 mock contract 验证；真实 Data MCP HTTP 联调留在下一增量**。

本增量完成：

- 新增项目自有 `DataMcpGateway`，调用链固定为“工具授权检查 → input schema 校验 → MCP transport → output schema 校验 → evidence 落盘 → Agent 摘要视图”。Report Agent 不导入任何 `data_mcp` Python 模块。
- `McpSettings.enabled_tools` 必须且只能包含五个标准工具，缺少、增加或重复均在配置加载期失败。
- 新增 required readiness：通过 MCP `tools/list` 比对五工具，required 服务缺工具时阻止任务进入执行阶段；服务返回额外工具不会自动授权给 Agent。
- 新增共享 contract registry，直接读取 `/app/contracts/mcp/*.json`，使用 JSON Schema Draft 2020-12 分别校验输入和输出；错误响应或 tool 名错配不会写入 evidence。
- 新增 `WorkspaceEvidenceStore`。每次合规调用生成不可猜测的 `evidence_id`，完整统一外壳以规范 JSON 写入只读 `/workspace/evidence`，记录 SHA-256 和大小。
- Gateway 只向 Agent 返回 `status/summary/warnings/data_preview/evidence_id`；超长数据标记 `truncated`，后续通过带 offset/limit 上限的 evidence chunk 接口读取，避免 MCP 全量结果挤入上下文。
- 新增官方 `mcp==2.x` Streamable HTTP adapter：固定 HTTP(S) endpoint，拒绝 URL 内嵌凭证、query 和 fragment；使用 `ClientSession.initialize/list_tools/call_tool`，支持 structured content 与 JSON text fallback。
- 三环境增加同构 `data_mcp.contracts_dir: /app/contracts/mcp`；Report Agent package 显式声明 `mcp`、`jsonschema`、`pytest-asyncio` 和类型依赖，不依赖 Data MCP package 的传递安装。

验证覆盖：required readiness 缺工具、五工具配置完整性、未授权工具、非法输入不发起调用、非法输出不落 evidence、`success/partial/empty/failed` 四状态透传、大响应预览与全文分块读取、evidence 路径防逃逸、HTTP endpoint 安全和响应解析。

当前边界：本增量使用 mock transport 验证 gateway/contract/evidence 完整链路，并完成真实 SDK transport adapter 的单元验证；尚未启动 Data MCP 服务执行 Streamable HTTP e2e，也未把 gateway 包装为 LangChain tools 注入 Harness。下一增量完成这两项及调用事件审计。

验证结果：Report Agent 全量测试 `60 passed, 2 skipped`；Ruff、mypy、`uv lock --check` 与 `git diff --check` 全部通过。跳过项仍为专用 MySQL schema 集成测试和 Linux Bubblewrap 安全测试。

### Phase 3 · MVP 2：Harness Tool 注入、审计与真实 MCP Readiness（2026-09-09）

状态：**已完成并通过自动化及本地真实协议验证**。

本增量完成：

- 新增 `build_data_mcp_tools`，按 contract registry 为五个标准工具生成 `StructuredTool`；工具描述和 `args_schema` 直接来自共享 JSON contract，不在 Agent 侧维护第二套参数模型。
- 工具 coroutine 只调用 `DataMcpGateway`，将 `EvidenceView` 序列化给模型；Deep Agents 集成测试验证模型发起 `query_track_labels` tool call、Gateway 生成 evidence、ToolMessage 返回 `evidence_id`，再由模型继续完成响应。
- Gateway 审计依赖改为 Application 层 `EventSink` 协议，避免 Application 反向依赖 Harness 实现产生循环 import；`WorkspaceAuditLog` 作为可替换实现注入。
- MCP 调用记录 `tool.started/tool.completed/tool.failed`，成功生成 evidence 后记录 `artifact.created`，包含 tool、status、evidence_id、path 和 SHA-256，不记录业务调用参数与潜在敏感材料。
- 增加可重复的 `REPORT_AGENT_TEST_DATA_MCP_URL` 集成测试入口，用于验证真实服务暴露且只暴露五个标准工具。
- 本地启动当前主分支 `bjs-data-mcp` Streamable HTTP 服务，通过 Report Agent 的官方 MCP 2.x adapter 完成 initialize、`tools/list` 和 session terminate；返回五工具集合完全一致。该验证未调用业务工具，不访问外部业务数据源。

验证结果：默认全量测试 `62 passed, 3 skipped`；其中 live Data MCP 测试在未设置 URL 时跳过。本轮显式启动 `http://127.0.0.1:18001/mcp` 后，live readiness 测试 `1 passed`。Ruff、mypy、`uv lock --check` 与 `git diff --check` 全部通过。

当前边界：真实协议的服务初始化和工具发现已通过，但五个业务工具的真实响应仍可能依赖外部模型、数据库或第三方服务，本轮未擅自产生这些调用。下一增量建立可控 mock MCP HTTP server 覆盖五工具 contract e2e，并开始定义 `ReportDraft` 对 evidence 的强引用约束。

### Phase 3 · MVP 3：五工具 HTTP Contract E2E 与 ReportDraft Evidence 强引用（2026-09-09）

状态：**Phase 3 代码退出条件已满足；test 环境真实业务调用验收待外部依赖可控时执行**。

本增量完成：

- 建立可控的 MCP 2.x Streamable HTTP mock server，通过真实 TCP、真实 `ClientSession` 和真实 Gateway 依次调用五个标准工具；每个响应均通过对应 output schema，并在 workspace 生成独立 evidence 文件。
- 增加五工具 × `success/partial/empty/failed` 的 20 组 contract 矩阵，确认所有工具共享统一降级状态语义，而不是只验证某一个工具。
- 增加源码边界回归检查，确保 `apps/report_agent/src/report_agent` 不出现 `import data_mcp` 或 `from data_mcp`；双方只通过 MCP 协议和 `contracts/mcp` 共享契约。
- 新增不可变 `ReportDraft` 基础模型，包括 section、narrative、fact claim、missing item、draft status 和 schema version；section/claim ID 必须唯一，`ready_for_render` 不允许残留 missing item。
- 关键事实 `FactClaim.critical=true` 时必须至少包含一个 evidence citation。citation 同时包含稳定 `evidence_id` 和 RFC 6901 JSON Pointer，不接受只写模糊来源名称。
- 新增确定性引用完整性校验：evidence 文件必须存在，JSON Pointer 必须实际指向统一外壳内的字段；`empty/failed` evidence 禁止支撑事实，`partial` evidence 必须在 claim 上明确填写 disclosure，`success` 可正常使用。
- `WorkspaceEvidenceStore` 增加按 ID 读取完整合规 evidence 的内部能力，仍不向模型直接暴露任意文件路径。

验证结果：Report Agent 全量测试 `92 passed, 3 skipped`；Ruff、mypy、`uv lock --check` 与 `git diff --check` 全部通过。三个跳过项分别为未常驻启动的 live Data MCP、未提供专用 schema 的 MySQL saver，以及当前 Windows 主机上的 Linux Bubblewrap 测试；前两项均保留显式集成测试入口，Bubblewrap 已在前序 Docker runtime 验证通过。

Phase 判断：Phase 3 的代码级退出条件已经满足——五工具、四状态、协议隔离和报告事实到 evidence 的定位均有自动化验证。为了不把外部服务波动带入确定性 CI，真实业务数据响应仅作为 test 环境验收项保留。`ReportDraft` 只完成了支撑 evidence 强引用的最小结构，Phase 4 的 Skill、完整 document contract、DOCX 工具与视觉 QA 尚未开始。

### Phase 4 · MVP 1：Investment Report Skill 与零幻觉交付契约（2026-09-10）

状态：**已完成并通过自动化验证；Word 工具实现与视觉 golden 留在后续增量**。

本增量完成：

- 在 `apps/report_agent/skills/investment-report` 建立正式 repository Skill，包含 `SKILL.md`、渐进加载 references、薄校验脚本和界面元数据。
- 固定 Data MCP 五工具调用顺序为 `extract_project_profile → query_track_labels → match_listed_peers → query_comparable_valuation → match_investors`，并纳入 `allowed-tools` 强约束。
- 固化“Data MCP 是成稿事实唯一来源”：用户材料只用于识别和确认查询输入；示例模板、训练知识、互联网和模型推断均不得补齐报告事实。
- 将 `ReportDraft` 门禁从“仅 critical claim 必须引用”收紧为“所有 `FactClaim` 均必须引用”，避免模型通过非关键标记绕过证据约束。
- 定义 `success/partial/empty/failed` 的写作策略、关键输入不足时的二次交互、章节省略规则和三个业务确认节点。
- 定义 DOCX 从零创建、稳定 claim anchor、来源批注作者“投资报告智能体”、全页渲染、OOXML 结构校验和暂存后发布顺序。
- 对用户提供的参考 DOCX 完成结构审计并固化版式基线及 SHA-256；仅复用其视觉体系和章节意图，不继承示例事实、直接格式和错误编号。
- 定义 PDF 前 1–3 页视觉分类路由：slide-like 使用逐页多模态识别，document-like 使用 PaddleOCR，混合或低置信度材料允许按页路由并交叉校验。
- 补充三环境同构的 MinIO `object_prefix` 和预签名 URL 有效期配置。发布只允许由 Phase 5 服务侧 artifact service 执行，模型和 sandbox Shell 均不接触 MinIO 凭据。

验证结果：Skill Creator 结构校验通过；Report Agent 全量测试 `96 passed, 3 skipped`；Ruff、mypy、`uv lock --check`、Skill 薄脚本 CLI smoke 和 `git diff --check` 全部通过。三个跳过项仍为 live Data MCP、专用 MySQL schema 和 Windows 主机上的 Bubblewrap 环境测试。

当前边界：开发机捆绑文档运行时未发现 LibreOffice，参考模板暂只完成 OOXML 结构审计，尚未形成逐页 PNG golden。下一增量先实现完整 document contract 与材料解析工具，再独立实现 Word P0 工具（创建、更新、批注、渲染、验证）；渲染 runtime 补齐后必须对全部页面完成人工与自动视觉验收。

### Phase 4 · MVP 2：Material Contract 与多格式解析工具（2026-09-10）

状态：**代码 MVP 已完成并通过自动化验证；PaddleOCR/多模态模型的真实服务调用及旧 Office 转换留在后续增量**。

本增量完成：

- 新增稳定 `ParsedMaterial` contract，统一 material id、源文件哈希、格式、结构块、页码/幻灯片/工作表/单元格定位、PDF 类型、页面预览和警告。
- 文件识别以内容签名为主、扩展名为辅，拒绝把伪装扩展名当作合法 Office/PDF 文件。
- 使用独立开源实现解析 DOCX、PPTX、XLSX、XLS、CSV 和文本 PDF，不复制 Codex Documents Skill 脚本；Excel 使用计算后的单元格值视图，避免把公式字符串当成业务结果。
- PDF 先做文本密度检测；不能确定为文本型时自动渲染前 1–3 页 PNG，并通过 `inspect_page_image` 以多模态消息内容交给模型判断 `slide_like/document_like/mixed`。
- 新增 `MaterialIngestionService`，严格限定只解析当前 task 的 `/workspace/input`，不允许模型借解析工具读取 working、evidence 或宿主任意路径。
- 新增 `list_workspace_files`、`parse_materials`、`read_material_chunk`、`inspect_page_image` 四个 Agent 工具；长材料按最多 50 个结构块渐进读取，避免整份附件进入上下文。
- 解析材料明确不属于报告证据，只能用于确认 Data MCP 查询参数；成稿事实仍必须由 MCP evidence 支撑。
- Report Agent 显式锁定 `pymupdf/python-docx/python-pptx/openpyxl/xlrd` 依赖，并增加格式检测、定位、分页预览、路径隔离和多模态内容回归测试。

当前边界：扫描 PDF 已能稳定产生供多模态模型查看的页图，但模型分类结果到“逐页多模态识别或 PaddleOCR”的异步适配器尚未实现；`.doc/.ppt` 已被识别但会明确要求受控转换，不做静默猜测。下一增量补齐这两个 service-owned adapter，并将解析结果持久化为可恢复 artifact，然后进入 Word P0 工具。

验证结果：Report Agent 全量测试 `106 passed, 3 skipped`；Skill 校验、Ruff、mypy、`uv lock --check` 和 `git diff --check` 均通过。跳过项仍为需要外部条件的 live Data MCP、专用 MySQL schema 和 Linux Bubblewrap 测试，不是本增量新增失败。

### Phase 4 · MVP 3：扫描 PDF 识别路由与可恢复材料 Artifact（2026-09-10）

状态：**代码 MVP 已完成并通过 mock HTTP 与全量回归；真实 PaddleOCR/模型服务联调待环境验收**。

本增量完成：

- 新增 `DocumentRecognitionRouter`，前 1–3 页分类为 `document_scan` 时逐页调用 PaddleOCR，分类为 `slide_scan` 时逐页调用多模态模型；`mixed_or_unknown` 必须显式按页路由，不允许系统擅自选一路导致静默误识别。
- 新增 OpenAI-compatible 多模态 HTTP adapter，使用独立 `MULTIMODAL_MODEL`、固定 temperature 0 和 JSON 响应约束；页面以 data URL 发送，不要求模型访问宿主文件路径。
- 新增 Paddle layout HTTP adapter，使用 multipart 页面上传并兼容从嵌套 `markdown/text/content/result` 中提取正文；凭据只存在于 service-owned adapter。
- 所有识别块记录 `recognition_method`、页码与可选 confidence，区分 embedded text、PaddleOCR 和 multimodal，便于审计与问题定位。
- 每次材料解析将完整 `ParsedMaterial` 以 material id 持久化到 task workspace；Agent/worker 重建后可恢复分块读取，不依赖进程内缓存。
- test/UAT/prod 配置结构新增 `multimodal_model`、PaddleOCR URL/token、超时、预览页数和混合 PDF 严格路由开关；UAT/prod 仅保留空环境变量槽位，不复制 test 凭据。
- HTTP adapter 使用 mock transport 验证授权头、图片消息、确定性参数、multipart 上传和响应归一化，未消耗外部模型/OCR 服务额度。

验证结果：Report Agent 全量测试 `112 passed, 3 skipped`；Ruff、`uv lock --offline --check` 和 `git diff --check` 通过。mypy 首次发现多模态 content 列表推断过宽，已增加明确类型标注，最终复验结果记录在本增量完成检查中。

当前边界：自建 PaddleOCR endpoint 的实际 multipart 字段与返回外壳仍需用 test 服务做一次非生产材料联调；旧 `.doc/.ppt` 仍明确返回“需要受控转换”，不伪装成已支持。下一增量进入 Word P0 Toolkit，同时在 runtime 中补齐 LibreOffice 渲染/旧 Office 转换能力。

### Phase 4 · MVP 4：Word P0 Toolkit 与交付门禁（2026-09-10）

状态：**代码 MVP 与 OOXML 结构验证已完成；Docker Desktop Linux engine 未启动，容器内真实 LibreOffice 渲染待补验**。

本增量完成：

- `ReportDraft` 增加证据化表格 contract，表头属于结构文本，所有正文和表格数据单元格均使用带 citation 的 `FactClaim`；`ready_for_render` 明确拒绝未引用的 narrative，封堵模型把事实藏入自由文本的路径。
- 从空白 DOCX 创建正式报告，按参考模板建立 A4 页面、边距、标题/一级标题/二级标题/正文中文字体基线，不复制示例模板事实或错误编号。
- section/claim 使用确定性 bookmark anchor；更新操作依据当前语义草稿重建同名文档，旧版本可由 workspace diff/trash 审计，不依赖易漂移的段落序号。
- 为每个事实 claim（含表格单元格）创建真实 Word comment，作者固定为“投资报告智能体”，内容包含 MCP 工具、来源名、evidence id 和 JSON Pointer。
- 验证器检查 DOCX ZIP、comments part、relationship、Content Types override、批注 id 的 start/end/reference 一致性、数量和作者；结构失败的文件不会写入 output。
- 新增 create/update/add comments/validate/render/stage/delete/restore 八个 Agent Word 工具。删除使用已有软删除与恢复机制，不直接物理删除报告。
- 新增 LibreOffice DOCX→PDF 与 PyMuPDF 全页 PNG 渲染器，以及 `.doc/.ppt/.xls` 到 OOXML 的受控 LibreOffice converter；runtime 镜像声明 Writer/Impress/Calc 和 Noto CJK 字体依赖。
- stage 不接受“结构验证通过”作为充分条件：当前 DOCX 哈希必须已有完整 render 记录，并由调用方确认视觉复核通过；报告更新后旧 render 记录自动失效。

验证结果：Report Agent 全量回归为 `118 passed, 3 skipped`；Ruff、mypy、`uv lock --offline --check` 和 `git diff --check` 通过。测试真实生成并解包 DOCX，确认 3 个事实批注、固定作者、Evidence 文本、bookmark 和 OOXML wiring 全部存在；渲染器通过可控双页 PDF 测试确认逐页 PNG 输出。

环境限制：尝试构建 `bjs-report-agent-runtime:0.2.0` 时 Docker Desktop Linux named pipe 不存在，说明本机 Docker engine 当时不可连接；宿主机也没有可用 `soffice`。因此本增量没有把 mock renderer 测试冒充真实视觉验收。待 Docker engine 可连接后，应立即执行镜像构建、真实报告渲染、全部页面检查和 golden 固化。

### Phase 4 · MVP 5：完整 Harness 工具集与 Docker Word 视觉验收（2026-09-10）

状态：**已完成代码、容器运行和代表性报告逐页视觉验收**。

本增量完成：

- 新增可恢复的 `ReportDraftService` 与 `create_report_draft/upsert_report_section/validate_report_draft` 工具；草稿按 task 写入 `/workspace/working/drafts`，worker 重建后可继续逐章节完善。
- 新增受控 `read_evidence_chunk` 工具，模型只能用合规 evidence id 分块读取 MCP 结果，不能用任意路径绕过 evidence store。
- 新增 `build_investment_report_tools` 统一装配入口，将材料解析、五个 Data MCP 工具、evidence、草稿、Word 和服务侧发布端口合并为正式 Investment Report Harness 工具集。
- 工具装配严格执行 repository Skill 的 `allowed-tools`：缺少声明工具、重复工具或出现未授权工具都会在 Agent 启动前失败，Skill 不再只是提示词约定。
- Word render receipt 从进程内字典改为按当前 DOCX SHA-256 持久化到 task workspace。渲染和暂存可以跨 worker/进程续接，报告内容一旦变化，旧 receipt 自动失效。
- 增加无 pytest 依赖的生产镜像 smoke 入口，可在真实 runtime 中创建含中文、表格和三个 MCP 来源批注的 DOCX，并执行 LibreOffice→PDF→逐页 PNG 完整链路。

Docker 验收结果：

- 成功构建 `bjs-report-agent-runtime:0.2.0`，镜像摘要 `sha256:a8e88c3c54290bcc15c9c90b378b21a4f65e482f5b790d44afeedd58ac7d5efe`，镜像进程用户为 `report-agent`。
- 容器运行在只读根文件系统和独立可写 task workspace 下；LibreOffice `7.4.7.2` 与 `Noto Sans CJK SC` 字体可用。
- 真实生成 `投资人匹配报告.docx`，结构校验确认三个事实批注及作者“投资报告智能体”；LibreOffice 生成 PDF 后由 PyMuPDF 输出 1 页 PNG。
- 已检查全部 1 页渲染：中文标题、日期、一级标题、正文及两列表格均正常，无乱码、遮挡、截断、溢出或异常空白页。本轮代表性 smoke 页面可作为 runtime 基线，但参考模板的完整章节 golden 仍需在 Word P1 固化。
- 视觉确认后使用新建的 `WordReportService` 进程读取持久化 render receipt 并成功暂存；staging 文件 SHA-256 与 output 原件一致，证明门禁可跨进程续接。

回归结果：Report Agent 全量测试 `119 passed, 4 skipped`；Ruff、mypy、`uv lock --check` 与 `git diff --check` 全部通过。四个跳过项分别需要常驻 Data MCP、专用 MySQL schema、宿主 LibreOffice 和宿主 Linux Bubblewrap；Word 的真实 LibreOffice 路径已由本轮生产容器 smoke 覆盖。

验证说明：Report Agent 测试必须从自身 project/test path 执行；直接从根目录用 Report Agent 虚拟环境收集整个 monorepo，会因 Data MCP 是独立 package 而产生导入错误，该命令不属于有效的跨包测试方式。两个 package 应分别按各自项目环境验证。

当前边界：`publish_report` 已作为 service-owned 注入端口进入完整工具集，但 MinIO 上传和预签名 URL 仍属于 Phase 5，不在本增量伪造实现；PaddleOCR 真实服务契约、参考模板全章节视觉 golden 和复杂分页/目录/图表继续作为 Phase 4 后续增量。

### Phase 4 · MVP 6：完整报告 Word P1 与 Visual Golden（2026-09-10）

状态：**已完成参考模板逐页审计、完整匿名报告生成、结构验收和 Docker visual golden**。

本增量完成：

- 在项目 Docker runtime 中将用户参考模板渲染为 10 页 PNG 并逐页检查。模板确认为 A4 纵向、单节、左右 1.25 英寸及上下 1 英寸边距；同时确认其没有 Heading 样式、目录字段和页码，正文大量使用直接格式，财务表及投资人表依赖自然跨页。
- 生产实现继续从空白 DOCX 构建，不复制参考模板的示例事实或直接格式；保留其正式中文报告、黑色标题层级、A4 页面和表格表达方式。
- `ReportDraft` 增加 1–3 级语义标题，并把报告标题纳入事实门禁。`ready_for_render` 必须提供与标题完全一致、带 Data MCP citation 的 `title_claim`，标题同样生成来源批注。
- Word 作者实现 Heading 1/2/3、标题黑色且无装饰线、正文两端对齐及首行缩进、动态 PAGE 页脚。报告日期支持调用方显式传入 ISO 日期，golden 不再依赖容器时区。
- 表格实现按内容权重分配列宽、禁用默认自动列宽、统一单元格内边距和垂直对齐、浅蓝表头、重复表头及可扩展行高；没有通过固定行高压缩长文本。
- 建立完整匿名报告 fixture，覆盖项目分析、核心资产、财务、交易条件、市场、上市公司对标、投资匹配分析和投资人明细，包含五列表、六列表及跨页三列表。fixture 的所有 67 个事实单元均来自匿名 mock MCP evidence，不使用参考模板事实。
- 新增 `tests/golden/investment-report-word.json`，固定 LibreOffice 7.4.7.2、Noto Sans CJK SC、报告日期、页面尺寸及三页 PNG SHA-256；新增显式环境开关控制的 golden 集成测试，避免其他 LibreOffice/字体版本产生误报。

真实验收结果：

- 重新构建正式镜像 `bjs-report-agent-runtime:0.2.0`，摘要为 `sha256:a2391e258c608abb74ac6eae5836ac9ac03e14f6278cfb683430bf5225885492`，运行用户仍为 `report-agent`。
- 镜像在只读根文件系统和独立可写 workspace 下生成 3 页 DOCX/PDF/PNG；三页图像与 golden 的尺寸和 SHA-256 全部一致。
- 已逐页检查三页：标题与日期清晰，标题下无残留蓝线；正文无乱码、重叠和截断；五列及六列表可读；三列投资人表在第 2–3 页跨页后正确重复表头，未拆断单行；页码位置一致。
- Documents Skill 审计脚本确认单节 A4 页面、5 个 Heading 1、6 个 Heading 2 和 footer PAGE 字段；批注提取确认 67 条批注、67 条均有锚点、作者全部为“投资报告智能体”。

验证结果：Report Agent 全量测试 `120 passed, 5 skipped`；Ruff、mypy、`uv lock --check`、`git diff --check` 通过。新增 golden 测试默认要求固定 Word runtime，宿主 Windows 无 LibreOffice 时明确跳过；本轮已在正式 Docker runtime 中执行等价生成、指纹比对和人工逐页验收。

Phase 判断：Word P1 与视觉基线已经具备，但 Phase 4 的退出条件还差最后一个增量——让 Deep Agent 在可控 mock MCP 会话中自主完成“材料参数→五工具→evidence→逐章节草稿→DOCX→渲染→暂存”，并验证缺失数据时会省略章节或请求用户，而不是直接调用 fixture。真实 PaddleOCR 服务联调仍作为环境验收项保留。

### Phase 4 · MVP 7：Deep Agent 自主报告链路与缺失数据行为（2026-09-10）

状态：**已完成；Phase 4 代码级退出条件满足**。

本增量完成：

- 新增完整 Deep Agent 集成测试。模型不是绕过 Harness 直接调用 service，而是通过 Skill 授权后的正式工具依次执行 `list_workspace_files`、五个 Data MCP 工具、草稿创建、三次章节 upsert、草稿验证、Word 创建、渲染、页图查看、结构校验和暂存。
- 五个 MCP 调用顺序锁定为 `extract_project_profile → query_track_labels → match_listed_peers → query_comparable_valuation → match_investors`；测试确认每次调用均生成独立 evidence，最终报告 9 个事实单元全部引用对应 evidence locator。
- 新增 `inspect_report_page` 多模态工具，只允许读取 `/workspace/working/renders/<report>/page-N.png`，拒绝 input、output 或宿主任意图片路径。Skill 明确要求查看 `render_word_report` 返回的每一页。
- render receipt 增加 `inspected_pages`。`stage_report` 除检查当前 DOCX 哈希、结构和调用方视觉结论外，还会校验当前渲染的全部页面均实际经过 `inspect_report_page`；少看任意一页均拒绝暂存。
- 增加关键输入不足分支：任务空间没有材料且用户未提供企业全称、交易标的时，Agent 返回具体补充问题，不发起 Data MCP 调用，也不产生伪 evidence。
- 增加 `empty` 降级分支：五个工具仍完整调用，但 `query_comparable_valuation` 返回 `empty` 时，Agent 构建的草稿和 DOCX 均省略“对标与估值参考”及其示例内容，不用模板要求倒逼模型补数。
- `build_investment_report_tools` 增加可选 `WordReportService` 注入点，用于在确定性 Agent 集成测试中替换渲染器；生产默认仍构建真实 LibreOffice service，不引入第二套 Word 实现。

真实 Docker 复验：

- 正式镜像重新构建为 `sha256:a229e1e6b7cd70cab7b1ebfa13ba854c8f9e8104753463dfcfbeae57acbbd9c9`，用户为 `report-agent`。
- 在只读容器根文件系统中重新生成完整匿名报告，渲染三页、逐页登记 inspection receipt 后成功暂存；output 与 staging SHA-256 一致。
- 已重新检查三页 PNG，标题、正文、五/六列表和跨页投资人表均无乱码、截断、重叠或分页回归；三页尺寸与 SHA-256 继续完全匹配 MVP 6 golden。

验证结果：新增三条 Agent 行为测试全部通过，覆盖完整成功链路、关键输入追问和 MCP `empty` 章节省略。Report Agent 全量测试 `123 passed, 5 skipped`；Ruff、mypy、`uv lock --check` 和 `git diff --check` 全部通过。五个跳过项仍分别要求常驻 Data MCP、专用 MySQL schema、宿主 LibreOffice、固定 golden runtime 和宿主 Linux Bubblewrap；本轮 Docker smoke 已覆盖真实 LibreOffice、固定 golden runtime 和容器文件系统路径。

Phase 4 退出判断：Agent 已能在 mock MCP 环境中自主调用正式工具完成完整 DOCX，所有报告事实可定位到 evidence，缺失数据不会被模板或模型推断补齐，Word 结构、批注、渲染、逐页查看、视觉 golden 和暂存门禁均有验证。真实 PaddleOCR 和 test Data MCP 业务响应受外部服务状态影响，作为 Phase 5 端到端环境验收项继续执行，不再阻塞 Phase 4 代码完成。

### Phase 5 · MVP 1：同步开发者调试 API 与页面（2026-09-10）

状态：**代码完成并通过本地自动化验证；真实模型与 Data MCP 联调待环境验收**。

本增量完成：

- 新增项目自有 `SynchronousRunService`，单次请求创建独立 `task_id/session_id/run_id` 与 task workspace，将上传材料通过可信入口导入 `/workspace/input`，再调用正式 Deep Agent 执行器。
- 新增 `ConfiguredAgentExecutor`，按现有配置组装 OpenAI-compatible 模型、Bubblewrap backend、Data MCP gateway、Investment Report Skill、完整工具集、预算、工具输出卸载、主动压缩与硬停止中间件；API 不建立第二套 Agent 流程。
- 新增 `POST /api/dev/runs` 同步 multipart 接口和 `/dev` 无构建开发者页面，支持文字输入、多文件上传、Agent 最终文字、工具/MCP 输入输出轨迹及 Word 下载展示，不引入 SSE 或复杂前端状态机。
- 工具轨迹从同一 Agent 消息链提取，并按敏感字段名递归脱敏、按配置截断；不修改生产 `WorkspaceAuditLog` 的最小披露策略。
- 新增受控 DOCX 下载接口，只接受合法 task id、文件名及 `/workspace/staging` 内文件；未经过 Word 校验与暂存门禁的 output 文件不能下载。
- 三环境配置增加 `dev_ui_enabled/max_upload_mb/dev_trace_max_chars`。仅 test 默认开放调试页面，UAT/prod 默认返回 404。
- runtime 镜像纳入 API 所需 contracts 和环境配置，并暴露 8000 端口；新增 `report-agent-api` 命令。

验证结果：新增 RunService/API 测试覆盖上传文件名净化、总量限制入口、轨迹关联、敏感参数脱敏、Agent 文本、暂存 Word 下载和非 test 环境关闭行为。Report Agent 全量测试为 `127 passed, 5 skipped`；Ruff、mypy、`uv lock --check` 和 `git diff --check` 全部通过。mypy 首轮发现的 trace 可空类型和 `SecretStr` 参数类型已修正并复验通过。

容器验证：首次读取 `ghcr.io/astral-sh/uv:0.7.20` manifest 时遇到一次 TLS handshake timeout，重试后成功构建 `bjs-report-agent-runtime:0.3.0`，镜像摘要为 `sha256:15b2314dfd1301db61e1d0e9362d356a23327db19f268b74a544a0b3db8de830`。以 test 配置启动容器后，`GET /health` 返回 `ok`，`GET /dev` 返回 HTTP 200 且包含调试台页面标题；smoke 容器随后已停止并自动删除。本轮未触发会消耗模型配额或依赖真实 Data MCP 业务数据的报告生成请求。

MVP 1 当时边界：该增量只提供已暂存 DOCX 的同进程本地下载，没有伪装为 MinIO 发布；此临时边界已由紧随其后的 MVP 2 替换，当前主路径只返回 MinIO artifact。

### Phase 5 · MVP 2：MinIO Artifact Service 与预签名下载（2026-09-10）

状态：**已完成并通过真实 test MinIO 验证**。

本增量完成：

- 新增领域对象 `PublishedArtifact`，固定返回 `artifact_id/filename/sha256/size/bucket/object_key/download_url/expires_at`，不向调用方暴露服务端本地路径或存储凭据。
- 新增项目自有 `MinioArtifactService`。对象键按 `object_prefix/task_id/artifact_id/filename` 隔离，只允许发布 task workspace staging 根目录中已登记的 DOCX，output 或任意宿主路径均被拒绝。
- `publish_report` 从临时本地登记端口替换为真实 MinIO 上传端口；服务侧读取 MinIO 环境引用并持有凭据，模型和 Bubblewrap sandbox 只看到发布工具及返回的 artifact 元数据。
- 同一 Agent run 内按已暂存文件 SHA-256 幂等复用发布结果，避免模型重试造成重复对象；跨 worker/跨进程幂等将在任务持久化增量中通过 artifact repository 完成。
- 同步 RunService 不再扫描 staging 拼接本地下载路由，只返回 Agent 真实调用 `publish_report` 后产生的 artifact；没有完成发布的任务不能被标记为 completed。
- 开发者页面直接消费预签名 URL，并展示 artifact id、SHA-256、文件大小和链接过期时间；上一增量的本地文件下载接口已移除，不保留并行交付路径。

验证结果：mock MinIO 单测覆盖对象内容、content type、对象键、预签名有效期、SHA-256、重复发布幂等和拒绝未暂存文件；RunService/API 测试已切换为正式 artifact 响应契约。使用 test 环境真实 MinIO 完成一次唯一 smoke 对象上传、stat 校验和预签名 URL 生成，验证结束后精确删除该 smoke 对象，测试结果 `1 passed`。Report Agent 全量回归为 `133 passed, 6 skipped`，Ruff、mypy、`uv lock --check` 和 `git diff --check` 全部通过。

Docker 复验：包含 MinIO SDK 的 `bjs-report-agent-runtime:0.3.0` 已重建，镜像摘要为 `sha256:cfd85ea4a376208bd9fb88273c94ea90c50607d48651f2b2dd6a4aa487c60398`；容器 `/health` 返回 `ok`，`/dev` 返回 HTTP 200，页面包含 artifact 元数据展示，smoke 容器随后已停止并自动删除。

下一增量：实现持久化 task/session/run/artifact 元数据及查询 API，使同步执行结果在服务重启后仍可查询，并为后续 worker、重试、人工 interrupt/resume 和 SSE 提供唯一状态源。

### Phase 5 · MVP 3：MySQL 任务元数据与恢复查询 API（2026-09-10）

状态：**已完成并通过真实 test MySQL 重建查询验证**。

本增量完成：

- 新增 `StoredTask/StoredRun` 领域读模型与 `RunRepository` application port，持久化边界不依赖 FastAPI、PyMySQL 或 LangGraph 实现。
- 新增 MySQL repository，原子创建 task/session/run，执行结束后保存状态、Agent 最终文本、脱敏工具轨迹与 Artifact 索引；执行器抛出异常时记录 `failed + error_type`，不保存异常正文或凭据。
- 新增四张项目专用表的显式 migration：`report_agent_tasks`、`report_agent_sessions`、`report_agent_runs`、`report_agent_artifacts`。API 启动不执行 DDL，部署者必须通过 `report-agent-db-migrate --apply` 明确应用迁移。
- 同步 RunService 已将 repository 设为必需依赖。生产入口注入 MySQL repository，测试注入 in-memory 实现；两者遵循同一 port，不存在 SQLite 或第二套生产状态路径。
- 新增 `GET /api/tasks/{task_id}`、`GET /api/runs/{run_id}`、`GET /api/artifacts/{artifact_id}`。Run 详情包含保存后的工具轨迹和 Artifact；Artifact 及 Run 查询通过服务侧 MinIO adapter 重新签发 URL，避免恢复查询返回过期链接。
- 保持当前一请求一 task/session/run 的同步 MVP 语义；表结构和标识已经分离，为后续同 task 多 session、多 run、interrupt/resume 和 worker 接管保留稳定主键，不用重构当前 API 响应。

真实 MySQL 验证：先只读检查确认 test 数据库不存在 `report_agent_%` 表，再执行仅含四条 `CREATE TABLE IF NOT EXISTS` 的 migration。随后写入唯一 task/session/run/artifact 测试记录，销毁并重建 repository 实例后成功查询完整状态、轨迹和 Artifact；最后按 artifact→run→session→task 外键顺序精确删除测试记录。四张专用空表作为已应用 schema 保留，未读取或修改其他业务表。

回归与容器验证：Report Agent 全量测试 `135 passed, 7 skipped`，另行启用真实 MySQL metadata 测试为 `1 passed`；Ruff、mypy、`uv lock --check` 与 `git diff --check` 全部通过。runtime Dockerfile 不再单独依赖根和 Data MCP README 的 COPY，Report Agent README 仍随整个 package 目录进入镜像。重建 `bjs-report-agent-runtime:0.3.0` 成功，镜像摘要为 `sha256:a34bd514f6c31299ee58fe90f5c633e47adcc781e56e572a433593a3b0422833`；容器 `/health` 返回 HTTP 200，查询不存在 run 返回 HTTP 404，随后已停止并删除 smoke 容器。

下一增量：实现 Redis 队列和 worker，将同步 RunService 的执行部分拆成可恢复 job，同时保留当前 repository 为唯一状态源；先实现提交、领取、完成和失败，再增加取消、重试与并发限制。

本地宿主机联调补充：新增 `deploy/environments/test/report-agent.local.yaml`，允许 Windows 宿主机使用本地仓库路径，并将 Data MCP 地址改为 `http://127.0.0.1:8001/mcp`；Docker test 配置继续使用容器地址 `http://data-mcp:8001/mcp`。两套配置共用同一份运行环境变量和 Agent 代码路径。

### Phase 5 · MVP 1.1：工具失败信封与参数自修复循环（2026-09-10）

状态：**已完成并通过自动化验证**。

本增量针对真实 DOCX 联调中 `extract_project_profile` 被错误传入 `project_profile` 后 Agent 直接复述校验错误的问题，补齐 Harness 的失败恢复语义：

- 新增 `ToolFailureEnvelopeMiddleware`，把工具执行异常转换为有界、结构化的错误 ToolMessage，字段包含 `status/tool/retryable/error_type/error/next_action`；未知内部异常不向模型暴露原始细节。
- 新增 `ToolArgumentRecoveryMiddleware`。当最近一次工具结果为可恢复失败时，将当前工具的 `allowed_schema` 注入失败信封；如果模型试图不发起修正调用便结束，Harness 在配置预算内再次要求其修改参数，禁止原参数重复和向用户暴露内部校验文本。
- `harness.tool_argument_repair_attempts` 成为三环境显式配置，当前为 2；每次额外模型尝试仍经过现有模型调用预算，不绕过 `max_model_calls`。
- 强化 Investment Report Skill 的五工具数据流：`file_info/material_url → extract_project_profile.data.profile → project_profile → tags/track_tags`，明确画像工具禁止接收 `project_profile/material_id/本地路径`。
- 强化 `extract_project_profile` 合同字段描述，使模型在 tool schema 层直接看到 `file_info` 和 `material_url` 的来源与禁止项。
- RunService 不再把未恢复的工具错误归类为普通 `needs_input`；如果同名工具后续成功则视为已恢复，否则返回 `failed`。

验证结果：新增确定性 Deep Agent 集成测试，模拟“错误参数 → 模型企图直接结束 → Harness 强制修正 → 正确参数重调 → 工具成功”，确认失败与成功 ToolMessage 均留在同一消息链；新增 RunService 未恢复失败状态测试。Report Agent 全量回归为 `131 passed, 5 skipped`，Ruff、mypy、`uv lock --check` 和 `git diff --check` 全部通过。

边界说明：该循环处理的是需要模型改变行为或参数的语义恢复。网络超时、限流、5xx 等“原参数重试”应在下一增量组合 LangChain `ToolRetryMiddleware`，采用退避和幂等控制；两类重试不得混为一套无限循环。
