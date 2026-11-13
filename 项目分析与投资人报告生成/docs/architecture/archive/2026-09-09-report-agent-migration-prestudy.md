# Report Agent 现状梳理与主分支迁移预研

> 调研日期：2026-09-09
> 调研对象：`origin/feature/report-agent`（`ae251392ee58d3f4f727a643e876ad7b8be31e3a`）与当前 `main` 上已标准化的 Data MCP 契约
> 本文目的：记录 Agent 的真实运行链路、工程现状、与新版 Data MCP 的差异，以及后续迁移改造边界。本文不实施 Agent 代码合并。

## 1. 结论摘要

当前 Agent 已具备“材料上传与解析 → Agent 调用工具 → Data MCP 取数 → 生成 DOCX → 添加来源批注”的原型闭环，所选 Agent 框架方向也不落后：使用 LangChain v1 的 `create_agent` 和 LangGraph checkpointer，符合当前官方推荐入口。问题主要不在框架选型，而在框架外围的工程实现与业务契约：会话状态、Skill 激活、工具治理、Data MCP 契约、报告模板、证据链和测试体系尚未形成一致、可靠的生产链路。

不建议把 `feature/report-agent` 原目录直接复制到 `main`。推荐按主分支现有 `uv workspace + src layout + contracts` 标准迁移，并优先修复以下 P0：

1. `api/agents/routes.py` 使用未定义的 `self._make_context_logger(...)`，启用 Skill 的后端请求会在构建 Agent 时直接报 `NameError`。
2. FastAPI 每次请求都新建 Agent 和 `MemorySaver`，相同 `thread_id` 也无法跨请求续接；Skill 规定的“先向用户确认、下一轮继续”在 API 路径上不成立。
3. Skill 流程与新版 Data MCP 契约冲突：旧流程先调用 `query_track_labels`，新版契约却要求先有 `project_profile`；旧 Agent 没有提供该必填参数。
4. 旧 `mcp_mapping.py` 不兼容主分支统一响应外壳，且主动丢弃 `sources`、`warnings`、`evidence`、`conflicts` 等关键字段；`industry_pe=float(len(choice))` 更是无业务含义的伪数据，必须删除。
5. Skill 的动态加载实际不会重建 Agent system prompt，`allowed-tools` 只解析、不执行，导致“加载了 Skill”与“遵守 Skill/工具白名单”并不等价。
6. `write_report` 没有传入随 Skill 保存的 `report_template_source.docx`，实际生成的是通用新文档，不是按业务 Word 模板写作。

## 2. 当前目录与职责分布

Agent 分支约有 83 个 `apps/report_agent` 文件，核心代码现状如下：

```text
apps/report_agent/
├─ README.md
└─ src/
   ├─ api/
   │  ├─ app.py                 # FastAPI 组装与依赖初始化
   │  ├─ agents/
   │  │  ├─ routes.py          # Agent HTTP 入口与每请求组装
   │  │  ├─ tools.py           # 840 行：全部工具及大量领域逻辑
   │  │  ├─ mcp_mapping.py     # 旧 Data MCP 名称/入参/出参翻译
   │  │  └─ downloader.py      # 远程文件下载
   │  ├─ tasks/                # 上传任务与状态
   │  ├─ parsers/              # 解析调度 API
   │  ├─ reports/              # DOCX schema、渲染、批注、下载
   │  ├─ history/              # 会话历史文件存储
   │  ├─ llm/                  # 一套自定义 OpenAI 客户端
   │  └─ gradio_app.py         # 1410 行 UI + 编排 + 状态修复
   ├─ harness/
   │  ├─ active/               # Agent、LLM、Skill registry、限流
   │  └─ scripts/              # 自定义上下文裁剪与日志
   ├─ parsers/                 # PDF/Word/XLSX 解析实现
   ├─ skills/                  # Skill、引用文件、Word 模板（位置不合理）
   ├─ workspace/               # 文件系统存储
   ├─ delivery/                # 空目录
   ├─ mcp/                     # 空目录
   ├─ skill_runtime/           # 空目录
   └─ tool_runtime/            # 空目录
```

