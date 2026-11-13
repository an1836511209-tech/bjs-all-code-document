# Report Agent 本地启动指南

2026-10-31 更新：本地/test/UAT 的 DMP 已切换为独立模拟 HTTP 服务。启动 MCP 前另开终端运行 `scripts/start-local.ps1 dmp-mock`；生成附件还需 API 与 `workbook-worker`。模拟器默认 10,000 家机构、每家约 3,000 个标签，支持大报文与故障场景；完整命令见 [DMP 模拟器说明](scripts/dmp_mock/README.md)。

> 适用版本：`main`（2026-10-29 之后）
> 覆盖两种运行方式：**本地 Python 直接运行**、**Docker 容器运行**
> 仓库结构：`apps/report_agent`（Agent 服务）+ `apps/data_mcp`（MCP 工具服务）

---

## 0. 先理解三件事

### 0.1 两个服务和一个可选附件进程

| 服务 | 作用 | 默认端口 |
|---|---|---|
| `data_mcp` | MCP 工具（项目画像、投资人匹配、工商、网页搜索、挂牌财务、赛道标签） | 8001 |
| `report_agent` | FastAPI + Agent 编排，跑 Skill 流程，产出 Word | 8000 |
| `institution_workbook_worker` | 独立生成投资机构匹配 Excel；使用该功能时启动 | 无 |

`report_agent` 通过 MCP（streamable-http）调 `data_mcp`，**两个都要起**。

2026-10-29 新增的匹配附件需要 MySQL 持久化任务与独立 worker；不能继续使用 `inmem_server.py` 来验证跨进程附件。下文的本地命令已切换到正式 API 入口。

2026-10-30 兼容旧命令：配置启用匹配附件时，`inmem_server.py` 会自动转到正式持久化 API 入口；配置未启用时仍使用内存模式。已运行的旧进程需要重启才能加载该修复。

### 0.2 配置文件的分工

```
deploy/environments/<env>/
├── runtime.env                   ← 环境变量（密钥、地址），唯一一份
├── report-agent.yaml             ← 容器版配置（容器内路径 + bubblewrap 沙箱）
├── report-agent.local.yaml       ← 本地版配置（仓库相对路径 + filesystem 沙箱）
└── data-mcp.yaml                 ← MCP 配置（两种方式共用）
```

`runtime.env` 是 **Docker Compose 的** `env_file` **格式**，Python 不会自动读取，两种运行方式下的注入方式不同（见下）。

### 0.3 依赖矩阵

| 组件 | 本地 Python | Docker | 说明 |
|---|---|---|---|
| MySQL | ✅ 需要 | ✅ 需要 | 正式 API、检查点和附件队列均需持久化 |
| Redis | ❌ 不需要 | ❌ 不需要 | 配置里有 `REDIS_*`，但代码中无实际使用 |
| MinIO | ✅ 需要 | ✅ 需要 | Word 与 Excel 的发布、稳定下载依赖对象存储 |
| Gotenberg | ⚠️ 可选 | ⚠️ 可选 | 仅影响 doc/docx 在线预览 |
| PaddleOCR / Tika | ⚠️ 可选 | ⚠️ 可选 | 影响扫描件解析质量 |
| bubblewrap | ❌ 不需要 | ✅ 需要 | 本地走 `filesystem` 后端 |

---

## 1. 前置准备

### 1.1 代码与依赖

```powershell
cd <repo>
uv sync            # 或 pip install -e apps/report_agent -e apps/data_mcp
```

验证：

```powershell
python -c "import report_agent, data_mcp, uvicorn; print('ok')"
```

### 1.2 确认大文件已拉取

`resources/reference_data/data_mcp/listed_peer_index/vectors.bin` 走 Git LFS，约 117 MB。

```powershell
git lfs pull
Get-Item resources\reference_data\data_mcp\listed_peer_index\vectors.bin | Select-Object Length
# 期望：123346944
```

文件只有约 130 字节时说明是 LFS 指针未拉取，此时首次启动会**重建索引（20–40 分钟）**。

