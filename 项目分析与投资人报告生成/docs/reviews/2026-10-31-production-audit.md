# 多用户无账号部署审计（2026-10-31）

审计场景：一台服务器运行 Docker，用户共用 `/console/` 链接，自行上传材料、生成和下载报告，当前没有账号系统。

结论：当前实现不能直接当作多个互不相关用户的报告服务开放。首先要补匿名会话归属、全局任务容量和失败状态一致性。可以继续不做账号系统，但任务必须有服务端验证的归属。

本次读取的是当前工作区，包括原有未提交修改。未修改业务代码、配置或原有测试；新增本文和 `.runtime/diagnostics/production_audit_*` 隔离复现脚本。没有连接生产数据库、模型、MinIO 或其他业务接口。

P1 表示应在多人开放前处理；P2 表示正常操作即可遇到的功能或长期运行问题。

## 1. P1：所有用户共享历史列表及任务控制权限（已复现）

位置：[api/app.py:649](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/api/app.py:649)、[console.js:2271](D:/Project/bjs-investment-report-agent/frontend/assets/console.js:2271)。关联的材料下载、任务状态、停止和删除接口同样没有归属检查。

触发：用户 A 创建任务，用户 B 用全新浏览器打开同一个链接。前端自动把服务器全部历史会话放入 B 的“历史记录”。B 能进入 A 的会话，查看材料、获取生成结果、补充内容，以及停止任务。执行中的会话不能直接删除，但 B 可以先停止，再软删除。

证据：两个独立 HTTP 客户端中，B 能列出 A 的任务，状态接口返回 200，下载得到 A 上传的 `PRIVATE_MATERIAL`，停止返回 `cancelled: true`，随后删除返回 200。这不需要猜测任务 ID。

修复：服务端签发匿名会话 cookie，并将 owner 标识持久化到任务；列表、状态、SSE、材料、产物、补充回答、附件、停止、删除全部检查归属。不能只用前端 localStorage 过滤；需要分享时另外签发权限受限的分享链接。

## 2. P1：只有单会话互斥，没有全局并发和接入容量（已复现）

位置：[runs.py:189](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/application/runs.py:189)、[runs.py:293](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/application/runs.py:293)、[compose.yaml:66](D:/Project/bjs-investment-report-agent/compose.yaml:66)。

触发：一个用户连续新建多个会话，或者多个人同时生成。每个新 task 都直接 `asyncio.create_task()`；没有全局信号量、队列容量或提交频率限制。单次模型/工具预算不会限制同时运行的任务数。

证据：隔离测试同时提交 20 个新任务，20 个全部接受，`_active_tasks` 同时为 20。报告容器整体只有 4 GB 内存、2 CPU、256 进程的限制。实际超过容量时可能触发模型/解析服务限流、内存或进程耗尽，重启后影响全部运行中任务；本次没有进行 OOM 压测。

修复：设置可配置的全局运行容量和有界等待队列，满载明确返回 429/503 或排队状态；给匿名会话设置提交频率及并行上限。主报告仍在进程内执行期间，继续保持单 API 进程，不能靠增加 worker 数解决。

## 3. P1：上传和链接的大小校验发生在资源已经消耗之后（部分已复现）

位置：[api/app.py:108](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/api/app.py:108)、[api/app.py:163](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/api/app.py:163)、[runs.py:410](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/application/runs.py:410)、[compose.yaml:39](D:/Project/bjs-investment-report-agent/compose.yaml:39)。

本地文件先全部 `upload.read()` 进入内存，链接先由 `client.get()` 完整缓冲响应；之后才检查每条链接和整批材料的大小。后端没有与前端“五个附件”对应的数量限制。Nginx 请求体上限不限制服务器从 URL 拉取的响应体。

证据：把链接限制缩小为 8 字节，模拟上游分三段共返回 60 字节，实际全部读取 60 字节后才返回 413。因此 100 MB 并不是下载过程中的内存保护。

Docker 额外风险：`/tmp` 是 128 MB tmpfs，multipart 临时文件也会消耗这块空间。多个未超单请求上限的上传同时进行，也可能把 `/tmp` 撑满而在业务校验前失败。这一项依据配置和处理顺序判断，未实测容器 ENOSPC。