最大的结构问题是“目录名存在，但职责没有落进去”：`skill_runtime`、`tool_runtime`、`mcp`、`delivery` 只是占位；真实逻辑分别堆在 `harness/active`、`harness/scripts`、`api/agents/tools.py` 和 `api/agents/mcp_mapping.py`。同时，Skill 作为可配置业务资产被放入 Python `src` 包内，UI 又直接访问 Agent 私有字段和存储私有字段，边界十分模糊。

## 3. 当前核心运行流程

### 3.1 材料进入与解析

1. `POST /api/v1/tasks` 校验文件扩展名、MIME 和大小，将文件保存到 `workspace/{task_id}/uploads`，并写任务元数据。
2. `ParseRunner` 通过 daemon thread 异步处理上传目录中的文件。
3. PDF：PyMuPDF 分页渲染，再逐页调用多模态模型识别和分类；Word：读取段落与表格；XLSX：按 Sheet 转 Markdown。
4. 解析结果写入 `workspace/{task_id}/parsed`，并派生材料 Markdown，供 Agent 分块阅读或上传 MinIO 后交给 Data MCP。

这里存在两个入口不一致的问题：默认模块级 `app = create_app()` 创建的是空 `ParserRegistry`，不会注册 PDF/Word/XLSX pipeline；只有 Gradio 自建 `TestClient` 时显式注册。因此直接运行 FastAPI 模块时，上传任务可能被标记完成但实际没有处理任何文件。解析任务也只存在于进程内线程，进程重启后会被标记失败，不具备持久队列、重试和取消能力。

### 3.2 Agent 构建与会话

1. `POST /api/v1/agents/run` 确定 `task_id` 和 Skill 名称，按需下载 `file_urls`。
2. 路由把 `task_id` 拼进一段标记为 `[系统通知]` 的普通用户消息。
3. 有 Skill 时，每个 HTTP 请求重新创建 `AgentTools`、工具列表、Agent graph 和 `MemorySaver`；无 Skill 时使用注入的通用 Agent。
4. `Agent.run()` 以 `thread_id=task_id` 调用 LangChain `create_agent` 生成的 graph。

