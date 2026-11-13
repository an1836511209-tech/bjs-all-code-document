# BJS Data MCP

Data MCP 是投资报告的数据能力服务：把材料参数和业务查询转换为可验证、最小披露的 MCP 响应。它不访问 Report Agent workspace，不维护报告上下文，也不生成 Word。

## 一次调用经过什么

```text
MCP Host / Report Agent
  -> MCPServer tool
  -> contracts/mcp input_schema 校验
  -> 对应 feature service
     -> 配置加载
     -> 外部 API / MySQL / Excel 语料 / Embedding / Rerank
     -> feature 内部结果
  -> responses.py 去供应商化、最小披露、状态归一
  -> contracts/mcp output_schema 校验
  -> MCP structured response
```

`server.py` 是跨服务边界；`features/` 内的原始结构不是公共 API。所有工具均为只读语义，异常由 `guard_tool_errors` 转换为不泄露配置、响应正文和堆栈的协议错误。

## 正式工具

| 工具 | 输入重点 | feature 数据链 | 对外 `data` |
| --- | --- | --- | --- |
| `extract_project_profile` | `company_name`，`material_url` 或 `file_info` | 材料正文 + 企查查 + 智谱搜索 -> HiAgent 画像 -> 字段证据/冲突归一 | `profile`、`field_details`、`conflicts` |
| `query_track_labels` | `company_name`、`project_profile` | LMS 优先；未配置/失败/空结果时 HiAgent；结果经本地 taxonomy 过滤 | `tags` |
| `query_comparable_valuation` | `tags`，可选 `company_name` | 参数写入 HiAgent `state.company_name/state.tags`，`userChatInput` 保持空串 | `content` |
| `match_listed_peers` | `tags`、可选 `summary/top_n/field_weights` | Excel 语料 -> 磁盘 embedding 索引 -> 标签/摘要多路召回 + 关键词补召回 -> RRF 融合 | `query`、`weights_used`、`peers`（中文业务键）、精简 `meta` |
| `match_investors` | `company_name`、`track_tags`、`project_profile` | DMP 或 MySQL 内部库 + 企查查股东过滤 + HiAgent 网络候选 -> 机构过滤/去重/截断 | `candidates`、`counts`、`shareholder_filter_applied` |
| `query_company_registry` | `company_name` | 企查查 ECIInfoVerify/GetInfo -> 工商/行业/股东/主要人员摘要 | `company` |
| `search_company_web` | `company_name`，可选 `search_keywords` | 智谱 Web Search；无关键词时用配置模板，有关键词时只查补充词 | `company_name`、`searches` |
| `query_cbex_listing_financials` | `project_name`，可选 `detail_url`、`category` | 北交互联官网检索挂牌项目并解析主要财务指标，金额统一为万元 | `annual`、`latest`、`detail_url`、`candidates` |

推荐编排顺序：

```text
extract_project_profile
  -> query_track_labels
  -> match_listed_peers + query_comparable_valuation
  -> match_investors
```

Report Agent 当前仍只启用原先五个工具。`query_company_registry`、`search_company_web` 与 `query_cbex_listing_financials` 已在 Data MCP 暴露，供 MCP Host 或后续 Agent 接入时使用；其中挂牌财务须在用户确认属于北交互联挂牌项目后再调用。上述三个工具尚未接入 Report Agent。单个工具失败不应阻断其他工具。

## 统一响应和业务状态

```json
{
  "schema_version": "1.0",
  "tool": "match_listed_peers",
  "status": "success",
  "summary": "...",
  "data": {},
  "sources": [],
  "warnings": []
}
```

| 状态 | 语义 | 调用方动作 |
| --- | --- | --- |
| `success` | 有可用结果且未记录降级 | 可消费 `data` |
| `partial` | 有可用子集，但存在 warning/降级 | 只使用已证实部分并披露限制 |
| `empty` | 调用完成但无合适业务结果 | 不补造事实，可调整参数或记录缺口 |
| `failed` | 无法形成业务结果 | 不读取预期业务字段，按错误语义处理 |

