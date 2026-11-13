# 架构文档导航

本目录把“当前事实”“架构决策”和“历史迁移材料”分开维护。开发同学排查或扩展功能时，按下列顺序阅读，不要从 `archive/` 推断当前实现。

## 推荐阅读顺序

1. [Data MCP 当前标准架构](data-mcp-standardized-architecture.md)：五项数据能力、内部数据源、状态归一和已知限制。
2. [MCP 交互契约](../../contracts/mcp/README.md)：两个服务之间的唯一共享接口、双端校验和变更规则。
3. [Report Agent 当前架构](report-agent-architecture.md)：API、Harness、Prompt、Skill、上下文、Evidence、Markdown、Word 和发布主链。
4. [环境配置与部署](../../deploy/environments/README.md)：test/UAT/prod 的配置职责、启动、迁移和运维。
5. ADR：已经接受且仍约束当前实现的关键决策。

分批设计：[一页纸 BP 持久检查点与恢复位置](2026-10-29-one-pager-checkpoint-resume-design.md)。第一批实际恢复能力与启用边界见 [ADR-0003](adr/0003-one-pager-resumable-harness.md)；固定业务图与完整降调用目标仍待后续实施。

## 当前系统关系

```text
用户材料
  -> Report Agent 材料解析
  -> Material Evidence ───────────────┐
                                      v
用户目标 -> Skill + Deep Agent -> 报告 Markdown -> ReportContent -> Word -> MinIO
                         |
                         v
                  contracts/mcp
                         |
                         v
                     Data MCP
        外部 API / MySQL / Excel / Embedding / Rerank
                         |
                         v
                  Data MCP Evidence ───┘
```

两个 Evidence 来源最终都用 `evidence_id` 约束报告事实；Data MCP 不管理 Agent workspace，Report Agent 不读取 Data MCP 内部结构。

## 文档分类

| 分类 | 文件 | 维护规则 |
| --- | --- | --- |
| 当前架构 | `data-mcp-standardized-architecture.md`、`report-agent-architecture.md` | 代码、契约或主链改变时同批更新 |
| ADR | `adr/*.md` | 决策变化时新增 ADR；不篡改历史背景 |
| 历史归档 | `archive/*.md` | 只用于理解迁移原因，不作为当前开发契约 |
| 运维 | `deploy/environments/README.md` | 配置字段、启动方式或环境拓扑改变时更新 |
| 接口 | `contracts/mcp/README.md` + JSON | 公共字段/工具改变时两端同批更新 |

## 变更影响速查

| 你要改什么 | 至少检查 |
| --- | --- |
| Data MCP 数据源或算法 | feature、response adapter、契约语义、四状态、Data MCP 架构 |
| MCP 字段或新增工具 | 五份/新增 JSON、两端 schema、环境工具清单、Skill、readiness、两端 README |
| Agent 写作行为 | `investment-report/SKILL.md`、references、Markdown parser、真实材料验收 |
| 上下文/大结果 | middleware、Context Store、环境阈值、消息完整性和恢复测试 |
| Word/批注 | ReportContent、Word service/scripts、artifact 版本、结构/视觉门禁 |
| 部署配置 | Settings、三环境 YAML、test local YAML、Compose/Dockerfile、部署 README |

## 当前边界

- 系统已经完成同步开发链路，但不是异步生产任务平台。
- 报告主模型已从旧 `ReportDraft/FactClaim` 切换为 `ReportContent`，并以 Markdown 作为模型编辑界面。
- MySQL 元数据持久化已接入。一页纸可显式启用专用 MySQL checkpointer 和卡片恢复；投资报告仍使用原执行路径。Redis 队列尚未接入。
- Word 结构校验已进入发布门禁；视觉渲染是否执行由环境配置控制，并需与实际工具面共同验收。

若文档与运行代码冲突，以当前代码、JSON Schema 和环境配置为事实，并在同一改动中修正文档。