修复：请求入口限制文件数量、单文件及总量；流式接收并逐块计数；URL 下载使用流式响应，累计到上限立即中止，同时限制链接数量和总耗时。按实际并发配置上传临时目录容量，返回明确的 413/容量错误。

## 4. P1：材料链接允许访问服务器内网及回环地址（已复现）

位置：[api/app.py:98](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/api/app.py:98)。

触发：用户把回环、内网或云元数据地址填入材料链接，或者外部链接重定向到这些地址。代码只检查 http/https，并自动跟随重定向，没有域名、解析 IP 或重定向目标检查。

证据：模拟公开材料地址返回 302 后，客户端确实继续请求了 `http://127.0.0.1:8000/internal`。模拟未访问真实内网。

影响：服务器替匿名用户请求自身可达地址，构成 SSRF；也能消耗内网服务及报告服务资源。

修复：优先明确允许的材料来源域名；如果必须允许任意公网链接，校验解析出的 IPv4/IPv6，并对每次重定向重新校验，禁止回环、私网、链路本地、保留地址及元数据地址，同时配置出站网络限制。确需内部材料来源时使用显式允许列表。

## 5. P1：用户下载 Word 会阻塞整个 API 的事件循环（已复现）

位置：[api/app.py:743](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/api/app.py:743)、[minio.py:124](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/infrastructure/artifacts/minio.py:124)。MySQL 查询也有直接在 async 路径执行同步 I/O 的情况，例如 [api/app.py:386](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/api/app.py:386)。

触发：一个人点击 Word 下载，MinIO 网络响应慢。XLSX 分支已使用 `asyncio.to_thread()`，DOCX 分支却直接执行同步 `read_object()`，会阻塞同一事件循环的报告执行、SSE 心跳、停止、健康检查和其他请求。

证据：用模拟存储阻塞 0.4 秒，原本应 10 毫秒触发的 asyncio 定时器延迟到 0.426 秒。下载请求本身返回 200，所以这是跨用户影响，不能只检查下载成功与否。

修复：将 DOCX 读取及同步仓储调用移出事件循环，配置底层 I/O 超时；下载尽量流式传输。只给外层 coroutine 加超时不能终止仍卡在同步网络读取里的线程，底层超时也要有。

## 6. P1：确认回答提交失败，会先清掉仍有效的问题（已复现）

位置：[runs.py:226](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/application/runs.py:226)。

触发：用户在确认卡点击提交，代码先把 `interaction.json` 写为 running、`pending_question=None`，再执行 MySQL `repository.create()`。如果数据库此时短暂故障，接口报错，但是确认卡的服务端状态已经被清掉。

证据：注入 create 故障，任务从 `needs_input` 变为 `running`、pending question 变成 null，而新任务没有开始；数据库恢复后原卡重试仍报“这个问题已经回答或已更新，请刷新当前对话”。

修复：明确提交的持久化提交点，保证数据库接受失败时保留原问题和原状态；使用幂等提交 ID，重试应返回同一接受结果，而非制造新一轮或丢弃确认卡。

## 7. P1：结果落库等收尾异常不在异常处理范围内（已复现）

位置：[runs.py:457](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/application/runs.py:457)、[runs.py:495](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/application/runs.py:495)、[runs.py:545](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/application/runs.py:545)。

触发：模型执行已返回，但产物校验、状态写入或 `repository.finish()` 失败。现有 try/except 只包住 executor；收尾代码报错会直接退出后台 Task，跳过 `run.completed/run.failed` 事件。

证据：模拟 finish 数据库故障后，MySQL 替身内该 run 仍是 running，活动任务数已是 0，event bus 没有终止事件。前端的 SSE 可以继续收心跳，因而不会自动触发断线恢复，呈现一直执行中。

修复：把完整执行及收尾纳入状态机和异常处理；提供独立于落库成功与否的终止通知及错误记录；为已发布产物建立可重试、幂等的结果对账，避免落库失败就重复生成报告。错误处理中的 `repository.fail()` 本身也要防御数据库不可用。

