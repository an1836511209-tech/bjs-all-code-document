"""
任务级 Token 用量累计

通过 contextvars 在一次提取/审核任务内累计所有低代码智能体 bill 消耗，
支持嵌套任务（如审核内调用提取）复用外层累加器。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Optional, TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from src.services.llm.models import AgentResponse


@dataclass
class TokenUsageTracker:
    """单次任务的 Token 累计器"""

    task_type: str
    task_id: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    billed_call_count: int = 0

    def add_from_response(self, response: "AgentResponse") -> None:
        """
        从 Agent 响应中累加 bill token。

        取最后一个带 bill 的 choice（与业务解析使用最后一个 choice 一致），
        避免流式多 choice 时重复累加。
        """
        self.call_count += 1
        if not response or not response.choices:
            return

        bill = None
        for choice in reversed(response.choices):
            if choice.bill is not None:
                bill = choice.bill
                break

        if bill is None:
            return

        prompt = int(bill.promptTokens or 0)
        completion = int(bill.completionTokens or 0)
        total = int(bill.totalTokens or 0)
        if total <= 0:
            total = prompt + completion

        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total
        self.billed_call_count += 1

    def log_summary(self) -> None:
        """输出任务级 Token 汇总日志"""
        logger.info(
            f"任务Token统计 | "
            f"类型={self.task_type} | "
            f"task_id={self.task_id or '-'} | "
            f"promptTokens={self.prompt_tokens} | "
            f"completionTokens={self.completion_tokens} | "
            f"totalTokens={self.total_tokens} | "
            f"智能体调用={self.call_count} | "
            f"含bill调用={self.billed_call_count}"
        )


_current_tracker: ContextVar[Optional[TokenUsageTracker]] = ContextVar(
    "llm_token_usage_tracker", default=None
)


def get_current_token_tracker() -> Optional[TokenUsageTracker]:
    """获取当前任务的 Token 累计器（无任务上下文时返回 None）"""
    return _current_tracker.get()


def record_agent_token_usage(response: "AgentResponse") -> None:
    """若当前处于任务 Token 统计作用域，则累加本次响应的 bill"""
    tracker = _current_tracker.get()
    if tracker is not None:
        tracker.add_from_response(response)


@contextmanager
def token_usage_scope(
    task_type: str,
    task_id: Optional[str] = None,
) -> Iterator[TokenUsageTracker]:
    """
    任务级 Token 统计作用域。

    - 外层任务：新建累计器，退出时写汇总日志
    - 嵌套任务（如审核内提取）：复用外层累计器，退出时不单独打日志
    """
    parent = _current_tracker.get()
    if parent is not None:
        yield parent
        return

    tracker = TokenUsageTracker(task_type=task_type, task_id=task_id)
    token = _current_tracker.set(tracker)
    try:
        yield tracker
    finally:
        tracker.log_summary()
        _current_tracker.reset(token)
