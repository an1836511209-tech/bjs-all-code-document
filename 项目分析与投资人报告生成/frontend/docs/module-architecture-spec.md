# 前端模块拆分架构 Spec

> **文档性质**：重构规格（Architecture Spec），不是评估报告。
> **对象**：`frontend/assets/console.js`（2365 行，单文件 IIFE）+ `frontend/assets/console.css`（860 行）
> **基线**：`a6773e4`
> **方法**：静态量化分析（函数级调用图 + 跨簇依赖边 + 状态字段引用统计）+ Chrome headless 实测 + 子代理独立设计
> **状态**：待评审

---

## 0. TL;DR

| 结论 | 依据 |
|---|---|
| **可以拆，但不能用 ES Modules** | 实测 `file://` 下 `<script type="module">` **被 CORS 拦截，模块不执行**。README.md:56-58 承诺 `file://` 可用 |
| **用经典 `<script>` + `window.BP` 命名空间** | 实测 `file://` 下多文件按序加载、共享命名空间、启动序列 —— **全部正常** |
| **新文件必须放 `frontend/assets/` 下** | `api/app.py:245-249` 只挂载了 `/console/assets` |
| **不能同时修 P0 和重构** | 两件事改同一批行（`console.js:1918` 等），会互相掩盖。**先修 P0，再重构** |
| **真正的症结不是"文件太大"，是双份真相源** | `runtime` 的 **13/17 个字段在全局 `state` 里有副本**，换栈机制只为同步这两份 |
| **消除换栈不用改 74 个函数** | 用 **getter 代理**：`runtime` 本就拥有那 13 个字段，把 `state` 的对应字段变成 runtime 的**视图**即可。改动只在 `03-state.js` 内部约 25 行 |
| **有一处隐藏约束极易踩中** | `tests/conversation-titles.cjs` **把 `console.js` 当文本切片** → `fallbackTitle`/`maybeAutoTitle` 不能搬家 |

**推荐方案**：13 个模块文件 + 保留 `withRuntime` 作为过渡适配层，**分 5 个批次迁移**，每批可独立验证与回滚。预计总工作量 3–5 天。

---

## 1. 为什么现在要拆

### 1.1 规模

| 指标 | 数值 |
|---|---|
| `console.js` 总行数 | **2365** |
| 顶层函数 | **89** |
| 正式的 section 分隔注释 | **6 处** |
| 引用共享状态的函数 | **74 / 89（83%）** |
| `innerHTML` 赋值点 | 29 |
| `fetch` 调用点 | 10 |
| 定时器 | 10 |
| 最长函数 | `handleLiveEvent` 105 行 / **28 个分支** |
| 次长 | `reconcileConversation` 73 行 / **28 个分支** |

### 1.2 代价是真实的

上一轮评审发现的 5 个 P0/P1 bug，**全部出现在跨簇边界上**：

| Bug | 边界性质 |
|---|---|
| `el.skillSelect` 空白 | `core/dom` 定义 → `session`/`run/live` 写入 → `composer` 读取 —— **三处不一致** |
| `convos` 窄屏不可达 | `core/css` 依赖它，但 `core/dom` 的 `el` 映射表里**根本没有这个键** |
| 工具行倾倒 JSON | `run/live` 产出 → `ui/tools` 渲染，**无翻译层** |
| 失败被覆盖成完成 | `run/live` 的 `run.completed` 无条件写 `ui/plan` 的状态 |
| `artifact.created` 渲染下载按钮 | `run/live` 直接调 `ui/document`，**绕过契约校验** |

> **规律**：单文件里没有边界，跨簇调用是"随手调一下"，编译器不管、review 也不容易看出来。拆成模块后，这些调用变成**显式的导入依赖**，越界会被立刻看见。

### 1.3 拆分的真实收益（不是"文件小好看"）

| 收益 | 具体体现 |
|---|---|
| **契约显式化** | `run/live` 想调 `ui/document` 必须导入，导入清单就是契约审查表 |
| **Bug 定位** | 「`el.skillSelect` 三处不一致」在单文件里要全文搜索；拆分后是「`core/dom` 导出 vs `session` 写入」两个文件的对照 |
| **可测试性** | 现在 14 个测试全是 E2E（Playwright 驱动真实浏览器），没有单元测试。拆分后可对纯函数（`normalizePublishedText`、工具名映射）做单元测试 |
| **可替换** | `run/mock` 与 `run/live` 现在共用渲染函数（mock 通过 `window.MOCK_SCRIPT` 事件序列驱动 live 的渲染路径）。拆分后可让两者共用一个**事件 → 渲染** 的派发表，mock 天然覆盖 live 的所有分支 |
| **CSS 可分层** | 现在 CSS 与 JS 的 class 名靠约定关联，860 行无组织。拆分后可与 JS 模块同构组织 |

---

## 2. 硬约束（不可违反）

| # | 约束 | 来源 | 验证方式 |
|---|---|---|---|
| C1 | **无构建步骤** —— 不能引入 npm、打包器、TS 编译 | 当前是纯静态 | `index.html` 只有 2 个 `<script>` |
| C2 | **`file://` 必须能打开** | README.md:56-58 | Chrome headless `file://` 实测 |
| C3 | **DOM id 契约不可变** | 8 个 .cjs 测试依赖 | 实测用到的 id：<br>`#input` `#sendBtn` `#runStatus` `#skillSelect` `#paper` `#previewTitle` `#previewToggle` `#closePreview` `#shell` `#convoFilesBody` `#attachBtn` `#urlBtn` `#workbookStatus` `#institutionWorkbook` `#artifactTabs` |
| **C3-b** | **`fallbackTitle` / `maybeAutoTitle` 必须留在 `assets/console.js`** | `tests/conversation-titles.cjs` **把 `console.js` 当文本切片** | 见下方详述 —— **这条最容易被漏掉** |
| C4 | **新文件必须在 `frontend/assets/` 下** | `api/app.py:245-249` 只挂载 `/console/assets` | 读 `app.py` |
| C5 | **事件契约不变** | `docs/event-contract.md` | 后端与前端共同依赖 |
| C6 | **后端同端口提供** —— 不能要求用户起 Node 服务 | README.md:44-47 | `app.py` 挂载 |
| C7 | **可迁到任意框架** —— 事件契约不变 | README.md:106 | 设计约束 |
| **C8** | **`mock` 模式必须完全不依赖 `fetch`** | `file://` 下 fetch 到 `http://127.0.0.1:8000` 会被 CORS 拦截 | 实测 + 逻辑推演 |

