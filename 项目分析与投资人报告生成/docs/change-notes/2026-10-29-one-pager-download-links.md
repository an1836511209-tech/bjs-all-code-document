# 一页纸 BP 发布后的下载链接统一

## 修改前的问题与方案

本记录在修改实现之前创建。

用户反馈：发布回复属于海康智联任务，但右侧下载指向另一个任务的北京中科新微特文档，并且地址以省略号截断。两个地址的 task_id、artifact_id 均不同，不能当作同一文件签名刷新的差异处理。

当前代码存在两种链接来源：发布回复直接展示对象存储签名 URL，文档卡片和文件列表使用 `/api/artifacts/{artifact_id}/content`。另外，预览还保留可变的全局 `state.doc`，顶栏预览按钮与聊天切换必须核对文档归属。旧 localStorage 中可能保留被截断的签名 URL。

计划统一以发布产物的 `artifact_id` 为下载依据：

1. 发布回复、右侧预览、文档卡片和文件列表都使用稳定的 Agent 下载接口，不向用户展示会过期的对象存储签名地址。
2. 预览显式绑定所属聊天和具体产物；切换聊天不复用其他聊天的可变预览对象。
3. 历史页面恢复时，以后端产物索引重建链接，修复可确认归属的旧签名地址；缺少可靠产物标识时不猜测、不使用被截断的链接。
4. 增加回归：两个任务的不同文档、同任务多个版本、切换与刷新，以及正文链接和右侧下载按钮指向同一产物。

## 验证记录

已完成：

- 发布回复使用 `/api/artifacts/{artifact_id}/content`，不再展示签名 URL 及其失效时间；前端把同一路径解析为当前 Agent 的完整地址，并提供可点击链接。
- 右侧预览、历史文档卡片和文件列表共用同一个 URL 构造函数。预览对象绑定聊天、任务与产物；移除了顶栏重复的点击监听，打开文件列表不会再次读取其他聊天的全局文档。
- 事件流校验 task_id；刷新时用当前任务的服务端产物元数据修正旧文件名与地址，移除缓存中混入的其他任务产物。历史回复按各自的 Artifact ID 重建稳定下载链接，不根据最新文档猜测版本。
- 后端任务快照补齐该任务所有已发布产物，以便旧版本和最新版本分别恢复。
- 22 项下载、问答和异步运行测试通过。无头 Chrome 验证两个任务、同任务多版本、文档卡片/正文/预览地址相同、旧截断缓存修复及实际下载归属；脚本异常为零。所有文档和对象存储均使用合成数据，没有访问用户提供的签名地址。

复现命令：

```powershell
.venv/Scripts/python.exe -m pytest apps/report_agent/tests/unit/test_download_links.py apps/report_agent/tests/unit/test_conversation_interactions.py apps/report_agent/tests/unit/test_async_runs.py -q
# 独立测试服务，另开终端运行 browser 脚本；需已安装 Playwright 与 Chrome
.venv/Scripts/python.exe frontend/tests/download_server.py
node frontend/tests/download-links.cjs
```

生效需要重启后端并刷新前端。稳定下载入口由 Agent 读取当前产物的对象存储记录，因此不依赖页面缓存的过期签名；如果文件在存储中已删除，接口仍会正常返回下载失败，不会改指向另一个产物。此前浏览器缓存中完全缺少 Artifact ID 的地址不会被猜测修复。
