# BJS Report Agent

Report Agent 是材料理解、Agent 编排和 Word 交付服务。它把上传材料和 Data MCP 响应统一保存为 Evidence，模型按 `investment-report` Skill 完整读取事实、写作并添加来源批注，确定性代码负责校验和发布。

## 当前调用主链

```text
POST /api/dev/runs
  -> SynchronousRunService
     -> 创建 task_id/session_id/run_id/workspace_id
     -> 保存上传文件并创建 MySQL 元数据
  -> ConfiguredAgentExecutor
     -> 加载模型、workspace backend、Data MCP gateway、Skill、预算和 middleware
     -> Data MCP readiness：五个工具必须可发现
     -> build_investment_report_tools + ToolPolicy
     -> Deep Agents 单主 Agent
        1. parse_materials -> material_id + Material Evidence
        2. 完整分页读取材料
        3. 五个 Data MCP 工具 -> Data MCP Evidence
        4. 读取 Evidence，处理 partial/empty/failed
        5. write_file/edit_file/read_file 维护 report.md
        6. create_word_from_md -> ReportContent -> DOCX artifact
        7. add_report_comments -> 新 DOCX artifact 版本
        8. validate_and_publish_word -> PublishedArtifact
  -> SynchronousRunService 以真实 artifact 决定 completed/needs_input/failed
```

模型的最终文本不是交付成功依据。只有 MinIO 上传成功并返回 `PublishedArtifact`，应用层才返回 `completed` 和下载信息。

## 模型行为是怎样组装的

### 1. Harness

`harness/factory.py` 是唯一允许构建 Deep Agents 的模块。当前使用一个主 Agent，关闭框架自带 summarization、`task` 工具和通用 subagent，避免与项目自己的上下文、工具和状态治理重复。

### 2. Prompt 与 Skill

系统提示词来自 `skills/investment-report/SKILL.md`，引用文件由 `SkillCatalog` 暂存到只读 `/workspace/references`。Skill 负责：

- 五个 Data MCP 工具的逻辑顺序和失败后继续策略；
- 必须完整读取材料和外溢结果后才能写作；
- Markdown 章节、详细度、citation 和自检规则；
- 缺失数据、省略章节、零证据不交付；
- 核心事实批注范围和最终发布顺序。

代码不依赖模型自觉完成安全边界：工具选择由 `allowed-tools` + `ToolPolicy` 执行，上传、Evidence、state、memory 和 references 禁止模型写入。

### 3. Tool 分层

| 工具组 | 主要工具 | 责任 |
| --- | --- | --- |
| Context | `get_working_context`、`list_context_indexes`、结果分页/搜索 | 恢复进度、读取外溢大结果 |
| Materials | `parse_materials`、`read_material_chunk` | 解析上传文件并产生 Material Evidence |
| Data MCP | 五个契约工具 | 获取外部事实并产生 Data MCP Evidence |
| Evidence | `read_evidence`、`search_evidence` | 按需读取完整 Evidence，不靠聊天记忆写事实 |
| Word | `create_word_from_md`、`edit_word_document`、`add_report_comments`、`manage_word_comments`、`validate_and_publish_word` | Markdown 转 ReportContent/DOCX、批注、校验和发布 |

`create_report_content/upsert_report_section/...` 等结构化工具仍存在于底层工具工厂，但当前 `investment-report` Skill 未允许它们，默认主链使用 Markdown 编辑模式。

### 4. Middleware 顺序与作用

执行器按以下逻辑组合 middleware：参数修复、空 tool-call 防护、模型/工具/时间预算、失败 envelope、工具大结果外溢、上下文压缩与硬停止、workspace 状态投影、消息完整性保护、脱敏调用日志。

- 大型成功结果写入 `/workspace/logs/tool-results`，模型收到 `result_id` 后必须分页读完。
- Evidence 不依赖普通 tool result 作为事实源，完整 envelope 独立写入 `/workspace/evidence`。
- 上下文达到配置阈值时，旧消息摘要写入 `/workspace/memory/conversation-history.md`；稳定 ID 和事实仍以 workspace 索引为准。
- 预算由 `max_model_calls/max_tool_calls/run_timeout_seconds` 约束。

## 两条 Evidence 数据链

### Material Evidence

```text
上传文件 -> parse_materials -> 解析 blocks + material_id
                           -> 同一解析结果封装为 Evidence + evidence_id
```

`material_id` 只用于分块读材料；`evidence_id` 才能用于报告 citation。二者不可互换，也不能改前缀推导。

### Data MCP Evidence

```text
StructuredTool 参数
  -> 本地 input schema 校验
  -> Streamable HTTP MCP
  -> 本地 output schema 校验
  -> 完整 envelope 落盘
  -> 返回轻量 EvidenceView
  -> read_evidence/search_evidence 读取具体事实
```

轻量视图只包含 `evidence_id/tool/status/summary/warnings/json_roots` 等定位信息；拿到 ID 不等于已经读取事实。

## ReportContent 与 Word

`create_word_from_md` 读取 `/workspace/report/report.md`，解析 `<!-- cite: evidence_xxx -->`，生成并校验 `ReportContent`：标题、公司、章节、段落/列表/表格行、引用和缺失项。默认按段、列表项、表格行绑定 Evidence。

随后 `WordReportService`：

1. 用 `python-docx` 从内容创建 DOCX；
2. 用 `word-document/scripts` 增加、提取、修改、解决或移除真实 OOXML 批注；
3. 校验 ZIP、核心 OOXML parts、批注关系/锚点和 SHA-256；
4. 在开启视觉门禁时用 LibreOffice 渲染并要求逐页检查；
5. staging 后由 `MinioArtifactService` 上传并生成权威下载信息。

