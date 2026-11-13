# 环境配置与部署手册

本目录是 test、UAT、生产三套运行配置的事实源。业务服务为 Data MCP 和 Report Agent；模型、MySQL、Redis、MinIO、OCR、HiAgent、LMS、企查查等依赖由各环境配置接入。

test/UAT 的 DMP 默认使用独立模拟 HTTP 服务，附件功能已开启。使用 `scripts/start-nonprod.ps1 test|uat`（Linux 为 `sh scripts/start-nonprod.sh test|uat`）构建并启动 API、MCP、DMP 模拟器和独立附件 worker。生产仍使用真实 DMP，不加载模拟覆盖文件。数据量、故障场景与离线验收见 [DMP 模拟器说明](../../scripts/dmp_mock/README.md)。

## 目录与职责

```text
deploy/environments/
├── test/
│   ├── runtime.env
│   ├── data-mcp.yaml
│   ├── report-agent.yaml
│   └── report-agent.local.yaml   # Windows 宿主联调专用
├── uat/
│   ├── runtime.env
│   ├── data-mcp.yaml
│   └── report-agent.yaml
└── prod/
    ├── runtime.env
    ├── data-mcp.yaml
    └── report-agent.yaml
```

| 文件 | 读取方 | 内容边界 |
| --- | --- | --- |
| `runtime.env` | uv、Compose、两个进程 | 环境名、配置指针、模型/MySQL/Redis/MinIO/OCR 变量和凭据 |
| `data-mcp.yaml` | `data_mcp.shared.settings` | Data MCP 各 feature 的业务接入、数据源、重试、权重和阈值 |
| `report-agent.yaml` | `report_agent.settings.load_settings` | 容器路径、模型引用、预算、上下文、沙箱、MCP、材料处理和持久化 |
| `report-agent.local.yaml` | 本地 Report Agent | 与 test 容器配置语义相同；`${REPO_ROOT}` 在加载时解析为当前 clone 根目录 |
| `contracts/mcp/*.json` | 两个服务 | 五个工具的跨服务输入输出契约，不属于环境差异 |

配置链：

```text
Data MCP:    runtime.env -> DATA_MCP_CONFIG -> data-mcp.yaml -> settings.py -> feature
Report Agent: runtime.env -> REPORT_AGENT_CONFIG -> report-agent.yaml
             -> YAML 解析 -> Pydantic 严格校验 -> 不可变 Settings -> bootstrap 依赖注入
```

同一项只保留一个事实源。Report Agent YAML 用 `{env: VARIABLE_NAME}` 引用 `runtime.env` 中的值；Data MCP 当前业务接入值保存在环境 YAML。test/UAT/prod 的这些文件均有意纳入私人仓库版本控制，使新 clone 自带完整运行配置。配置值不应再复制到 README、Prompt、ToolMessage、workspace 或日志。

## 环境差异

| 项目 | test 宿主 | test 容器 | UAT/生产 |
| --- | --- | --- | --- |
| Report Agent 配置 | `report-agent.local.yaml` | `report-agent.yaml` | 对应环境 `report-agent.yaml` |
| Data MCP URL | `127.0.0.1:8001/mcp` | `data-mcp:8001/mcp` | 部署网络中的 Data MCP 地址 |
| workspace | Windows 绝对路径 | `/var/lib/report-agent/workspaces` | 持久卷/受控 tmpfs |
| sandbox backend | `filesystem`，仅 test 允许 | `bubblewrap` | 必须 `bubblewrap` |
| 开发页 `/dev` | 可开启 | test 可开启 | 不作为入口；`dev_ui_enabled` 仍为 true，否则 `/api/` 不可用 |
| Word 视觉门禁 | 可按联调需要关闭 | 按配置 | 上线前明确验收策略 |

`filesystem` backend 只能出现在 test；配置模型会拒绝 UAT/生产使用它。三个环境的 Report Agent 必须配置且只配置五个标准 Data MCP 工具。

## 部署前检查

### Runtime 变量

至少确认以下类别均有当前环境真实值：

