# Data MCP 当前标准架构

> 状态：当前实现说明
>
> 事实基线：`apps/data_mcp`、`contracts/mcp` 与三套环境配置
>
> 更新日期：2026-09-11

## 1. 定位

Data MCP 是 Report Agent 的事实、计算、候选匹配与来源服务。它回答“可用数据是什么、结果如何计算、发生了什么降级”，不理解 Agent workspace，不决定报告章节，也不生成 DOCX。

设计边界：

1. feature 内部可适配供应商和存储结构，对外只暴露稳定契约。
2. MCP 工具是只读业务能力；环境在进程启动时选择，不允许调用者传 `env` 跨环境路由。
3. 每次调用在 feature 前校验输入、在返回前校验输出。
4. 对 Agent 最小披露：保留可写作数据和业务 warning，隐藏凭据、路径、SQL、堆栈和原始供应商响应。
5. 业务结果由 `status` 表达，不能用 HTTP/MCP 传输成功替代。

## 2. 组件与依赖

```text
entrypoints.py
  -> mcp/server.py (MCPServer, stdio / Streamable HTTP)
     -> mcp/schemas.py -> contracts/mcp/*.json
     -> features/<capability>/service.py
        -> shared/settings.py
        -> shared/http/retry_client.py
        -> shared/integrations/*
        -> MySQL / Excel / Embedding / Rerank / external APIs
     -> mcp/responses.py
     -> mcp/tool_errors.py
```

依赖方向是 `MCP boundary -> feature -> shared adapter`。feature 的返回值允许包含内部诊断字段，但只有 `responses.py` 选择的字段能跨服务。

## 3. 公共调用生命周期

```text
1. MCP SDK 解析 tool arguments
2. server.py 构造公共 payload
3. validate_tool_input(tool, payload)
4. 调用 feature service
5. adapter 将内部结果变为统一 envelope
6. validate_tool_output(tool, envelope)
7. MCP SDK 返回 structured content
```

发生异常时，`guard_tool_errors` 记录服务端异常，把校验、上游或内部异常转换为经过输出契约校验的安全 `status=failed` envelope。调用方只看到可执行的业务级说明，不会得到配置、响应正文或堆栈。

## 4. 统一 envelope

```json
{
  "schema_version": "1.0",
  "tool": "query_track_labels",
  "status": "partial",
  "summary": "本次获得 2 个赛道标签",
  "data": {"tags": ["示例标签"]},
  "sources": [{"name": "hiagent", "status": "used"}],
  "warnings": [
    {"code": "DATA_INCOMPLETE", "message": "主数据源不可用，已降级", "retryable": false}
  ]
}
```

| 状态 | 判定 | Agent 使用规则 |
| --- | --- | --- |
| `success` | 有数据且 adapter 未接收到 warning | 可使用数据 |
| `partial` | 有数据，同时存在 warning/降级 | 只使用可验证子集，披露限制 |
| `empty` | 调用完成，但核心结果为空或识别为无结果 | 不写对应事实 |
| `failed` | 合法失败 envelope，通常 `data={}` | 不读取预期业务字段 |

当前 `responses.envelope()` 的通用规则是：`empty` 优先，其次有 warning 则为 `partial`，否则为 `success`。各 adapter 必须正确识别自己的“核心结果为空”。

## 5. 数据链

### 5.1 项目画像 `extract_project_profile`

输入：企业全称，加 `material_url` 或 `file_info` 至少一个；可选用户补充和搜索词。

```text
材料 URL/正文
  -> 材料正文归一
企业名称
  -> 企查查工商/上市/行业摘要
搜索词
  -> 智谱网页搜索摘要
上述上下文
  -> HiAgent 项目画像
  -> 固定画像字段 + field_details + conflicts + warnings
  -> adapt_project_profile
```

字段级详情保留 `supported/inferred/conflicted/missing`、置信度、推断依据和可公开证据。公共响应不返回企查查、智谱、HiAgent 原始包。

扩展注意：新增画像字段要同步固定字段列表、HiAgent 输出约束、归一逻辑、契约、下游 Skill 与测试；只改 Prompt 会造成字段被归一层丢弃。

### 5.2 赛道标签 `query_track_labels`

