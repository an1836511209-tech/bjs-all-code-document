# AI Chat 与 Artifacts 接入契约

模板提供沉浸式对话、流式 thinking、折叠工具调用，以及文档、表格、演示文稿、自定义看板四类成果预览。打开 `/dashboard/ai-chat` 即可体验，无需模型密钥。

当前使用真实 HTTP SSE 和 AI SDK `useChat`，服务端响应仍是确定性的演示脚本。输入框可以多轮发送，但不会理解任意自然语言；选择的示例决定返回内容。会话默认保存在当前浏览器，刷新可恢复，参见[历史会话与后端接入](./history.md)。本模板没有实现服务端会话存储、鉴权、模型调用或 Office 转换服务。

用户输入图片/附件采用独立上传及标准 file part，见[图片与输入附件接入](./attachments.md)。它与 `data-artifact` 输出成果互不替代。

## 路径与职责

| 位置 | 职责 |
| --- | --- |
| `src/features/ai-chat/chat.ts` | 消息类型、`DefaultChatTransport`、场景入口 |
| `src/app/api/ai-chat/route.ts` | 模拟流式接口，也是实际后端接入位置 |
| `src/features/ai-chat/components/` | 无头像会话、Markdown、thinking、工具披露、输入区 |
| `src/features/ai-chat/artifacts/types.ts` | Artifact v1 类型 |
| `src/features/ai-chat/artifacts/schemas.ts` | 事件信封及预览数据运行时校验 |
| `src/features/ai-chat/artifacts/state.ts` | 按 ID/revision 合并、历史恢复 |
| `src/features/ai-chat/artifacts/registry.tsx` | 可信预览组件与 schema 注册 |
| `src/features/ai-chat/artifacts/demo-data.ts` | 演示数据，不能当作真实业务数据 |

AI Chat 使用持续事件流，属于一般 CRUD `service → queries` 模式之外的明确例外；不要把 token 更新改成 React Query 轮询。

## 为什么使用独立事件

