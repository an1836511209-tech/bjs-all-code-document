# 错误提示与恢复接入

## 选择反馈方式

- 字段校验使用 `FieldError` 和项目 `useAppForm`，关联对应输入，不额外弹 toast。
- 保存/删除等操作失败使用 Sonner `toast.error`：说明受影响操作及下一步，保留用户输入。请求失败不代表服务端未执行，删除失败应先刷新确认状态再重试。
- 持续存在、仍可继续使用的降级状态使用 `src/components/feedback-notice.tsx`，默认 `severity="warning"`，以 `role="status"` 礼貌播报。标题、说明及操作分层，窄屏自动换行；不只用颜色传达状态。
- 当前操作或局部区域不可用时使用 `severity="error"`，以 `role="alert"` 播报。按钮使用项目 Button，装饰图标隐藏于辅助技术。文案由功能提供，保持所在页面语言。
- 页面渲染或 Suspense 查询异常使用 `src/components/route-error.tsx`，由 App Router 的 `error.tsx` 接入。普通错误不应替换整个应用外壳。

## 页面边界与重试

`src/app/error.tsx` 保护根布局下的页面与 dashboard 布局；`src/app/dashboard/error.tsx` 保留侧栏与头部。概览页及各并行槽保留独立边界，局部故障不隐藏正常卡片。`global-error.tsx` 只处理根布局异常，包含自己的 html/body 和内联样式，不依赖失效的主题 Provider 或全局样式。

共享 RouteError 同时调用 React Query 的错误边界 reset、`router.refresh()` 和 Next.js 提供的 `reset()`，重置错误查询缓存与查询失败状态并更新服务器组件，保留成功缓存，避免切回原失败查询时再次抛出旧错误。重试期间禁用按钮并显示进度。默认不自动重放 mutation、聊天请求或工具执行，避免重复提交副作用。

异常原始对象交给 Sentry，不将 `error.message`、堆栈或服务端响应正文直接渲染。可显示 Next.js digest 作为支持参考编号。API 接入应在 service 层映射已知业务错误为安全文案；未知异常使用通用说明。不要把令牌、请求头、会话内容或个人资料作为提示或监控附加信息。

```tsx
<FeedbackNotice title='会话尚未保存' actions={<Button onClick={retry}>重试保存</Button>}>
  浏览器存储空间不足，最新修改尚未保存。请先导出会话，再释放空间后重试。
</FeedbackNotice>
```

AI Chat 的存储保护、JSON 导出及临时模式见 [历史会话契约](./aichat/history.md)。读取失败不能用初始空记录覆盖旧数据。浏览器当前状态和未来服务端会话存储应使用各自的适配器，流式传输继续遵循 AI Chat 的 SDK 契约。

## 扩展与验证

新增页面继承 dashboard 边界；需隔离区域失败时新增局部 `error.tsx` 并复用 RouteError。通过 `bun run cleanup sentry` 移除监控时，清理模板会保留相同提示与恢复行为，替换共享组件中的 Sentry 调用。

运行 `bun run typecheck`、`bun run lint:strict`、`bun run format:check`、`bun run build`。保持应用运行后执行 `bun run test:feedback:browser` ；涉及 AI Chat 时还需按对应指南运行单元与浏览器回归。浏览器故障注入覆盖消息请求失败、记录损坏/禁用/配额和查询重试；截图与报告仅写入忽略目录 `coverage/`。真实后端仍需验证鉴权、业务错误映射、幂等和部署环境故障恢复。
