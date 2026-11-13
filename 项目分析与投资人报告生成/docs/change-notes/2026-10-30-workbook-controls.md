# 附件开关无响应与隐藏 URL 入口

日期：2026-10-30。

## 现象与原因

本机 8000 的 `/api/features` 实际返回 `institution_workbook.enabled=false`、`worker_online=false`。进程检查确认用户启动的是旧的 `apps/report_agent/scripts/inmem_server.py`；该入口没有向 API 注入附件服务。前端遇到功能关闭/读取失败就禁用复选框，并同时隐藏说明区域，因此只有“点击没反应”的表现。

另一个独立条件是 worker：只有 MCP 与 API 两个进程不会执行持久化辅助队列。缺 worker 不应禁用选择开关，但应明确显示待启动状态。

## 修复

- 旧 `inmem_server.py` 命令在配置开启附件时转到正式持久化 API，保证 API 和独立 worker 共享 MySQL；配置关闭时保留原内存模式。旧进程须重启后生效。
- 后端可选服务初始化失败记录异常类型，避免无声禁用；不记录凭据或完整异常载荷。
- 前端始终显示附件状态。功能关闭、读取失败、报告执行中分别说明原因；报告运行期间锁定本轮选项。
- worker 未启动时允许勾选，显示启动后才会处理附件。提供“刷新状态”操作，网络/服务恢复后重新读取能力；返回页面也按时间间隔刷新。状态检查不创建 run、不写聊天消息。
- 隐藏 URL 按钮，保留 DOM 节点和既有处理逻辑，避免破坏初始化与历史草稿。增加明确的 hidden 样式，并更新脚本/样式版本号。

## 验证

`test_local_entrypoints.py` 覆盖旧入口在开启/关闭配置下的持久化选择；`workbook-controls.cjs` 覆盖不可用原因、worker 未启动时可勾选、状态恢复、选项保留、URL 隐藏和零报告提交。另回归现有附件任务测试及 `institution-workbook.cjs` 的生成、预览下载和失败隔离。

结果：旧入口与附件单元测试共 24 项通过；两组浏览器测试通过，pageerror 为零。Ruff、JavaScript 语法和 diff 空白检查通过。本机 MCP 工具清单已确认包含 `export_matched_institutions`，无需为此重启 MCP。

本次仅做本地替身测试与本机服务只读诊断，未调用真实 DMP/模型，也未启动用户业务 worker。用户现有 API/MCP 进程未被中断。

## 使用

在原 API 终端 Ctrl+C 后运行 `scripts/start-local.ps1 api`；MCP 已加载导出工具时可保持运行。另开终端运行 `scripts/start-local.ps1 workbook-worker`。刷新 `/console/` 即可加载新 UI，点击“刷新状态”可复查服务状态。详细步骤见 [本地启动说明](../../report-agent-本地启动说明.md)。
