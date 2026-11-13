"""中间件测试桩：不启动真 agent，直接驱动中间件的钩子。

中间件是"模型/工具调用前后插的一层包装"，行为都集中在这几个钩子上：

* ``before_model`` / ``abefore_model`` —— 模型调用前（预算、思考强度）
* ``wrap_model_call`` / ``awrap_model_call`` —— 包住模型调用（日志、改请求）
* ``wrap_tool_call`` / ``awrap_tool_call`` —— 包住工具调用（预算、失败兜底）

把它们单独驱动，比跑一次 14 分钟的真实 run 便宜得多，也能断言"没被调用"这种
负面行为。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeTool:
    name: str = "query_track_labels"
    description: str = "测试桩"


@dataclass
class FakeToolCallRequest:
    """``ToolCallRequest`` 的最小替身：中间件只读 ``tool`` 和 ``tool_call``。"""

    tool_call: dict[str, Any] = field(
        default_factory=lambda: {"id": "call_1", "name": "query_track_labels", "args": {}}
    )
    tool: FakeTool = field(default_factory=FakeTool)


class Recorder:
    """记录 handler 是否被调用、被调了几次。"""

    def __init__(self, result: Any = None, error: BaseException | None = None) -> None:
        self.calls = 0
        self._result = result
        self._error = error

    def handle(self, request: Any) -> Any:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result

    async def ahandle(self, request: Any) -> Any:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result
