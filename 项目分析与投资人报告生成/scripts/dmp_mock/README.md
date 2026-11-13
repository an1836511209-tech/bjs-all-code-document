# DMP 模拟接口与附件稳定性验收

仅用于 test、UAT。替换 DMP HTTP 地址，API、MCP、标签关联、Excel 清洗/校验和独立附件 worker 继续使用业务实现。生产配置不改为 mock，生产模式或 APP_ENV=prod 下禁止启动模拟器。

## 默认数据量

- 可匹配机构库 10,000 家，个人库 50,000 人；按 offset/limit 生成当前页，不在内存里构造全部名单。
- 每家机构约 3,000 个无关行业标签，加上本次请求标签。200 家响应超过 16 MiB；实际数值由验收脚本输出。
- Excel 沿用现有首批最多 200 家规则。增加模拟库规模和响应长度不改变生产分页/导出规则。
- 个人查询保留相同字段并按本页返回 count，测试环境配置 limit=500；不发送长机构标签，以免无意义扩大个人统计报文。
- 相同参数返回相同顺序、分数、命中标签与“测试机构”名称；支持单个/多个标签。
- 鉴权使用固定、公开的 `mock-dmp-*` 测试凭据，校验 SHA1 签名、时间戳、nonce、网关 HMAC-SM3。mock 模式不会读取真实 DMP/API 平台密钥。

## 本地启动

在仓库根目录四个终端分别执行（先确保现有数据库/MinIO配置及附件表已就绪）：

```powershell
.\scripts\start-local.ps1 dmp-mock
.\scripts\start-local.ps1 mcp
.\scripts\start-local.ps1 api
.\scripts\start-local.ps1 workbook-worker
```

浏览器打开 `http://127.0.0.1:8000/console/`，勾选附带匹配表，提交报告。默认模拟服务是 `127.0.0.1:8025`。更改端口时给 dmp-mock 与 mcp 两个命令传相同的 `-MockPort`。

只让 Excel 第一次失败，报告匹配正常：

```powershell
.\scripts\start-local.ps1 dmp-mock -ExportScenario fail_once
```

切换场景需要重启模拟器；同一个实例不在请求进行时变更场景。已有 MCP/API 进程必须加载本次新代码后才能发出测试用途头。脚本不会自动停止用户原有进程。

## test / UAT 容器一键启动

在相应宿主机准备好本环境的 `deploy/environments/<env>/runtime.env`、数据库、MinIO 后执行：

```powershell
.\scripts\start-nonprod.ps1 test
.\scripts\start-nonprod.ps1 uat
```

Linux：

```sh
sh scripts/start-nonprod.sh test
sh scripts/start-nonprod.sh uat
```

默认会构建当前代码并启动 DMP 模拟器、Data MCP、Report API 和附件 worker。访问 API 端口 5129 的 `/console/`。API 和 worker 共享同一个环境的工作区、数据库配置及对象存储配置；test/UAT 工作区和 Compose 项目分开，新增模拟器及 worker 只在覆盖文件的 `dmp-mock` profile 中启用。

两个环境同机运行时设置不同端口。例如 UAT 使用 `-McpPort 5138 -ApiPort 5139 -MockPort 8035`；Linux 使用 `DATA_MCP_PORT=5138 REPORT_AGENT_PORT=5139 DMP_MOCK_PORT=8035 sh scripts/start-nonprod.sh uat`。脚本默认 test/UAT 使用不同 Docker 子网；与宿主网络冲突时通过 `-DockerSubnet` 或 `BJS_DOCKER_SUBNET` 调整。

模拟器无业务数据卷，不使用运行时真实凭据。业务端口为容器内 8025，宿主诊断端口只绑定回环。生产部署不加载 `compose.dmp-mock.yaml`，不能通过此脚本选择 prod。

本次不新增数据库表；新环境仍需要按已有迁移流程初始化业务表及附件表。此服务只替换 DMP，画像、赛道标签、模型、OCR、MinIO 等其他依赖仍按所在环境配置工作。

## 场景与响应格式

| 参数 | 取值 |
| --- | --- |
| `--report-scenario` | 仅影响报告中的 DMP 机构/个人请求，默认 normal |
| `--export-scenario` | 仅影响独立 Excel 导出请求，默认 normal |
| `--wrapper` | direct（直接对象）、body、data |
| `--institutions` / `--individuals` | 匹配库数量，默认 10000 / 50000 |
| `--labels` | 每家机构无关标签数，默认 3000，上限 10000 |
| `--delay` | timeout 场景等待秒数，默认 35 |

场景：normal、empty、dirty、invalid_json、invalid_items、http_401、http_429、http_500、timeout、fail_once、oversize。

`fail_once` 按调用用途、投资人类型、查询标签组独立计数；首次返回 500，后续正常。报告保留原 HTTP 重试策略，独立 Excel 不自动重试，用户手动重试后恢复。`oversize` 流式发送超过 64 MiB 的有效 JSON 标签字符串，验证客户端实际读取上限。dirty 含空名称、字符串数字、NaN、缺失/截断标签。

容器场景通过 `DMP_MOCK_REPORT_SCENARIO`、`DMP_MOCK_EXPORT_SCENARIO`、`DMP_MOCK_WRAPPER`、`DMP_MOCK_INSTITUTIONS`、`DMP_MOCK_INDIVIDUALS`、`DMP_MOCK_LABELS` 配置。PowerShell 一键脚本提供 `-ExportScenario`、`-Wrapper`；Linux 第二个参数为导出场景。

## 诊断

- `GET /health`：模拟器标识、环境、场景、数据量，不返回凭据。
- `GET /__mock__/stats`：累计有效查询数及最近 100 次请求的来源、标签指纹、分页、状态、响应字节数与耗时，不记录原始长列表、签名或 token。
- 请求路径：`/v3/API_DMP_DMP_APEX_InquiryInvestorProfileMatchingSrv`，GET/POST。
- `count` 为本页条数，`hasMore` 根据模拟库大小计算。

单实例最多 2 个并行请求，场景计数最多 256 个键。普通响应预估超过 48 MiB 时返回 413，超限保护专门使用流式 oversize 场景，避免多个大响应同时构造导致模拟器耗尽内存。超时/超限客户端断开后，服务能继续处理下一次请求。不同自动化用例使用独立端口与固定场景实例，避免串扰。

## 无外部依赖的一键验收

```powershell
.\scripts\start-local.ps1 check-dmp-mock -Iterations 100
# 或跨平台
python -m scripts.dmp_mock.verify --iterations 100
```

需要仓库开发虚拟环境（pytest、现有应用依赖），不用读 runtime.env、不调用真实模型、数据库、DMP 或 MinIO。脚本自动启动/关闭临时 HTTP 模拟器及真实 MCP 子进程，使用合成报告上下文、内存任务/对象存储替身，验证：

- GET/POST、三种包装、两层鉴权、空表/脏数据/错误 JSON/HTTP 错误/超时/超过 64 MiB。
- 默认大响应先清洗再通过 MCP 传输，不把长标签或机构原文带入报告证据。
- 默认 100 次真实 MCP 导出，每次校验 XLSX 哈希、四列、排序、行数及标签；再将 10 个任务同时入队并逐个交付，核对标签没有串用。
- 真实 HTTP/MCP 导出失败保留原报告；手动重新生成可恢复；API 能预览及下载实际 XLSX。

结果及 MCP 子进程日志位于脚本打印的 `.runtime/dm*` 测试专用短目录。保留短路径以避免 Windows 原子临时文件超过路径长度限制。该验收不替代真实 MySQL/MinIO 部署和生产网关联调。
