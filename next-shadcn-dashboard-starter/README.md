# Admin Dashboard 前端基线模板

**团队内部前端基线模板**，用于统一各项目（demo / POC / 内部系统）的页面样式与代码结构。Next.js 16 + shadcn/ui（Base UI 原语）+ TypeScript + Tailwind CSS v4。

## 技术栈

- **框架**：[Next.js 16](https://nextjs.org)（App Router）+ React 19
- **UI**：[shadcn/ui](https://ui.shadcn.com)（Base UI 原语）+ [Tailwind CSS v4](https://tailwindcss.com)
- **数据**：[TanStack React Query](https://tanstack.com/query)（SSR 预取 + `useSuspenseQuery`）、[TanStack Table](https://tanstack.com/table)
- **表单**：[TanStack Form](https://tanstack.com/form) + [Zod](https://zod.dev)
- **URL 状态**：[nuqs](https://nuqs.47ng.com)
- **图表**：[Recharts](https://recharts.org)
- **命令面板**：[kbar](https://kbar.vercel.app)（Cmd+K）
- **包管理**：Bun（npm 亦可）
- **可选**：Sentry 错误追踪（默认未配置，不生效）

## 快速开始

```bash
bun install
cp env.example.txt .env.local   # 或直接创建，内容见 env.example.txt
bun run dev                     # http://localhost:3000
```

`.env.local` 无必填项；`NEXT_PUBLIC_APP_URL` 本地开发保持默认即可，部署时改为正式域名（用于 OG 图解析）。模板不含登录/认证，需要时通过数据层对接自有后端（如 JWT）。

## 目录结构

```
src/
├── app/                    # 路由层（页面很薄，只做组装）
│   ├── dashboard/          # 所有后台页面
│   └── api/                # 可选的 BFF 路由（当前为 mock 数据）
├── features/               # ★ 业务层，一个功能一个文件夹
│   └── <name>/
│       ├── api/
│       │   ├── types.ts    # 契约（响应结构、筛选参数、payload）
│       │   ├── service.ts  # 数据访问层 —— 换真实后端只改这个文件
│       │   └── queries.ts  # React Query 配置（key factory + queryOptions）
│       ├── components/     # 该功能的表格、表单、弹窗
│       └── schemas/        # Zod 校验
├── components/
│   ├── ui/                 # shadcn 基础组件（勿直接改，扩展为主）
│   ├── layout/             # 侧边栏、顶栏、页面容器
│   ├── icons.tsx           # 图标唯一注册入口（禁止直接 import @tabler）
│   └── themes/             # 主题系统（10 套主题 + 字体配置）
├── config/                 # 导航菜单、常量
├── hooks/                  # 通用 hooks
├── lib/                    # 工具（cn、query-client、searchparams）
└── styles/                 # 全局样式 + themes/*.css
```

## 数据层模式（对接真实后端）

普通业务页面的数据来自 `features/*/api/service.ts`（默认 mock）。对接 Python / Java 后端时：

- **直连**：`service.ts` 里 `fetch('https://your-api/...')`，保持 `types.ts` 字段契约一致即可，组件与 queries 零改动
- **BFF**：走 `src/app/api/` 代理（解决 CORS、统一鉴权头）

规范细节见 [AGENTS.md](./AGENTS.md)。

AI Chat 采用 `useChat` + HTTP SSE，接入方式见 [AI Chat 与 Artifacts 契约](./docs/aichat/artifacts.md)。

## 内置演示页面

| 页面 | 说明 |
| :--- | :--- |
| `/dashboard/overview` | 数据总览（并行路由、图表） |
| `/dashboard/product` | 商品表格（React Query + nuqs 全量模式，**新增功能前先读这个范例**） |
| `/dashboard/users` | 用户表格 |
| `/dashboard/forms/*` | 表单示例（basic / advanced / multi-step / sheet） |
| `/dashboard/kanban` | 拖拽看板 |
| `/dashboard/chat` | 消息 UI |
| `/dashboard/ai-chat` | 历史会话、沉浸式流式对话、折叠工具、文档/表格/PPT/自定义看板成果预览 |
| `/dashboard/react-query` | React Query SSR 模式演示（Pokemon API） |
| `/dashboard/elements/icons` | 图标浏览页 |

**新项目建议**：第一个业务功能写完后，用 cleanup 脚本删掉不需要的演示页：

```bash
bun run cleanup --list
bun run cleanup kanban chat ai-chat notifications   # 按需
```

## AI Chat 与成果物

输入区支持图片粘贴、多文件选择、拖放、上传重试与附件消息；提供可运行的本地临时上传接口和标准 file part 契约。默认不解析附件或调用真实模型，后端接入、文件有效期与鉴权要求见[图片与输入附件](./docs/aichat/attachments.md)。

`/dashboard/ai-chat` 提供中文长对话演示：文字按约 90 字符/秒平滑显示、thinking 独立限高滚动、工具请求与返回折叠展示、上翻暂停与到底恢复跟随，以及成果物侧栏。历史会话侧栏支持新建、标题搜索、切换、重命名、确认删除与浏览器本地恢复，桌面/手机分别使用侧栏和抽屉。生成中先停止再切换，避免会话串流。

完整文档见 [AI Chat 开发指南](./docs/aichat/README.md)，会话数据模型及后端对接见[历史会话契约](./docs/aichat/history.md)。默认存储仅限当前浏览器，不提供账号隔离或跨设备同步；真实项目需接入自己的鉴权和服务端会话存储。

演示通过 `/api/ai-chat` 发送真实 SSE，但使用模拟内容，不需要模型密钥。成果物以版本化 `data-artifact` 事件交付；内置办公三件套的结构化预览和自定义 BI 注册示例，真实 Office 下载文件需由后端生成。开发前阅读 [协议、后端接入与自定义 renderer](./docs/aichat/artifacts.md)，对应 skill 位于 `.agents/skills/ai-chat-artifacts/`。

验证：`bun run test:ai-chat`；启动开发服务后运行 `bun run test:ai-chat:browser`、`bun run test:ai-chat:typewriter`、`bun run test:ai-chat:history` 和 `bun run test:ai-chat:themes`（首次先 `bunx playwright install chromium`）。浏览器报告输出到忽略目录 `coverage/`。

## 新项目流程

1. 在本仓库 GitHub 页面 **Use this template**（需先在 Settings 勾选 Template repository）生成新仓库
2. `bun install` → 开发；AI 协作入口见 [AGENTS.md](./AGENTS.md)，按当前任务从[技能导航](./.agents/skills/README.md)选择需要阅读的 skill。具体工具的自动发现能力以其配置为准
3. 参照 `features/products` 的结构新增业务功能；完成后用 cleanup 裁剪演示页

## 使用文档

| 开发任务 | 指南 |
| :--- | :--- |
| 为当前任务选择 skill | [技能导航：触发条件、适用边界与阅读顺序](./.agents/skills/README.md) |
| 开发业务表单 | [表单组件与校验](./docs/forms.md) |
| 调整主题和字体 | [主题配置](./docs/themes.md) |
| 接入 AI 对话、历史会话和成果物 | [AI Chat 开发指南](./docs/aichat/README.md) |
| 错误提示与故障恢复 | [错误处理指南](./docs/error-handling.md) |
| 部署新项目 | [构建与部署](./docs/deployment.md) |

## 致谢

基于 [Kiranism/next-shadcn-dashboard-starter](https://github.com/Kiranism/next-shadcn-dashboard-starter)（MIT License），感谢原作者 [@Kir4n](https://github.com/Kiranism)。
