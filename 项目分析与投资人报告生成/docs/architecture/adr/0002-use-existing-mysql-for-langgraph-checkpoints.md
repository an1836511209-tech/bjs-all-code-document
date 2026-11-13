# ADR-0002：使用现有 MySQL 承载 LangGraph checkpoint

- 状态：Accepted
- 日期：2026-09-09
- 对应批次：Batch 2 / Phase 1

## 背景

项目 test 环境已有 MySQL、Redis 和 MinIO，没有 PostgreSQL。此前目标架构把 PostgreSQL 写成默认持久化组件，但这不是现有基础设施约束，也会额外增加部署和运维成本。

LangGraph 官方直接维护 PostgreSQL 和 SQLite checkpointer，并提供自定义 checkpointer 的规范与一致性测试；MySQL 通过第三方 `langgraph-checkpoint-mysql` 接入。

## 决策

1. test、UAT、prod 统一复用现有 MySQL，不为 Report Agent 强制新增 PostgreSQL。
2. 使用 `langgraph-checkpoint-mysql[pymysql]`，依赖版本由 `uv.lock` 固定。
3. 第三方 saver 只能经 `report_agent.infrastructure.persistence` adapter 访问，业务层和 Harness factory 不直接拼接 MySQL DSN。
4. MySQL 配置继续使用现有 `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_DATABASE`、`MYSQL_USER`、`MYSQL_PASSWORD`、`MYSQL_CHARSET` 环境变量。
5. `saver.setup()` 只允许在显式数据库迁移任务中执行，worker/API 启动不得自动建表。
6. 集成环境必须使用专用 checkpoint schema，并满足 MySQL 8.0.19+ 或 MariaDB 10.7.1+。
7. LangGraph 或 MySQL saver 升级时，必须运行 checkpoint 一致性测试、并发测试和进程重建后的 session resume 测试。

## 后果

- 复用已有基础设施，减少一套数据库的部署、监控和备份成本。
- MySQL saver 并非 LangGraph 官方维护，存在版本兼容风险；adapter、锁版本和契约测试用于控制该风险。
- 共享业务库不会被应用启动过程隐式执行 DDL。
- 如果第三方 saver 后续无法满足一致性、性能或维护性要求，需要新增 ADR 决定自研 saver 或引入 PostgreSQL。

## 当前落实

- `report_agent.infrastructure.persistence.checkpoints` 已封装 MySQL DSN 和 saver 生命周期。
- `report-agent-db-migrate --apply` 当前只应用 Report Agent task/session/run/artifact 元数据表；API 启动不会自动执行 DDL。
- 2026-10-29 第一批：新建且显式启用的一页纸任务通过异步 adapter 接入专用 schema，已验证真实 MySQL 进程重建和 interrupt/resume。投资报告与旧任务保留原路径；具体边界见 [ADR-0003](0003-one-pager-resumable-harness.md)。