输入：`company_name + project_profile`。

```text
LMS 已配置
  -> 调用 LMS，按配置次数和间隔重试
  -> 有标签：返回
  -> 失败/空：记录 warning
LMS 未配置或无有效结果
  -> HiAgent fallback
  -> taxonomy 白名单过滤
  -> 去重标签
```

本地 taxonomy 只做结果校验，不再承担本地召回。若 taxonomy 不可用，结果会保留但标记 warning；无有效标签则为 `empty`。

### 5.3 历史成交估值 `query_comparable_valuation`

输入：赛道标签（必填）、可选企业全称。

```text
tags -> format_tags_for_state -> HiAgent state.tags
company_name -> HiAgent state.company_name（可空）
userChatInput -> 固定空串
  -> HiAgent chat completions
  -> choice/choices content 合并
  -> adapt_comparable_valuation -> data.content
```

`tags` 不应被改写到自然语言 `userChatInput`。feature 内部会保留 `choice/state` 便于测试和诊断，但公共契约只返回 `content`。

已知边界：adapter 目前只把空正文及少量“未找到/无可比”短语识别为 `empty`。上游若用 HTTP 200 返回其他业务失败文案，仍可能误判为 `success`；修改该能力时应优先增加结构化错误识别或明确的失败短语测试。

### 5.4 上市公司匹配 `match_listed_peers`

输入：`tags`；可选 `summary/top_n/field_weights`。

```text
tags + summary -> 多路检索（摘要语义 / 标签+行业语义 / 关键词补召回）
Excel 目录 -> 合并/去重上市公司语料
各路 top_k_recall -> Reciprocal Rank Fusion
top_n -> 公共 peers（assessment_status=not_assessed）
```

五字段是产业链位置、产品服务、赛道标签、目标客户、盈利模式。自定义权重必须提供全部五项、总和约等于 1，且产业链位置与产品服务的合计不低于契约阈值。

候选身份与估值为中文顶层键（证券代码/证券名称/PE 等）。`final_score` 是 RRF 排名分，不是可比概率；`enable_rerank` 不参与 v2 主路径。

公共 `meta` 只保留 matching_version、score_kind、语料规模、召回数、是否重排和 embedding backend；数据目录和源文件列表不会跨服务。

已知边界：retrieval_v2 只提供待核验线索，不做业务可比性判定；没有独立的“无有效候选”硬阈值；`top_n` 代表截断数量，不代表结果一定业务相关。

### 5.5 投资人匹配 `match_investors`

输入：企业全称、赛道标签、项目画像。`label_type` 由服务端固定为「股权转让/增资」，agent 无需填写。

```text
DMP 首选（label_type 固定；label_name=赛道标签）：
  investor_type=机构 -> items 作内部机构候选
  investor_type=个人 -> 仅取 total/count 写入 individual_count
  机构调用失败 -> MySQL 内部库 fallback

企业名称 -> 企查查股东名单
内部机构候选 -> 股东过滤 -> 按分数截断

project_profile + tags -> HiAgent 网络候选
网络候选 -> 股东过滤 -> 与内部机构去重 -> 截断

内部机构 + 网络机构 -> candidates
```

个人投资人只进入内部计数（`counts.internal_individuals_excluded`），不进入公共合并列表。企查查失败时仍可返回候选，但 `shareholder_filter_applied=false` 且 response 为 `partial`；Report Agent 必须披露“可能包含现有股东”。

已知边界：多标签当前不做累计覆盖度；内部过滤尚未覆盖全部冻结、清退、不接受推荐等业务状态；公共候选还未拆分机构名、联系人名和内部稳定 ID。

### 5.6 企业工商补充 `query_company_registry`

输入：企业全称。

```text
企业名称
  -> 企查查 ECIInfoVerify/GetInfo（与项目画像、投资人股东过滤同一接口）
  -> 工商、行业、股东、主要人员摘要
  -> adapt_company_registry
```

公共响应不返回联系方式、Logo 和供应商原始包。状态 `201` 或无 Result 为 `empty`。该工具只补充报告事实，不生成项目画像。

### 5.7 公开网页补充 `search_company_web`

输入：企业全称；可选补充检索词。

