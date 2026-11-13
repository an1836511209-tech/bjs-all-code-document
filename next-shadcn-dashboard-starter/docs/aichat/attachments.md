# 图片与输入附件接入

`/dashboard/ai-chat` 支持点击输入区的加号多选、直接粘贴剪贴板图片、向输入区拖入文件，以及不带文字的附件消息。使用现有 shadcn `Attachment` 组件显示图片缩略图、文件名、大小、上传状态、失败重试和移除。普通文本粘贴不受影响；上传中、存在失败附件时不能发送，上传中不能切换会话，移除正在上传的文件会中止客户端请求。流式生成期间不能添加或修改附件。

上传与聊天是两个请求：先取得服务端文件引用，再通过 AI SDK `FileUIPart[]` 发送。协议采用 [AI SDK 文件对象](https://ai-sdk.dev/docs/ai-sdk-ui/chatbot#attachments)，不把 FileList 自动转换的 Base64 写进消息。输入附件是用户提供的资料，与助手输出的 `data-artifact` 成果物分开管理。

## 路径与扩展点

| 路径 | 职责 |
| --- | --- |
| `src/features/ai-chat/attachments/types.ts` | 文件白名单、容量限制、上传 DTO schema、URL 边界及 FileUIPart 转换，共享给前端、接口、历史恢复 |
| `attachments/service.ts` | 浏览器上传服务，替换远程上传请求的入口；使用 FormData，由浏览器设置 boundary，不使用默认 JSON Content-Type |
| `attachments/use-attachments.ts` | 会话级临时队列、并行上传、去重、AbortController、重试及 blob URL 释放；不是聊天消息或服务器文件的权威存储 |
| `attachments/store.ts` | 仅在 Node 服务端导入的临时文件存储与基础内容校验；真实项目替换为持久化文件仓库 |
| `attachments/body.ts` | 按实际读取字节数限制请求体，包含无 Content-Length 的请求 |
| `src/app/api/ai-chat/attachments/route.ts` | multipart 上传接口 |
| `src/app/api/ai-chat/attachments/[id]/route.ts` | 文件读取接口，使用异步路由 params |
| `src/app/api/ai-chat/route.ts` | 消息文件引用校验与流式生成入口 |
| `src/features/ai-chat/components/chat-attachment.tsx` | 草稿、历史附件的共享呈现；图片使用不经过优化代理的 next/image |

这里的上传是会话级临时资源传输，不建立 React Query 查询缓存。未来增加文件库 CRUD 时，按项目 `api/types/service/queries/mutations` 和 React Query 规范接入；token 流继续使用 `useChat`。

缩略图错误回调必须保持稳定引用（`useCallback`），图片源变化时才通过 key 重建加载状态。不要在 `next/image` 上传入随 token 更新而变化的内联 `onError`：当前 Next.js 会因此重新绑定图片 ref 并再次设置 src，导致已加载缩略图在流式期间重复刷新。附件浏览器回归会在真实 SSE 增长时逐帧检查解码状态、DOM 身份、src/srcset 写入和图片请求。

## 默认策略

- 每条消息最多 **5 个文件**，每个最多 **10 MiB**，合计最多 **20 MiB**；界面以 MB 简写。空文件不接受。常量在 `types.ts`，调整限制时同时检查网关、存储、解析服务和模型能力。
- 图片：PNG、JPEG、WebP、GIF；文档：PDF、DOCX、XLSX、PPTX；文本/数据：UTF-8 TXT、Markdown、CSV、JSON。SVG、HTML、可执行文件、旧版二进制 Office 文件等不在默认白名单中。
- 客户端检查扩展名、声明 MIME、大小和数量；服务端再次校验。允许浏览器没有 MIME、通用 octet-stream、文本类型的合理差异，忽略 MIME 的 charset 参数。
- 服务端用 sharp 校验图片元数据、真实格式与 4,000 万像素上限；PDF 检查签名，Office 检查 ZIP 容器签名，文本校验 UTF-8/NUL，JSON 额外校验语法。**这不是完整文档解析或恶意文件扫描**，不能据此保证文件可被业务解析器处理。文件名仅作展示，磁盘路径只使用服务端 UUID。
- 上传请求体最多 10 MiB + 64 KiB multipart 开销；聊天 JSON 最多 4,000,000 字节。超限按实际流读取中止，不能只信 Content-Length。

## 上传与读取 HTTP 契约（已实现）

`POST /api/ai-chat/attachments`，`multipart/form-data`，一次仅包含一个 `file` 字段；多选时前端逐文件请求。成功 `201`：

```json
{
  "attachment": {
    "id": "cbbd92b9-6364-4d68-af8e-2900d5a79f4b",
    "filename": "需求截图.png",
    "mediaType": "image/png",
    "size": 102400,
    "url": "/api/ai-chat/attachments/cbbd92b9-6364-4d68-af8e-2900d5a79f4b",
    "expiresAt": "2026-10-20T04:00:00.000Z"
  }
}
```

`size` 是原始字节数，`expiresAt` 是 UTC ISO 时间。客户端必须运行时校验 DTO，不能自行构造服务端文件引用。失败响应使用 `{ "code": "INVALID_FILE", "error": "可公开的错误说明" }`：

| 状态 | code | 处理 |
| --- | --- | --- |
| 400 | `INVALID_REQUEST` | multipart 无效、文件字段缺失或多余 |
| 413 | `TOO_LARGE` | 请求体或本条消息附件总大小超限 |
| 415 | `INVALID_FILE` | 类型、内容、编码、空文件或文件大小不符合策略 |
| 500 | `UPLOAD_FAILED` | 存储/服务异常；保留本地选择，可逐文件重试 |

客户端显示固定安全文案，不直接展示任意后端 error.message。上传过程显示不确定进度；没有伪造的百分比。移除/中断不能保证服务端未落盘，重复上传也可能产生不同 ID；生产去重与幂等由后端处理。

`GET /api/ai-chat/attachments/:id` 返回原始文件；图片 inline，其他文件 attachment，UTF-8 文件名、`X-Content-Type-Options: nosniff`、沙箱 CSP、`Cache-Control: private, no-store`。无效/不存在/过期返回 `404 FILE_UNAVAILABLE`；读取异常返回 `500 FILE_UNAVAILABLE`。缩略图读取失败显示占位图标，原始文件不存在时需重新选择上传。

## 聊天请求中的文件（已实现）

保留现有 `id/conversationId/scenario/messages` 请求，文件放在用户消息 `parts` 内：

```json
{
  "id": "conversation-001",
  "conversationId": "conversation-001",
  "scenario": "long",
  "messages": [{
    "id": "user-001",
    "role": "user",
    "parts": [
      { "type": "text", "text": "请分析这张截图" },
      {
        "type": "file",
        "filename": "需求截图.png",
        "mediaType": "image/png",
        "url": "/api/ai-chat/attachments/cbbd92b9-6364-4d68-af8e-2900d5a79f4b"
      }
    ]
  }]
}
```

使用 `sendMessage({ text, files: uploaded.map(toFilePart) }, options)`。允许空文字，但必须有附件。所有历史 file part 校验 URL/MIME/数量；只接受本站文件读取路径及 UUID，禁止任意外部 URL、data:、blob:、javascript:。新一轮文件还必须存在、未过期、文件名和 MIME 与服务端记录一致，合计不超过限制。新文件无效/过期在 SSE 开始前返回 `400 FILE_UNAVAILABLE`；仓库暂不可用返回 `503 FILE_UNAVAILABLE`。历史过期附件仍可展示文件名，不阻止后续纯文本对话。

**当前演示仅验证文件与消息传输，不读取附件语义、不调用模型、不解析 Office/PDF。** 带附件的演示回复会明确此边界。输入的文件名或内容不用于触发成果物预览。生成失败时 canonical 用户消息与文件引用保留，不自动重发；检查网络或重新上传后继续对话。

## 历史、有效期与删除

`ConversationSnapshot.draftAttachments?: UploadedAttachment[]` 为历史 v1 的兼容性可选字段；已发送的标准 file part 随 canonical messages 保存。旧记录无需迁移；新字段和 file URL 在恢复边界校验。仅上传完成的草稿引用可持久化；上传中/失败的 File、AbortController、blob 预览不写入 localStorage，刷新后需重新选择。历史总大小上限仍为 4,000,000 字节，附件原始数据不会计入浏览器存储。

本地演示文件保存在操作系统临时目录 `shadcn-ai-chat/<工作目录 SHA256 前16位>/`，以 UUID 命名，默认 **24 小时**有效。后续上传会清理同目录超过该期限的文件；没有定时清理任务，系统清理临时目录也可能提前使其失效。单机可写文件系统能跨同目录服务重启保留文件，但不保证容器重建、Serverless 或多副本可用，不能当作持久对象存储。

移除草稿、删除会话仅删除引用，不立即删除服务端文件，避免破坏已发送消息或其他引用。前端不调用 DELETE；模板没有实现文件删除/续期/重签名接口。生产项目须由引用计数或保留策略清理孤儿文件。临时文件到期后历史文字仍保留，但文件本身不会随 JSON 备份导出或恢复。

## 接入真实模型或 Agent

1. 替换 `store.ts` 为持久对象存储及数据库元数据，保留上传 DTO。当前模板无登录鉴权，文件 URL 的随机 ID 仅提供不可预测性，持有 URL 的人可读取；**不能将演示路由直接用于私密生产资料**。业务上传、读取、聊天引用均须验证当前用户、租户、会话和文件归属，并配置 CSRF、限流、配额、扫描、审计及保留策略。
2. 前端 `url` 保持稳定的本站文件 ID 路径，由 BFF 认证读取或重定向到短期签名 URL；不要把会过期的对象存储签名 URL 当作永久消息引用。更改 URL 契约须同步 `types.ts`、历史校验、服务端校验、UI 和测试，不能仅修改 fetch 地址。
3. 在 `POST /api/ai-chat` 中按 ID 解析并授权所有需要用作模型上下文的文件。服务端获取可信字节或签名 URL，将相对地址转换为模型支持的数据形式，再调用 `convertToModelMessages`/`streamText` 或 Agent 适配器；不能把本站相对 URL 原样交给远程模型，也不能让模型下载客户端任意地址。
4. 图片交给具备视觉能力的模型，PDF 按供应商能力决定原文件或提取文本；DOCX/XLSX/PPTX、CSV 等接入受限解析服务。不要假设所有模型支持任意 MIME。解析文本标记为不可信用户资料，保留来源与权限，不把文档里的指令提升为系统指令。限制解压大小、页数、像素、行列、解析超时及上下文 token。
5. 若需要异步扫描/OCR/索引，设计独立 `uploaded/processing/ready/failed` 权威状态及查询接口；当前 201 只表示模板基础校验并存储完成，不代表生产解析成功。把未 ready 附件阻挡在发送前，前端状态不能代替服务端判定。
6. 定义会话/文件绑定、幂等 requestId、取消与清理协议；后台 OCR/Agent 任务不会因为浏览器 AbortController 自动停止。真实后端可补充 401、403/404、409、429 状态码，统一应用层安全错误映射。

## 验证

```bash
bun run typecheck
bun run lint:strict
bun run format:check
bun run test:ai-chat
# 启动应用；可用 AI_CHAT_BASE_URL 指定端口
bun run test:ai-chat:attachments
bun run test:ai-chat:history
bun run test:ai-chat:browser
```

附件浏览器检查使用真实上传/读取接口与系统剪贴板，聊天回复用确定性 SSE fixture。覆盖多选、只发附件、粘贴、拖放、取消、失败重试、大小/数量限制、历史恢复及移动端溢出。脚本在操作系统临时目录产生演示文件，浏览器截图与结果写入忽略的 `coverage/ai-chat-attachments/`。真实模型理解、解析准确率和生产文件权限需由接入团队单独验证。
