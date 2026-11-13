# 对话工作台（独立前端）

投资报告 Agent 的**对话式工作台**。与 `apps/report_agent/src/report_agent/api/static/dev.html` 完全独立：

- 不修改任何 Python 代码（除 `api/app.py` 里挂载本目录的一小段）
- 纯静态（HTML + CSS + 原生 JS），无需构建
- 由 FastAPI 同端口提供：`http://127.0.0.1:8000/console`

## 设计原则

**对话是主入口，工作流是执行出来的。**

用户只做两件事：描述需求、在关键节点做决策。Skill、工具、MCP 调用是 Agent 在后台自动编排的，但**执行过程和结果全部呈现在对话流里**，而不是藏到单独的监控面板。

一条 Agent 消息里可以包含：

| 元素 | 说明 |
|---|---|
| 文本 | Agent 的自然语言回复（打字机呈现） |
| 执行计划 | 6 步 todo 卡片，实时更新状态与耗时 |
| 工具调用 | 每次 skill 工具 / MCP 调用的行内记录，带状态与耗时 |
| 确认卡 | 需要用户决策时内联出现（如"非优质信息是否展示"） |
| 文档卡 | 生成的 Word 产物，点击打开右侧 A4 预览 |

## 文件结构

```
frontend/
├── README.md
├── index.html                 # 主页面（按编号顺序加载 modules/*）
├── assets/
│   ├── styles/                # 样式分层（tokens → 各区块 → responsive → overrides）
│   ├── mock-events.js         # 一次完整 one-pager 对话脚本（必须最先加载）
│   ├── modules.order.json     # 模块加载顺序（与 index.html 保持一致）
│   └── modules/
│       ├── 00-util.js         # $ / $$ / esc / svg / ICON / lazy 绑定
│       ├── 01-config.js       # SKILL_PLANS / TOOL_STEP_HINTS / STORAGE_KEY
│       ├── 02-dom.js          # el 映射表 + 顶栏状态 / 计时 / 侧栏 / 弹窗
│       ├── 03-state.js        # ui / state / runtimeOf / withRuntime / 持久化
│       ├── 04-plan.js         # 执行计划面板
│       ├── 05-tools.js        # 工具调用折叠组
│       ├── 06-approval.js     # 确认卡与提问卡
│       ├── 07-message.js      # 消息流
│       ├── 08-files.js        # 本对话文件区
│       ├── 09-document.js     # 文档卡 / A4 预览 / 产物页签
│       ├── 10-run.js          # SSE 订阅、live 与 mock 播放器、事件派发
│       ├── 11-workbook.js     # 投资机构匹配表附件
│       ├── 12-sidebar.js      # 项目树与对话切换
│       ├── 13-composer.js     # 输入区 / 草稿 / 附件 / 发送
│       ├── 14-session.js      # 会话恢复与标题
│       └── 99-boot.js         # 启动序列（唯一允许依赖全部模块的文件）
├── tests/
│   ├── dom-contract.cjs       # 纯文本：id 契约 + el 映射表一致性
│   ├── dom-smoke.cjs          # CDP 冒烟：下拉框 / 侧栏 / 焦点环 / mock 播放
│   └── *.cjs                  # 端到端用例（需要 Playwright + mock server）
└── docs/
    ├── event-contract.md      # 前后端共享的事件契约
    └── module-architecture-spec.md  # 模块拆分的规格与迁移记录
```

### 模块约定

- **无构建**：经典 `<script>` 顺序加载，没有打包器与 TypeScript。
- **只有一个全局**：`window.BP`，每个模块挂一个命名空间（`BP.plan` / `BP.run` …）。
- **跨模块引用走 lazy 绑定**：对象用 `BP.lazy(ns, key)`（转发 Proxy），函数用箭头函数转发，
  原始值（布尔/字符串）用访问函数 `() => BP.ns.NAME`。这样模块之间即使互相引用（`el ↔ state`）
  也不依赖加载顺序，只要**调用发生在 99-boot 之后**。
- **新增功能放对模块**：按职责放进 `modules/NN-*.js`，不要往 `index.html` 里塞内联脚本。
- **改 DOM id 先跑** `node tests/dom-contract.cjs`。


## 访问方式

### 1. 同端口服务（推荐）

```
http://127.0.0.1:8000/console
```

`/console` 会 307 跳转到 `/console/`，静态资源在 `/console/assets/*`。

实现见 `apps/report_agent/src/report_agent/api/app.py`：

- `_resolve_frontend_dir()` 默认解析 `<repo>/frontend`，可用 `REPORT_AGENT_FRONTEND_DIR` 覆盖
- `GET /console/` 返回 `index.html`
- `app.mount("/console/assets", StaticFiles(...))`
- 不受 `dev_ui_enabled` 限制

### 2. 直接双击（设计用）

`file://` 打开 `index.html` 也能看 Mock 演示，API 默认指向 `http://127.0.0.1:8000`。

### 3. 真实事件流

```
http://127.0.0.1:8000/console/?run=run_xxx&mode=live
```

或点右上角「真实」模式切换。

> 后端尚未提供 SSE 端点，见 `docs/event-contract.md`。

## 对话脚本（Mock）

`mock-events.js` 是一段完整对话：

1. 用户提问
2. Agent 回复并展示 6 步执行计划
3. 逐条调用工具（`parse_materials`、`extract_project_profile`、`match_investors`…）
4. 中途内联确认「非优质信息是否展示」
5. 完成后出现文档卡，自动打开右侧预览

默认 2× 速，约 8 秒看完；右下角可切 1× / 2× / 4×。

## 事件契约

见 `docs/event-contract.md`。前端消费的对话事件：

| 事件 | 呈现 |
|---|---|
| `ai.say` | 追加一段 AI 文本 |
| `skill` | 顶部 Skill 徽章 |
| `plan.add` / `plan.update` | 执行计划卡 |
| `tool.start` / `tool.end` | 行内工具记录 |
| `approval` | 内联确认卡（暂停，等待选择） |
| `doc.ready` | 文档卡 + 右侧预览 |
| `done` | 结束本轮 |

Live 模式下，后端 `AgentEvent` 会被映射到同一套 UI：`todo.updated` → 计划卡，`tool.started/completed` → 工具行，`approval.required` → 确认卡，`artifact.validated` → 文档卡。

## 设计取舍

1. **不把执行过程做成独立面板**：用户在看对话，不该为了看进度而切换视图。
2. **确认卡内联**：决策发生在它影响的上下文旁边，而不是全屏弹窗。
3. **`partial` / `empty` 用橙色**：Skill 规定 Data MCP 的局部失败不连锁放弃，UI 不能渲染成失败。
4. **文档卡点击才打开预览**：避免完成瞬间强制跳转打断阅读；完成后自动滚到卡片。
5. **产物未发布不显示下载**：`artifact.created` 只显示"生成中"，`artifact.validated` 才可下载。

## 后续

- 后端加 `GET /api/runs/{run_id}/events`（SSE）与 `POST /api/runs/{run_id}/resume`
- 补 `todo.updated` / `step.started|completed` / `tool.progress` 三类事件
- 如需嵌入正式产品，`assets/` 下的三份文件可直接迁到任意框架，事件契约不变