HTTP 200 或 MCP 调用完成只代表传输成功，不代表 `status=success`。当前历史估值适配器仅识别空内容和少量“无结果”短语，部分上游业务失败正文仍可能被误判；调用方必须同时检查 `status`、`summary`、`warnings` 和数据内容。

## 对外最小披露

- 项目画像不返回企查查、智谱或 HiAgent 原始响应。
- 历史估值只返回合并后的 `data.content`，不公开 `choice/state`。
- 上市公司只返回精简候选和少量运行元数据，不公开服务路径、源文件路径。
- 投资人只返回机构候选视图，不返回内部 raw、电话、邮箱；个人候选不进入合并结果。
- `shareholder_filter_applied=false` 时，调用方不得声称已经排除现有股东。

完整输入/输出字段见 [MCP 契约维护说明](../../contracts/mcp/README.md)。

## 代码导航与扩展点

```text
src/data_mcp/
├── entrypoints.py               # CLI 参数与 transport 启动
├── mcp/
│   ├── server.py                # 工具注册、边界校验
│   ├── responses.py             # 统一 envelope 与最小披露 adapter
│   ├── schemas.py               # contracts/mcp 加载与 JSON Schema 校验
│   ├── agent_guidance.py        # Host 可见的工具说明
│   └── tool_errors.py           # 安全错误转换
├── features/                    # 纵向业务能力
└── shared/
    ├── settings.py              # 单环境配置加载
    ├── http/retry_client.py     # 受控 HTTP 重试
    └── integrations/            # HiAgent、企查查等共享接入
```

修改现有工具时按以下顺序：

1. 先定义 `contracts/mcp/<tool>.json` 的输入、输出和兼容策略。
2. 修改 feature 内部数据获取/计算，不直接把原始结果暴露到 MCP。
3. 修改 `responses.py` adapter，明确空结果、降级与最小披露。
4. 保持 `server.py` 的输入和输出双向校验。
5. 补 feature、adapter、schema 和 MCP 集成测试。
6. 如果增加配置字段，同步 `settings.py`、test/uat/prod 三套 YAML 和配置测试。

把新工具交给 Report Agent 调用时，还需要同步 `STANDARD_DATA_MCP_TOOLS`、三套 `report-agent*.yaml`、Skill `allowed-tools` 和 MCP readiness 测试。只在 Data MCP 注册工具并不算 Agent 集成完成。

## 配置与运行

`DATA_MCP_CONFIG` 指向一个环境的 `data-mcp.yaml`，`DATA_MCP_CONTRACTS_DIR` 指向仓库根 `contracts/mcp`。业务工具不接受 `env` 参数，进程启动后只服务一个环境。

```powershell
uv sync --package bjs-data-mcp --group test --group lint

# Report Agent 使用的独立服务
uv run --env-file deploy/environments/test/runtime.env --package bjs-data-mcp data-mcp --transport streamable-http --host 127.0.0.1 --port 8001

# MCP Host / Inspector
uv run --env-file deploy/environments/test/runtime.env --package bjs-data-mcp data-mcp --transport stdio
npx @modelcontextprotocol/inspector uv run --env-file deploy/environments/test/runtime.env --package bjs-data-mcp data-mcp --transport stdio
```

HTTP endpoint：`http://127.0.0.1:8001/mcp`。CLI feature 直调仅用于诊断，其输出可能是内部结构，跨服务集成必须走 MCP Server。

## 验证

```powershell
uv run --package bjs-data-mcp pytest apps/data_mcp/tests
uv run --package bjs-data-mcp ruff check apps/data_mcp/src apps/data_mcp/tests
uv run --package bjs-data-mcp mypy apps/data_mcp/src/data_mcp
```

真实 stdio/HTTP 用例会访问外部系统。执行前确认环境、网络和凭据；失败时优先检查配置选择、契约错误、对应 feature 日志及统一响应中的业务状态。

更完整的数据源、算法和已知限制见 [Data MCP 当前标准架构](../../docs/architecture/data-mcp-standardized-architecture.md)。