LangChain `create_agent` 是当前 v1 标准入口，并原生支持 middleware、runtime context、结构化输出和动态工具，因此无需更换 Agent 框架（[LangChain Agents](https://docs.langchain.com/oss/python/langchain/agents)、[LangChain v1 release](https://docs.langchain.com/oss/python/releases/langchain-v1)）。需要改的是使用方式：`task_id`、workspace、依赖客户端应进入 runtime context，而不是伪装成用户消息；checkpointer 应由应用生命周期统一持有。官方也明确把内存 checkpointer定位于开发场景，生产应使用数据库支持的 checkpointer（[Short-term memory](https://docs.langchain.com/oss/python/langchain/short-term-memory)）。

当前 Gradio 为绕过 API 无法续接的问题，额外维护 `_AGENT_CACHE[(task_id, skill)]`，还直接操作 Agent graph 私有状态以修复孤立 tool call。结果是 Gradio 与正式 API 有两套不同会话语义，API 测试不能代表 UI，UI 成功也不能证明 API 可用。

### 3.3 Skill 加载与执行

`SkillRegistry` 可读取 `SKILL.md` frontmatter、正文和 references；`investment_report` Skill 描述了确认节点、五类 Data MCP 调用、报告章节、表格及批注规范。

但运行实现存在三处断层：

- `SkillActivationMiddleware` 不是 LangChain middleware，只在 Agent 初始化时拼一次 system prompt。之后调用 `load_skill` 只修改集合，不重建 prompt。
- `load_skill` 工具只返回 `body_length` 等元信息，不把 Skill 正文返回给模型。因此默认模式下模型调用“加载 Skill”后仍看不到写作规则。
- frontmatter 的 `allowed-tools` 只保存于对象中，没有参与工具过滤、授权或调用拦截。

这意味着当前可靠的唯一方式是请求一开始就指定 Skill；所谓运行中发现并加载 Skill 的能力并未真正完成。后续应使用正式 middleware 在 `before_model` 动态注入有效 Skill 上下文，或更简单地在进入任务时一次性解析 Skill 并构建受限工具集。工具权限必须以代码执行为准，不能只依赖提示词。

### 3.4 Data MCP 调用链

旧链路如下：

```text
investment_report Skill
  → mcp_invoke(capability, params)
  → api/agents/mcp_mapping.py 二次改名和改字段
  → deps.py 修改 sys.path
  → import src.mcp.client.DataMcpClient
  → DATA_MCP_ROOT/run.py --stdio
  → 旧 Data MCP 工具
```

该链路无法直接接入当前主分支：新版 Data MCP 已是 `data_mcp` 可安装包，通过 `data-mcp` / `python -m data_mcp` 启动，客户端路径为 `data_mcp.mcp.client`，且统一使用 `schema_version/tool/status/summary/data/sources/warnings` 响应外壳。Agent 不应继续用 `sys.path` 注入和私有源码导入连接另一个应用。

更重要的是业务语义发生了变化：

| 环节 | 旧 Agent 假设 | 主分支 Data MCP 契约 | 影响 |
|---|---|---|---|
| 赛道标签 | 只传 `company_name`，并且第一个调用 | 必须传 `company_name + project_profile` | 当前调用会校验失败；流程顺序必须调整 |
| 项目画像 | 映射成 `{name,type,sector,description}` | `data.profile` 固定字段，并提供 `field_details/conflicts` | 旧映射丢失证据和冲突信息 |
| 历史估值 | 期待 `choice[0].content` 或 `financials` | 读取 `data.content`，并声明为外部 Agent 生成、未核验内容 | Skill 取值路径错误，可信度表述也错误 |
| 上市可比 | 主动删除 `evidence/missing_fields/field_scores` | 要求结合这些字段复核排序和置信度 | 旧映射破坏报告溯源能力 |
| 投资人匹配 | 使用 `merged`，把文件 URL 当画像传递 | 需要真实 `project_profile + track_tags`；结果在 `data.candidates` | 参数与响应均不兼容 |
| 错误与降级 | 自定义摘要或吞掉异常 | 依据 `status/warnings/sources` 决定降级 | 当前可能把 partial/empty 误当成功 |

建议删除 capability 二次语义层，Agent 直接以五个正式 MCP tool 名及其 JSON Schema 工作。如果需要隐藏传输细节，只保留一个薄的 `DataMcpGateway`，职责限定为生命周期、超时、重试、契约验证和审计，不得改写业务数据。

推荐业务顺序：

```text
读材料并确认公司信息
  → extract_project_profile
  → query_track_labels(company_name, project_profile)
  → [query_comparable_valuation || match_listed_peers]
  → match_investors(company_name, track_tags, project_profile)
  → 证据归一化与缺口检查
  → 按写作 Skill 和 Word 模板生成报告
```

### 3.5 报告生成与来源批注

`write_report` 接收结构化 `ReportContent`，调用 renderer 输出 DOCX；`update_report` 支持按标题更新章节；`annotate_report_sources` 通过 OOXML 添加 Word 批注。这一思路总体合理，但模板链路没有打通：`investment_report/references/report_template_source.docx` 虽然存在，`write_report` 调用 `render_report(out_path, content)` 时没有传 `template_path`，所以业务模板从未被使用。

现有证据模型也不足：MCP 完整结果只放在当前 `AgentTools._mcp_results` 内存字典，新的 HTTP 请求或进程重启即丢失；来源批注依赖模型自行计算段落索引和锚点，文档更新后容易错位。正确做法是先把每次工具输入、完整响应、契约版本、调用时间和来源写入任务级 evidence ledger，再让报告字段引用稳定的 `evidence_id`，最终由确定性渲染器生成批注。

Word 交付还缺少结构和视觉验收：应检查 OOXML 关系、批注关系、标题层级、表格数量、模板样式继承、链接有效性，并至少用 LibreOffice/Word 兼容链路渲染 PDF/图片进行页面检查。

## 4. 工程化评估

### 4.1 Python 包与依赖管理

Agent 分支没有自己的 `pyproject.toml`、lock、正式依赖组、ruff/mypy/pytest 配置；README 仍包含开发者本机绝对路径和 Conda 启动方式。测试位于被 `.gitignore` 排除的 `LDZ_TEMP/test/api`，依赖声明也不完整，不能构成可重复 CI。

主分支已采用根级 `uv workspace` 和 Data MCP 的 Hatchling `src layout`。Agent 应新增 `apps/report_agent/pyproject.toml` 并加入 workspace members，至少分出 runtime、test、lint 依赖组，锁定 Python 范围和 LangChain/LangGraph 主版本，提供 console script。禁止复用 Data MCP 的 requirements 或依赖其源码路径。

### 4.2 分层与依赖方向

当前 `api/agents/tools.py` 同时负责 HTTP 适配、文件读取、解析调度、Skill 生命周期、MCP 调用、MinIO、报告写入和批注，属于典型“大工具模块”。`gradio_app.py` 又复制编排并越过公开接口访问 `_graph`、`_context_manager`、`_ws`、`_parsed_dir` 等私有成员。

建议目标结构：

```text
apps/report_agent/
├─ pyproject.toml
├─ src/report_agent/
│  ├─ entrypoints/             # API、worker、可选 demo UI
│  ├─ application/
│  │  ├─ workflows/            # 投资报告阶段编排与确认状态机
│  │  └─ ports/                # MCP、存储、解析、LLM、渲染接口
│  ├─ agent_runtime/
│  │  ├─ factory.py            # create_agent 与 middleware 组装
│  │  ├─ context.py            # task/session runtime context
│  │  ├─ middleware.py         # Skill、限次、重试、日志
│  │  └─ checkpoints.py        # 持久化会话
│  ├─ skill_runtime/           # Skill 发现、解析、校验、工具授权
│  ├─ tool_runtime/
│  │  ├─ materials.py
│  │  ├─ data_mcp.py
│  │  └─ reports.py
│  ├─ infrastructure/
│  │  ├─ data_mcp/             # 标准 MCP transport/gateway
│  │  ├─ persistence/          # workspace/evidence/checkpoints
│  │  ├─ parsers/
│  │  └─ word/
│  └─ domain/                  # Report、Evidence、Task 状态模型
├─ skills/                     # 可版本化业务资产，不塞进 Python 包源码
│  ├─ investment_report/
│  └─ word_operations/
└─ tests/
   ├─ unit/
   ├─ contract/
   ├─ integration/
   └─ golden/
```

依赖方向应为 `entrypoints → application → domain/ports`，基础设施实现 ports；API 和 UI 都只能调用 application service，不得直接操纵 Agent graph 或 workspace 私有目录。Data MCP 与 Report Agent 只共享 `contracts/`，不互相导入业务源码。

### 4.3 上下文与运行治理

自定义 `AtomicSafeContextManager`（约 460 行）和 context logger 反映了长工具结果、孤立 tool call 和 400 错误等真实问题，但当前默认关闭，Gradio 又另写补丁修 graph state，说明机制没有收敛。LangChain 当前已有 summarization、context editing、tool/model call limit、retry 等 middleware（[Built-in middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in)）。迁移时应优先组合标准 middleware，并为“AI tool call 与 ToolMessage 必须成对”增加回归测试；只有标准能力无法满足的原子性要求才保留最小自定义实现。

当前 `max_iterations=100` 只是放宽递归上限，不能替代成本和失控保护。建议按阶段设置 model/tool call limits、超时、重试预算和幂等键，并把需要用户确认的步骤建模为显式 workflow state，而不是希望模型在下一次内存对话里自行续接。

## 5. 已发现问题清单

| 优先级 | 问题 | 位置 | 后果 | 建议 |
|---|---|---|---|---|
| P0 | 未定义 `self` | `api/agents/routes.py` | Skill API 构建即失败 | 改为公开 factory，并加 API smoke test |
| P0 | 每请求新建 checkpointer | routes / harness | 无法跨轮确认与恢复 | 应用级持久 checkpointer，session 与 task 分离 |
| P0 | Skill 与新版 MCP 顺序/参数冲突 | `skills/investment_report/SKILL.md` | `query_track_labels` 必填校验失败 | 画像先行，严格使用主分支 contracts |
| P0 | MCP 映射制造/丢失数据 | `mcp_mapping.py` | 估值伪值、证据和冲突消失 | 删除语义映射，保留统一外壳原始数据 |
| P0 | Skill 动态加载和工具白名单未执行 | `skill_middleware.py`, `tools.py` | 模型未获规则，工具越权风险 | 真 middleware + 执行期工具过滤 |
| P0 | 模板文件未参与渲染 | report tools / renderer | 输出不符合正式模板 | 模板纳入 Skill artifact 与确定性渲染流程 |
| P1 | 默认 FastAPI parser registry 为空 | `api/app.py` | 正式 API 不解析材料 | 统一 bootstrap 注册，启动时自检 |
| P1 | MCP 结果只存内存 | `AgentTools._mcp_results` | 重启/跨请求丢证据 | 持久 evidence ledger |
| P1 | UI 自建 Agent、修私有 graph state | `gradio_app.py` | API/UI 行为分裂 | UI 只调公开 application API |
| P1 | “系统通知”放进用户消息 | routes | 易被覆盖且污染历史 | typed runtime context / AgentState |
| P1 | 解析只用 daemon thread | parser runner | 无持久重试与可观测性 | worker/队列或可恢复任务执行器 |
| P1 | 下载 SSRF 仍有重定向/DNS 重绑定窗口 | downloader | 远程 URL 安全风险 | 禁止/逐跳校验重定向，连接 IP 校验，域名 allowlist |
| P1 | task_id 未集中校验 | workspace storage | 潜在目录穿越和跨任务读取 | UUID/slug 类型校验 + resolve 后根目录约束 |
| P1 | 来源批注靠段落索引 | report comments | 更新章节后批注错位 | evidence id + bookmark/content control |
| P2 | `tools.py`、`gradio_app.py` 超大 | 多处 | 难测试、难替换 | 按领域 adapter 拆分 |
| P2 | 两套 LLM 抽象 | `api/llm` 与 `harness/active/llm.py` | 配置和重试行为不一致 | 一个 port，多 adapter，统一配置 |
| P2 | 模块导入即创建 app/workspace | `api/app.py` | 测试副作用、配置时序混乱 | 显式 app factory / lifespan |
| P2 | `ask_user` 协议为死代码 | AgentResult / schema | API 声称可等待但不会产生状态 | 由 workflow interrupt 实现或删除字段 |
| P2 | Skill 内存在重复、互相矛盾规范 | `investment_report/SKILL.md` | 模型执行不稳定 | 拆工作流、写作、模板和验收规则，自动 lint |
| P2 | 测试与依赖在 `LDZ_TEMP` | 临时目录 | CI 不可复现 | 迁入正式 tests 并纳入 uv lock |

说明：下载器已有 scheme、私网 IP、文件大小与类型检查，基础方向正确；但 HEAD 与 GET 使用两个连接，且没有把最终连接地址/每次跳转重新做同等校验，因此不应认定为完整 SSRF 防护。

## 6. 建议迁移批次

### 批次 A：建立可安装骨架和边界

- 创建 `apps/report_agent/pyproject.toml`，加入根 `uv workspace`。
- 将代码迁到 `src/report_agent`，消除 `api`、`src` 等易冲突顶层导入。
- 把 Skill 移到 `apps/report_agent/skills`，建立 Skill schema/lint。
- 先迁 domain model、ports 和配置，不接业务流程。

验收：全新环境 `uv sync` 后可 import、启动 health；ruff、mypy、pytest 可从仓库根统一执行。

### 批次 B：打通标准 Data MCP 网关

- 按主分支 MCP 启动方式实现 transport，不修改 `sys.path`。
- 直接暴露五个正式工具 schema，删除 `mcp_mapping.py`。
- 对统一响应外壳做 schema 校验并持久化完整结果。
- 完成五工具 contract test，覆盖 success/partial/empty/failed。

验收：Agent 侧不导入 `apps/data_mcp` 源码；契约版本不兼容时明确失败；证据字段不被截断或改写。

### 批次 C：重建 Agent、Skill 和可恢复工作流

- 应用级 Agent factory/checkpointer；区分 `task_id`、`session_id`、`run_id`。
- 以 runtime context 注入 workspace 和服务依赖。
- 实现 Skill 动态上下文与 allowed-tools 强制过滤。
- 把“读取材料—元信息确认—取数—写作—验收”建成显式状态机，确认节点可跨请求恢复。
- 引入标准 middleware 的限次、重试、摘要和 context editing，减少私有 graph 修补。

验收：API 两轮确认测试通过；进程重启后可恢复；未授权工具不可见且不可调用；相同幂等键不重复生成报告。

### 批次 D：报告模板、证据链和 Word QA

- 以正式 DOCX 模板作为渲染输入，定义模板版本与占位结构。
- 建立 evidence ledger，报告字段和批注引用 `evidence_id`。
- 对 Data MCP 的 `status/sources/warnings/conflicts/evidence` 建立确定性降级规则。
- 增加 DOCX 结构、批注、标题、表格、链接及渲染截图的 golden tests。

验收：报告内容、模板和数据均可追溯版本；任意数字能定位到材料块或 MCP evidence；Word/LibreOffice 打开无修复提示，关键页面视觉检查通过。

### 批次 E：API/UI 收口与运行治理

- Gradio 仅作为 API 客户端，删除 `TestClient`、Agent cache 和私有状态修复。
- 解析进入可恢复 worker；增加超时、取消、重试和健康检查。
- 对下载、task path、日志脱敏和租户隔离做安全测试。
- 增加端到端测试：上传真实 fixture → 解析 → 模拟 MCP → 两轮确认 → DOCX 验证。

验收：API 与 UI 共享同一状态和编排；服务重启不丢任务证据；CI 能无外部真实凭证完成确定性回归。

## 7. 合并时的边界原则

1. Data MCP 负责外部数据检索、项目画像、赛道、估值、上市可比与投资人候选；Agent 负责用户材料解析、流程确认、写作和 Word 交付。
2. 两个应用共享契约和测试 fixture，不共享内部 Python 模块，不通过 `sys.path` 拼接源码。
3. Skill 是业务流程与写作规范，不承担传输适配、伪造缺省数据或修补接口不兼容。
4. Agent 输出不得把外部 Agent 生成文本当成已核验事实；`partial/empty/failed` 必须在工作流和报告中显式降级。
5. 原始材料、MCP 完整响应、写作中间态和最终报告分别持久化；聊天上下文不是事实数据库。
6. 先让后端 API 在无 Gradio 条件下通过端到端测试，再接 UI；不能继续以 UI 缓存掩盖后端状态缺失。

## 8. 迁移前建议补充的决策

进入代码合并前，需要在实现方案中明确但不必阻塞本次预研的事项：生产 checkpointer/任务队列采用何种持久化组件；正式 Word 模板是否允许调整占位符；Skill 是否需要热更新与版本回滚；用户材料和 MCP 证据的保留周期；单任务并发、模型调用预算和超时上限。这些选择会影响基础设施实现，但不改变上述分层和 P0 修复结论。