---

## 2. 方式一：本地 Python 直接运行（推荐日常开发）

特点：改代码后重启相应进程即可，不需要重建镜像。使用 `runtime.env` 中配置的 MySQL 与 MinIO；不需要本机另外启动 Docker 或 Redis。

### 2.0 匹配附件：首次升级与快捷启动

在仓库根目录运行一次增量迁移（已有主任务表时使用，只创建附件表，不重跑主业务迁移）：

```powershell
cd D:\Project\bjs-investment-report-agent
.\scripts\start-local.ps1 migrate-workbook
```

分别在三个 PowerShell 终端运行；脚本会读取测试环境变量并选择本地配置：

```powershell
# 终端 1
.\scripts\start-local.ps1 mcp

# 终端 2
.\scripts\start-local.ps1 api

# 终端 3：需要生成匹配附件时运行
.\scripts\start-local.ps1 workbook-worker

# 终端 4：模拟dmp api数据
.\scripts\start-local.ps1 dmp-mock
```

每个终端都先进入仓库根目录。浏览器打开 `http://127.0.0.1:8000/m4Kp9Qx2Lv7Nc1Rd8Ws3Tf6Yb0Hz/v1/ai-service/console/`，刷新缓存后可见“附带投资机构匹配表”，默认未勾选。开启后 Word 先交付，Excel 随后出现在文件预览侧；未勾选时不运行附件流程。

本地配置已设 `institution_workbook.enabled: true`，容器、UAT、生产配置保持默认关闭。worker 与 API 必须使用相同数据库和工作区目录；每个工作区只运行一个 worker。服务已运行时，在原终端按 Ctrl+C 停止对应进程后重启，避免占用 8000/8001 端口。

检查功能及 worker 心跳：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/features
```

`institution_workbook.enabled` 和 `worker_online` 均为 `true` 表示功能开启且 worker 在线。新建数据库须先按项目原流程初始化主业务表，附件迁移不能代替它。

如果“附带投资机构匹配表”无法勾选，先看输入框下方的原因：

- “当前服务未启用”：确认使用本地配置，重启 API 后点“刷新状态”。旧进程不会自动载入代码变更。
- “当前报告执行中”：本轮附件选项已经锁定，发送报告前选择；报告结束后可再修改。
- “附件生成服务未启动”：开关仍可勾选并保存，但要在第三个终端运行 worker 才会生成 Excel。只有 MCP 和 API 两个进程时，原报告仍可正常交付。
- “暂时无法读取附件功能状态”：服务恢复后点“刷新状态”，无需重新建立对话。

2026-10-30 起隐藏输入框的 URL 按钮。前端脚本和样式地址包含版本号；更新后刷新页面加载新资源。

### 2.1 终端 1 —— 启动 Data MCP（8001）

**PowerShell：**

```powershell
cd <repo>

Get-Content deploy\environments\test\runtime.env -Encoding UTF8 | ForEach-Object {
  $l = $_.Trim(); if (-not $l -or $l.StartsWith('#')) { return }
  $i = $l.IndexOf('='); if ($i -lt 1) { return }
  [Environment]::SetEnvironmentVariable($l.Substring(0,$i).Trim(), $l.Substring($i+1), 'Process')
}

python -m data_mcp.entrypoints --transport streamable-http --host 127.0.0.1 --port 8001
```

**bash / zsh：**

```bash
cd <repo>
set -a; source deploy/environments/test/runtime.env; set +a
python -m data_mcp.entrypoints --transport streamable-http --host 127.0.0.1 --port 8001
```

等待以下两行出现后再继续（约 20–30 秒）：

```
reusing listed peer embedding index at ...
listed peer embedding index ready: companies=5019 dim=1024
```

### 2.2 终端 2 —— 启动 Report Agent（8000）

**PowerShell：**

```powershell
cd <repo>

