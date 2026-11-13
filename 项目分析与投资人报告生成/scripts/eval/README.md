# Agent 评测框架（scripts/eval）

把「这次跑得贵不贵、稳不稳」变成**可断言、可回归、可进 CI** 的东西。

上一轮定位超预算，靠的是人工解析 `agent.ndjson`。这个框架把那件事固化下来：
**trace → 指标 → 断言 → 退出码**。

---

## 三种用法

### 1. 离线分析已有日志（最快，零依赖，不需要服务）

```bash
python scripts/eval/analyze_log.py path/to/agent.ndjson
python scripts/eval/analyze_log.py path/to/agent.ndjson --json out/report.json
```

输出：

```
==============================================================
agent trace report
==============================================================
sessions          : 1
model calls       : 59
tool calls        : 63
wall seconds      : 1098.4
model seconds     : 876.2
tool seconds      : 228.4
context peak      : 122 messages
edit_file calls   : 22
batch_edit calls  : 0
write_todos calls : 8

tool histogram:
  edit_file                          22      0.1s
  write_todos                         8      0.0s
  read_evidence                       6      0.1s
  ...
```

### 2. 拿现成日志按用例断言（离线回归）

```bash
python scripts/eval/run_eval.py --case investment-report-cites --log path/to/agent.ndjson
```

不联网、不起服务，直接用历史 trace 判定某个用例的断言。**开发时的快环。**

### 3. 真的跑一次 agent（需要服务在跑）

```bash
# 先起服务（见 scripts/start-local.ps1）
python scripts/eval/run_eval.py --list
python scripts/eval/run_eval.py --case investment-report-cites
python scripts/eval/run_eval.py --all
```

产出落在 `artifacts/eval/<case>/`：
- `<case>.eval.json` —— 指标 + 断言结果
- `<case>.ndjson` —— 完整 trace 留档

**退出码**：全部通过 → `0`；任一断言失败 → `1`。可以直接进 CI。

---

## 用例长什么样

用例是声明式 JSON，放在 `scripts/eval/cases/`：

```json
{
  "id": "investment-report-cites",
  "description": "补 cite 必须用 batch_edit 一次改完，不得逐段 edit_file",
  "skill": "investment-report",
  "message": "帮我根据当前材料，生成投资人匹配报告",
  "materials": ["scripts/eval/materials/01-明泰微电子_项目简介.docx"],
  "timeout_seconds": 2400,
  "assertions": {
    "max_model_calls": 60,
    "max_tool_calls": 90,
    "max_edit_file_calls": 3,
    "min_batch_edit_calls": 1,
    "max_write_todos_calls": 3,
    "max_context_peak": 80,
    "max_wall_seconds": 1500,
    "required_tools": ["check_citation", "create_word_from_md"],
    "forbidden_tools": []
  }
}
```

### 支持的断言字段

| 字段 | 含义 |
|---|---|
| `max_model_calls` | 模型调用次数上限（预算纪律） |
| `max_tool_calls` | 工具调用次数上限 |
| `max_wall_seconds` | 墙钟时长上限 |
| `max_edit_file_calls` | 单条改文件的次数上限（**逐段改的信号**） |
| `max_batch_edit_calls` | 批量改文件的次数上限 |
| `max_write_todos_calls` | 重写计划次数上限 |
| `max_context_peak` | 上下文消息数峰值上限 |
| `min_model_calls` / `min_edit_file_calls` / `min_batch_edit_calls` | 下限 |
| `required_tools: [...]` | 这些工具必须至少出现一次 |
| `forbidden_tools: [...]` | 这些工具不许出现 |

---

## 设计边界（重要）

**这个框架只断言「可确定性判定」的量**：调用次数、上下文增长、工具分布、是否触顶。

**内容质量不在这里判**——「报告写得好不好」需要人或 LLM judge，那属于另一层。
刻意把两者分开，是为了让 CI 里的断言**永远不 flaky**。

---

## 材料怎么放

- `scripts/eval/materials/` 里的小 `.docx` 已随仓库提交，**开箱即跑**
- 大文件（PDF / PPTX / XLSX）被 `.gitignore` 忽略 —— 需要时自己放进去，不污染仓库
- 用例里的 `materials` 路径相对**仓库根目录**解析

---

## 加一个新用例

1. 复制 `cases/investment-report-cites.json` 改 `id` / `assertions`
2. 先跑一次 `--case <新id>`，看真实指标
3. 按真实值收紧阈值（**留 10~20% 余量**，避免模型波动导致 flaky）
4. 提交

---

## 目录

```
scripts/eval/
  README.md          ← 本文件
  analyze_log.py     ← trace → 指标（纯标准库，零依赖）
  run_eval.py        ← 驱动：提交 run / 取 trace / 判定
  cases/*.json       ← 声明式用例
  materials/         ← 素材（小文件入库，大文件本地放）
```

`analyze_log.py` 只用标准库，可以单独拷走用。

---

## 附：跑各层测试的命令

| 层 | 命令 | 需要什么 |
|---|---|---|
| 后端单测 | `python -m pytest apps/report_agent/tests -q` | 无 |
| 前端契约 | `node frontend/tests/dom-contract.cjs` | 无（纯文本校验） |
| 前端技能路由 | `node frontend/tests/skill-routing.cjs` | 无（CDP，默认 `file://`） |
| 前端冒烟 | `node frontend/tests/dom-smoke.cjs` | **需要本地服务**（默认打 `http://127.0.0.1:8000/console/`）；`file://` 下能过 4/5，剩下那项是 `file://` 读不到 CSSOM 的限制 |
| 评测用例 | `python scripts/eval/run_eval.py --all` | 需要本地服务 |
| 离线回归 | `python scripts/eval/run_eval.py --case <id> --log <agent.ndjson>` | 无 |

> `dom-smoke.cjs` 和 `skill-routing.cjs` 都用 Node 内置 WebSocket + CDP，**不需要 npm install**。
> `skill-routing.cjs` 默认自己算 `file://` 路径，所以**不用起服务**。