- `APP_ENV`、`DATA_MCP_CONFIG`、`DATA_MCP_CONTRACTS_DIR`、`REPORT_AGENT_CONFIG`；
- `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`MULTIMODAL_MODEL`、`LLM_MAX_CONTEXT_TOKENS`；
- `MYSQL_HOST/PORT/DATABASE/USER/PASSWORD/CHARSET`；
- `REDIS_HOST/PORT/PASSWORD/DB`；
- `MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY/BUCKET/SECURE`；
- `PADDLE_OCR_URL`、`PADDLE_OCR_TOKEN`。

`LLM_MAX_CONTEXT_TOKENS` 是模型输入窗口，不是回答长度；缺失、非整数或小于 4096 会使 Agent 拒绝执行。

Data MCP YAML 还应逐 feature 检查 HiAgent/LMS/DMP/企查查、内部库、Excel 语料、Embedding/Rerank 的地址、路径、凭据、超时和开关。UAT/生产不得自动继承 test 接入值。

### 私有仓库配置策略

- `runtime.env`、`data-mcp.yaml`、`report-agent.yaml` 和本地 test YAML 必须随代码提交，不依赖 clone 之外的隐藏配置文件。
- `.gitignore` 显式保留 `deploy/environments/**/*.env` 和 `*.yaml`；新增环境时也应放在该目录并提交。
- `docker compose config` 默认会展开配置值，日常验证使用 `config --quiet`，避免终端输出噪声进入日志。
- `.runtime`、虚拟环境、缓存、日志、临时渲染和生成报告不属于配置，继续忽略。
- 如果仓库以后改变可见范围，再单独执行凭据轮换和 Secret 管理迁移；当前交付以完整可克隆为优先。

## Windows 本地 test 联调

安装依赖：

```powershell
uv sync --all-packages --group test --group lint
```

终端一：

```powershell
uv run --env-file deploy/environments/test/runtime.env --package bjs-data-mcp data-mcp --transport streamable-http --host 127.0.0.1 --port 8001
```

终端二：

```powershell
$env:REPORT_AGENT_CONFIG = (Resolve-Path "deploy/environments/test/report-agent.local.yaml").Path
uv run --env-file deploy/environments/test/runtime.env --package bjs-report-agent report-agent-db-migrate --apply
uv run --env-file deploy/environments/test/runtime.env --package bjs-report-agent report-agent-api
```

验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Test-NetConnection 127.0.0.1 -Port 8001
Start-Process http://127.0.0.1:8000/dev
```

`/health` 只验证进程；Report Agent 每次 run 开始前还会执行 Data MCP 五工具 readiness，真实 run 才能覆盖模型、MySQL、MinIO、OCR 和业务数据依赖。

## Docker test

先只校验 Compose：

```powershell
docker compose --env-file deploy/environments/test/runtime.env config --quiet
docker compose --env-file deploy/environments/test/runtime.env build
```

显式迁移远程 MySQL，再启动服务：

```powershell
docker compose --env-file deploy/environments/test/runtime.env run --rm report-agent report-agent-db-migrate --apply
docker compose --env-file deploy/environments/test/runtime.env up -d
docker compose --env-file deploy/environments/test/runtime.env ps
```

地址：Report Agent `http://127.0.0.1:8000`，开发页 `/dev`，Data MCP `http://127.0.0.1:8001/mcp`。

常用运维：

```powershell
docker compose --env-file deploy/environments/test/runtime.env logs --tail 200 data-mcp report-agent
docker compose --env-file deploy/environments/test/runtime.env restart data-mcp report-agent
docker compose --env-file deploy/environments/test/runtime.env down
```

`down` 不删除远程 MySQL/MinIO 数据；但 test workspace 当前使用容器 tmpfs，容器重建后中间文件不可恢复。

## UAT 与生产

在目标环境显式选择配置，不依赖默认 test：

```powershell
$env:APP_ENV = "uat"
$env:BJS_ENV_FILE = "deploy/environments/uat/runtime.env"
docker compose --env-file $env:BJS_ENV_FILE config --quiet
docker compose --env-file $env:BJS_ENV_FILE build
docker compose --env-file $env:BJS_ENV_FILE run --rm report-agent report-agent-db-migrate --apply
docker compose --env-file $env:BJS_ENV_FILE up -d
```

生产服务器按离线 tar 部署时，不要在服务器上 `build`。当前拓扑、单实例约束和更新方式见 [当前生产部署方案](../当前生产部署方案.md)。[生产服务器部署](../生产部署.md) 只保留更早的两容器步骤。

在能构建的机器上把 `uat` 换成 `prod` 即可本地构建。上线前还必须：

