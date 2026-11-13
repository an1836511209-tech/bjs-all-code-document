# Data MCP 项目画像集成测试

这组测试验证 **Report Agent 与 Data MCP 之间的项目画像链路**，重点是
`extract_project_profile` 的两种材料输入方式：

```
用户材料 PDF
  → parse_materials        （report_agent 本地解析，产出 material_id + blocks）
  → export_parsed_md       （上传 MinIO，返回 presigned URL）
  → material_url           （传给 Data MCP）
  → extract_project_profile（Data MCP 下载 URL + 企查查 + 智谱 + HiAgent）
  → evidence/*.json        （落盘，供 agent 用 read_evidence 读取）
```

历史上有两个坑，这组测试就是防止它们复发的：

1. **把本地路径当 URL 传** —— `material_url` 只接受 `http/https`，传
   `/workspace/input/xx.pdf` 会被 schema 拒绝。
2. **把模型摘要当材料传** —— `file_info` 曾经只传了 637 字（材料实际 7718 字），
   导致画像提取为空。正确做法是 `export_material_text` 返回完整正文。

## 前置条件

这些是**集成测试**：它们会连真实服务。缺任何一个，相关用例会 `skip`
而不是 `fail`，所以本地没有完整环境时 `pytest` 依然是绿的。

| 依赖 | 用途 | 缺失时 |
|---|---|---|
| `deploy/environments/test/runtime.env` | MinIO 端点、密钥、bucket | 全部 `skip` |
| MinIO（`MINIO_ENDPOINT`） | 上传 material_url | `test_material_url*.py` 跳过 |
| Data MCP（`http://127.0.0.1:8001/mcp`） | 5 个 MCP 工具 | MCP 相关用例跳过 |
| 一份已解析的材料 JSON | 测试输入 | 画像用例跳过 |
| HiAgent / 企查查 / 智谱 | Data MCP 的上游 | 不影响 `skip` 判断，但会让画像返回 `empty` |

### 准备材料 JSON

材料 JSON 来自任何一次跑过的投资报告任务：

```
.runtime/report-agent-workspaces/<task_id>/working/materials/material_<32hex>.json
```

测试默认用下面这个（历史任务留下的），也可以用环境变量覆盖：

```powershell
$env:MCP_PROFILE_MATERIAL = "D:\...\material_xxxxxxxx.json"
```

### 启动依赖服务

```powershell
# Data MCP（端口 8001）
$repo = "D:\Rome_workspace\北交所\主干\bjs-investment-report-agent"
# 先加载 runtime.env 到当前进程，再启动
python -m data_mcp.entrypoints --transport streamable-http --host 127.0.0.1 --port 8001

# MinIO 需要可访问；本地可用 docker 起
docker run -d --name minio -p 9000:9000 -p 9001:9001 `
  -e "MINIO_ROOT_USER=admin" -e "MINIO_ROOT_PASSWORD=Admin@123456" `
  -v /data/minio:/data minio/minio:RELEASE.2025-04-22T22-12-26Z server /data --console-address ":9001"
```

bucket（`MINIO_BUCKET`，默认 `bjstest`）必须已创建，否则 `upload_markdown` 会失败。

## 手动执行（推荐先跑这个）

`manual_probe.py` 不依赖 pytest，一步一步打印耗时，卡在哪里一眼能看到：

```powershell
cd D:\Rome_workspace\北交所\主干\bjs-investment-report-agent

# 默认：用最近一次任务的材料，走 material_url，超时 60s
python apps\report_agent\tests\unit\mcp_profile\manual_probe.py

# 快速判断是否卡在 HiAgent（30 秒就放弃）
python apps\report_agent\tests\unit\mcp_profile\manual_probe.py --timeout 30 --limit 600

# 只测内联文本，验证"不走 MinIO"的路径
python apps\report_agent\tests\unit\mcp_profile\manual_probe.py --mode text

# 指定材料与公司
python apps\report_agent\tests\unit\mcp_profile\manual_probe.py `
    --material .runtime\report-agent-workspaces\task_xxx\working\materials\material_xxx.json `
    --company "惠然科技有限公司" --limit 2000
```

输出示例：

```
[1] 读材料
    OK   材料就绪                       chars: 7454
[2] 上传 MinIO
    OK   0.41s  expires=2026-10-26 07:54:01
[3] 回读 MinIO（验证 presigned URL 可下载）
    OK   0.19s  status=200  bytes=1409
[4] 调 MCP extract_project_profile（timeout=30.0s, mode=url）
    FAIL 30.4s 后超时/断开：ExceptionGroup
    判断：MinIO 与 URL 都正常（步骤 2/3 通过），
          超时发生在 Data MCP 内部 —— 大概率是 HiAgent 的
          project_profile agent 不返回模型响应。
```

**怎么读**：

| 卡在第几步 | 含义 | 去查 |
|---|---|---|
| 1 | 材料 JSON 不存在或没正文 | `--material` 路径 |
| 2 | MinIO 连不上 / bucket 不存在 / 密钥不对 | `MINIO_*` 环境变量、`bjstest` bucket |
| 3 | presigned URL 无法下载 | MinIO 的公网地址、防火墙 |
| 4 超时 | MinIO 正常，Data MCP 内部卡住 | HiAgent 的 `project_profile` agent |
| 4 返回 `empty` | 链路通但画像为空 | `warnings` 里的上游降级原因 |

退出码：`0` = success/partial，`1` = empty，`2` = 调用失败。