Get-Content deploy\environments\test\runtime.env -Encoding UTF8 | ForEach-Object {
  $l = $_.Trim(); if (-not $l -or $l.StartsWith('#')) { return }
  $i = $l.IndexOf('='); if ($i -lt 1) { return }
  [Environment]::SetEnvironmentVariable($l.Substring(0,$i).Trim(), $l.Substring($i+1), 'Process')
}

# 必须覆盖：容器版配置的路径与沙箱在本地不可用
$env:REPORT_AGENT_CONFIG = "deploy\environments\test\report-agent.local.yaml"

python -m report_agent.entrypoints.api --host 127.0.0.1 --port 8000
```

**bash / zsh：**

```bash
cd <repo>
set -a; source deploy/environments/test/runtime.env; set +a
export REPORT_AGENT_CONFIG=deploy/environments/test/report-agent.local.yaml
python -m report_agent.entrypoints.api --host 127.0.0.1 --port 8000
```

出现 `Uvicorn running on http://127.0.0.1:8000` 即为就绪。

### 2.3 验证

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing | Select-Object -Expand Content
```

期望返回：

```json
{"status":"ok","console":"ok","console_dir":"<repo>/frontend"}
```

浏览器打开 **http://127.0.0.1:8000/m4Kp9Qx2Lv7Nc1Rd8Ws3Tf6Yb0Hz/v1/ai-service/console/**

### 2.4 停止

```powershell
# 在各自运行服务的终端按 Ctrl+C。
```

### 2.5 说明：为什么必须覆盖 `REPORT_AGENT_CONFIG`

| 配置项 | `report-agent.yaml`（容器版） | `report-agent.local.yaml`（本地版） |
|---|---|---|
| `workspace_root` | `/var/lib/report-agent/workspaces` | `${REPO_ROOT}/.runtime/report-agent-workspaces` |
| `skill_roots` | `/app/apps/report_agent/skills` | `${REPO_ROOT}/apps/report_agent/skills` |
| `sandbox.backend` | `bubblewrap` | `filesystem` |
| `data_mcp.url` | `http://data-mcp:8001/mcp` | `http://127.0.0.1:8001/mcp` |
| `contracts_dir` | `/app/contracts/mcp` | `${REPO_ROOT}/contracts/mcp` |

`${REPO_ROOT}` 由 `report_agent/settings/loader.py` 自动展开（向上查找含 `pyproject.toml` 与 `apps/report_agent` 的目录），**不需要设置该环境变量**。

其余参数（模型调用上限、工具白名单、上下文压缩、超时）两份完全一致，因此本地运行能如实反映业务流程行为。

### 2.6 后台运行（可选，单终端）

```powershell
cd <repo>
Get-Content deploy\environments\test\runtime.env -Encoding UTF8 | ForEach-Object {
  $l = $_.Trim(); if (-not $l -or $l.StartsWith('#')) { return }
  $i = $l.IndexOf('='); if ($i -lt 1) { return }
  [Environment]::SetEnvironmentVariable($l.Substring(0,$i).Trim(), $l.Substring($i+1), 'Process')
}
$env:REPORT_AGENT_CONFIG = "deploy\environments\test\report-agent.local.yaml"

$logDir = "$env:TEMP\report-agent-logs"; New-Item -ItemType Directory -Force -Path $logDir | Out-Null

Start-Process python -ArgumentList "-m","data_mcp.entrypoints","--transport","streamable-http","--host","127.0.0.1","--port","8001" `
  -RedirectStandardOutput "$logDir\mcp.log" -RedirectStandardError "$logDir\mcp.err" -WindowStyle Hidden
Start-Sleep -Seconds 28

Start-Process python -ArgumentList "-m","report_agent.entrypoints.api","--host","127.0.0.1","--port","8000" `
  -RedirectStandardOutput "$logDir\agent.log" -RedirectStandardError "$logDir\agent.err" -WindowStyle Hidden
Start-Process python -ArgumentList "-m","report_agent.entrypoints.institution_workbook_worker" `
  -RedirectStandardOutput "$logDir\workbook.log" -RedirectStandardError "$logDir\workbook.err" -WindowStyle Hidden
Start-Sleep -Seconds 15

