"""Model-driven reasoning control.

The business flow is orchestrated by the *skill*, not by this module: the skill
says **when** reasoning is worth spending, the model decides **whether** to ask
for it, and the code only translates that decision into provider parameters.

That split is deliberate. A heuristic here ("turn thinking off after a read
tool") would hard-code a process into Python, and the skill has to keep working
on its own when this platform is gone — so the tool is an *optional capability*:
if it is absent, the skill's guidance still tells the model to think before a
judgement call, it simply cannot lower the level explicitly.

One-shot semantics: ``set_thinking('deep')`` applies to the **next** model call
and then falls back to ``auto``. Persisting it would let a single "off" leak into
every later judgement step.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest
from langchain_core.tools import StructuredTool

from report_agent.harness.thinking import (
    ThinkingAdapter,
    ThinkingMode,
    parse_mode,
    thinking_params)

#: A plan step may declare its own reasoning level as a leading tag, e.g.
#: ``[off] 3.1 抄写工商字段``. The level travels *with the plan* rather than
#: depending on the model remembering a tool call mid-flow — in a live run the
#: model planned six steps and never once called ``set_thinking``.
_STEP_LEVEL_RE = re.compile(r"^\s*[\[【(（]\s*(auto|off|on|deep)\s*[\]】)）]", re.I)


def parse_step_level(content: object) -> str | None:
    """Read the leading ``[off]``-style tag from a plan step, if any."""
    match = _STEP_LEVEL_RE.match(str(content or ""))
    return match.group(1).lower() if match else None


#: Levels the model may request, mapped to the provider-facing mode.
_LEVELS: dict[str, ThinkingMode] = {
    "auto": ThinkingMode.AUTO,
    "off": ThinkingMode.OFF,
    "on": ThinkingMode.ON,
    "deep": ThinkingMode.ON,
}

#: ``deep`` asks for an explicit budget where the provider supports one.
_DEEP_BUDGET = 2048

#: Levels that spend extra reasoning get a larger budget than the default.
_BUDGETS: dict[str, int] = {"deep": _DEEP_BUDGET}


class ThinkingControl:
    """Per-run reasoning level, defaulting to whatever the operator chose."""

    def __init__(self, default: ThinkingMode = ThinkingMode.AUTO) -> None:
        self._default = default
        self._pending: str | None = None
        self._history: list[tuple[str, str]] = []

    @property
    def history(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._history)

    def request(self, level: str, reason: str = "") -> str:
        """Record a one-shot request; unknown levels fall back to ``auto``."""
        key = (level or "").strip().lower()
        if key not in _LEVELS:
            key = "auto"
        self._pending = key
        self._history.append((key, reason))
        return key

    def consume(self) -> tuple[ThinkingMode, int | None]:
        """Take the pending level for one call and reset to the run default."""
        if self._pending is None:
            return self._default, None
        level = self._pending
        self._pending = None
        return _LEVELS[level], _BUDGETS.get(level)


class ThinkingPolicyMiddleware(AgentMiddleware[Any, Any, Any]):
    """Translate the plan's declared level into request parameters."""

    def __init__(self, control: ThinkingControl, adapter: ThinkingAdapter) -> None:
        self._control = control
        self._adapter = adapter

    # -- read the level out of the execution plan -------------------------
    def before_model(self, state: Any, runtime: Any = None) -> None:
        self._sync_from_plan(state)

    async def abefore_model(self, state: Any, runtime: Any = None) -> None:
        self._sync_from_plan(state)

    def _sync_from_plan(self, state: Any) -> None:
        """Apply the in-progress step's declared level before the call.

        Reading it every call (instead of once) means a plan edit mid-flow takes
        effect immediately, and no state has to be cleaned up when a step ends.
        """
        try:
            todos = (state or {}).get("todos") or []
            current = next(
                (item for item in todos if isinstance(item, dict)
                 and item.get("status") == "in_progress"),
                None,
            )
            level = parse_step_level(current.get("content")) if current else None
            if level:
                self._control.request(level, "plan")
        except Exception:  # noqa: BLE001 - a malformed plan must not break the run
            return

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelCallResult[Any]],
    ) -> ModelCallResult[Any] | Any:
        return handler(self._apply(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelCallResult[Any]]],
    ) -> ModelCallResult[Any] | Any:
        return await handler(self._apply(request))

    def _apply(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        try:
            mode, budget = self._control.consume()
            params = thinking_params(self._adapter, mode, budget=budget)
        except Exception:  # noqa: BLE001 - never break a run over a thinking hint
            return request
        if not params:
            # AUTO with a provider that thinks by default: send nothing so the
            # deployment keeps its own setting.
            return request.override(model_settings={"extra_body": None})
        return request.override(model_settings={"extra_body": params})


def build_thinking_tools(control: ThinkingControl) -> tuple[StructuredTool, ...]:
    """The ``set_thinking`` tool. Optional capability — the skill works without it."""

    def set_thinking(level: str, reason: str = "") -> str:
        accepted = control.request(level, reason)
        return (
            f"下一次模型调用使用思考级别 `{accepted}`（只影响一次，随后回到默认）。"
            + (f"理由：{reason}" if reason else "")
        )

    return (
        StructuredTool.from_function(
            set_thinking,
            name="set_thinking",
            description=(
                "临时调整**下一次**模型调用的思考强度——**通常不需要用它**："
                "在 `write_todos` 的每一步开头写 `[off]` / `[on]` / `[deep]` / `[auto]`，"
                "流程会自动按当前进行中的那一步决定，比临时调用更可靠。\n"
                "只在计划外的突发情况用它。level 取值：\n"
                "- `auto`：交回模型/部署默认\n"
                "- `off`：纯搬运、改格式、修错别字\n"
                "- `on`：需要判断（选口径、合并事实、决定章节取舍）\n"
                "- `deep`：跨多份材料核对、数值对账、口径冲突取舍\n"
                "只影响一次调用，不需要手动改回。"
            ),
        ),
    )


def control_from_run_mode(raw: str) -> ThinkingControl:
    """Seed the control from the run-level ``thinking`` form field."""
    return ThinkingControl(parse_mode(raw))
