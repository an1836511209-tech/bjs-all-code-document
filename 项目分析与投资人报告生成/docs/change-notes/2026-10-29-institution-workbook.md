# 可选投资机构匹配 Excel 与独立附件任务

日期：2026-10-29。对应 [实现计划](../superpowers/plans/2026-10-28-institution-match-workbook.md)。

## 用户行为

聊天框增加“附带投资机构匹配表”，默认关闭。开启后，选项保存在当前对话中，回答补充卡片时继承；关闭时不触发附件导出。选项通过表单独立传递，不作为用户消息进入模型。

Word 先完成并交付，独立 worker 随后处理持久化辅助任务。成功时，右侧新增 Excel 页签、前 20 行预览和稳定下载入口，不抢当前 Word 的预览焦点；失败、取消和重试只修改附件任务，不重新启动报告 Agent、不修改原报告完成状态和内容。

## 实现边界

- 新 MCP `export_matched_institutions` 只查询 DMP 机构，固定 offset=0、limit=200，一次请求，无分页与自动重试。原 `match_investors` 的机构/个人、内部库和裁剪规则保持原实现。
- 四列：投资机构名称、权重分数、匹配标签数（接口）、匹配到的标签。最后一列仅为实际查询标签与 `label_name_list` 的完整名称交集；保留接口数量，不猜补差异。
- 当前项目的材料哈希、画像、标签证据与用户补充被固定成快照。少量可信标签直接复用；超过默认 5 个或来源需复核时，最多一次模型选择，并验证标签属于候选、引用属于材料原文。也可以手动选择或单独更新标签。
- 新主体画像会使旧主体标签失效。旧任务缺少可信来源关联时跳过附件，不能靠“最近一次标签”猜测。
- 辅助任务使用新表 `report_agent_auxiliary_jobs`。领取、阶段保存和附件追加均独立提交；不调用主报告的 `finish()`。过期领取无法追加附件，外部请求结果未知时不自动重放。
- 同上下文重试可复用已保存的合法选择和工作簿；上传失败不要求再次调用模型和 DMP。每个新附件仍使用自己的任务/辅助任务对象键。
- 单 worker、单并发；DMP 实际流量上限 64 MiB、Excel 上限 2 MiB、总预算默认 120 秒。Base64 与原始长标签列表不写入主报告证据、模型消息或日志。

## 本地接入

`deploy/environments/test/report-agent.local.yaml` 开启服务能力，用户复选开关仍默认关闭。其他环境保持默认关闭。

详细命令见 [本地启动说明](../../report-agent-本地启动说明.md)。在仓库根目录：

```powershell
# 已有主业务表时，首次升级只添加附件表
.\scripts\start-local.ps1 migrate-workbook

# 分别在三个终端运行
.\scripts\start-local.ps1 mcp
.\scripts\start-local.ps1 api
.\scripts\start-local.ps1 workbook-worker
```

正式入口使用 MySQL repository；`inmem_server.py` 不能与独立 worker 共享任务状态。API 与 worker 必须使用相同工作区、数据库和环境变量。worker 使用工作区 OS 锁，本期适用于同机共享目录；容器部署需要另外配置 worker 服务及共享卷，本次没有启用容器或生产环境。

## 验证与限制

新增测试覆盖标签规范化与交集、脏数据、真实 XLSX、契约与文件校验、上下文归属、用户补充快照、选择次数、重复发现、上传重试、主报告失败隔离和 API 预览下载。另有专用 MySQL 集成测试验证并发领取、幂等追加、重启中断恢复和过期结果拦截；集成数据使用独立测试库。

浏览器回归使用真实前后端和真实 XLSX，替换外部 DMP/对象存储：验证默认关闭、Word 先交付、Excel 不抢焦点、刷新后恢复、关闭时无导出请求、附件失败保留原报告。

真实外部服务的连通性及完整报告耗时仍取决于测试环境。不得把浏览器替身测试当作真实 DMP、模型精选和 MinIO 全链路验收。

### 本次复验结果

- Data MCP：18 项新增导出测试与 29 项既有匹配/补充工具测试，合计 47 项通过。
- Report Agent：22 项附件测试与 58 项原执行、设置、卡片、下载、检查点测试通过；其中原检查点的 1 项专用数据库用例因未启用对应标志跳过。
- 辅助任务专用 MySQL 集成测试：1 项通过，验证并发领取、幂等追加、取消后的迟到结果和请求结果未知时不自动重放。
- 按不同用例去重合计 128 项通过、1 项跳过；浏览器测试通过，pageerror 为零。Ruff、7 个新增模块的 Mypy（包含未标注函数体检查）、JavaScript 语法与 diff 空白检查通过。
- 已用 `scripts/start-local.ps1 migrate-workbook` 在配置的测试数据库执行 003 迁移，创建附件表；未更改原任务/报告数据。未重启用户现有 API/MCP 进程。
- 合成负载：响应 6,704,193 字节、200 行，精简行 JSON 26,782 字节，Excel 11,235 字节；处理 2.88 秒，tracemalloc 观察到约 20.1 MB 的 Python 分配峰值。这不代表真实网络耗时、进程 RSS 或 64 MiB 上限下的压力结果。

复验命令（Python 使用仓库 `.venv`）：

```powershell
# 在 apps/data_mcp 下
python -m pytest tests/unit/features/investor_match/test_workbook.py tests/unit/features/investor_match/test_investor_match.py tests/unit/mcp/test_supplemental_tools.py -q

# 在仓库根目录
python -m pytest apps/report_agent/tests/unit/test_institution_workbook.py -q
python -m pytest apps/report_agent/tests/unit/test_async_runs.py apps/report_agent/tests/unit/test_settings_loader.py apps/report_agent/tests/unit/test_conversation_interactions.py apps/report_agent/tests/unit/test_business_type_question.py apps/report_agent/tests/unit/test_registry_correction.py apps/report_agent/tests/unit/test_download_links.py apps/report_agent/tests/unit/test_one_pager_checkpoints.py -q
$env:BJS_WORKBOOK_INTEGRATION='1'
python -m pytest apps/report_agent/tests/unit/test_institution_workbook_mysql.py -q
```

浏览器验收使用独立 `frontend/tests/institution_workbook_server.py`（8024）与 `frontend/tests/institution-workbook.cjs`。测试进程已停止。前端重新验收时应启动新的 fixture 进程，避免复用上轮内存任务状态。

真实联调未执行：自动审批拒绝了“一次真实 DMP 查询并将结果临时上传/下载到 MinIO 后删除”的测试，指出运行时凭据、真实机构数据及外部暴露范围需要用户明确授权。该拒绝不影响已完成的本地测试，也不能视为外部接口不可用。