### 2.1 C3-b 详解：`conversation-titles.cjs` 把 `console.js` 当文本读

**这是最容易踩的一条约束，任何"把 session 相关代码搬走"的方案都会踩中。**

```js
// frontend/tests/conversation-titles.cjs
const source = fs.readFileSync('frontend/assets/console.js', 'utf8');
function extract(name) {
  const sync  = source.indexOf(`  function ${name}(`);
  const async = source.indexOf(`  async function ${name}(`);
  const start = sync >= 0 ? sync : async;
  assert(start >= 0);                                    // ← 找不到就断言失败
  return source.slice(start, source.indexOf('\n  }', start) + 4);
}
const context = { AbortController, setTimeout, clearTimeout,
  ui:{activeConversation:'a'}, el:{chatTitle:{textContent:''}},
  currentConversation:()=>conversation, getApiBase:()=>'',
  saveState(){}, renderProjects(){}, fetch:()=>{...} };
vm.createContext(context);
vm.runInContext(extract('fallbackTitle') + '\n' + extract('maybeAutoTitle'), context);
```

**三重约束**：

| # | 约束 | 后果 |
|---|---|---|
| 1 | 两个函数**必须物理存在于 `frontend/assets/console.js`** | 搬到 `14-session.js` → `assert(start>=0)` 失败 → **测试变红** |
| 2 | 必须保持**两空格缩进的顶层函数声明** | `  function fallbackTitle(` 的精确匹配 |
| 3 | 函数体**不得引用新全局**（如 `BP.`） | vm 沙箱只有 9 个全局：`AbortController, setTimeout, clearTimeout, ui, el, currentConversation, getApiBase, saveState, renderProjects, fetch` |

> **第 3 条的推论**：即便把文件搬走，函数体也不能写成 `BP.config.xxx` 之类 —— 沙箱里没有 `BP`。

**处置方案（二选一）**：

- **方案 1（推荐，零风险）**：**这两个函数不搬家**，留在 `console.js` 里；`14-session.js` 只放 `hydrateFromBackend`。代价是 `console.js` 最后仍不为空。
- **方案 2**：同步改测试的读文件路径 —— 改 `readFileSync('frontend/assets/console.js')` → 指向新文件，**断言与 fixture 一律不动**。

> ⚠️ 方案 2 的风险：测试与被测代码的耦合路径变了，但断言逻辑没变 —— 可接受。**但绝不能把断言改松**。

---

## 3. 加载方式：实测结论

### 3.1 ES Modules 在 `file://` 下不可用（实测）

```
测试：<script type="module" src="main.js">  →  import { A } from './mod-a.js'
结果：window.__ok === undefined   →  模块未执行
原因：file:// 源的模块请求被 CORS 策略拦截（Origin: null）
```

**C2 被直接否决** —— README 明确承诺 `file://` 打开能看 Mock 演示。

> 若要保住 `file://`，只能放弃 ESM。

### 3.2 经典 `<script>` + 全局命名空间：实测可行

```html
<script src="assets/arch-util.js"></script>   <!-- 定义 window.BP.util -->
<script src="assets/arch-state.js"></script>  <!-- 定义 window.BP.state -->
<script src="assets/arch-ui.js"></script>     <!-- 定义 window.BP.ui -->
<script src="assets/arch-boot.js"></script>   <!-- 组合启动 -->
```

实测结果：`ARCH:1|2|rendered:X` —— **按序加载、共享命名空间、启动序列全部正确**。

**结论**：采用 **`window.BP` 单一命名空间 + 经典 script 标签**。

### 3.3 加载顺序约束

依赖必须按拓扑序排列。实测出的约束：

```
1. util.js        无依赖           $ / $$ / esc / svg / ICON
2. config.js      无依赖           SKILL_PLANS / TOOL_STEP_HINTS / STORAGE_KEY
3. dom.js         util             el 映射表、$、applyTheme、setStatus、syncHeader
4. state.js       util, dom        ui / runtime / loadState / saveState / findConversation
5. <其余模块>     上述四者
6. boot.js        全部             启动序列（当前 IIFE 末尾的 async IIFE）
```

> **`mock-events.js` 必须最先加载** —— 它只做一件事：`window.MOCK_SCRIPT = {...}`（L14），无任何依赖。但 `console.js:781/1092/1157/1169/1187` 会读它，所以它必须在 `console.js` 拆分后的所有文件之前。

### 3.4 缓存失效

现有模式：`?v=20261030-workbook-controls`（`index.html` 已有）。拆分后每个文件都需要版本号，或改用目录级版本号：

```html
<script src="assets/modules/util.js?v=20261030-1"></script>
```

`StaticFiles` 会忽略 query string 做文件查找，**已实测兼容**。

---

## 4. 目标模块结构

### 4.1 目录布局

```
frontend/assets/
├── console.css              # 保留（拆分方案见 §7）
├── mock-events.js           # 保留不动（纯数据，最先加载）
└── modules/
    ├── 00-util.js           # $ $$ esc svg ICON
    ├── 01-config.js         # SKILL_PLANS TOOL_STEP_HINTS STORAGE_KEY
    ├── 02-dom.js           # el 映射表 + 顶栏/状态/计时
    ├── 03-state.js         # ui runtime loadState saveState findConversation withRuntime
    ├── 04-plan.js          # 执行计划面板
    ├── 05-tools.js         # 工具调用组
    ├── 06-approval.js      # 确认卡
    ├── 07-message.js       # 消息流（文本/工具组/确认卡/文档卡）
    ├── 08-files.js         # 文件区 + 文件预览
    ├── 09-document.js      # 文档卡 + A4 预览面板 + artifact tabs
    ├── 10-run.js           # live + mock 事件驱动（最后抽）
    ├── 11-workbook.js      # 投资机构匹配表附件
    ├── 12-sidebar.js       # 项目树
    ├── 13-composer.js      # 输入区
    ├── 14-session.js       # 只放 hydrateFromBackend（标题函数留在 console.js，见 C3-b）
    └── 99-boot.js          # 启动序列
```

> **编号前缀是为了保证加载顺序**。经典 script 没有声明式依赖，顺序就是契约 —— 编号让顺序在文件列表里一目了然，也让 review 时能立刻看出「谁在谁前面」。
>
> `modules/` 子目录在 `assets/` 下，**符合 C4**。

### 4.2 模块职责与预估行数

按实测的簇函数体行数统计（总和 2293）：

| 模块 | 簇 | 实测行数 | 预估 | 职责 |
|---|---|---|---|---|
| `10-run.js` | `run/live` + `run/mock` | 378 + 77 | **~430** | SSE 订阅、事件派发、live/mock 播放器 |
| `03-state.js` | `core/state` | 284 | ~300 | 会话状态、持久化、runtime 生命周期 |
| `07-message.js` + `08-files.js` + `09-document.js` | `ui/message` + `ui/files` + `ui/document` | 89+242+119 = 450 | **~430**（拆 3 个） | 消息流 / 文件区 / 文档卡与预览 |
| `13-composer.js` | `composer` | 182 | ~185 | 输入区、草稿、附件、发送 |
| `12-sidebar.js` | `sidebar` | 179 | ~175 | 项目树、对话列表 |
| `02-dom.js` | `core/dom` | 160 | ~160 | DOM 引用、顶栏、计时、弹窗 |
| `11-workbook.js` | `feature/workbook` | 150 | ~155 | 匹配表附件 |
| `06-approval.js` | `ui/approval` | 126 | ~130 | 确认卡 |
| `14-session.js` | `session` | 121 | **~60** | **只放 `hydrateFromBackend`** —— `fallbackTitle`/`maybeAutoTitle` 必须留在 `console.js`（见 C3-b） |
| `05-tools.js` | `ui/tools` | 90 | ~90 | 工具调用组 |
| `04-plan.js` | `ui/plan` | 79 | ~85 | 执行计划 |
| `01-config.js` | `domain/tools` + 常量 | 17 + 60 | ~75 | 常量表 |
| `00-util.js` | — | ~30 | ~30 | 工具函数 |
| `99-boot.js` | 启动序列 | ~25 | ~25 | 启动 |

**最大文件 ~430 行**（`10-run.js`）—— 从 2365 行降到 430 行以内，且每个文件职责单一。

> `10-run.js` 仍是最大的。§6 的第 3 步会把它进一步拆成 `10-run-live.js` / `10-run-mock.js` / `10-run-events.js`（事件派发表）。

### 4.3 依赖方向（单向无环）

```
        00-util  ←  01-config
             ↓
          02-dom
             ↓
         03-state
             ↓
    ┌────────┼────────┬─────────┬──────────┐
    ↓        ↓        ↓         ↓          ↓
04-plan 05-tools 06-approval 07-message 12-sidebar
    ↑        ↑        ↑         ↑          ↑
    └────────┴────────┴─────────┴──────────┘
                  ↑        ↑
            10-run    11-workbook
                  ↑        ↑
             13-composer  14-session
                       ↑
                    99-boot
```

**规则**：
1. 箭头只能向下，**禁止反向 import**
2. `03-state` 不 import 任何 UI 模块（它只有出边 0，是纯依赖中枢）
3. `10-run` 可以 import 所有 UI 模块（它是派发层），但 UI 模块**不得** import `10-run`
4. `99-boot` 是唯一允许 import 全部模块的文件

> 现状的跨簇出边数（实测）可直接验证这个方向可行：
> `core/state` 出边 **0**、`domain/tools` 出边 **1**、`ui/tools` 出边 **1**、`ui/plan` 出边 **2** —— 这些天然是叶子。
> `run/live` 出边 **13** 是最难的，但它正是派发层，放在上层正好。

### 4.4 各模块的公开接口

```js
// 00-util.js
window.BP.util = { $, $$, esc, svg, ICON };

// 01-config.js
window.BP.config = { SKILL_PLANS, TOOL_STEP_HINTS, STORAGE_KEY };

// 02-dom.js
window.BP.dom = {
  el,                    // DOM 映射表（唯一来源）
  applyTheme, setStatus, syncHeader,
  startTimer, stopTimer, scrollBottom, autoGrow, openInputDialog
};

// 03-state.js
window.BP.state = {
  ui,                    // 持久化状态
  runtimeOf, threadFor, findConversation, currentConversation,
  renderingConversation,
  withRuntime,            // 过渡期保留，见 §6.2
  loadState, saveState, recordMessage
};

// 04-plan.js
window.BP.plan = { createPlan, hidePlan, restorePlan, updatePlan, ensurePlan, advancePlanForTool };

// 05-tools.js
window.BP.tools = { ensureToolGroup, setToolGroupState, appendTool, finishTool };

// 06-approval.js
window.BP.approval = { showApproval, normalizeQuestionPayload };

// 07-message.js
window.BP.message = {
  addUserMessage, createAIMessage, appendAIText, showSkill, renderHistory,
  renderConvoFiles, collectConversationFiles, openFilesPanel, openFilePreview,
  fileChip, bindFileChips, filesBlock,
  docCardEl, showDocCard, openPreview, closePreview, resetAll,
  renderArtifactTabs, showArtifact, loadWorkbookPreview,
  artifactDownloadUrl, normalizePublishedText, renderAIText
};

// 10-run.js
window.BP.run = { getApiBase, submitLive, subscribeEvents, failRun,
                  handleLiveEvent, reconcileConversation, addLiveDoc,
                  resetRunUi, trimEvent, startMock, handleMockEvent, finishTurn };

// 11-workbook.js
window.BP.workbook = { renderWorkbookStatus, requestWorkbook,
                       startAuxiliaryPolling, pollAuxiliary, loadWorkbookFeature };

// 12-sidebar.js
window.BP.sidebar = { renderProjects, createConversation, replayEvents, openConversation };

// 13-composer.js
window.BP.composer = { renderAttachRow, syncComposerButton, cancelRun, queueHint,
                       send, saveDraft, loadDraft, clearDraft };

// 14-session.js
window.BP.session = { fallbackTitle, maybeAutoTitle, hydrateFromBackend };

// 99-boot.js  —— 唯一执行启动序列的文件
```

**命名空间约定**：每个模块**只写自己的键**（`BP.plan` 只由 `04-plan.js` 写）。这样「谁污染了谁」一眼可查。

---

## 5. 症结：`enterRuntime` / `exitRuntime` 换栈

### 5.1 问题本质

```js
// runtime 的 17 个字段
runId, status, aiEl, planEl, plan, tools, doc, artifactsById,
activeArtifactId, es, threadEl, queue, lastPayload, skill,
approvalId, timerId, startedAt

// 全局 state 的 26 个字段
mode, status, speed, eventIndex, paused, timers, autoScroll, aiEl,
planEl, plan, planSteps, planOwner, tools, doc, startedAt, timerId,
es, timelineBase, files, skill, runId, approvalId, lastPayload,
silentRender, renderingConversation, replaying
```

**实测：runtime 的 17 个字段中，13 个在 state 里有同名副本**：

```
runId, status, aiEl, planEl, plan, tools, doc, es,
lastPayload, skill, approvalId, timerId, startedAt
```

`enterRuntime` 把 runtime 的值**整体覆盖**进 state，`exitRuntime` 再还原 —— 这是一个**手工实现的依赖注入**，代价是：

- 任何函数都能读全局 `state`，**无法知道它依赖哪个对话**
- 89 个函数中 74 个隐式耦合
- 嵌套调用（`withRuntime` 套 `withRuntime`）依赖 `renderStack` 栈正确

### 5.2 state 字段引用热度（实测）

```
aiEl                25  ← 被换栈
doc                 21  ← 被换栈
planEl              18  ← 被换栈
skill               13  ← 被换栈
renderingConversation 13 ← 被换栈
replaying           13  ← 被换栈
runId               12  ← 被换栈
plan                10  ← 被换栈
toolGroup           10  ← 被换栈
files                9
silentRender         8  ← 被换栈
eventIndex / tools / timerId / approvalId   7  ← 被换栈
...
mode / status / speed / paused / timers / autoScroll / planSteps /
planOwner / startedAt / timelineBase / lastPayload / es     ← 未被换栈（12 个）
```

**结论非常清晰**：
- **14 个热字段**正是被换栈的那批 —— 它们是真正的 per-conversation 状态
- **12 个冷字段**（mode/speed/paused/timers/files/…）本来就是全局的，不该换栈

### 5.3 推荐方案：getter 代理（改动 ≈ 0 个函数）

**关键洞察**：`runtime` 对象**本来就拥有**那 13 个字段 —— `runtimeOf()`（L162-180）创建时就建好了 `aiEl/planEl/plan/tools/doc/skill/runId/status/es/...`。

> 所以「双份真相源」**不是 runtime 缺字段**，而是 **`state` 存了一份副本**。
> 正确做法不是「把 runtime 的值搬进 state」（那是换栈在做的事），而是**让 `state` 的这些字段变成 runtime 的视图**。

```js
// 03-state.js 内部实现
const CURRENT = { conversation: null };   // 当前渲染作用域指向哪个对话

// 这 13 个字段改为代理到 runtime
for (const key of ['aiEl','planEl','plan','tools','doc','startedAt','timerId',
                   'es','skill','runId','approvalId','lastPayload','status']) {
  Object.defineProperty(state, key, {
    get() {
      const rt = CURRENT.conversation ? runtimeOf(CURRENT.conversation) : null;
      return rt ? rt[key] : undefined;
    },
    set(v) {
      const rt = CURRENT.conversation ? runtimeOf(CURRENT.conversation) : null;
      if (rt) rt[key] = v;
    },
    configurable: true
  });
}
```

**收益**：

| 项 | 效果 |
|---|---|
| 改动的函数数 | **0** —— 74 个引用 `state.*` 的函数**一行都不用改** |
| 改动位置 | 只在 `03-state.js` 内部，约 25 行 |
| 双份真相源 | **从结构上消失** —— 不再是「两份要同步」，而是「只有一份，另一份是视图」 |
| `enterRuntime`/`exitRuntime` | 退化成「设置 `CURRENT.conversation`」 |

**三个必须注意的点**：

1. **必须删掉 `exitRuntime` 里那 13 行回写**（L227-239）：
   ```js
   runtime.aiEl = state.aiEl;      // ← 删
   runtime.toolGroup = state.toolGroup;   // ← 删
   ...共 13 行
   ```
   否则会用全局 state 的旧值**覆盖** runtime 的新值 —— 代理方案下这是数据损坏。

2. **`runtimeOf()` 内部不得读 `state.*`** —— 当前它只读 `conversation.lastRunId` / `conversation.activeSkill` ✅，**无递归**，保持即可。

3. **`toolGroup` / `planSteps` / `planOwner` / `silentRender` / `renderingConversation` / `replaying` 不进代理**：
   - `toolGroup` 虽在 `runtime` 里被动态赋值（L229），但它本质是「当前渲染作用域的临时工具组」，且 `ensureToolGroup`（L860）会检查 `state.toolGroup.root.isConnected` —— **保持原样最安全**
   - `silentRender`（8 次）/ `renderingConversation`（13 次）/ `replaying`（13 次）是**渲染期上下文**，不属于任何对话 —— 它们跟着「当前渲染作用域」走，语义上正确
   - `planSteps` / `planOwner` 引用少（3/4 次），且与 `plan` 生命周期一致 —— 可一并代理，但收益小

   > **结论**：13 个字段代理，覆盖了全部**高热度**（`aiEl` 25 / `doc` 21 / `planEl` 18 / `skill` 13 / `runId` 12 / `plan` 10），其余保持原样。

### 5.4 与「显式传参」方案的对比

| 方案 | 改动函数数 | 收益 | 风险 | 评价 |
|---|---|---|---|---|
| **A. 保持换栈，仅加模块适配层** | 0 | 拆分风险最低 | 换栈技术债保留 | 阶段 1 用 |
| **B'. getter 代理** | **0**（只改 `03-state.js` ~25 行） | **双份真相源结构上消失**；74 个函数一行不改 | 需删 13 行回写；需理解代理语义 | **推荐** |
| B. 渲染函数显式接收 runtime | ~30 | 最彻底、最显式 | 改动面大，需分批 | 备选 |
| C. Proxy 上下文 | ~10 | 改动小 | 调试困难、性能与可读性都变差 | **不推荐** |

### 5.5 渐进路径

**不要一次性做。** 理由：

1. 上轮刚定位的 3 个 P0 **都在同一批行**（`console.js:1918` 等），同时重构会让 bug 修没修对被噪声掩盖
2. `handleLiveEvent`（105 行 / 28 分支）已是最大复杂度热点，同时改结构 + 改逻辑必然失控

**路径**：

- **阶段 1（§6 批次 1-3）**：方案 A —— 拆文件，`withRuntime` 保持原样。**模块边界是物理的，依赖仍是隐式的。** 可独立验证、可回滚。
- **阶段 2（§6 批次 4，可延后）**：方案 B' —— getter 代理。**全部改动集中在 `03-state.js`，其他 13 个模块一行不动** → 回归面极小。

**阶段 2 是否要做，取决于阶段 1 完成后是否仍频繁出现「这个函数读的是哪个对话的 state」这类困惑。建议先做阶段 1，观察一个迭代周期再定。**

---

## 6. 迁移路线图

> **每一步都独立可验证、可回滚。** 验证手段统一为：14 个现有测试 + Chrome headless 截图对比。

### ⚠️ 前置：先修 P0，再重构

上轮 spec 的 3 个 P0 全部落在 `console.js` 的同一批行：

| P0 | 行号 | 与重构的关系 |
|---|---|---|
| Skill 下拉空白 | `1918`、`1967`、`2196`、`1220` | 跨 `02-dom` / `14-session` / `13-composer` / `10-run` —— **拆分时会被反复触碰** |
| 窄屏左栏不可达 | `console.css:730-739` + `el` 映射表 | 需要给 `02-dom` 加 `convos` —— **拆分时必然修改 `el`** |
| 按钮零焦点环 | `console.css` 全局 | 与拆分无关，可并行 |

**建议**：先按 [ui-optimization-spec.md](./ui-optimization-spec.md) 的批次 0 修完 P0，并提交；再开始本次重构。**不要混在同一批提交里。**

### 批次 1：抽基础设施（低风险）

**做什么**：
1. 新建 `modules/00-util.js`（`$` `$$` `esc` `svg` `ICON`）
2. 新建 `modules/01-config.js`（`SKILL_PLANS` `TOOL_STEP_HINTS` `STORAGE_KEY`）
3. 新建 `modules/02-dom.js`（`el` + 顶栏/状态/计时/弹窗）
4. 新建 `modules/03-state.js`（`ui` / `runtimeOf` / `loadState` / `saveState` / `withRuntime` …）
5. `console.js` 改为只做 `import` 副作用（把这些模块挂到 `BP` 上），**业务逻辑一行不动**

**加载顺序**：
```html
<script src="assets/mock-events.js"></script>
<script src="assets/modules/00-util.js?v=..."></script>
<script src="assets/modules/01-config.js?v=..."></script>
<script src="assets/modules/02-dom.js?v=..."></script>
<script src="assets/modules/03-state.js?v=..."></script>
<script src="assets/console.js?v=..."></script>
```

> **本批不拆业务模块**。`console.js` 仍是一个大文件，但从 `BP.util` / `BP.dom` / `BP.state` 取值。好处：一次只动 4 个文件，出问题立刻能定位。

**验收**：
- [ ] 14 个测试全部通过
- [ ] Chrome headless 1440px 截图与重构前**像素级一致**
- [ ] `file://` 打开能跑 mock
- [ ] `http://127.0.0.1:8000/console` 正常

### 批次 2：抽叶子模块（低风险）

**做什么**：按依赖顺序依次抽出，**每个模块单独一个提交**：

| 顺序 | 模块 | 理由 |
|---|---|---|
| 1 | `04-plan.js` | 出边 2，最独立 |
| 2 | `05-tools.js` | 出边 1 |
| 3 | `06-approval.js` | 出边 4 |
| 4 | `13-composer.js` | 出边 4；但**含 P0 的 `skillSelect` 读取**，修完 P0 再动 |
| 5 | `14-session.js` | **只搬 `hydrateFromBackend`**；`fallbackTitle`/`maybeAutoTitle` **留在 `console.js`**（C3-b） |

**每抽一个**：
1. 建文件，把函数搬过去，挂到 `BP.<name>`
2. `console.js` 里改成 `const { createPlan } = BP.plan;`（或直接 `BP.plan.createPlan(...)`）
3. 跑全部 14 个测试
4. 截图对比
5. 提交

> **一次只抽一个模块**。一次抽四个，出问题时无法判断是哪个引入的。

**验收**（每个模块）：
- [ ] 该模块的所有函数在 `BP.<name>` 上可访问
- [ ] 14 个测试通过
- [ ] 截图一致

### 批次 3：抽大模块（中高风险）

**做什么**：
1. `07-message.js`（450 行 → 3 个子模块，建议拆 `07-message.js` / `08-files.js` / `09-document.js`）
2. `12-sidebar.js`
3. `13-composer.js`
4. `11-workbook.js`
5. `10-run.js` —— **最后抽**，因为它出边 13，是所有 UI 模块的消费者

**`10-run.js` 的特殊处理**：

当前 `handleLiveEvent`（105 行 / 28 分支）是一个 **10 个 case 的派发表**，调用 12 个渲染函数，横跨 7 个簇。拆分时建议**先把它变成数据驱动的派发表**，再拆文件：

```js
// 拆分前：一个 105 行的 switch
function handleLiveEvent(ev) {
  switch (ev.type) {
    case 'run.started': ...
    case 'skill.activated': ...
    case 'plan.updated': ...
    // ... 10 个 case
  }
}

// 拆分后：派发表（每个 handler 是独立函数，可分文件）
const LIVE_HANDLERS = {
  'run.started':       (ev) => { ... },
  'skill.activated':   (ev) => { ... },
  'plan.updated':      (ev) => { ... },
  'tool.started':      (ev) => { ... },
  'tool.completed':    (ev) => { ... },
  'tool.failed':       (ev) => { ... },
  'approval.required': (ev) => { ... },
  'artifact.created':  (ev) => { ... },
  'run.completed':     (ev) => { ... },
  'run.failed':        (ev) => { ... },
};
function handleLiveEvent(ev) {
  const h = LIVE_HANDLERS[ev.type];
  if (h) h(ev);
}
```

**收益**：`handleLiveEvent` 的 28 个分支变成 10 个 1-3 行的表项，每个 handler 可单独测试；派发表本身就是一份**「事件 → 谁负责」的可视化契约**，评审时能直接对照 `docs/event-contract.md`。

**验收**：
- [ ] `handleLiveEvent` 拆成派发表 + 独立 handler
- [ ] 派发表与 `event-contract.md` 的事件类型逐条对齐
- [ ] 14 个测试通过

### 批次 4：消除换栈（可选，可延后）

见 §5.3 的 getter 代理方案。**全部改动集中在 `03-state.js` 内部约 25 行**，其他 13 个模块一行不动 → 回归面极小。

**具体步骤**：

1. 在 `03-state.js` 里为 13 个热字段定义 getter/setter 代理（§5.3 代码）
2. **删除 `exitRuntime` 里的 13 行回写**（L227-239）—— 否则会用 state 旧值覆盖 runtime 新值
3. `enterRuntime`/`exitRuntime` 简化为设置 `CURRENT.conversation`
4. `runtimeOf()` 内部保持不读 `state.*`（当前已满足）
5. `toolGroup` / `silentRender` / `renderingConversation` / `replaying` / `planSteps` / `planOwner` **不进代理**，保持原样

**验收**：
- [ ] `state` 的 13 个热字段已是代理（`Object.getOwnPropertyDescriptor(state,'aiEl').get` 存在）
- [ ] `exitRuntime` 里没有回写行
- [ ] 14 个测试通过
- [ ] 切换对话时，**对话 A 的 `aiEl`/`doc`/`plan` 不会被对话 B 覆盖**（这是当前换栈最脆弱的地方，改完后应写一个针对性测试）
- [ ] 新增单元测试：状态代理与 runtime 的一致性

### 批次 5：收尾

| 任务 | 说明 |
|---|---|
| `99-boot.js` | 把 IIFE 末尾的启动 async IIFE 独立出来 |
| 删除 `console.js` | 所有内容迁出后删除 |
| `index.html` 更新 | 换成多个 `<script>` 标签 |
| README 更新 | 补「文件结构」章节，说明模块职责与加载顺序约束 |

---

## 7. CSS 拆分方案（已按 §7.2 落地为 15 个文件，见 assets/styles/）

### 7.1 现状

| 指标 | 数值 |
|---|---|
| 总行数 | 860 |
| CSS 变量 | 55 |
| 顶层选择器块 | **335** |
| `@media` | 3（`max-width:1180` / `max-width:1023` / `print`） |

### 7.2 分层方案

```
frontend/assets/
├── console.css              # 仅保留 @import 入口（或保留全部，见取舍）
└── styles/
    ├── 01-tokens.css        # :root + [data-theme="dark"] 的 55 个变量
    ├── 02-base.css          # reset、body、滚动条、.app/.shell/.footer 布局骨架
    ├── 03-topbar.css        # 顶栏、状态 pill、计时、主题按钮
    ├── 04-sidebar.css       # .convos .project .convo .convo-files
    ├── 05-chat.css          # .chat .chat-head .messages .bubble .ai-text
    ├── 06-plan.css          # .task-panel .plan-step
    ├── 07-tools.css         # .tool-group .tool-line
    ├── 08-approval.css      # .approval .approval-opt
    ├── 09-document.css      # .paper .p-head .kpis .inv-table
    ├── 10-composer.css      # .composer .chip .tool-chip .attach-row
    ├── 11-preview.css       # .preview .doc-scroll
    └── 12-responsive.css    # 3 个 @media 集中管理
```

**与 JS 模块同构** —— `04-plan.js` ↔ `06-plan.css`，`05-tools.js` ↔ `07-tools.css`。这是无构建方案里最实际的组织方式。

### 7.3 `@import` vs 多 `<link>` —— 取舍

| 方案 | 优点 | 缺点 |
|---|---|---|
| **A. 单 `console.css` + `@import`** | 只需改一个文件；`index.html` 不变 | **`@import` 在解析阶段串行阻塞**，N 个文件依次排队 |
| **B. 多 `<link>` 标签** | 浏览器可并行请求；单文件失败不影响其他 | `index.html` 要加 N 个标签；顺序敏感（层叠） |

> **实测澄清**：CSS `@import` 在 `file://` 下**是可用**的（两个代理各自实测，均确认变量正常生效）。
> 推荐多 `<link>` 的真正理由是**串行阻塞**，**不是兼容性差异** —— 此前版本曾推测"`file://` 下 `@import` 有兼容问题"，该推测**不成立**，已修正。

**实测建议**：**用 B（多 `<link>`）**，理由：
- `file://` 下没有 HTTP 并行，多个 `<link>` 反而比串行 `@import` 快
- 层叠顺序显式可见，避免 `@import` 顺序被忽略

```html
<link rel="stylesheet" href="assets/styles/01-tokens.css?v=..." />
<link rel="stylesheet" href="assets/styles/02-base.css?v=..." />
...
```

**分层纪律**：`01-tokens.css` 必须最先（其他文件用 `var(--x)`）；`12-responsive.css` 必须最后。

> **注意**：CSS 拆分与 JS 拆分**可以解耦**。建议**先做 JS 拆分（批次 1-3），CSS 拆分作为独立批次**，避免同时出问题。

### 7.4 CSS 拆分的额外收益

当前 `console.css:859` 的 `#dce1e8` 是**唯一不在 token 体系内的硬编码色值**，且落在 `[data-theme="dark"]` 块之外 → 深色模式下表格边框失效。分层后 `01-tokens.css` 会强制所有颜色走 token，这类问题会自然暴露。

---

## 8. 风险清单

| # | 风险 | 可能性 | 影响 | 缓解 |
|---|---|---|---|---|
| R1 | **加载顺序错误** —— 经典 script 无声明式依赖，顺序错了就是 `undefined is not a function` | **高** | 启动失败 | ① 编号前缀 `00-`…`99-` 让顺序可见<br>② `99-boot.js` 是唯一的启动点<br>③ 每个模块顶部加断言：`if (!BP.state) throw new Error('03-state.js must load before 04-plan.js')` |
| R2 | **DOM id 契约破坏** —— 测试依赖 16 个 id | 中 | 测试全红 | ① 迁移期间**不改 `index.html` 的 id**<br>② 每批跑全部 14 个测试<br>③ `02-dom.js` 的 `el` 映射表成为 id 的唯一来源 |
| R3 | **监听器丢失（不是重复绑定）** | **高** | 按钮点了没反应 | 现状：`renderProjects` 每次 `innerHTML` **整体重建** DOM 再重新绑定 → **当前无重复绑定问题**（旧节点随 GC 释放）。真实风险是拆分后若把监听器提到模块顶层，而节点被 `innerHTML` 重建 → **监听器失效**。<br>→ **保持现有「绑定在渲染函数内」模式**，或**统一改事件委托**，**不要混用** |
| R3-b | **搬走 `fallbackTitle`/`maybeAutoTitle` 导致测试变红** | **高** | `conversation-titles.cjs` 断言失败 | 见 C3-b。这两个函数**留在 `console.js`**，或同步改测试的读文件路径（断言不动） |
| R4 | **`el.paper.innerHTML = doc.html` 这个 sink** | **中→高** | XSS / 内容注入 | 现状：29 处 `innerHTML`，所有生产者目前都正确 `esc()`，但**安全性是逐个生产者的约定，不是结构保证**<br>→ **拆分后风险升高**：`doc.html` 的生产者分散到 `09-document` / `11-workbook` / `mock-events`，review 更难看全<br>→ **正向解法**：改用**结构化 doc 对象** `{type,title,sub,blocks:[{kind:'h1'\|'p'\|'kpi'\|'table'\|'link',...}]}`，由 `09-document` **单一渲染器**统一转义 —— **这正是拆分的收益** |
| R5 | **SSE 连接泄漏** | 中 | 后台连接堆积 | 现状管理正确（订阅前先 `close()`、用 `runtime.es !== es` 守卫、终态事件关闭）→ 拆分后 **`runtime.es` 归 `10-run.js`**，**不要提到全局 state**，`runtime` 仍是 per-conversation 的 |
| R6 | **定时器归属混乱** | 中 | 切对话后回调打到错误对话 | 实测现状：`state.timers`（打字机 + mock 播放）是**全局**的，清理只在 mock 路径（`openConversation` L1993-1996 的 `if (state.mode === 'mock')`）—— **这是有意的**，因为真实 run 的 SSE 要保持活着<br>→ 拆分后：`runtime.timerId` → `02-dom`；`runtime.auxiliaryTimer` → `11-workbook`；`state.timers` → `10-run` 的 mock 播放器。**不要留在 `03-state`** |
| R7 | **`file://` 行为差异** | 中 | 本地演示失效 | 经典 script 两者一致 ✅，但 **`file://` 下 fetch 到 `http://127.0.0.1:8000` 会被 CORS 拦截** → **mock 模式必须完全不依赖 fetch**（见 C8）<br>→ 用 `tests/file-probe.cjs` 自动化验证，不要靠手双击 |
| R8 | **`?v=` 版本号遗漏** | 中 | 浏览器缓存旧文件 | 每个 `<script>` / `<link>` 都要带版本号；建议统一用一个常量 |
| R9 | **回归到单文件** —— 拆分后有人图省事把逻辑塞回 `console.js` | 中 | 架构退化 | ① 拆分完成后**删除 `console.js`**<br>② README 写明「新增功能放哪个模块」<br>③ `99-boot.js` 是唯一允许 import 全部的文件 |
| R10 | **与 P0 修复混合提交** | **高** | bug 修没修对无法判断 | **P0 修复单独提交并验证后，再开始重构**（§6 前置） |
| R11 | **`mock-events.js` 加载顺序** | 低 | mock 失效 | `mock-events.js` 必须**最先**加载（它定义 `window.MOCK_SCRIPT`，被 `console.js:781/1092/1157/1169/1187` 读取） |

---

## 9. 验收清单

### 9.1 每个批次都要过

- [ ] 14 个现有测试全部通过
- [ ] Chrome headless 1440px / 900px 截图与重构前一致
- [ ] `file://` 打开可跑 mock 演示（用新增的 `tests/file-probe.cjs` 验证）
- [ ] `http://127.0.0.1:8000/console` 正常
- [ ] 浏览器 Console 无报错
- [ ] `git diff` 只包含预期的文件移动

### 9.2 建议新增的两个测试工具

#### ① `tests/dom-contract.cjs` —— DOM id 契约守卫

**纯文本断言，不需要浏览器**，因此能进 CI 且极快。作用：防止重构中 id 漂移。

```js
// 断言 1：受测 id 存在于 index.html
const html = fs.readFileSync('frontend/index.html', 'utf8');
const IDS = ['input','sendBtn','runStatus','skillSelect','paper','previewTitle',
             'previewToggle','closePreview','shell','convoFilesBody','attachBtn',
             'urlBtn','workbookStatus','institutionWorkbook','artifactTabs'];
for (const id of IDS) {
  assert(html.includes(`id="${id}"`), `index.html 缺少 #${id}`);
}

// 断言 2：受测 id 都在 02-dom.js 的 el 表里（唯一来源）
const dom = fs.readFileSync('frontend/assets/modules/02-dom.js', 'utf8');
for (const id of IDS) {
  assert(dom.includes(`${id}: $('#${id}')`), `02-dom.js 的 el 表缺少 ${id}`);
}
```

#### ② `tests/file-probe.cjs` —— `file://` 可用性探针

现有 14 个测试都要 Playwright + 后端 server，但批次 1-2 的验收重点恰恰是「`file://` 还能不能打开」—— 这件事**不需要 Playwright**。

**实现要点**（零 npm 依赖，Node 24 内置 `WebSocket` + CDP）：

```js
// frontend/tests/file-probe.cjs
// 1. spawn chrome --headless=new --remote-debugging-port=<port>
// 2. GET http://127.0.0.1:<port>/json/list 拿 webSocketDebuggerUrl
// 3. WebSocket 连上，Runtime.enable + Log.enable + Page.enable
// 4. Page.navigate 到 file:// URL
// 5. Runtime.evaluate 读 #runStatus / #paper / window.MOCK_SCRIPT
// 6. 收集 Runtime.exceptionThrown + Log.entryAdded
```

**探针应断言**：
- `window.BP` 及其全部子命名空间已定义（批次 1 起逐步增加）
- `window.MOCK_SCRIPT` 存在（说明 `mock-events.js` 加载顺序正确）
- 无 `Runtime.exceptionThrown`
- 无 `Log.entryAdded` 的 error 级别条目
- `#runStatus` 有内容（说明启动序列执行到了）

> **理由**：手双击验证不可回归、不可自动化。批次 1 起用，**每次拆分后都要跑**。

#### ③ 语法检查

```bash
node --check frontend/assets/modules/*.js
```

零成本，能挡住绝大多数搬函数时的括号/引号错误。**每个模块提交前跑**。

### 9.3 拆分完成后额外要过

- [ ] `console.js` 已删除（或仅剩 3 行 import 说明）
- [ ] `index.html` 的 `<script>` / `<link>` 顺序正确，编号前缀连续
- [ ] 每个模块文件顶部有依赖断言
- [ ] README 有「文件结构」章节
- [ ] `docs/event-contract.md` 更新了「前端模块与事件处理器的对应关系」
- [ ] **新增单元测试**：至少覆盖 `normalizePublishedText`、工具名映射、`fallbackTitle` 三个纯函数
- [ ] **新增测试**：`handleLiveEvent` 派发表覆盖全部 10 个事件类型

---

## 10. 与其他工作的关系

| 工作项 | 关系 | 建议顺序 |
|---|---|---|
| [ui-optimization-spec.md](./ui-optimization-spec.md) 的 P0 修复 | **必须先做** —— 同一批行 | 1 |
| P1（工具摘要人话化 / 计划折叠 / 产物元数据） | 可与批次 3 并行 —— 都在 `10-run` / `05-tools` / `07-message` | 2 |
| P2（对比度 / 字号 / reduced-motion） | 与 JS 拆分**完全独立** | 可并行 |
| CSS 拆分 | 与 JS 拆分**解耦**，独立批次 | 3 |
| 阶段 2（消除换栈） | 可延后，观察后再定 | 4 |

---

## 附录 A：实测数据

**函数级调用图**（89 个函数，调用数前 10）：

```
runtimeOf              26      currentConversation    22
saveState              19      getApiBase             13
scrollBottom           12      withRuntime             9
stopTimer               8      setStatus               8
renderingConversation   8      threadFor               7
```

**跨簇依赖边**：共 66 条。各簇出边数：

```
core/state           0  ← 纯依赖中枢
domain/tools         1
ui/tools             1
ui/plan              2
ui/files             3
ui/message           3
ui/approval          4
ui/document          4
composer             4
feature/workbook     4
session              4
core/dom             6
run/mock             8
sidebar              9
run/live            13  ← 派发层，放上层
```

**复杂度热点**（行数 / 分支数）：

```
showApproval           107 / 17
handleLiveEvent        105 / 28   ← 派发表候选
withRuntime             78 / 1
reconcileConversation   73 / 28
submitLive              73 / 19
send                    69 / 10
```

**风险模式计数**：`innerHTML =` 29 处、`fetch(` 10 处、`localStorage` 6 处、定时器 10 处。

**技术验证**：

| 验证项 | 方法 | 结果 |
|---|---|---|
| ESM over `file://` | Chrome headless `file://` + `type="module"` | ❌ 模块未执行（CORS） |
| 经典 script over `file://` | Chrome headless `file://` + 多文件 | ✅ `CLASSIC:OK` |
| 多文件命名空间架构 | Chrome headless `file://` + 4 文件 + 启动序列 | ✅ `ARCH:1\|2\|rendered:X` |
| 深色对比度像素采样 | 解码 `chat-3-dark.png` 取字形像素 | `#777A7F` on `#08090C` = 4.62:1 |
| `app.py` 静态挂载范围 | 读 `api/app.py:245-249` | 仅 `/console/assets` |

---

## 附录 B：决策点

| # | 问题 | 选项 | 建议 |
|---|---|---|---|
| D1 | 拆分后是否消除换栈（阶段 2）？ | A 暂不做 / B 同期做 / C 观察后定 | **C** —— 先做阶段 1，观察一个迭代 |
| D2 | CSS 是否同步拆？ | A 同步 / B 独立批次 / C 不拆 | **B** —— 与 JS 解耦，降低同时出错的概率 |
| D3 | 模块粒度？ | A 15 个细粒度 / B 8 个粗粒度 / C 折中 | **C** —— `07-message.js`（450 行）拆 3 个，其余保持 |
| D4 | 命名空间形式？ | A `window.BP.x` / B `window.BP.x.y` / C IIFE 私有 + 显式导出 | **A** —— 最简单，调试时 `BP.plan` 一眼可见 |
| D5 | 模块间调用风格？ | A `BP.plan.createPlan()` / B 顶部解构 / C 依赖注入 | **B** —— 顶部解构让依赖在文件头可见 |
| D6 | 是否引入 lint？ | A 不引入 / B 加 ESLint flat config | **A** —— 保持无构建；但可用 `node --check` 做语法检查 |

---

*本文档为设计方案，未修改任何前端代码。所有量化数据来自对 `a6773e4` 基线的静态分析与 Chrome headless 实测。*
