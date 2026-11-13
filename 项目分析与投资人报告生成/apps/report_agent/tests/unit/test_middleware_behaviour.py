"""中间件行为回归：预算、工具失败兜底、调用日志落盘。

这三条是评审里"零测试 + 有实测缺陷"的交集：预算超限无人知晓、工具异常被
包成正常返回、日志曾泄漏预签名 URL 且无法 join 回 run。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from middleware_stubs import FakeToolCallRequest, Recorder
from report_agent.harness.budget import BudgetExceeded, BudgetPaused, RunBudget
from report_agent.harness.middleware.agent_logger import AgentCallLoggerMiddleware
from report_agent.harness.middleware.budget import BudgetMiddleware
from report_agent.harness.middleware.tool_recovery import ToolFailureEnvelopeMiddleware
from report_agent.runtime.workspace import TaskWorkspace

TASK_ID = "task_" + "e" * 32


# --------------------------------------------------------------------------- #
# BudgetMiddleware
# --------------------------------------------------------------------------- #

def test_model_budget_is_enforced_before_the_call_runs():
    """用量到线必须在**调用前**抛出，否则这次调用已经花掉了。\n\n    模型调用到线是**软中断**（`BudgetPaused`），不是失败：状态保留，用户回一句话\n    就接着做。只有运行时间耗尽才是硬超限（`BudgetExceeded`）。\n    """
    budget = RunBudget(max_model_calls=1, max_tool_calls=10, timeout_seconds=60)
    middleware = BudgetMiddleware(budget)
    recorder = Recorder(result="ok")

    middleware.before_model(state={}, runtime=None)  # 第 1 次，允许
    assert recorder.calls == 0

    with pytest.raises(BudgetPaused):
        middleware.before_model(state={}, runtime=None)  # 第 2 次，拒绝
    assert recorder.calls == 0, "被拒的调用不能真的执行"


def test_tool_budget_is_consumed_before_the_tool_runs():
    budget = RunBudget(max_model_calls=10, max_tool_calls=1, timeout_seconds=60)
    middleware = BudgetMiddleware(budget)
    recorder = Recorder(result="ok")

    middleware.wrap_tool_call(FakeToolCallRequest(), recorder.handle)
    assert recorder.calls == 1

    with pytest.raises(BudgetPaused):
        middleware.wrap_tool_call(FakeToolCallRequest(), recorder.handle)
    assert recorder.calls == 1


@pytest.mark.asyncio
async def test_async_path_enforces_the_same_budget():
    budget = RunBudget(max_model_calls=1, max_tool_calls=10, timeout_seconds=60)
    middleware = BudgetMiddleware(budget)
    await middleware.abefore_model(state={}, runtime=None)
    with pytest.raises(BudgetPaused):
        await middleware.abefore_model(state={}, runtime=None)


# --------------------------------------------------------------------------- #
# ToolFailureEnvelopeMiddleware
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_a_raising_tool_becomes_a_structured_error_message():
    middleware = ToolFailureEnvelopeMiddleware()
    recorder = Recorder(error=ValueError("bad argument: company_name"))

    message = await middleware.awrap_tool_call(FakeToolCallRequest(), recorder.ahandle)

    assert isinstance(message, ToolMessage)
    assert message.status == "error"
    envelope = json.loads(message.content)
    assert envelope["status"] == "failed"
    assert envelope["tool"] == "query_track_labels"
    assert envelope["retryable"] is True
    assert envelope["next_action"] == "revise_arguments_and_retry_tool"
    assert "bad argument" in envelope["error"]


@pytest.mark.asyncio
async def test_a_non_retryable_error_does_not_leak_internals():
    """不可重试的错误只给一句通用话，避免把堆栈/凭据写进对话上下文。"""
    middleware = ToolFailureEnvelopeMiddleware()
    recorder = Recorder(error=RuntimeError("secret token sk-abc123 leaked"))

    message = await middleware.awrap_tool_call(FakeToolCallRequest(), recorder.ahandle)

    envelope = json.loads(message.content)
    assert envelope["retryable"] is False
    assert envelope["next_action"] == "stop_and_report_business_failure"
    assert "sk-abc123" not in envelope["error"]


@pytest.mark.asyncio
async def test_a_successful_tool_passes_through_untouched():
    middleware = ToolFailureEnvelopeMiddleware()
    original = ToolMessage(content="ok", tool_call_id="call_1", name="query_track_labels")
    recorder = Recorder(result=original)

    message = await middleware.awrap_tool_call(FakeToolCallRequest(), recorder.ahandle)

    assert message is original


# --------------------------------------------------------------------------- #
# AgentCallLoggerMiddleware
# --------------------------------------------------------------------------- #

class _ModelRequest:
    """``ModelRequest`` 的最小替身：日志只读这几个字段。"""

    def __init__(self, messages, system_prompt=""):
        self.messages = messages
        self.system_prompt = system_prompt
        self.tools = []
        self.tool_choice = None


def _workspace(tmp_path: Path) -> TaskWorkspace:
    workspace = TaskWorkspace(tmp_path / TASK_ID)
    workspace.initialize()
    return workspace


def _read_log(workspace: TaskWorkspace) -> list[dict]:
    path = workspace.root / "logs" / "agent.ndjson"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.asyncio
async def test_every_log_line_carries_run_identity(tmp_path):
    """没有 run_id，三份日志（agent / events / 审计）根本无法关联。"""
    workspace = _workspace(tmp_path)
    logger = AgentCallLoggerMiddleware(workspace, run_id="run_x", task_id=TASK_ID)
    middleware = logger

    await middleware.awrap_model_call(
        _ModelRequest([HumanMessage("你好")]), Recorder(result="ok").ahandle
    )

    rows = _read_log(workspace)
    assert rows and all(row["run_id"] == "run_x" for row in rows)
    assert all(row["task_id"] == TASK_ID for row in rows)
    assert all("logged_at" in row for row in rows)


@pytest.mark.asyncio
async def test_presigned_urls_never_reach_the_log(tmp_path):
    workspace = _workspace(tmp_path)
    middleware = AgentCallLoggerMiddleware(workspace, run_id="run_y", task_id=TASK_ID)
    message = HumanMessage(
        content=(
            "看这个 http://minio:9000/b/o.md?X-Amz-Credential=admin%2F2026"
            "&X-Amz-Signature=deadbeef&X-Amz-Date=20260101"
        )
    )

    await middleware.awrap_model_call(_ModelRequest([message]), Recorder(result="ok").ahandle)

    text = (workspace.root / "logs" / "agent.ndjson").read_text(encoding="utf-8")
    assert "deadbeef" not in text
    assert "admin%2F2026" not in text
    assert "[REDACTED]" in text


@pytest.mark.asyncio
async def test_only_new_messages_are_logged_each_call(tmp_path):
    """整段历史每次都落盘是 O(n²)：一次真实报告写到 3.5MB。"""
    workspace = _workspace(tmp_path)
    middleware = AgentCallLoggerMiddleware(workspace, run_id="run_z", task_id=TASK_ID)
    recorder = Recorder(result="ok")

    first = [HumanMessage("一"), HumanMessage("二")]
    await middleware.awrap_model_call(_ModelRequest(first), recorder.ahandle)
    second = [*first, HumanMessage("三")]
    await middleware.awrap_model_call(_ModelRequest(second), recorder.ahandle)

    rows = [row for row in _read_log(workspace) if row.get("kind") == "model_call"]
    assert [row["input"]["messages_logged"] for row in rows] == [2, 1]
    assert [row["input"]["messages_count"] for row in rows] == [2, 3]


@pytest.mark.asyncio
async def test_a_rebuilt_history_is_logged_again(tmp_path):
    """压缩会重建消息列表，长度变短时必须重发，否则新历史不会被记录。"""
    workspace = _workspace(tmp_path)
    middleware = AgentCallLoggerMiddleware(workspace, run_id="run_w", task_id=TASK_ID)
    recorder = Recorder(result="ok")

    await middleware.awrap_model_call(
        _ModelRequest([HumanMessage(str(i)) for i in range(5)]), recorder.ahandle
    )
    await middleware.awrap_model_call(_ModelRequest([HumanMessage("压缩后的摘要")]), recorder.ahandle)

    rows = [row for row in _read_log(workspace) if row.get("kind") == "model_call"]
    assert rows[-1]["input"]["messages_logged"] == 1


def test_pause_is_a_distinct_type_from_hard_exceeded():
    """软中断和硬超限必须是两个类型：前者可续跑，后者不可。

    `_execute` 靠类型区分——`BudgetPaused` 走 needs_input（用户回一句继续），
    `BudgetExceeded` 走 failed。混成一个类型，暂停会被误判成失败。
    """
    from report_agent.harness.budget import BudgetExceeded, BudgetPaused

    assert not issubclass(BudgetPaused, BudgetExceeded)
    assert not issubclass(BudgetExceeded, BudgetPaused)

    # 时间耗尽仍是硬超限
    clock = [0.0]
    budget = RunBudget(max_model_calls=200, max_tool_calls=None, timeout_seconds=10,
                       clock=lambda: clock[0])
    clock[0] = 11.0
    with pytest.raises(BudgetExceeded):
        budget.snapshot()