# 历史会话与后端接入

## 默认模板行为

桌面（宽度至少 1024px）默认显示历史侧栏，手机使用左侧 Sheet。侧栏使用平整背景、搜索与新建入口、单行标题的“最近对话”列表和低对比选中态；不显示每行日期、消息数或常驻编辑/删除图标。会话更多菜单在悬停、键盘焦点或触屏下显示，重命名与确认删除均收在菜单内。列表按消息更新时间倒序，支持标题搜索与当前项标识。

新建会保留已有对话；空白且无草稿的当前会话可直接复用，删除最后一项会创建新的空白对话。标题默认取首条用户消息前 80 个 UTF-16 代码单元；手动命名后不再自动覆盖。对话正文与输入区居中，最大宽度 768px，保持阅读行宽一致。

侧栏和成果物预览分别控制：打开桌面成果预览时暂时隐藏历史栏；关闭预览后恢复，或通过标题旁的历史按钮返回。小屏两个面板均使用有标题、支持 Escape 和焦点管理的 Sheet。

生成和逐字显示期间，禁用新建、切换、重命名、删除。用户可先停止再切换。每个会话以 ID 为 React key 和 `useChat.id`，切换时隔离草稿、示例选择、消息、工具、错误和成果状态。恢复的成果不会自动弹开；仍为 `generating` 的成果展示未完成提示，不伪造服务端成功或更高 revision。

## 源码职责

| 文件（相对 `src/features/ai-chat/`） | 职责 |
| --- | --- |
| `history/types.ts` | Conversation、ConversationSnapshot、ConversationHistory 类型 |
| `history/state.ts` | 新建、标题生成、快照更新、删除及容量常量 |
| `history/service.ts` | 版本化本地存储适配器、恢复边界校验 |
| `components/ai-chat-workspace.tsx` | 加载、保存、异常提示、当前会话挂载 |
| `components/conversation-history.tsx` | 搜索、列表、会话操作与重命名表单 |
| `components/ai-chat-demo.tsx` | 单个会话的流式交互与成果恢复 |

## 浏览器存储契约（已实现）

键为 `ai-chat:history:v1`，只在客户端加载。首屏先展示 Skeleton，读取、验证完成后挂载会话，避免 SSR hydration 差异。存储 JSON：

```ts
interface ConversationHistory {
  schemaVersion: 1;
  activeId: string;
  conversations: Conversation[];
}
interface Conversation {
  id: string;                    // crypto.randomUUID()，不会从标题派生
  title: string;                 // 1–80 个 UTF-16 代码单元
  titleSource: 'automatic' | 'manual';
  createdAt: string;             // UTC ISO 8601
  updatedAt: string;             // 最近消息更新；查看、草稿、重命名不改变排序
  messages: DemoUIMessage[];     // 完整 SDK parts，不是 typewriter 展示副本
  artifacts: ArtifactState;      // 已校验的权威最新快照，按 ID 保存
  draft: string;
  scenario: 'document' | 'spreadsheet' | 'presentation' | 'dashboard' | 'long';
}
```

最多保留 50 个会话、每个会话最多 200 条消息、本地 JSON 最多 4,000,000 字节；达到上限提示用户清理或新建，不自动淘汰历史。已有 198 条消息时拒绝继续发送（预留一轮用户/助手消息）。草稿输入与恢复校验上限 100,000 个代码单元。超限和配额错误不会删除旧存储。

快照在请求提交、完成、停止、失败以及空闲编辑时更新，存储写入合并 300ms，页面隐藏退出（`pagehide`）或路由卸载时尝试刷新。流式 token 不触发 localStorage 写入。强制退出或流中刷新只能恢复最近保存的用户请求/已完成内容，**不保证恢复尚未保存的部分响应**，也不自动续传/重发请求。

读取前校验版本、会话/消息 ID、时间、结构和成果 schema；空消息数组是合法的新建/草稿会话，不传入要求非空的 SDK 校验器；非空消息结构使用 AI SDK `safeValidateUIMessages`，工具业务数据仍需真实后端按工具 schema 校验。消息中的无效成果由现有接收边界忽略。恢复时先 `collectArtifacts(messages)`，再按 revision 合并独立权威快照，避免乱序消息覆盖最新成果。

读取失败显示紧凑的中性「临时会话模式」提示，区分记录格式不兼容与浏览器存储权限异常，不覆盖原记录，也不引导用户直接清理站点数据。写入失败显示「会话尚未保存」与重试保存按钮，区分容量上限、浏览器配额与权限问题；恢复存储后保存当前内存快照并清除提示。两类提示都提供「导出当前会话」，导出的是包含完整消息、草稿与成果快照的 JSON 备份，不是 Office 文件；模板尚未提供备份导入 UI，恢复需由开发者按本契约校验后接入。临时模式不会在刷新后自动恢复；离开前应先导出。浏览器禁用存储、清理数据、无痕会话结束都可能导致记录丢失。此适配器不提供账号隔离、跨设备同步、并发标签页合并或备份；同一浏览器多标签页为最后写入者覆盖。业务项目应替换为服务器存储，并在登出/切换租户时清理相关缓存。