```text
未传 search_keywords
  -> project_profile.zhipu.query_templates
传入 search_keywords
  -> 只检索这些词，并带上企业全称
  -> 智谱 Web Search
  -> 标题、链接、摘要、站点名；跨查询按 URL 去重
  -> adapt_company_web_search
```

部分查询失败且仍有结果时为 `partial`。全部查询都失败时为 `failed`。搜索摘要不是已审计事实。

Report Agent 标准工具清单尚未包含这两个工具。

### 5.8 北交互联挂牌财务 `query_cbex_listing_financials`

输入：挂牌项目全称；可选官网详情 URL 和挂牌类型。

```text
用户已确认是北交互联挂牌项目
  -> 按项目全称检索 otc.cbex.com 四类挂牌列表
  -> 唯一匹配则打开详情页
  -> 解析「主要财务指标」表，金额统一为万元
  -> adapt_cbex_listing_financials
```

多个同名候选或搜索未完成时返回候选，不提取财务。`quality_status=multi_year_extracted` 且无质量问题为 `success`；有数据但存在解析问题为 `partial`；没有匹配项目为 `empty`。公共响应不返回页面 HTML。Report Agent 标准工具清单尚未包含该工具；Data MCP `agent_guidance` 规定须在用户确认挂牌后再调用。

## 6. 配置与外部调用

```text
runtime.env
  DATA_MCP_CONFIG -> deploy/environments/<env>/data-mcp.yaml
  DATA_MCP_CONTRACTS_DIR -> contracts/mcp
```

`shared/settings.py` 负责仓库相对路径解析、环境块选择和 feature 配置。配置按 `project_profile`、`track_labels`、`historical_valuation`、`listed_peer_match`、`investor_match`、`investor_network` 等业务域组织。

共享 HTTP 重试只覆盖连接错误、超时、429 和 5xx；明确的参数/鉴权类 4xx 不应盲目重试。feature 自己的业务 fallback 与 HTTP transport retry 是两层不同机制。

传输：

- stdio：本地 MCP Host、Inspector 和协议集成测试；stdout 必须保持协议干净。
- Streamable HTTP：Report Agent 和独立服务调用，固定 `/mcp`。
- CLI feature 直调：诊断入口，不受公共 response adapter 约束，不能作为跨服务契约。

## 7. 与 Report Agent 的连接

Report Agent 不直接使用 Data MCP 的 `DataMcpClient` 或 feature。生产链路为：

```text
Report Agent StructuredTool
  -> 本地契约校验
  -> StreamableHttpMcpTransport
  -> Data MCP
  -> 本地契约再校验
  -> 完整 envelope 写 WorkspaceEvidenceStore
  -> 轻量 EvidenceView 返回模型
```

Data MCP 只负责提供事实；Evidence ID、workspace 持久化、Markdown 写作、citation、Word 批注和发布都属于 Report Agent。

## 8. 修改与扩展

### 修改现有 feature

1. 明确内部数据变化是否改变公共语义。
2. 先更新契约或确认无需更新。
3. 在 feature 中处理数据源、fallback 和内部诊断。
4. 在 `responses.py` 中做状态、来源、warning 和最小披露。
5. 覆盖 success/partial/empty/failed，特别是 HTTP 200 业务失败。
6. 跑 feature、MCP schema、stdio/HTTP 集成和 Report Agent consumer 测试。

### 新增公共工具

新增工具是双服务发布：必须同时更新 Data MCP server/guidance/adapter、`contracts/mcp`、Report Agent 标准工具清单和环境 YAML、Skill、readiness、Evidence 与端到端测试。若只需内部组合，优先留在现有 feature 内。

## 9. 验证基线

```powershell
uv run --package bjs-data-mcp pytest apps/data_mcp/tests
uv run --package bjs-data-mcp ruff check apps/data_mcp/src apps/data_mcp/tests
uv run --package bjs-data-mcp mypy apps/data_mcp/src/data_mcp
```

真实外部验收至少验证：工具发现、五工具四状态、历史估值 state 映射、股东过滤标志、公共响应无 raw/凭据/内部路径，以及 Report Agent 能按同一契约保存和读取 Evidence。