foreach ($p in 8000,8001) {
  $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  Write-Host ("{0} -> {1}" -f $p, $(if ($c) { "up pid $($c.OwningProcess)" } else { 'DOWN' }))
}
```

日志写入 `$env:TEMP\report-agent-logs\`。

---

## 3. 方式二：Docker 容器运行

特点：完整复现部署形态（MySQL、bubblewrap 沙箱、只读根文件系统、资源限制）。镜像构建较慢，代码改动需要重新 build。

### 3.1 前置

- Docker Desktop（**WSL2 backend**，Linux 容器模式）
- 分配给 Docker 的内存 ≥ 8 GB
- 首次构建会安装 LibreOffice 与中文字体，镜像约 1.5 GB

### 3.2 启动

```powershell
cd <repo>

$env:APP_ENV = "test"
$env:BJS_ENV_FILE = "deploy/environments/test/runtime.env"

docker compose build          # 首次约 10-20 分钟
docker compose up -d
docker compose logs -f report-agent
```

### 3.3 访问

| 用途 | 地址 |
|---|---|
| Console | http://localhost:5129/console/ |
| 健康检查 | http://localhost:5129/health |
| Data MCP | http://localhost:5128/mcp（容器内为 `data-mcp:8001`） |

### 3.4 停止与清理

```powershell
docker compose down            # 停容器，保留 workspaces/
docker compose down -v         # 连同 volume 删除（工作区数据会丢失）
```

### 3.5 启用生产环境配置

```powershell
$env:APP_ENV = "prod"
$env:BJS_ENV_FILE = "deploy/environments/prod/runtime.env"
docker compose up -d
```

---

## 4. Docker 运行的常见问题

### 4.1 `systempaths=unconfined` 被拒绝

`compose.yaml` 的 `report-agent` 服务包含：

```yaml
security_opt:
  - seccomp=unconfined
  - apparmor=unconfined
  - systempaths=unconfined
cap_add:
  - SYS_ADMIN
  - NET_ADMIN
  - SYS_PTRACE
```

这三项是让容器内的 `bubblewrap` 沙箱可用的必要条件，但 **Docker Desktop（Windows）通常不支持** `systempaths`，报错形如 `invalid option: systempaths` 或容器无法启动。

绕开方式：在同目录新建 `compose.local.yaml`（不修改原文件）：

```yaml
services:
  report-agent:
    read_only: false
    cap_add: []
    security_opt: []
    tmpfs: []
    environment:
      REPORT_AGENT_CONFIG: /app/deploy/environments/test/report-agent.dockerlocal.yaml
```

再新建 `deploy/environments/test/report-agent.dockerlocal.yaml`：复制 `report-agent.yaml`，仅把

```yaml
sandbox:
  backend: bubblewrap     # 改为
  backend: filesystem
```

然后启动：

```powershell
docker compose -f compose.yaml -f compose.local.yaml up -d
```

> 该方式不具备进程隔离，仅用于本地验证，不要用于生产。

### 4.2 子网冲突

```yaml
networks:
  default:
    ipam:
      config:
        - subnet: "${BJS_DOCKER_SUBNET:-10.201.0.0/24}"