## 8. P2：文件选择器承诺的格式，标准解析链路不支持（已复现）

位置：[frontend/index.html:120](D:/Project/bjs-investment-report-agent/frontend/index.html:120)、[detection.py:15](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/infrastructure/materials/detection.py:15)。

触发：用户正常选择 TXT、Markdown、PNG、JPG、JPEG。前端 accept 明确允许，后端接收并开始运行，但 `parse_materials` 使用的检测器只接受 PDF、Office 和 CSV，以上五类都会抛 `UnsupportedMaterialError`。相反，解析器支持 CSV，选择器却没有列出它。

证据：对五种后缀调用当前格式检测器，全部返回 UnsupportedMaterialError。TXT/MD 可能被模型绕到普通文件读取，但不能据此认为材料解析链路支持；图片没有对应的独立图片解析分支。

修复：统一前后端格式清单，提交前给出准确提示；需要支持的文本/图片实现明确解析路径。损坏、加密、格式伪装文件也应返回可理解的材料错误，不能等耗费模型调用后才发现。

## 9. P2：快速双击发送会排队再执行一份相同请求（浏览器已复现）

位置：[console.js:1180](D:/Project/bjs-investment-report-agent/frontend/assets/console.js:1180)、[console.js:2235](D:/Project/bjs-investment-report-agent/frontend/assets/console.js:2235)、[console.js:1645](D:/Project/bjs-investment-report-agent/frontend/assets/console.js:1645)。

触发：首次提交等待服务器 202 响应时，页面已经变成 running，但输入内容仍在；第二次点击进入“排队”分支，把原内容保存为下一条请求。后续完成或出现确认问题时，队列会自动提交。

证据：真实 Chrome 页面、模拟接口延迟 500 毫秒，双击一次发送产生两个 POST，请求都包含同一条内容。

影响：重复调用、重复上传和重复生成；如果中间出现确认卡，原请求还可能被当作该问题的回答自动送出。队列只在内存中，刷新会丢掉页面承诺“已排队”的内容。

修复：提交尚未接受时禁用或去重发送；有意追加消息和防双击分开处理。需要持久排队时应有服务端队列/明确的可恢复状态；不要自动拿未看过问题前输入的内容回答确认卡。

## 10. P2：失败后刷新，重试按钮变成无操作（浏览器已复现）

位置：[console.js:1278](D:/Project/bjs-investment-report-agent/frontend/assets/console.js:1278)、[console.js:109](D:/Project/bjs-investment-report-agent/frontend/assets/console.js:109)。

触发：任务失败，用户刷新或重新进入后点击“重试”。按钮只能读取内存中的 `runtime.lastPayload`；该对象没有持久化，File 对象也不能按现有方式恢复。失败事件却会被重放，因此按钮仍然显示。

证据：刷新后点击重试，请求计数保持 1，按钮自身被移除，没有发出新的提交请求。

修复：基于服务端已保存的任务输入提供幂等重试接口；前端恢复时明确绑定可重试动作。确实缺少输入时提示补传，不能显示点击无效的按钮。

## 11. P2：结束事件与工作区没有自动回收策略（已确认代码路径及内存留存）

位置：[event_bus.py:35](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/application/event_bus.py:35)、[event_bus.py:77](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/application/event_bus.py:77)、[runs.py:133](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/application/runs.py:133)。

event bus 提供了 `forget()`，当前没有生产调用方；任务结束后事件仍保留。会话删除只写 deleted_at，材料、工作区和对象存储产物仍保留，当前没有自动过期和清理任务。

证据：隔离脚本结束 21 个 run 后，21 个事件缓冲仍在内存。没有进行长期内存或磁盘压测。

影响：长期运行持续增长；用户以为删除已经释放空间，实际仍可能耗尽内存或磁盘，最终影响所有报告。

修复：事件缓冲设有界条数、容量和 TTL，恢复依赖持久快照；明确材料/产物保留时间与删除语义，监测剩余磁盘并做可追踪的清理。

