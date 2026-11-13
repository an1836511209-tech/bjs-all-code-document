"""Deterministic per-run model/tool/time budgets."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


class BudgetExceeded(RuntimeError):
    """硬超限：运行时间耗尽之类不可续跑的情况。"""


class BudgetPaused(RuntimeError):
    """软中断：本轮调用次数用完，任务暂停，等用户回一句话接着做。

    与 :class:`BudgetExceeded` 的区别是**这不是失败**：workspace 里的材料、证据、
    正文都还在，用户下一条消息会开新一轮、接着当前状态往下走。
    """


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    model_calls: int
    tool_calls: int
    elapsed_seconds: float


class RunBudget:
    """只计数的运行预算；上限为 ``None`` 时**不拦截**。

    轮次限制已经停用：任务靠上下文压缩持续管理下去，模型真的陷入循环时由用户
    在控制台手动中止。这里仍然计数，因为用量是排障和成本核算的依据；`None`
    只表示"不因为计数而中断"。
    """

    def __init__(
        self,
        *,
        max_model_calls: int | None = None,
        max_tool_calls: int | None = None,
        timeout_seconds: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        initial: BudgetSnapshot | None = None,
        persist: Callable[[BudgetSnapshot], None] | None = None,
    ) -> None:
        for label, value in (
            ("max_model_calls", max_model_calls),
            ("max_tool_calls", max_tool_calls),
            ("timeout_seconds", timeout_seconds),
        ):
            if value is not None and value < 1:
                raise ValueError(f"{label} must be positive when set")
        self._max_model_calls = max_model_calls
        self._max_tool_calls = max_tool_calls
        self._timeout_seconds = timeout_seconds
        self._clock = clock
        self._started_at = clock() - (initial.elapsed_seconds if initial else 0)
        self._model_calls = initial.model_calls if initial else 0
        self._tool_calls = initial.tool_calls if initial else 0
        self._persist = persist
        self._lock = threading.Lock()

    def consume_model_call(self) -> BudgetSnapshot:
        return self._consume("model")

    def consume_tool_call(self) -> BudgetSnapshot:
        return self._consume("tool")

    def snapshot(self, *, check_limits: bool = True) -> BudgetSnapshot:
        with self._lock:
            return self._snapshot_checked(check_limits=check_limits)

    def _consume(self, kind: str) -> BudgetSnapshot:
        with self._lock:
            snapshot = self._snapshot_checked()
            if kind == "model":
                if self._max_model_calls is not None and self._model_calls >= self._max_model_calls:
                    raise BudgetPaused("model call budget reached; paused for user to continue")
                self._model_calls += 1
            else:
                if self._max_tool_calls is not None and self._tool_calls >= self._max_tool_calls:
                    raise BudgetPaused("tool call budget reached; paused for user to continue")
                self._tool_calls += 1
            snapshot = BudgetSnapshot(self._model_calls, self._tool_calls, snapshot.elapsed_seconds)
            if self._persist:
                self._persist(snapshot)
            return snapshot

    def _snapshot_checked(self, *, check_limits: bool = True) -> BudgetSnapshot:
        elapsed = self._clock() - self._started_at
        if check_limits and self._timeout_seconds is not None and elapsed >= self._timeout_seconds:
            raise BudgetExceeded("run time budget exhausted")
        return BudgetSnapshot(self._model_calls, self._tool_calls, elapsed)