## pytest 运行

```powershell
cd D:\Rome_workspace\北交所\主干\bjs-investment-report-agent\apps\report_agent

# 只跑这组
pytest tests/unit/mcp_profile -v

# 看哪些被跳过及原因
pytest tests/unit/mcp_profile -v -ra

# 单个文件
pytest tests/unit/mcp_profile/test_project_profile.py -v
```

## 耗时：请按需分组运行

**全量跑一次约 9 分钟**（实测 542 秒，18 个用例）。慢在两类用例：
每个 HiAgent 调用在 agent 不健康时要等满超时窗口，而
`extract_project_profile` 内部还有 3 次重试。

### 快速组（约 20 秒，日常回归用这个）

```powershell
pytest tests/unit/mcp_profile -v -k "not answers_within and not small_material_url and not inline_file_info"
```

覆盖：MinIO 往返、`export_parsed_md` 无对象存储时报错、5 个 MCP 的返回契约、
HiAgent 配置检查（不发起网络调用）。

### 慢速组（约 8 分钟，只在排查 MCP 问题时跑）

```powershell
# 只测画像的两种输入
pytest tests/unit/mcp_profile/test_project_profile.py -v

# 只测 HiAgent 单次耗时
pytest tests/unit/mcp_profile/test_hiagent_health.py -v -k answers_within
```

### 单条

```powershell
# 最短的画像探测（600 字材料）
pytest "tests/unit/mcp_profile/test_project_profile.py::test_profile_with_small_material_url[600]" -v
```

## 已知失败与判读

全量跑完会看到 3 条失败，都是**上游问题**，不是测试写错：

| 用例 | 现象 | 原因 |
|---|---|---|
| `test_upload_markdown_overwrites_same_key` | 第二次 GET 拿到旧内容 | MinIO 预签名 URL 有 CDN/客户端缓存，或 `put_object` 后立即 GET 读到旧对象；重跑通常通过 |
| `test_investor_match_returns_json` | `TimeoutError`（MCP transport 300s） | `match_investors` 的 HiAgent 分支慢 |
| `test_profile_with_inline_file_info` | `TimeoutError` | `project_profile` 的 HiAgent agent 不返回（见下节） |

**判读原则**：

- `TimeoutError` / `ReadTimeout` → 上游慢，**不是契约坏了**
- `AssertionError`（字段缺失、不是 JSON、schema 错）→ **契约坏了，要修**
- `skip` → 依赖没起，看 `-ra` 的原因

## 最小可用验证（30 秒内）

想确认"材料能否通过 MinIO 送到 MCP"，只跑这两条：

```powershell
pytest tests/unit/mcp_profile/test_material_url.py::test_upload_markdown_returns_downloadable_url -v
pytest tests/unit/mcp_profile/test_hiagent_health.py::test_agent_paths_use_singular_agent -v
```

第一条证明 MinIO 可写可读，第二条证明 HiAgent 配置用的是能返回 200 的单数路径。

## 文件说明

| 文件 | 覆盖内容 |
|---|---|
| `conftest.py` | 共享 fixture：读 `runtime.env`、加载 settings、探测 MinIO / Data MCP、准备材料文本；服务缺失时 `skip` |
| `test_material_url.py` | `MinioArtifactService.upload_markdown` 往返、同 key 覆盖、`export_parsed_md` 在无对象存储时报错 |
| `test_project_profile.py` | `extract_project_profile` 的 4 种输入：小材料 URL（600/2000 字）、本地路径被拒、内联 `file_info`、缺参数 |
| `test_mcp_tools.py` | 其余 4 个 MCP 的契约：`match_listed_peers` 必须带 PE/PB、`query_track_labels` 对空 profile 报 schema 错、`query_comparable_valuation` / `match_investors` 必须返回 JSON |
| `test_hiagent_health.py` | HiAgent 三/四个 agent 的配置检查 + 路径必须是单数 `agent` + 单次调用耗时探测 |

## 已知问题

### `project_profile` 的 HiAgent agent 会超时

```
agent_id: 9422be358adb4c5c8513b95524e97c96
现象:     POST https://uat.agentspro.cn/openapi/agent/chat/completions/v1
          ReadTimeout（60s / 120s / 400s 都试过，无响应）
对照:     historical_valuation 的 423343a9… 同一 host/token 正常返回
结论:     单个 agent 的问题，不是 HiAgent 平台整体故障
```

因此 `test_agent_answers_within_window[project_profile]` 会 `skip`，
Data MCP 的 `extract_project_profile` 返回 `empty`。链路本身（MinIO 下载、
企查查、智谱）都是通的，日志可见：

```
GET  MinIO  /exports/.../material.md  → 200 OK
GET  api.qichacha.com/ECIInfoVerify   → 200 OK
POST open.bigmodel.cn/api/paas/v4/web_search × 4 → 200 OK
POST uat.agentspro.cn/...             → ReadTimeout
```

### `match_investors` 曾返回非 JSON

`McpTransportError: Data MCP text response is not valid JSON`。
`test_mcp_tools.py::test_investor_match_returns_json` 会兜住这个回归。

## 约定

- 这组测试**不修改生产代码**，只调用公开接口。
- 新增探测时，优先断言"契约"（返回 JSON、字段存在、错误码正确），
  而不是断言"数据一定非空"——上游数据会变，契约不该变。
- 需要新依赖时，在 `conftest.py` 加 fixture，并在缺少依赖时 `skip`。
