# 主题与字体配置

本指南用于调整模板外观、添加主题和配置本地字体。主题颜色与明暗模式分别管理：`data-theme` 选择主题，`next-themes` 管理 `dark` 状态。

## 相关文件

| 文件 | 用途 |
| --- | --- |
| `src/styles/themes/*.css` | 各主题的颜色、字体、圆角和阴影 token |
| `src/styles/theme.css` | 导入主题 CSS |
| `src/components/themes/theme.config.ts` | `THEMES` 列表与 `DEFAULT_THEME` |
| `src/components/themes/active-theme.tsx` | 主题状态与 `active_theme` cookie |
| `src/components/themes/theme-selector.tsx` | 主题切换入口 |
| `src/components/themes/font.config.ts` | 已加载字体及 `fontVariables` |
| `src/app/layout.tsx` | 将字体变量应用到页面 |

## 修改默认主题

在 `src/components/themes/theme.config.ts` 修改：

```ts
export const DEFAULT_THEME = 'claude';
```

值必须与 `THEMES` 中某项的 `value` 一致。已有用户的 `active_theme` cookie 优先于默认值；测试新默认值时清除此 cookie，或使用无痕窗口。

## 添加新主题

1. 复制 `src/styles/themes/claude.css` 为 `src/styles/themes/team.css`。
2. 将复制文件内所有 `[data-theme='claude']` 改为 `[data-theme='team']`，包括明暗选择器和 Tailwind 映射部分。
3. 调整颜色、字体、圆角和阴影，保留完整的明暗 token 与 `@theme inline` 映射。
4. 在 `src/styles/theme.css` 添加：

```css
@import './themes/team.css';
```

5. 在 `src/components/themes/theme.config.ts` 的 `THEMES` 数组中添加：

```ts
{ name: 'Team', value: 'team' }
```

6. 如需默认启用，将同文件的 `DEFAULT_THEME` 设为 `'team'`。

主题文件中的选择器结构如下；复制现有完整主题后修改，不要只保留下面的部分 token：

```css
[data-theme='team'] {
  --background: oklch(0.98 0.005 95);
  --foreground: oklch(0.25 0.02 95);
  --primary: oklch(0.6 0.13 40);
}

[data-theme='team'].dark {
  --background: oklch(0.2 0.01 95);
  --foreground: oklch(0.95 0.005 95);
}
```

业务组件使用 `bg-background`、`text-foreground`、`bg-primary` 等语义类。图表使用 `--chart-1` 至 `--chart-5`，侧边栏使用 `--sidebar-*`。颜色值遵循现有主题的 OKLCH 格式。

## 字体配置

默认字体由本地 `geist` npm 包提供，并配合系统字体栈；构建不依赖 Google Fonts。无需新增字体时，直接使用现有配置。

需要品牌字体时，将字体文件放入 `src/assets/fonts/`，在 `src/components/themes/font.config.ts` 使用 `next/font/local`，保留现有 Geist 配置：

```ts
import localFont from 'next/font/local';
import { GeistSans } from 'geist/font/sans';
import { GeistMono } from 'geist/font/mono';
import { cn } from '@/lib/utils';

const teamSans = localFont({
  src: '../../assets/fonts/team-sans.woff2',
  variable: '--font-team-sans',
  display: 'swap'
});

export const fontVariables = cn(
  GeistSans.variable,
  GeistMono.variable,
  teamSans.variable
);
```

字体路径相对于 `font.config.ts`，示例文件需替换为项目实际字体。模板在 `src/app/layout.tsx` 将 `fontVariables` 应用到 `<html>`，与主题的 `--font-sans` 定义处于同一作用域。扩展时保留此结构和其他属性：

```tsx
<html lang='en' suppressHydrationWarning data-theme={themeToApply} className={fontVariables}>
```

如果 `<html>` 已有类名，用 `cn()` 合并。字体变量必须在引用它的元素或祖先上定义；只在 `<body>` 加载变量，无法供 `<html>` 上的主题 token 引用。随后在主题 CSS 中使用：

```css
[data-theme='team'] {
  --font-sans: var(--font-team-sans), 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
```

字体需覆盖项目使用的语言；缺少中文字形时会回退到系统字体。仅在项目允许构建时访问外部字体服务时，才考虑改用远程字体。

## 检查与排查

- 切换主题和明暗模式，检查表单、弹层、图表、侧边栏和文字对比度。
- 刷新后主题应保留；默认值不生效时检查 `active_theme` cookie。
- 新主题不在列表：检查 `THEMES` 注册；已在列表但颜色不变：检查 CSS 导入和选择器名称。
- 字体不生效：检查字体文件路径、`fontVariables` 导出和 CSS 变量引用。
- 字体变量应位于 `<html>`；不要在 body 将继承的 `--font-sans`、`--font-mono`、`--font-serif` 重置为 `initial`。
- 表面色必须配对前景色：`secondary/secondary-foreground`、`card/card-foreground`、`popover/popover-foreground`、`sidebar-accent/sidebar-accent-foreground`。不要依赖不相关父元素的文字颜色。
- 修改后运行 `bun run typecheck` 和 `bun run build`，确认配置与字体资源可以编译。

AI Chat 的具体 token 分工、扩展约定及 `bun run test:ai-chat:themes` 说明见[AI Chat 主题适配](./aichat/theming.md)。