`data-artifact` 是本模板定义的应用数据类型，承载在 [AI SDK 自定义数据流](https://ai-sdk.dev/docs/ai-sdk-ui/streaming-data) 中。传输格式遵循 [UI Message Stream Protocol](https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol)，并不意味着 Artifact 的业务字段是跨厂商统一标准。设计参考了 [AI SDK Artifacts 扩展模式](https://chatbot.ai-sdk.dev/docs/customization/artifacts)。

模型可以调用 `createArtifact` / `updateArtifact` 等业务工具；服务端执行、校验结果，再发送成果事件。前端不解析正文中的“已生成”、Markdown 链接、文件名或特殊代码围栏来决定是否打开侧栏。工具结果与成果物是两种不同的消息块：前者解释执行过程，后者描述可查看的交付。

```text
用户请求 → 智能体调用业务工具 → 后端生成/保存/校验成果
        → tool-output-available（调用结果）
        → data-artifact（成果快照） → 前端校验与合并 → 卡片 + 预览面板
```

## Artifact v1

```json
{
  "type": "data-artifact",
  "id": "report-001",
  "data": {
    "schemaVersion": 1,
    "id": "report-001",
    "revision": 2,
    "status": "ready",
    "kind": "document",
    "title": "9 月经营分析报告",
    "description": "按已确认口径生成的经营分析",
    "preview": {
      "renderer": "document",
      "version": 1,
      "data": { "markdown": "# 经营分析\n\n本月收入……" }
    },
    "autoOpen": true
  }
}
```

- `schemaVersion`：事件信封版本，目前只接收 `1`。
- `id`：同一会话内唯一且跨更新稳定；外层 data part ID 和内层 ID 保持一致。同一条消息里同 ID 更新会替换已有 data part。
- `revision`：每次快照递增的正整数，状态变化也递增。重复或更旧事件忽略；同 ID 不能改变 `kind`。
- `status`：`generating`、`ready`、`error`。`ready` 至少包含预览或文件；`error` 必须含可读 `error`。较新 revision 可以启动一次新修订。
- `kind`：`document`、`spreadsheet`、`presentation`、`custom`。未知业务形态使用 `custom`，通过 renderer 标识扩展。
- `preview`：可选的结构化预览，`renderer` + `version` 决定本地渲染器；`data` 必须是 JSON 数据。
- `file`：可选的真实文件，字段为 `url`、`name`、`mimeType`、可选 `sizeBytes`。只有 `ready` 且文件地址有效才展示下载。
- `autoOpen`：新成果首次到达时的打开提示。关闭后，同一成果的后续状态或版本更新不会强制重新打开。

**更新发送完整快照，而非 JSON patch 或文本 delta。** 先发送 revision 1 / generating，再发送 revision 2 / ready。大文件不放入消息事件；只发送有界预览和文件引用。错误、未知渲染器都有降级展示；已知渲染器的不合法数据在接收边界被拒绝，不覆盖上一份有效快照。

成果事件不可设为 `transient: true`，否则不进入消息历史。持久化完整 `UIMessage.parts`；载入历史后先用 `collectArtifacts(messages)` 还原状态，禁止恢复时自动打开所有历史成果。服务端应保存权威最新快照，并保证发出事件的 revision 顺序；仅保存 SDK 最后替换过的 data part 无法恢复被乱序覆盖的旧历史。

## Node / Python / Java 后端

Node 端直接使用 `createUIMessageStream` 与 `createUIMessageStreamResponse`，参考项目中的可运行路由。实际生成服务替换演示数据即可；不需要改会话组件。发送工具调用的请求和返回时保持 `toolCallId` 一致。

其他语言输出同样的 SSE 数据。响应头包括 `Content-Type: text/event-stream` 和 `x-vercel-ai-ui-message-stream: v1`；代理层应关闭流缓冲。最小文本加成果响应如下，每个 `data:` 事件后有一个空行：

```text
data: {"type":"start","messageId":"assistant-001"}

data: {"type":"text-start","id":"text-001"}

data: {"type":"text-delta","id":"text-001","delta":"报告已整理好。"}

data: {"type":"text-end","id":"text-001"}

data: {"type":"data-artifact","id":"report-001","data":{"schemaVersion":1,"id":"report-001","revision":1,"status":"ready","kind":"document","title":"报告","preview":{"renderer":"document","version":1,"data":{"markdown":"# 报告\n\n正文"}},"autoOpen":true}}

data: {"type":"finish","finishReason":"stop"}

data: [DONE]

```

这不是 OpenAI Chat Completions 的原始 SSE。若后端现有接口使用其他事件格式，在 BFF/transport 边界转换一次，保留稳定消息、工具和成果 ID，不要让每个 UI 组件各自解析供应商格式。

生产接入时由服务端鉴权并校验成果归属，下载地址由服务端生成，不能直接信任模型提供的 URL。私有文件可采用同源下载接口或短期签名 URL；跨域下载要由服务端设置 `Content-Disposition`。前端只限制危险 URL scheme，不能替代后端权限控制。停止演示会中断 HTTP 请求；真实后台长任务需要另外定义 jobId 和取消接口，不能仅凭客户端停止就声称服务端任务已经取消。

## 办公三件套的支持范围

| 类型 | 当前已实现的在线预览 | 实际 Office 文件接入 |
| --- | --- | --- |
| 文档 | Markdown 标题、列表、表格、代码与正文 | 后端生成 DOCX 并返回 `file`；同时提供 Markdown 预览 |
| 表格 | 多工作表、表头与数据、独立横向/纵向滚动 | 后端生成 XLSX 并返回 `file`；同时提供 sheets JSON，公式以计算结果展示 |
| 演示文稿 | 分页、缩略图、标题、要点和演讲备注 | 后端生成 PPTX 并返回 `file`；同时提供 slides JSON |
| 自定义 | 已注册的 BI 看板 | 同一契约，按需要提供 JSON 预览和文件 |

模板实现的是三类办公成果的结构化预览，不是任意 DOCX/XLSX/PPTX 二进制文件的高保真解析器，也不是在线 Office 编辑器。演示没有伪造 Office 下载文件。若项目需要保留原始分页、复杂图表、公式或母版，推荐后端转换为 PDF/分页图片，或接入自部署的 Office 查看/编辑服务，再注册对应预览器。具体服务部署和许可需由落地项目决定，基础模板不绑定第三方云查看器。

## 接入自定义成果物

1. 在共享 schema 模块定义可序列化数据结构。例如 `company.capacity:1`，加入 `builtinPreviewValidators`（或向 reducer 传入包含它的 validators），让接收边界拒绝坏数据、保留上一份有效快照。仅在 UI registry 注册 schema 只能阻止错误渲染，不能阻止坏快照替换状态。后端用相同 schema 校验工具输出。
2. 编写可信 React 组件，接收 `{ data, artifact }`，复用主题 token 和项目 Icons。
3. 在 `registry.tsx` 注册 schema 与组件：

```tsx
defineArtifactRenderer({
  id: 'company.capacity',
  version: 1,
  label: '产能看板',
  schema: capacityPreviewSchema,
  component: CapacityPreview
});
```

4. 服务端发送 `kind: 'custom'`、`preview: { renderer: 'company.capacity', version: 1, data: ... }` 的 `data-artifact`。无需修改对话布局、工具组件或成果面板。
5. 数据形状发生不兼容变化时新增 renderer version；未知版本显示安全回退。不要在消息中发送 React 源码、JavaScript、可执行 HTML 或动态模块地址。

## 滚动与交互约定

### 流式文字显示

`streaming/use-typewriter-messages.ts` 在展示层缓冲当前助手的正文与 thinking，网络接收和 `useChat.messages` 始终保留原始完整数据。默认约 **90 个可见字符/秒**，按动画帧均匀释放；积压超过正常显示能力时自动追赶，网络完成后的尾部最多显示 800ms，避免模拟打字拖延结果。参数集中在 `streaming/presentation.ts` 的 `TYPEWRITER_CONFIG`，不增加“立即显示”或速度控制入口。

按 Unicode grapheme 切分，保留中文、组合字符和 emoji；英文单词整体释放，配对标点与相邻字符一起显示，流尚未结束时暂存未完成的末尾单词，减少行尾文字先出现再换行的跳动。历史记录初次挂载直接呈现；停止或错误时展示已收到内容并结束队列。减少动态效果模式、后台页面直接同步已接收文本，清空或切换回复时取消旧 RAF。工具与成果物数据不做逐字动画，事件仍即时处理，对话中的后续内容遵循消息顺序展示。

正文与文档预览统一使用 `components/chat-markdown.tsx` 封装的 **Streamdown**。它负责 GFM、不完整 Markdown 的自动修复与分块 memoization；默认接入官方 `@streamdown/cjk`，处理中文标点旁的强调和链接边界。`src/styles/globals.css` 的 `@source` 用于生成库内的 Tailwind 样式；无需再接入 react-markdown、remark-gfm 或单独的修复器。保持 streaming 分块结构，完成时仅结束修复/忙碌状态，避免整段切换渲染树。普通 Markdown 仍可能因新增表格、标题或显式换行发生正常排版变化，不能承诺任意输入完全不重排。

默认启用 Streamdown 原生逐字淡入：`fadeIn`、120ms、`sep: char`、`stagger: 0`，只改变透明度，不添加位移或模糊。显示队列负责速度，因此动效不再叠加延迟；已完成内容移除动画 span，减少动态效果偏好禁用动画。参数集中在 `ChatMarkdown` 的 `animation` 常量，不自行维护字符动画 DOM。工具栏默认关闭，不加载代码高亮、数学或 Mermaid 插件。显示队列仅控制节奏和安全边界，不解析 Markdown。原 MessageScroller 仍是唯一滚动跟随所有者，显示队列不设置滚动位置。需要额外格式时，在统一适配器中按产品需求引入官方插件，并保持主题、安全策略和清理脚本同步。

安全边界：保留 Streamdown 默认 sanitize/harden 插件，但移除 raw-HTML 解释插件并启用 `skipHtml`；外部图片仅显示占位文字，链接使用默认安全 URL 过滤及 `noopener noreferrer`，模型不能提供可执行 HTML/JavaScript。自定义组件和插件配置提升到模块级，避免每次释放文字时重新创建组件。

针对一次收到大段内容的浏览器验证：`bun run test:ai-chat:typewriter`，报告在忽略目录 `coverage/ai-chat-typewriter/`。覆盖独立显示进度、完整字符、原始历史不被截断、减少动态效果、停止与重置，以及桌面/手机逐帧行尾位置、动画释放、Markdown 节点稳定性和安全边界；原有 `test:ai-chat:browser` 继续验证真实 SSE 与滚动/成果物交互。

### 滚动与布局

- 主对话显式使用 `MessageScrollerProvider autoScroll`，没有用户头像和外围聊天卡片，助手正文使用 ghost Bubble。
- thinking 默认展开，限高 160px，内部独立跟随；可手动折叠。嵌套滚动的 wheel/touch/key 意图不能冒泡影响外层。
- 工具默认一行，点击展开 input/output；依据工具自身状态展示完成/失败，停止后的旧调用不能在新一轮再次显示运行中。
- 用户上翻时保留阅读位置，回到底部或点击“回到最新”恢复；不能每次 token 都无条件 `scrollIntoView`。
- `ChatScrollViewport` 使用 primitive 的 `scrollToEnd` 处理聚焦滚动区后的 End 键，避免浏览器原生滚动只到达流式更新前的旧底部。其他滚动行为仍由 MessageScroller 负责。
- 正文和 thinking 共用 `ChatScrollViewport`：通过 Base UI 的 `render` 将 ScrollArea 与 MessageScroller 合成为同一个 DOM 滚动视口。MessageScroller 管理跟随/锚定，ScrollArea 管理独立滑块的比例和拖动；不能再嵌套第二个滚动视口或增加跟随 hook。[Base UI 组合说明](https://base-ui.com/react/components/scroll-area)。
- `chat-scroll-viewport.module.css` 仅作用于此功能：禁用原生滚动条和随滚动变化的视口渐隐遮罩；实际溢出时显示固定颜色/透明度的滑块，不随悬停或 `data-autoscrolling` 隐藏。高度使用 120ms 过渡平滑衔接内容增长；视口处于 `data-scrollable="start"`（跟随最新内容）时固定滑块下沿，浏览历史时位置立即响应，拖动或系统要求减少动态效果时取消过渡；强制颜色模式使用系统颜色。滑块仍按真实内容比例缩短，不冻结为虚假的固定长度。
- 桌面预览与对话并排；小于 1024px 使用 Sheet，支持关闭、Escape 和焦点管理。

## 开发检查

```bash
bun run typecheck
bun run lint:strict
bun run test:ai-chat
bun run build
# 浏览器首次安装
bunx playwright install chromium
# 另一个终端保持 bun run dev 运行
bun run test:ai-chat:browser
bun run test:ai-chat:typewriter
```

浏览器检查默认连接 `http://localhost:3000`，可用 `AI_CHAT_BASE_URL` 指定其他地址。普通回归产物写入 `coverage/ai-chat/`，逐字显示检查产物写入 `coverage/ai-chat-typewriter/`，均为 Git 忽略的本地文件。接入真实后端后，应使用实际模型、数据、流式代理与文件服务测试对应流程。

自定义滚动条的指针拖动发生在 viewport 的兄弟节点上，不能自然到达 MessageScroller 的滚动意图处理器。`ChatScrollViewport` 在滚动条 pointerdown 捕获阶段向同一 viewport 转发零增量 wheel 意图，让原状态机先退出跟随；不自行设置 scrollTop 或另建跟随逻辑。更换 primitive 后应复核其指针支持，并运行包含流中拖动的浏览器回归。
