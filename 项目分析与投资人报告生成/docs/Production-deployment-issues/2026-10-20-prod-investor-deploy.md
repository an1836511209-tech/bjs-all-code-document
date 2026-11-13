# 2026-10-20 生产投资人匹配部署排查

当天在生产机 `bjs-investment-report-agent-main` 上调试 `match_investors`：日志双「内部服务错误」、API 平台无 DMP 消费、`meta.env` 为 `uat`。**本页记录的是部署/配置类踩坑，不是改镜像才能修的产品缺陷。** 需改代码包的问题见 [2026-10-22](2026-10-22-dmp-word.md)。

## 归类：哪些是「bug」，哪些不是

| 现象 | 是否代码 bug | 实际性质 |
| --- | --- | --- |
| `DMP investor lookup failed: 内部服务错误` + `investor database fallback failed: 内部服务错误` | 否 | **症状**：DMP 未发出 HTTP 和/或 MySQL 连不上；当日主因见下两行 |
| `meta.env: "uat"`，但 `APP_ENV=prod`、`DATA_MCP_CONFIG=.../prod/data-mcp.yaml` | 否 | **部署错误**：挂载路径是 prod，**文件正文仍是 UAT**（注释、`current_env: uat`、UAT 的 DMP/MySQL 地址） |
| API 平台无消费，日志只有「内部服务错误」（无 `DMP HTTP …`） | 否 | **配置未进进程**：容器内 `DMP_APP_SECRET` 长度为 0 → `_is_dmp_configured` 为 false，**请求在 POST 前被跳过**；不是「key 填错但已发出」 |
| 以为 `docker-compose exec … --env-file prod/runtime.env` 能临时切 prod | 否 | **操作误解**：`exec` 用的是**容器启动时**的环境；`--env-file` 主要给 compose 变量替换，不刷新已运行容器 |
| 改 `runtime.env` 后只 `exec` 不重载容器，secret 仍为空 | 否 | **运维**：`env_file` 只在 **create/recreate** 时注入，需 `up -d --force-recreate data-mcp` |
| 容器内 `uv run --package bjs-data-mcp` → `Permission denied` on `~/.cache/uv` | 否 | **用法**：镜像内用户 `data-mcp` 无 home；应直接 `exec data-mcp data-mcp --match-investors …` |
| prod HiAgent 网络投资人调试「空」、UAT 有值 | 未在本会话坐实为代码 bug | **优先查 prod agentId 编排里 state 变量名**是否仍为 `project_profile` / `track_tags`；与 DMP 失败可并存 |
| Report Agent `execute` → bwrap cgroup namespace 失败 | 否 | **宿主机/内核能力**：与投资人 DMP 无关 |
| 误把 `app_key` 当 `DMP_APP_SECRET`、或把算好的 `x-gw-token` 写入 env | 否 | **配置认知**：网关用 `API_PLATFORM_TOKEN`（请求时 HMAC-SM3）；DMP 签名用 yaml 的 `app_key` + env 的 `DMP_APP_SECRET` |

**当日可确认的硬根因（服务器实测）：**

1. `deploy/environments/prod/data-mcp.yaml` 内容与 UAT 相同 → DMP/MySQL 指向错误环境。  
2. 容器内 `app_secret len 0`、`will_send_http False` → DMP **不会**打到 `10.3.1.71:30011`，API 平台无记录属预期。

## 1. prod 路径 + UAT 正文

容器内曾出现：

```text
DATA_MCP_CONFIG=/app/deploy/environments/prod/data-mcp.yaml
# Data MCP uat deployment configuration.
current_env: uat
```

`APP_ENV=prod` 只决定读**哪条挂载路径**；**正文写什么就连什么**。扁平 yaml 下 `current_env` 不另选一套嵌套块，但 **`meta.env` 会原样返回 `current_env`**，是判断「是否拷错文件」的最快信号。

修复：用仓库中真正的 prod 文件覆盖服务器同名路径，确认 `current_env: prod`、DMP `10.3.1.71:30011`、MySQL `10.254.19.160`、表名 `投资人权重全量` 等。

只改 yaml：**bind mount 立即生效**，Data MCP 每次读盘；仍建议 `up -d` 或 `restart data-mcp` 避免长期进程状态干扰排查。

## 2. DMP 未发出 HTTP：`DMP_APP_SECRET` 与诊断命令

DMP 要求五项均非空：`base_url`、`path`、`app_key`（yaml）、`x_gw_token`（来自 `API_PLATFORM_TOKEN`）、`app_secret`（来自 `DMP_APP_SECRET`）。缺一即 `RuntimeError`，对外统一 **「内部服务错误」**，**无** `DMP HTTP` 行。

生产机确认（勿打印 secret 全文）：

```bash
docker-compose --env-file deploy/environments/prod/runtime.env exec data-mcp python -c "
from data_mcp.shared.settings import load_investor_match_config
from data_mcp.features.investor_match.dmp_client import _is_dmp_configured
c = load_investor_match_config(None)['dmp']
print('base_url', c['base_url'])
print('API token len', len(c.get('x_gw_token') or ''))
print('app_secret len', len(c.get('app_secret') or ''))
print('will_send_http', _is_dmp_configured(c))
"
```

期望：`app_secret len > 0` 且 `will_send_http True`。若 token 有值、secret 为 0 → 填 `runtime.env` 后 **`up -d --force-recreate data-mcp`**。

| 容器内状态 | API 平台消费 | 日志 |
| --- | --- | --- |
| secret 或 token **为空** | 无 | 仅「内部服务错误」，无 `DMP HTTP` |
| 两者**非空但错误** | 通常有网关记录 | `DMP HTTP 4xx` / 「DMP 请求被拒绝」等 |

## 3. CLI 自测命令

```bash
docker-compose --env-file deploy/environments/prod/runtime.env exec data-mcp \
  data-mcp --match-investors \
  --company-name "测试公司全称" \
  --tags-str "某赛道标签" \
  --project-profile '{"所在行业":"测试"}'
```

不要用容器内 `uv run`（无写权限 home/cache）。

## 4. 与 2026-10-22 代码问题的边界

若 DMP 已通、仍出现 **MCP TaskGroup 崩溃、Word 机构表一行、个人 limit 恒为 1**，那是 **镜像内逻辑/解析器** 问题，改 yaml 不够。见 [2026-10-22 生产排查](2026-10-22-dmp-word.md) 的镜像分开发版说明。

## 5. 发布检查清单（投资人内部源）

- [ ] 服务器 `deploy/environments/prod/data-mcp.yaml` 前几行为 prod，`current_env: prod`  
- [ ] `runtime.env` 中 `APP_ENV=prod`，且 `DMP_APP_SECRET`、`API_PLATFORM_TOKEN` 已填  
- [ ] 容器内 `will_send_http True`  
- [ ] 失败时 grep：`DMP HTTP`（有则已出站；无则仍缺配置或 `_is_dmp_configured` false）  
- [ ] 改 `runtime.env` 后已 **force-recreate data-mcp**
