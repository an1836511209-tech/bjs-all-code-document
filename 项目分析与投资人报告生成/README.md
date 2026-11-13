# 北交所投资报告生成 Agent

本仓库包含两个可独立部署、通过契约协作的 Python 服务：

- **Data MCP**：负责事实查询、计算、候选匹配、来源和业务降级语义。
- **Report Agent**：负责材料理解、查询参数组装、模型编排、Evidence 管理、报告写作、Word 批注和产物发布。

两者只共享 [`contracts/mcp`](contracts/mcp/README.md) 中的五份 JSON Schema，不共享源码、数据库或供应商原始响应。

## 当前端到端链路

```text
用户消息/上传文件
  -> Report Agent 同步开发 API
  -> task/session/run/workspace 初始化
  -> 材料解析 -> Material Evidence
  -> investment-report Skill 激活
  -> Deep Agents 单主 Agent
     -> 依次调用五个 Data MCP 工具
     -> Data MCP 校验输入 -> feature -> 统一响应 -> 校验输出
     -> Report Agent 再次按同一契约校验 -> 完整响应保存为 Data MCP Evidence
     -> 按需读取材料/Evidence；大结果分页读取；上下文接近上限时压缩
     -> 在 workspace 中逐段编写并复核 report.md
     -> report.md -> ReportContent -> DOCX
     -> 模型根据已读原文添加真实 Word 批注
     -> OOXML 结构校验 -> staging -> MinIO
  -> 应用层仅用 PublishedArtifact 生成最终交付信息
```

当前报告内容边界是 `ReportContent`，不是旧的 `ReportDraft/FactClaim`。主写作路径是 Markdown 编辑模式：模型先维护 `/workspace/report/report.md`，`create_word_from_md` 再解析、校验证据并生成 DOCX。

## 架构边界

| 责任 | Data MCP | Report Agent |
| --- | --- | --- |
| 外部数据、计算、候选匹配 | 负责 | 只消费契约结果 |
| HTTP 200 内的业务状态 | 输出 `success/partial/empty/failed` | 必须先判断状态 |
| 用户材料解析 | 不访问 Agent workspace | 负责，并生成 Material Evidence |
| 报告写作与缺失数据表达 | 不负责 | 模型 + Skill 负责 |
| Evidence、workspace、上下文 | 不负责 | 应用代码负责 |
| DOCX、批注、结构校验、发布 | 不负责 | 确定性服务负责 |

硬边界：Report Agent 不得导入 `data_mcp` 源码或读取其内部 `choice/state/raw`；Data MCP 不得读取 Agent workspace 或生成报告。

## 仓库导航

```text
apps/data_mcp/                 # MCP Server、五项 feature、配置和测试
apps/report_agent/             # API、Harness、Skill、Evidence、Word 和发布
contracts/mcp/                 # 跨服务唯一业务契约及维护说明
deploy/environments/           # test/uat/prod 配置与部署手册
docs/architecture/             # 当前架构、ADR 和历史归档入口
resources/reference_data/      # 可版本化的小型参考数据
compose.yaml                   # 两个业务服务的本地/单机编排
pyproject.toml / uv.lock       # uv workspace 与锁定依赖
```

建议先读：

1. [总架构与阅读顺序](docs/architecture/README.md)
2. [Data MCP 当前标准架构](docs/architecture/data-mcp-standardized-architecture.md)
3. [MCP 契约维护说明](contracts/mcp/README.md)
4. [Report Agent 当前架构](docs/architecture/report-agent-architecture.md)
5. [环境配置与部署手册](deploy/environments/README.md)
6. [当前生产部署方案](deploy/当前生产部署方案.md)

## 快速开始

要求 Python 3.11+、[uv](https://docs.astral.sh/uv/)；完整沙箱与 Word 视觉渲染应在 Linux/Docker 中验证。

```powershell
uv sync --all-packages --group test --group lint
```

终端一启动 Data MCP：

```powershell
uv run --env-file deploy/environments/test/runtime.env --package bjs-data-mcp data-mcp --transport streamable-http --host 127.0.0.1 --port 8001
```

终端二设置本地配置、显式迁移数据库并启动 Report Agent：

```powershell
$env:REPORT_AGENT_CONFIG = (Resolve-Path "deploy/environments/test/report-agent.local.yaml").Path
uv run --env-file deploy/environments/test/runtime.env --package bjs-report-agent report-agent-db-migrate --apply
uv run --env-file deploy/environments/test/runtime.env --package bjs-report-agent report-agent-api
```

开发页：`http://127.0.0.1:8000/dev`；健康检查：`http://127.0.0.1:8000/health`。开发 API 支持 `files_`（文件上传）和 `urls`（每行一个 http/https URL，服务端下载）两种材料输入方式，详见 [Report Agent README](apps/report_agent/README.md#api)。

## Docker test 环境

```powershell
docker compose --env-file deploy/environments/test/runtime.env config --quiet
docker compose --env-file deploy/environments/test/runtime.env build
docker compose --env-file deploy/environments/test/runtime.env up -d
docker compose --env-file deploy/environments/test/runtime.env ps
```

Compose 只启动 Data MCP 和 Report Agent；模型、MySQL、Redis、MinIO、OCR 仍使用环境配置中的外部服务。数据库 DDL 不随 API 启动自动执行，首次部署必须显式运行迁移。

## 验证

```powershell
uv run --package bjs-data-mcp pytest apps/data_mcp/tests
uv run --package bjs-report-agent pytest apps/report_agent/tests
uv run --package bjs-data-mcp ruff check apps/data_mcp/src apps/data_mcp/tests
uv run --package bjs-report-agent ruff check apps/report_agent/src apps/report_agent/tests
uv run --package bjs-data-mcp mypy apps/data_mcp/src/data_mcp
uv run --package bjs-report-agent mypy apps/report_agent/src/report_agent
```

真实 Data MCP、MySQL、MinIO、OCR、模型与 Word 视觉验收依赖对应环境，不能用单元测试结果替代。

## 当前产品边界

- 已提供同步开发 API 与开发页面；不是正式异步任务平台。
- MySQL 已保存 task/session/run/artifact 元数据；MySQL checkpointer adapter 和 Redis 配置已存在，但当前同步主链尚未接入跨请求续跑。
- `visual_review_required=false` 时发布只执行 DOCX/OOXML/批注结构校验；开启后才要求 LibreOffice 渲染并逐页检查。
- `partial/empty/failed` 都不是完整成功；没有真实 `PublishedArtifact` 时 API 不得宣称报告已发布。

## 私有仓库配置策略

本仓库按私人部署仓库管理：`deploy/environments/test|uat|prod` 下的 `runtime.env`、Data MCP YAML 和 Report Agent YAML 均有意纳入 Git，包括启动所需的真实环境配置。其他机器 clone 后不需要另外寻找未提交的 `.env` 文件；Docker 配置可直接使用，本地 test YAML 会将 `${REPO_ROOT}` 自动解析为当前 clone 根目录。

`.runtime`、虚拟环境、缓存、日志和生成产物仍不提交，因为它们不是可移植的运行配置。