## 12. P1：默认生产配置下，运行中报告不能在容器重启后自动恢复（代码确认）

位置：[api/app.py:193](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/api/app.py:193)、[runs.py:335](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/application/runs.py:335)、[api/app.py:432](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/api/app.py:432)、[settings/models.py:48](D:/Project/bjs-investment-report-agent/apps/report_agent/src/report_agent/settings/models.py:48)。

触发：生成期间发布镜像、重启容器，或者容器 OOM/宿主机重启。普通报告只在当前 API 进程内执行；启动恢复只扫描带一页纸检查点的任务，而当前 prod YAML 未打开该开关。旧文件仍在不等于运行自动续接。

结果：普通报告中断；状态查询会提示“服务已重启，请在当前对话中重试以继续”。人工再次提交也不能理解为精确恢复上一个工具步骤。开启一页纸检查点只解决对应的新一页纸任务，不覆盖投资报告。

修复：短期发布前停止接单并等待活动任务结束，明确向用户显示中断与重试；长期为主报告建立持久任务接受、恢复/失败对账机制。本次没有实际停止生产容器。

## Docker 部署的三个额外问题

1. **P1，构建阻断**：[.dockerignore:34](D:/Project/bjs-investment-report-agent/.dockerignore:34) 排除了根目录 README.md，但 [data_mcp/Dockerfile:16](D:/Project/bjs-investment-report-agent/apps/data_mcp/Dockerfile:16) 的 COPY 又要求它。需加 `!README.md` 或调整 COPY。Docker 官方说明匹配文件会从构建上下文移除，[规则来源](https://docs.docker.com/build/concepts/context/#dockerignore-files)。本机 Docker 引擎未运行，未实跑镜像构建；也不代表已穷尽其他构建问题。
2. **P1，有条件发生**：[compose.yaml:19](D:/Project/bjs-investment-report-agent/compose.yaml:19) 将 MCP 发布到宿主机 5128，[compose.yaml:73](D:/Project/bjs-investment-report-agent/compose.yaml:73) 将 API 发布到 5129。若直接沿用仓库 Compose，端口不会仅绑定回环地址；服务器网络允许时可绕过 Nginx。生产文档已要求删 MCP ports、API 只绑定 127.0.0.1，但这些改动尚未固化到仓库生产 Compose。建议提交单独的生产覆盖文件。
3. **配置误用**：不显式传入 prod env 时，Compose 默认选 test 配置；当前仓库没有 workbook-worker 服务，prod 的机构匹配表也默认关闭。按现有默认部署，这项可选附件不会启用；启用时必须同步部署同目录 worker。保持 `dev_ui_enabled: true` 才能使用当前控制台 API，不能把关闭该开关当成访问控制。

## 验证记录

- 现有定向单元测试：27 passed，覆盖异步提交、会话删除、下载、会话交互及本地入口。并非完整测试集。
- [后端隔离复现脚本](D:/Project/bjs-investment-report-agent/.runtime/diagnostics/production_audit_repro.py)：跨客户端访问、20 任务并发、接收与收尾数据库故障、格式支持、事件留存。
- [浏览器复现脚本](D:/Project/bjs-investment-report-agent/.runtime/diagnostics/production_audit_browser.cjs)：实际加载当前 HTML/JS，用本地模拟 API 验证双击提交及刷新后重试。
- [I/O 边界复现脚本](D:/Project/bjs-investment-report-agent/.runtime/diagnostics/production_audit_io.py)：模拟 MinIO 延迟、URL 重定向与超限响应。
- 测试需要 Windows asyncio 本机 socketpair；沙箱网络限制下会卡住，因此测试在允许本机连接的执行环境完成。没有调用外部生产接口。
- 尚未做：Linux Docker 实际构建、真实报告生成、真实上游集成、多用户完整业务压测、真实重启恢复试验。

建议处理顺序：匿名任务归属 → 接入与资源边界 → 失败状态一致性和同步 I/O → 前端防重复及可恢复重试 → 格式清单 → 回收和部署流程。无需先完成完整账号系统，但应先把任务隔离做对。
