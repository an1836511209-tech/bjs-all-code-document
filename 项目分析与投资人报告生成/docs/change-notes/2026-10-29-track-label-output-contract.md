# 赛道标签输出与 MCP 契约不一致

问题：`query_track_labels` 已获得标签后，MCP 输出校验报 `data` 不允许出现 `source`、`local_recall_used`。公共契约 `contracts/mcp/query_track_labels.json` 只允许 `data.tags`，但 `adapt_track_labels` 不区分来源地输出了两个内部追踪字段。其影响范围包含 API 平台、HiAgent 兜底与本地召回，和输入画像使用字符串还是对象无关。

两个技能共用同一个 Data MCP server、输出适配器与契约，并没有一页纸专属的打标签服务。本地历史任务 `task_11e9c0ea4c9441f4975060202a8d843b` 的目标是“生成投资报告”、最终状态为 completed，但其 `query_track_labels` 证据也保存了同样的 VALIDATION 失败。因此，报告最终完成不代表标签步骤成功；不同环境或已缓存证据也不能作为两条路由契约相同的反证。

修复计划：维持严格的公共契约，`data` 仅返回业务字段 `tags`；保留既有 `sources` 并在其中显式标明 local_recall 使用状态。不要通过放开 additionalProperties 绕过校验，也不要因为校验失败丢弃已经获得的标签。

已实现：`adapt_track_labels` 的 `data` 仅保留 `tags`，来源仍通过 sources 的 lms、hiagent、taxonomy 表达，新增 local_recall 来源使用状态以保留原本的追踪含义。没有放宽 schema，也没有修改各来源的标签算法或吞掉上游告警。

验证：39 项标签契约、标签服务及补充工具测试通过。覆盖 API / fallback / local_recall 三来源、非空/空标签、对象/字符串画像、MCP server 完整入口及 Report Agent 的公共契约验证。测试中的模型和供应商调用均为模拟，未请求真实数据源。Ruff、类型检查和差异空白检查通过。

生效需要重启实际提供 `query_track_labels` 的 Data MCP 服务。已落盘的失败 evidence 不会自动变为成功；需要重新执行标签查询。若 Agent 或 Data MCP 使用 `DATA_MCP_CONTRACTS_DIR` 指向其他版本目录，应同步检查其契约版本；本次保留仓库标准 data.tags 契约不变。
