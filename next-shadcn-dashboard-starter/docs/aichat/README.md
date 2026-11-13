# AI Chat 开发指南

打开 `/dashboard/ai-chat` 体验模板。默认使用模拟响应，无需模型密钥。

| 指南 | 用途 |
| --- | --- |
| [历史会话与后端接入](./history.md) | 侧栏、新建/搜索/切换/重命名/删除、本地存储、服务端会话 API 建议 |
| [流式对话与成果物](./artifacts.md) | UI Message Stream、thinking、工具调用、成果事件与预览器扩展 |
| [图片与输入附件](./attachments.md) | 多选、粘贴、拖放、临时文件上传/读取、标准 file part、模型与 Agent 对接 |
| [主题适配](./theming.md) | 颜色配对、侧栏与图表 token、字体作用域、全主题浏览器回归 |

功能入口为 `src/features/ai-chat/components/ai-chat-workspace.tsx`；会话内容位于 `ai-chat-demo.tsx` 的 `AiChatSession`。修改前阅读 `.agents/skills/ai-chat-artifacts/SKILL.md`。功能可通过 `bun run cleanup ai-chat` 从派生项目移除。
