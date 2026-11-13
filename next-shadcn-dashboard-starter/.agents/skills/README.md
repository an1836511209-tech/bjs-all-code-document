# 项目技能导航

从“当前要完成什么任务”选择 skill，再读对应的 `SKILL.md`。这里提供任务入口，不重复技能里的操作步骤。项目级协作约定见 [AGENTS.md](../../AGENTS.md)，开发指南入口见 [README.md](../../README.md)。

## 怎么选

1. 新增或修改业务功能，先读项目专用的 `kiranism-shadcn-dashboard`；功能有专用契约时，再读对应指南。
2. 按实际涉及的组件、表单、数据或框架问题补充通用 skill。一个任务可以组合使用多个 skill，但不需要把整个目录读一遍。
3. 每个 skill 下的 `references/`、`rules/` 或完整 `AGENTS.md` 按问题继续查阅；入口已经足够时，不再展开全部参考文件。

仅修改文案、文档链接或已明确的小范围配置时，可直接处理。遇到报错时，先用错误和复现确定所属领域，再按下面的入口查阅；技能目录没有独立的调试或通用验收 skill，不必为了凑流程加载无关内容。

## 按任务查找

| 当前任务 / 触发条件 | 优先阅读 | 适用边界 / 何时补充 |
| :--- | :--- | :--- |
| 新增业务页面、表格、功能模块；修改菜单、主题或图表 | [kiranism-shadcn-dashboard](./kiranism-shadcn-dashboard/SKILL.md) | 本项目开发主入口，说明目录、数据层和页面约定；组件细节再补 `shadcn`，框架问题再补 `next-best-practices` |
| 新增或组合 shadcn 组件；修复 Dialog、Select、滚动区域、布局样式或组件交互 | [shadcn](./shadcn/SKILL.md) | 查对应 `rules/`，尤其注意 Base UI 与 Radix 的 API 差异；不因普通组件任务重新初始化项目或切换 preset |
| 开发表单、字段校验、动态字段、数组字段、联动或提交状态 | [项目表单指南](../../docs/forms.md) → [tanstack-form](./tanstack-form/SKILL.md) | 项目指南决定共享字段与封装，通用 skill 补充表单状态机制；表单 UI 需要时再查 `shadcn` 的 forms 规则 |
| 对接 CRUD 接口；处理查询缓存、分页筛选、mutation 或失效刷新 | [kiranism-shadcn-dashboard](./kiranism-shadcn-dashboard/SKILL.md) → [tanstack-query](./tanstack-query/SKILL.md) | 沿用 feature 的 types/service/queries/mutations 分层；查询 Hook 按当前页面的预取、Suspense 和 URL 状态选用，不机械套用单一 Hook |
| 修改路由、Server/Client 边界、Route Handler、metadata、图片字体；排查 hydration 或构建问题 | [next-best-practices](./next-best-practices/SKILL.md) | 阅读对应主题文件即可；普通组件排版无需展开全部 Next.js 规则，性能瓶颈再查 React 性能 skill |
| 排查 React/Next.js 加载慢、请求瀑布、包体积或频繁重渲染 | [vercel-react-best-practices](./vercel-react-best-practices/SKILL.md) | 根据实际瓶颈选择 `async-`、`bundle-`、`rerender-` 等规则；通用示例不构成引入 SWR 或替换现有 React Query 的理由 |
| 重构组件 API；处理大量布尔 props、复合组件、render props 或共享 context | [vercel-composition-patterns](./vercel-composition-patterns/SKILL.md) | 用于组件组合与状态边界；简单改文案或加一个按钮通常无需重构组件体系 |
| 用户要求 UI/UX 审查、可访问性检查或设计规范审计 | [web-design-guidelines](./web-design-guidelines/SKILL.md) | 明确审查范围，并按该 skill 获取最新规范；普通页面开发无需额外启动全站审计 |
| 修改错误提示、失败状态、重试或故障恢复 | [错误处理指南](../../docs/error-handling.md)；涉及组件或路由时补 `shadcn` / `next-best-practices` | 项目没有单独的错误处理 skill，直接使用现有共享反馈约定 |

## AI Chat and Artifacts

修改 `/dashboard/ai-chat`、`src/features/ai-chat/`，或涉及历史会话、流式文字、thinking、工具调用、跟随滚动、成果物预览与后端协议时，优先读 [ai-chat-artifacts](./ai-chat-artifacts/SKILL.md)。普通点对点消息页不走这个专用流程。

| 具体任务 | 阅读顺序 |
| :--- | :--- |
| 修改 AI Chat 页面或流式交互 | `ai-chat-artifacts` → [shadcn 聊天规则](./shadcn/rules/chat.md)（涉及聊天组件时） |
| 修改输入图片/附件上传、粘贴/拖放、文件引用或上传后端 | `ai-chat-artifacts` → [附件契约](../../docs/aichat/attachments.md) → `shadcn` 聊天规则；服务端文件路由补 `next-best-practices` |
| 修改历史会话、持久化或会话切换 | `ai-chat-artifacts` → [历史会话契约](../../docs/aichat/history.md) |
| 对接模型流、成果物事件或新增预览类型 | `ai-chat-artifacts` → [成果物与后端契约](../../docs/aichat/artifacts.md) |

AI Chat 的 token 流使用 `useChat` 与 SSE，不套用普通 CRUD 的 React Query 数据通道。服务端会话 CRUD 若采用 React Query，再补读 `tanstack-query`。其他说明见 [AI Chat 开发指南](../../docs/aichat/README.md)。

## 常见组合

| 任务示例 | 建议阅读顺序 |
| :--- | :--- |
| “新增订单列表，支持分页、筛选和编辑弹窗” | `kiranism-shadcn-dashboard` → `tanstack-query` → 项目表单指南；字段逻辑或弹窗 API 需要时补 `tanstack-form` / `shadcn` |
| “调整主题或新增一种配色” | `kiranism-shadcn-dashboard` → [主题指南](../../docs/themes.md)；组件样式需要时补 `shadcn` |
| “这个页面卡，查一下原因” | 先复现并定位请求、渲染或布局瓶颈 → `vercel-react-best-practices` 的对应规则；涉及服务端边界再补 `next-best-practices` |
| “检查弹窗的键盘操作和错误提示” | `web-design-guidelines` → `shadcn` 的相关规则 → 项目错误处理指南 |

## 项目约定与通用示例

根目录 `AGENTS.md` 说明项目整体约定，项目专用 skill 和 `docs/` 说明具体功能契约，通用 skill 提供库与框架的补充知识。通用示例与本项目封装不同，先核对当前源码、已安装版本及现有指南，不直接照搬，也不顺便迁移技术方案。

尤其注意：表单优先使用项目现有 `useAppForm` 和共享字段；查询 Hook 按页面现有数据模式选择；图标遵循 `@/components/icons` 的统一入口。文档与源码确有出入时，明确差异，再在当前任务范围内修正。

新增、删除或调整 skill 的职责时，同步更新本导航的触发条件、边界及链接；功能裁剪涉及的导航内容也应随功能移除。