每次编辑或批注变更都会生成新的 artifact 版本。模型不传输出路径、MinIO 凭据、视觉通过标记或下载 URL。

## Workspace 与状态

每个 task 一个隔离 workspace，主要权威文件为：

```text
/workspace/state/run-state.json
/workspace/evidence/index.json
/workspace/report/report-content.json
/workspace/artifacts/index.json
/workspace/state/result-index.json
/workspace/memory/working.md
```

MySQL 保存 task/session/run/artifact 元数据；workspace 保存本次执行的材料、Evidence、报告和中间产物。当前每次同步 API 请求创建新的 identity 和 Agent，MySQL LangGraph checkpointer adapter 尚未接入 `ConfiguredAgentExecutor`，因此“同 session 跨 HTTP 请求续跑”目前不是已实现能力。

## API

| 接口 | 说明 |
| --- | --- |
| `GET /health` | 进程健康检查，不代表外部依赖全部可用 |
| `GET /dev` | test 且 `dev_ui_enabled=true` 的开发页 |
| `GET /m4Kp9Qx2Lv7Nc1Rd8Ws3Tf6Yb0Hz/v1/ai-service/investment` | 对外入口。页面加载后地址栏改为 `/v1/ai-service/investment`，该干净路径返回 404 |
| `POST /api/dev/runs` | 上传消息/文件/材料 URL 并同步执行完整 run（`files_` 为文件上传，`urls` 为每行一个 http/https URL，服务端下载后统一处理） |
| `GET /api/runs/{run_id}` | 查询 run，刷新 artifact 限时地址 |
| `GET /api/tasks/{task_id}` | 查询 task |
| `GET /api/artifacts/{artifact_id}` | 查询 artifact 并刷新下载地址 |
| `GET /api/dev/runs/{task_id}/logs` | 开发环境读取脱敏 Agent 日志 |

队列、取消、自动重试、正式鉴权、异步 worker 和跨请求恢复尚未进入当前主链。

## 代码导航

```text
src/report_agent/
├── api/                     # FastAPI 与开发页
├── application/             # run、材料、Evidence、报告、Word 用例
├── domain/                  # identity、workflow、ReportContent、Artifact
├── harness/                 # Agent factory、工具与 middleware
├── infrastructure/          # MCP、MySQL、MinIO、材料和 Word adapter
├── runtime/                 # TaskWorkspace 与 Bubblewrap/filesystem backend
├── settings/                # 严格、不可变的 Pydantic 配置
└── skills/                  # Skill 发现、引用暂存和工具策略
skills/investment-report/    # 当前业务 Skill
skills/word-document/        # Word 参考规则与 OOXML 脚本
```

| 修改目标 | 首要位置 | 必须联动 |
| --- | --- | --- |
| 写作顺序、详细度、缺失数据、批注覆盖 | `skills/investment-report/` | Skill 行为测试/真实材料验收 |
| Prompt 可调用工具 | `SKILL.md allowed-tools`、`skills/policy.py` | 工具工厂与权限测试 |
| MCP 字段或工具 | `contracts/mcp`、`application/data_gateway.py` | Data MCP、环境工具清单、Skill |
| 材料格式/解析 | `application/materials.py`、`infrastructure/materials/` | Material Evidence 与分页读取 |
| citation/报告结构 | `domain/report_content.py`、`application/reports.py`、`infrastructure/word/md_parser.py` | Markdown 规范、Word authoring、测试 |
| Word 版式/批注/校验 | `infrastructure/word/`、`skills/word-document/` | Artifact 版本、结构/视觉测试 |
| 上下文与大结果 | `harness/context.py`、`harness/middleware/`、`application/context_store.py` | 配置阈值和恢复测试 |
| API/run 状态 | `api/app.py`、`application/runs.py`、`domain/workflow.py` | MySQL repository 与最终答复门禁 |
| 配置字段 | `settings/models.py` | test/uat/prod YAML、本地 YAML、部署 README |

## 本地运行

```powershell
uv sync --package bjs-report-agent --group test --group lint
$env:REPORT_AGENT_CONFIG = (Resolve-Path "deploy/environments/test/report-agent.local.yaml").Path
uv run --env-file deploy/environments/test/runtime.env --package bjs-report-agent report-agent-db-migrate --apply
uv run --env-file deploy/environments/test/runtime.env --package bjs-report-agent report-agent-api
```

启动前必须保证 Data MCP、MySQL、MinIO、模型和材料识别服务可达。开发调用：

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/dev/runs `
  -F "message=请读取材料并生成投资报告" `
  -F "files_=@E:\path\project.pdf" `
  -F "urls=https://example.com/material.pdf
https://example.com/report.docx"
```

## 验证

```powershell
uv run --package bjs-report-agent report-agent-spike --workspace-root .runtime/spike
uv run --package bjs-report-agent pytest apps/report_agent/tests
uv run --package bjs-report-agent ruff check apps/report_agent/src apps/report_agent/tests
uv run --package bjs-report-agent mypy apps/report_agent/src/report_agent
```

Windows 可以验证 filesystem backend、结构逻辑和单元测试；Bubblewrap、LibreOffice 页面渲染和容器安全边界必须在目标 Linux runtime 复验。

完整设计见 [Report Agent 当前架构](../../docs/architecture/report-agent-architecture.md)，环境差异见 [部署手册](../../deploy/environments/README.md)。
