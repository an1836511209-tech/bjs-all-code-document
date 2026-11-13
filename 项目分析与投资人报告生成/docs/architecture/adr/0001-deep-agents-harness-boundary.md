# ADR-0001：采用 Deep Agents 并设置项目适配边界

- 状态：Accepted
- 日期：2026-09-09
- 对应批次：Batch 1 / Phase 0

## 背景

Report Agent 需要自主规划、文件操作、上下文压缩、Skill 和可恢复会话，但业务范围仅限基于材料与 Data MCP 数据生产 Word。旧分支自行维护 Agent、MemorySaver、Skill 激活和上下文修补，已出现 API/UI 状态不一致、动态 Skill 不生效和私有 graph 耦合。

## 决策

1. 采用 Deep Agents/LangGraph 作为唯一 Agent Harness 基座。
2. 第三方 Harness 只能由 `report_agent.harness.factory` 构建，业务层不得直接依赖 `deepagents` 私有实现。
3. 模型、backend、tools、checkpointer 和 store 通过项目自有 `AgentBuildSpec` 注入。
4. 任务、会话、执行和工作空间使用不同标识，不再以单一 `task_id` 兼任全部职责。
5. Deep Agents 版本由 `uv.lock` 固定；升级必须重新运行 Harness 集成测试。
6. 不保留旧 Agent 内核作为运行时回退路径。框架缺口通过 adapter 或自有 middleware 解决。

## 已验证

- 解析版本：`deepagents==0.5.9`、`langchain==1.4.0`、`langgraph==1.2.11`。
- `create_deep_agent` 接受 model、backend、tools、checkpointer 和 store 等目标扩展点。
- 通过 fake tool-aware chat model 构建真实 Deep Agent graph。
- 同一 `thread_id` 的第二轮调用能读取第一轮 checkpoint 消息。
- 测试不调用外部模型，不依赖密钥和网络服务。

## 后果

- 项目可以复用规划、filesystem、summarization 和 Skill 等标准能力。
- 对框架版本变化的影响集中在 factory/middleware/backend adapter。
- 当前实现通过项目 adapter 组装 Deep Agents、Skill 工具白名单、项目自有上下文压缩、消息完整性保护和 Bubblewrap/filesystem backend。2026-10-29 起，一页纸新任务可显式启用 MySQL checkpointer 与真实恢复；投资报告及旧任务保持原路径，详见 [ADR-0003](0003-one-pager-resumable-harness.md)。