- 使用不可变镜像 tag，并记录代码 commit、配置版本、契约版本和迁移结果；
- 在反向代理提供 TLS、鉴权、请求大小限制和访问日志，不直接公网暴露 8000/8001；
- 保持 `dev_ui_enabled=true`。工作台页面在 `/console/`，提交和下载仍走 `/api/`；设成 false 后页面还在，接口全部 404。不要把 `/dev` 当作正式入口；
- 为 MySQL、Redis、MinIO 配置最小权限、备份、恢复演练、监控和网络控制；
- 在目标 Linux 验证 user namespace、Bubblewrap、只读根文件系统、workspace 写权限和进程/内存限制；
- 按环境决定是否开启视觉门禁；若开启，验证 LibreOffice、PDF/PNG 渲染和逐页检查。

## 导出 Docker 镜像 tar

离线部署或跨环境迁移时，先构建再导出为 tar 文件：

```bash
# 构建（以 uat 为例，prod 同理）
export APP_ENV=uat
export BJS_ENV_FILE=deploy/environments/uat/runtime.env
docker compose --env-file $BJS_ENV_FILE build

# 导出镜像到一个 tar（文件名带日期）
docker save -o bjs-investment-report-agent-images-$(date +%Y%m%d).tar bjs-data-mcp:0.1.0 bjs-report-agent:0.1.0
```

目标机器导入后，按 [生产服务器部署](../生产部署.md) 把运行目录放到 `/data/hiagent/bjs-investment-report-agent-main` 再启动。只 `docker load` 不会挂上宿主机的 prod 配置、`resources` 和 `workspaces`。

```bash
docker load -i bjs-investment-report-agent-images-20260923.tar
```

> `*.tar` 已在 `.gitignore` 中，不会误提交到仓库。

## 数据库与持久化边界

- `report-agent-db-migrate --apply` 是唯一允许执行项目 DDL 的入口；API 启动不建表。
- 当前 MySQL 保存 task/session/run/artifact 元数据。
- MySQL LangGraph checkpointer adapter 已存在，但未接入当前同步执行器；不要把数据库迁移成功等同于跨请求续跑已启用。
- Redis 当前只是配置依赖，尚未承载异步队列主链。
- MinIO 只接收通过 Word 校验和 staging 的最终产物；下载 URL 由服务端生成。

## 变更配置时的联动规则

| 变更 | 必须同步 |
| --- | --- |
| Data MCP feature 配置字段 | `settings.py`、test/uat/prod `data-mcp.yaml`、配置/feature 测试 |
| Report Agent 配置字段 | `settings/models.py`、三环境 YAML、test local YAML、bootstrap、测试 |
| MCP 工具增删 | `contracts/mcp`、两端代码、四份 Report Agent YAML、Skill、readiness 测试 |
| workspace/sandbox 路径 | Dockerfile、Compose mount/tmpfs、YAML、权限 smoke |
| 上下文阈值 | YAML + `LLM_MAX_CONTEXT_TOKENS` + 压缩/硬停回归 |
| Word 视觉策略 | `visual_review_required`、runtime 依赖、发布验收 |

## 常见问题

- 配置路径不存在：宿主用 `Resolve-Path` 得到 `report-agent.local.yaml` 的绝对路径；YAML 内 `${REPO_ROOT}` 会自动解析。容器使用 `/app/deploy/environments/<env>/report-agent.yaml`。
- Data MCP readiness 失败：先确认 `/mcp` 可达，再核对工具发现结果必须包含五个标准工具和相同契约目录。
- `failed` 被误当成功：检查 envelope `status/warnings/data`，不要只看 HTTP 200。
- MySQL 表不存在：显式执行 `report-agent-db-migrate --apply`；不要让 API 自动建表。
- MinIO bucket 不存在或无权限：预建 bucket 并授权配置账号；没有真实上传结果不得返回 completed。
- Bubblewrap `Operation not permitted`：检查 Linux user namespace、seccomp 和容器权限；UAT/生产不要降级为 filesystem backend。
- Word 视觉门禁失败：确认当前 artifact 已渲染且全部页面被检查；修改 DOCX 后必须重新渲染。
- Agent 上下文过大：检查 `LLM_MAX_CONTEXT_TOKENS`、压缩触发比例、外溢阈值，并确认模型确实分页读取 `result_id`。

架构说明见 [总架构入口](../../docs/architecture/README.md)。
