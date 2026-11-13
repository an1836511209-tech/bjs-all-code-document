# 一页纸生成不收敛：日志对比与 Linux 部署修复

## 实际阻断点

对比用户提供的 `1102生成成功.ndjson`、`1103生成失败.ndjson`：

- 11 月 3 日有 32 次 `edit_file`、4 次 `render_one_pager`，最终还在修正“多 5 字 / 多 13 字 / 多 3 字”，日志中没有发布产物。
- 新增的介绍 225–250、亮点 170–185 字硬区间，把写作建议变成了交付门槛；模型反复删改并遇到旧字符串找不到的问题。
- 草稿中的 `<src cite="..." .../>` 元数据未被去除。一次真实快照的六段字数被报为 512/432/556/447/558/427；正文实际为 267/310/198/209/199/189 字。
- 材料明确披露“总共可容纳约1180人”，旧的约数核对只支持金额和百分比，仍会误拦人数。
- 标为 11 月 2 日成功的日志中，正文审查完成，但最后仍报 `/app/.venv/lib/python3.12/skills/one-pager/assets/产权模板.docx` 缺失，没有 `validate_and_publish_one_pager` 成功记录。

## 修复范围

1. 字数区间恢复为建议。非空正文不会因少几字或略超目标反复修改；只保留介绍 400 / 亮点 220 字的原有兜底上限，预检与域模型保持一致。
2. 预检、正文解析和真实性检查共用来源标记清理函数，兼容 HTML 注释和 XML 自闭合 `<src .../>`，不修改正文事实。
3. 有当前任务证据支持的“约1180人”等计数允许保留；没有证据的约数仍然阻断。
4. 模板进入 wheel 的 `report_agent/resources/one_pager`，非 editable 安装优先读取随包资源。镜像构建时检查两种模板，避免直到写作结束才发现缺失。显式指定缺失模板目录仍报错。
5. 预检同时检查项目名称，避免通过预检后再单独报缺失。技能提示要求同一文件顺序修改，只创建一次，审查通过后直接渲染发布，不为字数建议或 warning 重写。

业务类型、财务披露确认、风险展示选择、投资人匹配和发布接口保持原有规则。

## 验证

- 回归测试：110 通过；1 项专用 MySQL 集成测试未配置而跳过。
- 使用今天失败日志中的草稿快照，匿名化公司名称及联系人后纳入回归 fixture；六段正文无需改写即可生成真实 DOCX，并走完 staging 和发布回调。
- 在本机 Linux Docker 容器中测试真实 wheel，禁用网络、根文件系统只读；两种模板均从安装包资源读取，均生成 DOCX/PDF 并完成本地发布回调。
- 发布回调使用本地校验替身，不访问生产 MinIO；没有连接或更新用户的服务器。
- Linux LibreOffice 对原有浮动文本框模板的 PDF 预览仍存在位置漂移和空白页，转换产生 3 页。本次没有修改模板版式，不能把 PDF 页数或“文件已产生”等同于排版验收；交付的 DOCX 应用 Word/WPS 检查版面。这与本次字数循环、模板路径缺失是不同问题。

可重复验证脚本：`scripts/verify_one_pager_delivery.py`。支持 `--wheel` 检查发布包资源、`--render-pdf` 检查 LibreOffice 转换。

## Linux 服务器更新

在项目根目录、确认修复文件已同步后，只重建报告服务。下面以 UAT 为例；生产环境把 `uat` 替换为 `prod`，沿用服务器原有配置：

```bash
APP_ENV=uat BJS_ENV_FILE=deploy/environments/uat/runtime.env docker compose build report-agent
APP_ENV=uat BJS_ENV_FILE=deploy/environments/uat/runtime.env docker compose up -d --no-deps --force-recreate report-agent
APP_ENV=uat BJS_ENV_FILE=deploy/environments/uat/runtime.env docker compose exec -T report-agent python -c 'from report_agent.infrastructure.word.one_pager_authoring import resolve_template; from report_agent.domain.one_pager import BusinessType; print(*(resolve_template(t) for t in BusinessType), sep="\n")'
```

安装包模式下，检查结果应指向 `site-packages/report_agent/resources/one_pager/`，两份 `.docx` 均应存在。单独修改宿主源码后只重启旧容器不会更新已安装的 Python 包。

更新后新建任务验证，或继续仍有执行预算的原任务。已因反复改稿耗尽预算的旧任务，其预算状态不会因部署自动清空。