```

若提示 `Pool overlaps with other one on this address space`：

```powershell
$env:BJS_DOCKER_SUBNET = "10.211.0.0/24"
docker compose up -d
```

### 4.3 端口被占用

`5128`（MCP）、`5129`（Agent）若已被占用，调整 `compose.yaml` 中 `ports` 的宿主端口。

### 4.4 `report-agent` 一直不启动

`report-agent` 依赖 `data-mcp` 健康检查通过（`depends_on: condition: service_healthy`）。`data-mcp` 启动时需要加载向量索引：

- 本地已 `git lfs pull` → 挂载 `./resources` 后直接复用，秒级完成
- 未拉取 LFS → 重建索引需 20–40 分钟，超过 healthcheck 的 `retries: 20 × interval: 10s` 窗口，会被判定为不健康

排查：

```powershell
docker compose logs -f data-mcp
```

### 4.5 `/console/` 返回 404

镜像中缺少 `frontend/` 目录。`apps/report_agent/Dockerfile.runtime` 必须包含：

```dockerfile
COPY frontend ./frontend
```

容器根文件系统为只读（`read_only: true`），无法在运行时挂载该目录。

### 4.6 容器内时间为 UTC

日志与文件时间戳为 UTC，与本地时区相差 8 小时（`Asia/Shanghai`）。

---

## 5. 两种方式的差异对照

| 维度 | 本地 Python | Docker |
|---|---|---|
| run 记录持久化 | MySQL（重启保留） | MySQL（重启保留） |
| 工作区 | `.runtime/report-agent-workspaces` | volume `./workspaces` |
| 命令执行沙箱 | `filesystem`（无隔离，可联网） | `bubblewrap`（隔离，禁网） |
| Office 页数计算 | 无 LibreOffice，`pages=null` | 有 LibreOffice，返回真实页数 |
| 中文字体 | 系统字体 | `fonts-noto-cjk` |
| 资源限制 | 无 | 4 GB 内存 / 2 CPU / 256 进程 |
| 根文件系统 | 可写 | 只读（仅 volume 与 `/tmp` 可写） |
| 代码改动生效 | 重启进程即可 | 需重新 `build` |
| 首启耗时 | 秒级 | 数分钟（索引与依赖） |

### 结论：本地运行可信与不可信的范围

**可信**：Skill 流程完整性、docx 内容与批注、工具契约、prompt 效果、模型调用次数、前后端联调。

**还需部署环境验证**：文档页数（本地无 LibreOffice）、高内存/CPU 压力下的稳定性、容器只读约束、多副本行为、容器首次启动耗时。当前附件 worker 只支持同机共享工作区的单进程运行。

---

## 6. 启动验收清单

启动完成后逐项确认：

- [ ] `GET /health` 返回 `status: ok` 且 `console: ok`
- [ ] 浏览器可打开 `/console/`，侧栏可展开
- [ ] 新建对话，选择 `chat` skill，发送一句话能收到回复（验证 LLM 通路）
- [ ] 选择 `one-pager` skill 上传一份 PDF，流程能推进到产出 docx
- [ ] 产出目录存在 `.docx` 文件，且 `artifacts/index.json` 有发布记录
- [ ] `logs/agent.ndjson` 有 `model_call` 与 `tool_call` 记录

---

## 7. 故障速查

| 现象 | 原因 | 处理 |
|---|---|---|
| `REPORT_AGENT_CONFIG is required` | 未设置该环境变量 | 执行 2.2 中的覆盖命令 |
| 工作区出现在 `/var/lib/report-agent/...` | 用了容器版配置 | 覆盖为 `report-agent.local.yaml` |
| 工具全部不可用 / `Connection refused` | `data_mcp` 未启动或未就绪 | 检查 8001 端口，等待索引加载完成 |
| `SignatureDoesNotMatch`（MinIO） | 密钥不正确 | 核对 `runtime.env` 的 `MINIO_SECRET_KEY` |
| 简历索引重建耗时过长 | LFS 文件未拉取 | `git lfs pull` |
| `GraphRecursionError: Recursion limit of 25` | 代码回归 | 检查 `bootstrap._run_agent` 是否显式传 `recursion_limit: 9_999` |
| `model call budget exhausted` | 模型调用次数超限 | 查看 `logs/agent.ndjson` 定位死循环 |

---

## 8. 目录与日志位置

```
<workspace_root>/<task_id>/
├── input/         上传材料
├── report/        one-pager.md / report.md
├── output/        生成的 docx
├── staging/       发布前副本
├── evidence/      证据索引
├── state/         run-state.json / conversation.json / pending.json
├── memory/        working.md
├── logs/          agent.ndjson     ← 排查问题首选
└── artifacts/     index.json
```

- 本地：`<repo>/.runtime/report-agent-workspaces/`
- 容器：宿主 `./workspaces/`（挂载到容器 `/var/lib/report-agent/workspaces`）
