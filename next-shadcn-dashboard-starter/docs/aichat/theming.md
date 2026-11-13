# AI Chat 主题适配

AI Chat 复用模板右上角的主题选择器与明暗切换，不建立独立配色或主题 Provider。`<html data-theme>` 选择主题，`next-themes` 管理 `.dark`；主题定义见[主题与字体配置](../themes.md)。

## 按用途使用 token

| 界面区域 | 背景 | 文字/状态 |
| --- | --- | --- |
| 沉浸式对话、成果面板 | `background` | `foreground` |
| 历史侧栏、手机历史抽屉 | `sidebar` | `sidebar-foreground`；边框用 `sidebar-border` |
| 历史选中项、悬停与展开的操作按钮 | `sidebar-accent` | `sidebar-accent-foreground`；焦点用 `sidebar-ring` |
| 用户消息、表格业务表头 | `secondary` | `secondary-foreground` |
| 文档纸面、幻灯片画布 | `card` | `card-foreground` |
| 菜单、重命名/删除对话框 | `popover` | `popover-foreground` |
| 主操作按钮 | `primary` | `primary-foreground` |
| BI 图表数据序列 | `chart-1` 至 `chart-5` | 负值/错误沿用业务约定的 `destructive` |

这些名称对应 `src/styles/themes/*.css` 中的变量和 Tailwind 语义类。背景和前景必须成对选择；`bg-secondary` 上的正文要明确使用 `text-secondary-foreground`，不能继承页面的 `foreground`。不同主题的 secondary 可能为深色，也可能在深色模式中仍是浅色。

半透明背景会与下层颜色混合。需要保证可读性或遮挡滚动内容的表头、侧栏和预览纸面使用完整的表面色，不能只通过降低透明度模拟层次。说明文字可以使用相应的弱化文字色，但关键表头和选中会话标题保持正常文字对比度。

## 组件扩展边界

- 优先使用共享组件的既有 variant，例如用户消息使用 `Bubble variant='secondary'`，由组件同时设置背景和文字。
- 侧栏按钮的主题状态集中在 `components/conversation-history.module.css`，通过语义变量扩展 `Button`。保留共享按钮的键盘、禁用和焦点行为，不直接修改 `src/components/ui/`。
- `ArtifactPanel` 明确指定 `background/foreground`；移动端 Sheet 中不能让预览文字继承弹层的 `popover-foreground`。Portal 中的菜单、对话框继续使用自己的 popover token。
- 自定义 renderer 遵循相同约定。不要读取当前主题名称后硬编码一组颜色，也不要让模型/后端传任意 CSS、主题名或可执行样式。Artifact v1 协议保持不变，主题只影响客户端呈现。
- 图表正向序列和图例使用同一 `chart-*` 色。不要将主按钮 `primary` 当成所有图表的固定数据色。

## 字体作用域

`src/app/layout.tsx` 将 `fontVariables` 放在 `<html>`。主题的 `--font-sans`、`--font-mono` 定义也在此处，才能引用已加载的 `--font-geist-sans` 等变量。`body` 继承完整别名；不要使用 `--font-sans: initial` 清除它，也不要只把字体变量放在 body 后让 html 引用后代的变量。

主题引用未打包的字体时会使用其后备字体栈；新增字体按照[字体配置](../themes.md#字体配置)加载，不额外引入在线字体依赖。

## 检查主题变化

```bash
# 先启动应用；浏览器首次安装：bunx playwright install chromium
bun run test:ai-chat:themes
```

可用 `AI_CHAT_BASE_URL` 指定待检查地址。脚本从 `theme.config.ts` 读取已注册主题，通过真实主题选择器和明暗按钮切换，检查桌面与移动端、四类预览、侧栏选中/悬停、菜单、对话框、字体以及刷新恢复。颜色以浏览器计算结果转换为 sRGB 后与实际 token 比较；选中会话和表头文字额外检查至少 4.5:1 的对比度。截图和报告保存在 Git 忽略目录 `coverage/ai-chat-themes/`。

新增主题或更换 token 时同时运行此检查及原有流式、历史会话回归。若 token 已匹配而关键文字对比度仍不够，应修正对应主题的语义配对；不要在单个页面覆盖成固定黑/白来掩盖主题问题。
