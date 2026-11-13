# Data MCP 与 Report Agent 交互契约

本目录是两个服务之间唯一共享的业务接口事实源。每个 `<tool>.json` 同时包含：

- `tool`：稳定工具名；
- `description`：提供给 Agent 的工具语义；
- `input_schema`：Report Agent 可以发送的参数；
- `output_schema`：Data MCP 必须返回的统一响应。

契约不描述 Data MCP 内部数据库表、HiAgent `state/choice`、服务 URL，也不描述 Report Agent 的 Evidence 文件路径和 Word 结构。

## 双端执行位置

```text
Report Agent 构建工具
  -> McpContractRegistry.input_schema() 生成 StructuredTool 参数模型
  -> 调用前 validate_input()
  -> Streamable HTTP MCP
  -> Data MCP server.validate_tool_input()
  -> feature + response adapter
  -> Data MCP server.validate_tool_output()
  -> MCP response
  -> Report Agent validate_output()
  -> WorkspaceEvidenceStore 完整落盘
  -> 模型只拿 EvidenceView，再按需读取事实
```

同一份 schema 在生产端和消费端各校验一次，防止某一端升级后静默漂移。

## 八份契约

| 文件 | 必填输入 | `data` 公共字段 | 关键约束 |
| --- | --- | --- | --- |
| `extract_project_profile.json` | `company_name`，且 `material_url/file_info` 至少一个 | `profile`、`field_details`、`conflicts` | 不返回供应商原始响应 |
| `query_track_labels.json` | `company_name`、`project_profile` | `tags` | profile 不得为空 |
| `query_comparable_valuation.json` | `tags` | `content` | `company_name` 可选；业务失败不能只看 HTTP |
| `match_listed_peers.json` | `tags` | `query`、`weights_used`、`peers`、`meta` | 自定义五项权重必须完整、合计 1.0，链条位置与产品服务合计至少 0.75；peers 使用中文业务键；`final_score` 为 RRF 排名分；每条 peer 含 `citations`（`source_name`/`source_url`/`quote`）供 Word 批注 |
| `match_investors.json` | `company_name`、`track_tags`、`project_profile`（勿臆测 `label_type`） | `candidates`（机构）、`counts`（含个人计数）、`shareholder_filter_applied` | 后一字段为假时不得宣称已排除股东；candidates 仅机构；个人见 `counts.internal_individuals_excluded`；每条 candidate 含 `citations` 供 Word 批注 |
| `query_company_registry.json` | `company_name` | `company` | 工商、行业、股东、主要人员摘要；不返回联系方式或供应商原始包。`company=null` 表示本次无结果 |
| `search_company_web.json` | `company_name`；可选 `search_keywords` | `company_name`、`searches` | 传入 `search_keywords` 后不再走默认模板；结果只含标题、链接、摘要和站点名 |
| `query_cbex_listing_financials.json` | `project_name`；可选 `detail_url`、`category` | `annual`、`latest`、`detail_url`、`candidates` | 金额单位为万元；多个候选时不返回财务，需带选定 `detail_url` 重试 |

所有输出都必须有：

```text
schema_version + tool + status + summary + data + sources + warnings
```

`status` 只允许 `success/partial/empty/failed`。失败 envelope 可以使用空 `data`；因此具体业务字段不能在所有状态下无条件设为 required。

## 契约变更规则

### 兼容变更

- 放宽可选输入，但保持旧输入仍有效；
- 在已有开放对象中增加可选字段；
- 改进 description、summary 或 warning 文案，不改变机器语义。

即使兼容，也必须同步两端测试和文档。

### 破坏性变更

- 删除/重命名字段或工具；
- 收紧 required、类型、enum、长度或数值约束；
- 改变 `status` 含义；
- 改变同一字段的单位、排序或数据来源语义。

破坏性变更必须提升 `schema_version`，并在同一发布批次同时修改 Data MCP producer、Report Agent consumer、环境工具清单、Skill 和测试；不得先单独发布一端。

## 修改一个工具的检查清单

1. 修改对应 JSON，并确认文件仍是合法 Draft 2020-12 Schema。
2. 修改 Data MCP feature 与 `mcp/responses.py`，确保只暴露 Agent 必需数据。
3. 修改 Data MCP `server.py` 入口签名或工具说明。
4. 检查 Report Agent `McpContractRegistry`、`DataMcpGateway` 和使用该字段的 Skill/写作逻辑。
5. 覆盖四种业务状态，特别是 `data={}` 的 `failed` 分支。
6. 跑两端 schema/unit/MCP transport 测试。

## 新增公共工具

除新建 schema 和 Data MCP 实现外，还必须修改：

- `apps/report_agent/src/report_agent/settings/models.py` 的标准工具集合；
- test/uat/prod 的 `report-agent.yaml`，以及 test 的本地 YAML；
- `apps/report_agent/skills/investment-report/SKILL.md` 的 `allowed-tools` 和流程；
- Data MCP readiness、工具选择、Evidence 和端到端测试；
- Data MCP/Report Agent/架构 README。

如果某能力只服务 Data MCP 内部，不需要被 Agent 自主调用，就不要为它新增公共 MCP 工具。

`query_company_registry`、`search_company_web` 与 `query_cbex_listing_financials` 已在 Data MCP 注册。Report Agent 的标准工具清单尚未纳入这三个工具；接入前不要把它们写成 Agent 的必调步骤。挂牌财务在 Data MCP 的 `agent_guidance` 中要求：先确认用户项目属于北交互联挂牌，再调用。

## 快速校验

```powershell
uv run --package bjs-data-mcp pytest apps/data_mcp/tests/unit/mcp apps/data_mcp/tests/integration/mcp
uv run --package bjs-report-agent pytest apps/report_agent/tests
```

相关实现：

- Data MCP：`apps/data_mcp/src/data_mcp/mcp/schemas.py`、`server.py`、`responses.py`
- Report Agent：`apps/report_agent/src/report_agent/infrastructure/mcp/contracts.py`、`application/data_gateway.py`、`harness/data_tools.py`