已上传草稿通过可选 `draftAttachments` 保存，已发送附件通过标准 file part 保存；浏览器不保存文件字节或 blob URL。上传中不能切换会话。文件有效期、恢复与模型接入见[图片与输入附件](./attachments.md)。

## 流式请求（已实现）

`POST /api/ai-chat` 继续使用 `DefaultChatTransport`，附加业务 body：

```json
{
  "id": "conversation-001",
  "conversationId": "conversation-001",
  "scenario": "document",
  "messages": [
    { "id": "user-001", "role": "user", "parts": [{ "type": "text", "text": "请整理经营分析报告" }] }
  ]
}
```

SDK 还会携带 `id`、`trigger` 等字段，`id` 与 `conversationId` 均来自当前会话 ID。演示路由校验 `messages`、`scenario`、请求大小及文件引用，不保存、不授权也不解释 `conversationId`；响应仅按示例生成。生产后端应校验两个 ID 一致，并验证会话属于当前登录用户/租户，不能只相信前端 ID。

响应流及工具/成果 schema 见[成果物契约](./artifacts.md)。业务持久化必须保存 canonical 消息及最新成果快照；恢复只展示历史，不应重新执行历史工具。

## 服务端会话 API（接入建议，未实现）

本模板没有这些 HTTP 路由。团队接入时可以采用以下约定，按实际后端调整：

| 操作 | 建议接口 | 返回/说明 |
| --- | --- | --- |
| 列表 | `GET /api/conversations?cursor=&limit=20&search=` | `{ items: ConversationSummary[], nextCursor: string \| null }`；摘要不含完整消息/成果 |
| 新建 | `POST /api/conversations` | `201`，会话摘要；服务端分配 ID |
| 详情 | `GET /api/conversations/:id` | Conversation 详情或等价服务端 DTO，含 canonical messages 与 artifacts |
| 重命名 | `PATCH /api/conversations/:id` | `{ title, expectedRevision }` → 最新摘要 |
| 删除 | `DELETE /api/conversations/:id` | `204`；删除消息/成果引用；文件保留策略由业务确定 |
| 生成 | `POST /api/ai-chat` | `{ conversationId, requestId, scenario?, messages? }` → UI Message SSE |

`ConversationSummary` 建议包含 `id/title/titleSource/createdAt/updatedAt/revision/messageCount`。列表固定 `updatedAt DESC, id DESC` 游标排序，搜索由服务端执行。采用服务端创建 ID 后再挂载 `useChat`；不要先用本地 ID 发送，再异步改 ID 导致响应归属不一致。

会话 CRUD 接入遵循仓库 `api/types.ts → service.ts → queries.ts → mutations.ts` 与 React Query/Suspense 规范；token 流继续使用 `useChat`，不进行轮询。将当前本地集合加载替换为列表/详情查询及创建、重命名、删除 mutation，组件保留呈现职责。后端返回的 DTO 在 service 边界做运行时校验，错误保留当前内容并提供重试。

服务端按会话串行或使用 revision 乐观并发；客户端请求附幂等 `requestId` 防止重试重复创建用户消息/执行工具，`expectedRevision` 冲突返回 `409` 并重新获取详情。完成/停止/失败持久化服务端实际状态，前端断开连接不代表后台作业取消。若支持后台执行/续传，需单独约定 run ID、事件序号、恢复游标、取消接口和服务端权威状态。

统一错误建议 `{ error: { code, message, requestId? } }`，区分 `400` 参数、`401` 未登录、`403/404` 无权/不存在、`409` 版本冲突、`429` 限流及 `5xx`。重命名/删除必须在服务端验证归属、长度和 revision；客户端禁用按钮不能代替鉴权或并发控制。

## 验证命令

```bash
bun run typecheck
bun run lint:strict
bun run format:check
bun run test:ai-chat
bun run build
# 保持开发服务器运行，首次需 bunx playwright install chromium
bun run test:ai-chat:browser
bun run test:ai-chat:typewriter
bun run test:ai-chat:history
```

历史浏览器回归覆盖增删改查、刷新、草稿、生成隔离、成果恢复、移动端及异常存储。报告与截图写入忽略目录 `coverage/ai-chat-history/`。模拟响应验证不等同于真实模型、鉴权数据库、跨设备同步或部署环境验收。
